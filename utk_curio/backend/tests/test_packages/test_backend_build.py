"""memo dev/91 commit 3 — backend drafts through the build service: the
static policy scan (escape-hatch families blocked, network per declared
permission), the probing phase (REAL sandbox workers — the A9 lesson), the
result's backend provenance, and the install-authority entry pin."""

from __future__ import annotations

import io
import zipfile

import pytest

from utk_curio.backend.app.packages import backend_policy, backend_runtime, build_jobs
from utk_curio.backend.app.packages.build_models import parse_build_request
from utk_curio.backend.app.packages.build_pipeline import run_build
from utk_curio.backend.app.packages.build_staging import read_artifact
from utk_curio.backend.app.packages.build_workspace import WorkerLimits

FAST = WorkerLimits(wall_time_seconds=20.0, cpu_seconds=10)

_OK_HANDLER = "def handle(payload):\n    return {'ok': True}\n"


def _fail_message(job) -> str:
    return " | ".join(e["message"] for e in job.events if e["phase"] == "failed")


@pytest.fixture(autouse=True)
def _fresh_jobs():
    build_jobs.reset_registry()
    yield
    build_jobs.reset_registry()


def _backend_kind() -> dict:
    return {
        "id": "counter-kind", "label": "Counter", "category": "computation",
        "engine": "python", "editor": "none", "hasCode": False,
        "hasWidgets": False, "hasGrammar": False,
        "inputPorts": [], "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
        "backendHandler": "word-count",
    }


def _backend_manifest(manifest_dict, *, permissions=None, handlers=None) -> dict:
    m = manifest_dict(kinds=[_backend_kind()])
    m["permissions"] = permissions if permissions is not None else ["server-code"]
    m["backend"] = {
        "entry": "backend/handler.py",
        "handlers": handlers or [{"name": "word-count", "timeoutClass": "quick"}],
    }
    return m


def _backend_request(manifest_dict, *, handler_src=_OK_HANDLER, permissions=None,
                     handlers=None):
    return parse_build_request({
        "mode": "create",
        "manifest": _backend_manifest(manifest_dict, permissions=permissions,
                                      handlers=handlers),
        "files": {"backend/handler.py": {"text": handler_src}},
    })


# ── the static policy scan ───────────────────────────────────────────────────
class TestPolicyScan:
    def _scan(self, src: str, *, net=False):
        return backend_policy.scan_backend_sources(
            {"backend/handler.py": src.encode()}, net_permission_declared=net)

    @pytest.mark.parametrize("line,code", [
        ("import ctypes", "backend-ctypes"),
        ("from ctypes import CDLL", "backend-ctypes"),
        ("import subprocess", "backend-spawn"),
        ("from multiprocessing import Pool", "backend-spawn"),
        ("import pty", "backend-spawn"),
        ("os.system('ls')", "backend-os-spawn"),
        ("os.popen('ls')", "backend-os-spawn"),
        ("os.execv('/bin/sh', [])", "backend-os-spawn"),
        ("eval('1')", "backend-dynamic-code"),
        ("exec('x = 1')", "backend-dynamic-code"),
        ("compile('1', '<s>', 'eval')", "backend-dynamic-code"),
        ("__import__('os')", "backend-dynamic-code"),
        ("import importlib", "backend-dynamic-import"),
        ("from flask import Flask", "backend-resident-service"),
        ("bp = Blueprint('x', __name__)", "backend-resident-service"),
        ("@app.route('/x')", "backend-resident-service"),
        ("import socketserver", "backend-resident-server"),
    ])
    def test_escape_hatch_families_block(self, line, code):
        findings = self._scan(f"{_OK_HANDLER}\n{line}\n")
        assert any(f.severity == "block" and f.code == code for f in findings), findings
        # Every finding carries file:line and a fix-naming message (A4/A5).
        blocked = next(f for f in findings if f.code == code)
        assert "backend/handler.py:" in blocked.message

    def test_network_blocks_undeclared_and_warns_declared(self):
        src = "import requests\ndef handle(payload):\n    return {}\n"
        undeclared = self._scan(src, net=False)
        assert any(f.severity == "block" and f.code == "backend-network-undeclared"
                   and "server-network" in f.message for f in undeclared)
        declared = self._scan(src, net=True)
        assert any(f.severity == "warn" and f.code == "backend-network-declared"
                   for f in declared)
        assert not any(f.severity == "block" for f in declared)

    def test_comments_non_backend_and_clean_sources_pass(self):
        findings = backend_policy.scan_backend_sources({
            "backend/handler.py": b"# import subprocess is documented here\n"
                                  b"def handle(payload):\n    return {}\n",
            "sources/note.tsx": b"import subprocess  // not python, not backend/",
            "backend/data.json": b"{}",
        }, net_permission_declared=False)
        assert findings == []

    def test_non_utf8_backend_source_blocks(self):
        findings = backend_policy.scan_backend_sources(
            {"backend/handler.py": b"\xff\xfe\x00"}, net_permission_declared=False)
        assert [f.code for f in findings] == ["backend-not-utf8"]


class TestDeclarationReading:
    def test_absent_backend_is_none(self, manifest_dict):
        assert backend_policy.backend_declaration(manifest_dict()) is None

    def test_valid_declaration_parses_through_the_one_grammar(self, manifest_dict):
        decl = backend_policy.backend_declaration(_backend_manifest(manifest_dict))
        assert decl is not None and decl.handler_names == ["word-count"]

    def test_malformed_declaration_raises_with_the_fix(self, manifest_dict):
        m = _backend_manifest(manifest_dict)
        m["permissions"] = []  # server-code missing
        with pytest.raises(backend_policy.BackendPolicyError, match="server-code"):
            backend_policy.backend_declaration(m)

    def test_missing_entry_file_is_a_block_finding(self, manifest_dict):
        decl = backend_policy.backend_declaration(_backend_manifest(manifest_dict))
        findings = backend_policy.validate_backend_files(decl, {})
        assert [f.code for f in findings] == ["backend-entry-missing"]
        assert "ride the draft" in findings[0].message


# ── the probing phase (real workers) ────────────────────────────────────────
class TestProbingPhase:
    def test_backend_draft_probes_and_ships(self, tmp_curio, manifest_dict):
        job = run_build("guest", _backend_request(manifest_dict),
                        toolchain=None, preview_runner=None, probe_limits=FAST)
        assert job.phase == "ready", job.to_payload()
        phases = [e["phase"] for e in job.events]
        assert "probing" in phases and "compiling" not in phases
        backend = job.result.backend
        assert backend["entry"] == "backend/handler.py"
        assert backend["probe"] == [{
            "handler": "word-count", "workerStatus": "ok",
            "durationMs": backend["probe"][0]["durationMs"],
            "limitsApplied": backend["probe"][0]["limitsApplied"], "ok": True,
        }]
        # backend/ ships in the deterministic archive.
        archive = read_artifact("guest", job.result.artifact_digest)
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            assert "backend/handler.py" in set(zf.namelist())
        # The result payload round-trips the backend provenance.
        assert job.result.to_payload()["backend"]["probe"][0]["ok"] is True

    def test_scan_block_fails_before_any_probe(self, tmp_curio, manifest_dict):
        job = run_build(
            "guest",
            _backend_request(manifest_dict,
                             handler_src="import subprocess\n" + _OK_HANDLER),
            toolchain=None, preview_runner=None, probe_limits=FAST)
        assert job.phase == "failed"
        assert "backend policy blocked" in _fail_message(job)
        assert "process spawning" in _fail_message(job)
        assert "probing" not in [e["phase"] for e in job.events]

    def test_undeclared_network_blocks_and_declared_ships_with_warning(
            self, tmp_curio, manifest_dict):
        src = "import ssl\n" + _OK_HANDLER
        blocked = run_build("guest", _backend_request(manifest_dict, handler_src=src),
                            toolchain=None, preview_runner=None, probe_limits=FAST)
        assert blocked.phase == "failed" and "server-network" in _fail_message(blocked)
        build_jobs.reset_registry()
        shipped = run_build(
            "guest",
            _backend_request(manifest_dict, handler_src=src,
                             permissions=["server-code", "server-network"]),
            toolchain=None, preview_runner=None, probe_limits=FAST)
        assert shipped.phase == "ready", shipped.to_payload()
        warns = [f for f in shipped.result.backend["findings"] if f["severity"] == "warn"]
        assert any(f["code"] == "backend-network-declared" for f in warns)

    def test_probe_failure_blocks_apply_naming_the_handler(self, tmp_curio, manifest_dict):
        job = run_build(
            "guest",
            _backend_request(manifest_dict,
                             handler_src="import not_a_real_module\n" + _OK_HANDLER),
            toolchain=None, preview_runner=None, probe_limits=FAST)
        assert job.phase == "failed"
        assert "backend probe failed for handler 'word-count'" in _fail_message(job)
        assert "not_a_real_module" in _fail_message(job)
        # No artifact was staged — an unprobed backend cannot reach Apply.
        assert job.result.status == "failed" and job.result.artifact_digest is None

    def test_missing_entry_file_fails_in_resolving(self, tmp_curio, manifest_dict):
        request = parse_build_request({
            "mode": "create",
            "manifest": _backend_manifest(manifest_dict),
            "files": {"sources/readme-ish.txt": {"text": "no backend file"}},
        })
        job = run_build("guest", request, toolchain=None, preview_runner=None,
                        probe_limits=FAST)
        assert job.phase == "failed"
        assert "backend-entry" in _fail_message(job) or "ride the draft" in _fail_message(job)

    def test_plain_draft_skips_probing(self, tmp_curio, manifest_dict):
        request = parse_build_request({
            "mode": "create", "manifest": manifest_dict(),
            "files": {"starters/demo-kind/Default.py": {"text": "return arg\n"}},
        })
        job = run_build("guest", request, toolchain=None, preview_runner=None)
        assert job.phase == "ready"
        assert "probing" not in [e["phase"] for e in job.events]
        assert job.result.backend is None


# ── the install-authority entry pin ──────────────────────────────────────────
class TestEntryPin:
    def test_pin_round_trip_and_drift_detection(self, tmp_curio, manifest_dict,
                                                make_archive):
        from utk_curio.backend.app.packages.installer import install_packageage_from_archive
        from utk_curio.backend.app.packages.storage import package_dir

        archive = make_archive(manifest=_backend_manifest(manifest_dict),
                               extra_files={"backend/handler.py": _OK_HANDLER.encode()})
        install_packageage_from_archive("guest", archive)
        dir_name = "ai.test.demo@1"
        pinned = backend_runtime.record_entry_pin("guest", dir_name)
        entry = package_dir("guest", dir_name) / "backend" / "handler.py"
        assert pinned == backend_runtime.entry_digest(entry.read_bytes())
        assert backend_runtime.pinned_entry_digest("guest", dir_name) == pinned
        # The pinned digest gates invocation: a match runs, drift 409s.
        out = backend_runtime.invoke_handler(
            "guest", dir_name, "word-count", {"text": "x"},
            expected_entry_digest=pinned, limits=FAST)
        assert out["reply"]["ok"] is True
        entry.chmod(0o644)
        entry.write_text("def handle(payload):\n    return {'tampered': True}\n")
        with pytest.raises(backend_runtime.BackendRuntimeError) as exc:
            backend_runtime.invoke_handler(
                "guest", dir_name, "word-count", {},
                expected_entry_digest=pinned, limits=FAST)
        assert exc.value.status == 409 and "reinstall" in str(exc.value)

    def test_backendless_install_clears_a_stale_pin(self, tmp_curio, manifest_dict,
                                                    make_archive):
        from utk_curio.backend.app.packages.installer import install_packageage_from_archive

        archive = make_archive(manifest=_backend_manifest(manifest_dict),
                               extra_files={"backend/handler.py": _OK_HANDLER.encode()})
        install_packageage_from_archive("guest", archive)
        assert backend_runtime.record_entry_pin("guest", "ai.test.demo@1")
        plain = make_archive(manifest=manifest_dict())
        install_packageage_from_archive("guest", plain, replace=True)
        assert backend_runtime.record_entry_pin("guest", "ai.test.demo@1") is None
        assert backend_runtime.pinned_entry_digest("guest", "ai.test.demo@1") is None
