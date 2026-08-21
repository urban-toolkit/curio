"""memo dev/91 commit 2 — the backend sandbox runtime + harness, exercised
with REAL worker subprocesses (the A9 lesson: fakes never catch what the
real toolchain refuses).

The suite installs a tiny backend-bearing package into a temp user store and
drives ``invoke_handler`` end-to-end: success, probe-without-execution,
handler failure, env scrub (a poisoned parent secret never reaches the
worker), the advisory network guard, persistent data dir + cap, timeout
kill, missing-reply contract error, digest drift, undeclared handlers,
payload bounds, and the audit ledger."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from utk_curio.backend.app.packages import backend_contract as bc
from utk_curio.backend.app.packages import backend_runtime as rt
from utk_curio.backend.app.packages.build_workspace import WorkerLimits

USER = "42"  # user keys are guest-or-numeric (storage._user_key_segment)
PKG = "curio.counter@1"

#: Tight limits keep the real-subprocess suite fast; the wall clock only has
#: to outlive interpreter startup.
FAST = WorkerLimits(wall_time_seconds=20.0, cpu_seconds=10)
KILL_FAST = WorkerLimits(wall_time_seconds=1.5, cpu_seconds=10)

_HANDLER_SRC = '''\
import json
import os


def _count(payload):
    return {"words": len(str(payload.get("text", "")).split())}


def _env_probe(payload):
    return {"present": [k for k in payload["names"] if k in os.environ]}


def _net(payload):
    import socket
    socket.socket()
    return {"reached": True}


def _remember(payload):
    data_dir = os.environ["CURIO_PKG_DATA_DIR"]
    path = os.path.join(data_dir, "note.txt")
    if "write" in payload:
        with open(path, "w") as fh:
            fh.write(payload["write"])
        return {"wrote": True}
    with open(path) as fh:
        return {"read": fh.read()}


def _boom(payload):
    raise RuntimeError("the handler exploded")


def _spin(payload):
    while True:
        pass


def _unserializable(payload):
    return {"x": object()}


HANDLERS = {
    "word-count": _count,
    "env-probe": _env_probe,
    "net": _net,
    "remember": _remember,
    "boom": _boom,
    "spin": _spin,
    "unserializable": _unserializable,
}
'''

_ALL_HANDLERS = ["word-count", "env-probe", "net", "remember", "boom", "spin",
                 "unserializable"]


def _install_pkg(monkeypatch, tmp_path: Path, *, permissions=None,
                 handler_src: str = _HANDLER_SRC) -> Path:
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    pkg = tmp_path / ".curio" / "users" / USER / "packages" / PKG
    (pkg / "backend").mkdir(parents=True)
    perms = [bc.PERMISSION_SERVER_CODE] + list(permissions or [])
    manifest = {
        "id": "curio.counter", "version": "1.0.0", "name": "Counter",
        "publisher": "t", "description": "d", "compatibility": {"major": 1},
        "permissions": perms,
        "templates": [{
            "id": "counter", "label": "Counter", "category": "computation",
            "engine": "python", "editor": "none", "hasCode": False,
            "inputPorts": [], "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "backendHandler": "word-count",
        }],
        "backend": {
            "entry": "backend/handler.py",
            "handlers": [{"name": n, "timeoutClass": "quick"} for n in _ALL_HANDLERS],
        },
    }
    (pkg / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pkg / "backend" / "handler.py").write_text(handler_src, encoding="utf-8")
    return pkg


def _ledger_rows(tmp_path: Path) -> list[dict]:
    root = tmp_path / ".curio" / "users" / USER / "package-backend-ledger" / PKG
    rows: list[dict] = []
    if root.is_dir():
        for day_file in sorted(root.glob("*.jsonl")):
            rows.extend(json.loads(line) for line in day_file.read_text().splitlines())
    return rows


class TestInvokeHandler:
    def test_success_end_to_end(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        out = rt.invoke_handler(USER, PKG, "word-count", {"text": "a b c"}, limits=FAST)
        assert out["reply"] == {"contract": bc.PKGBACKEND_CONTRACT_VERSION,
                                "ok": True, "result": {"words": 3}}
        assert out["workerStatus"] == "ok"
        assert out["invocationId"] and out["entryDigest"]
        rows = _ledger_rows(tmp_path)
        assert len(rows) == 1 and rows[0]["status"] == "ok"
        assert rows[0]["handler"] == "word-count"
        # The audit row records sizes and outcomes, never payload contents.
        assert "a b c" not in json.dumps(rows[0])

    def test_probe_answers_ok_without_running_the_handler(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        # "boom" raises on ANY execution — a probe must succeed anyway,
        # because load + resolution IS the health check (memo dev/91 §3).
        out = rt.invoke_handler(USER, PKG, "boom", bc.probe_payload(), limits=FAST)
        assert out["reply"]["ok"] is True
        assert out["reply"]["result"]["probe"] == "ok"

    def test_handler_exception_is_an_honest_handler_error(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        out = rt.invoke_handler(USER, PKG, "boom", {}, limits=FAST)
        assert out["reply"]["ok"] is False
        assert out["reply"]["kind"] == "handler-error"
        assert "the handler exploded" in out["reply"]["error"]
        assert _ledger_rows(tmp_path)[0]["status"] == "reply-handler-error"

    def test_unserializable_result_is_a_handler_error(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        out = rt.invoke_handler(USER, PKG, "unserializable", {}, limits=FAST)
        assert out["reply"]["ok"] is False and out["reply"]["kind"] == "handler-error"
        assert "non-JSON" in out["reply"]["error"]

    def test_worker_env_is_scrubbed_of_host_secrets(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        monkeypatch.setenv("CURIO_SEARCH_URL", "https://example.test/?api_key=SECRET")
        monkeypatch.setenv("AICONN_API_KEY", "hostsecret")
        out = rt.invoke_handler(
            USER, PKG, "env-probe",
            {"names": ["CURIO_SEARCH_URL", "AICONN_API_KEY", "CURIO_PKG_DATA_DIR"]},
            limits=FAST,
        )
        # The from-scratch env carries ONLY the sandbox's own vars.
        assert out["reply"]["result"]["present"] == ["CURIO_PKG_DATA_DIR"]

    def test_network_guard_blocks_undeclared_and_opens_declared(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        out = rt.invoke_handler(USER, PKG, "net", {}, limits=FAST)
        assert out["reply"]["ok"] is False
        assert "server-network" in out["reply"]["error"]

    def test_declared_network_permission_lifts_the_guard(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path,
                     permissions=[bc.PERMISSION_SERVER_NETWORK])
        out = rt.invoke_handler(USER, PKG, "net", {}, limits=FAST)
        # socket.socket() constructs without touching any real network.
        assert out["reply"] == {"contract": bc.PKGBACKEND_CONTRACT_VERSION,
                                "ok": True, "result": {"reached": True}}

    def test_data_dir_persists_across_invocations_and_caps(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        assert rt.invoke_handler(USER, PKG, "remember", {"write": "kept"},
                                 limits=FAST)["reply"]["result"] == {"wrote": True}
        assert rt.invoke_handler(USER, PKG, "remember", {},
                                 limits=FAST)["reply"]["result"] == {"read": "kept"}
        # Over-cap refuses the NEXT invocation with the stated 507 (§6.7).
        monkeypatch.setattr(rt, "DATA_DIR_MAX_BYTES", 1)
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "remember", {}, limits=FAST)
        assert exc.value.status == 507 and "clear it" in str(exc.value)

    def test_timeout_kills_the_worker_and_reports_502(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "spin", {}, limits=KILL_FAST)
        assert exc.value.status == 502 and "timeout" in str(exc.value)
        assert _ledger_rows(tmp_path)[0]["status"] == "worker-timeout"

    def test_worker_exit_zero_without_reply_is_a_502(self, monkeypatch, tmp_path):
        # os._exit(0) at entry import: the harness dies "successfully"
        # without writing a reply — the no-reply contract branch.
        _install_pkg(monkeypatch, tmp_path,
                     handler_src="import os\nos._exit(0)\n")
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "word-count", {}, limits=FAST)
        assert exc.value.status == 502
        assert "without a reply envelope" in str(exc.value)

    def test_worker_nonzero_exit_is_a_502(self, monkeypatch, tmp_path):
        # os._exit(3) bypasses even the harness's BaseException net — the
        # worker's own failure status is the diagnosis.
        _install_pkg(monkeypatch, tmp_path,
                     handler_src="import os\nos._exit(3)\n")
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "word-count", {}, limits=FAST)
        assert exc.value.status == 502
        assert "did not complete (failed)" in str(exc.value)
        assert _ledger_rows(tmp_path)[0]["status"] == "worker-failed"

    def test_entry_load_failure_is_a_handler_error(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path, handler_src="import not_a_real_module\n")
        out = rt.invoke_handler(USER, PKG, "word-count", {}, limits=FAST)
        assert out["reply"]["ok"] is False and out["reply"]["kind"] == "handler-error"
        assert "not_a_real_module" in out["reply"]["error"]  # §6.9: names the module


class TestRefusals:
    def test_unknown_package_and_handler_404(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, "curio.ghost@1", "h", {}, limits=FAST)
        assert exc.value.status == 404
        with pytest.raises(rt.BackendRuntimeError) as exc2:
            rt.invoke_handler(USER, PKG, "ghost", {}, limits=FAST)
        assert exc2.value.status == 404
        assert "word-count" in str(exc2.value)  # the refusal names the declared set

    def test_digest_drift_refuses_with_reinstall_guidance(self, monkeypatch, tmp_path):
        pkg = _install_pkg(monkeypatch, tmp_path)
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "word-count", {},
                              expected_entry_digest="0" * 64, limits=FAST)
        assert exc.value.status == 409 and "reinstall" in str(exc.value)
        # The pinned digest matches what's on disk → runs.
        good = rt.entry_digest((pkg / "backend" / "handler.py").read_bytes())
        out = rt.invoke_handler(USER, PKG, "word-count", {"text": "x"},
                                expected_entry_digest=good, limits=FAST)
        assert out["reply"]["ok"] is True

    def test_payload_bounds_refuse_before_any_worker(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "word-count",
                              {"blob": "x" * (bc.PAYLOAD_MAX_BYTES + 1)}, limits=FAST)
        assert exc.value.status == 413
        deep: object = 1
        for _ in range(bc.PAYLOAD_MAX_DEPTH + 1):
            deep = [deep]
        with pytest.raises(rt.BackendRuntimeError) as exc2:
            rt.invoke_handler(USER, PKG, "word-count", deep, limits=FAST)
        assert exc2.value.status == 422

    def test_no_worker_slot_is_a_503(self, monkeypatch, tmp_path):
        _install_pkg(monkeypatch, tmp_path)

        class NoSlot:
            def acquire(self, timeout=None):
                return False

            def release(self):  # pragma: no cover — never reached
                raise AssertionError("release without acquire")

        monkeypatch.setattr(rt, "_worker_slots", NoSlot())
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, PKG, "word-count", {}, limits=FAST)
        assert exc.value.status == 503

    def test_backend_less_package_404s(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
        pkg = tmp_path / ".curio" / "users" / USER / "packages" / "curio.plain@1"
        pkg.mkdir(parents=True)
        (pkg / "manifest.json").write_text(json.dumps({
            "id": "curio.plain", "version": "1.0.0", "name": "P", "publisher": "t",
            "description": "d", "compatibility": {"major": 1},
            "templates": [{
                "id": "t", "label": "T", "category": "computation",
                "engine": "python", "editor": "none",
                "inputPorts": [], "outputPorts": [],
            }],
        }), encoding="utf-8")
        with pytest.raises(rt.BackendRuntimeError) as exc:
            rt.invoke_handler(USER, "curio.plain@1", "h", {}, limits=FAST)
        assert exc.value.status == 404 and "no backend" in str(exc.value)


class TestOptionThreeSeam:
    def test_interpreter_is_operator_pinnable(self, monkeypatch):
        monkeypatch.delenv("CURIO_BACKEND_SANDBOX_PYTHON", raising=False)
        import sys
        assert rt.sandbox_interpreter() == sys.executable
        monkeypatch.setenv("CURIO_BACKEND_SANDBOX_PYTHON", "/opt/pinned/python")
        assert rt.sandbox_interpreter() == "/opt/pinned/python"

    def test_overlay_dir_rides_pythonpath(self, monkeypatch, tmp_path):
        # The reserved §0.1 Option-2 slot: an overlay module resolves from
        # PYTHONPATH inside the worker — dependency isolation as parameter
        # values, no contract change.
        _install_pkg(monkeypatch, tmp_path,
                     handler_src="import overlay_mod\n"
                                 "def handle(payload):\n"
                                 "    return {'from': overlay_mod.WHERE}\n")
        overlay = tmp_path / "overlay"
        overlay.mkdir()
        (overlay / "overlay_mod.py").write_text("WHERE = 'overlay'\n", encoding="utf-8")
        out = rt.invoke_handler(USER, PKG, "word-count", {},
                                overlay_dir=overlay, limits=FAST)
        assert out["reply"] == {"contract": bc.PKGBACKEND_CONTRACT_VERSION,
                                "ok": True, "result": {"from": "overlay"}}
