"""Tests for :mod:`utk_curio.backend.app.packages.build_packager` (dev/89 commit 5):
deterministic assembly, behaviorScript consistency, installer-path archive
validation, provenance shape, staging, and reproducibility.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from utk_curio.backend.app.packages import build_staging
from utk_curio.backend.app.packages.build_deps import DependencyReport, Finding
from utk_curio.backend.app.packages.build_extension import plan_create
from utk_curio.backend.app.packages.build_models import (
    parse_build_request,
    parse_build_result,
    request_digest,
)
from utk_curio.backend.app.packages.build_packager import (
    BUILDER_VERSION,
    PackagerError,
    assemble_archive,
    failed_result,
    finalize_build,
    manifest_dependencies_from_report,
    validate_archive,
)


def _full_manifest(manifest_dict) -> dict:
    """A schema-complete manifest (conftest shape) for install validation."""
    m = manifest_dict(kinds=[{
        "id": "note-kind",
        "label": "Research note",
        "category": "visualization",
        "engine": "javascript",
        "editor": "code",
        "hasCode": True,
        "hasWidgets": False,
        "hasGrammar": False,
        "inputPorts": [],
        "outputPorts": [],
        "templateDir": "starters/note-kind",
        "defaultTemplate": "starters/note-kind/Default.js",
    }])
    return m


def _request(manifest_dict, *, files=None, dependencies=None):
    return parse_build_request({
        "mode": "create",
        "target": "ai.test.demo@1",
        "manifest": _full_manifest(manifest_dict),
        "files": files if files is not None else {
            "starters/note-kind/Default.js": {"text": "return arg\n"},
            "README.md": {"text": "# Note\n"},
        },
        "dependencies": dependencies or {},
    })


def _report(**kwargs) -> DependencyReport:
    return DependencyReport(**kwargs)


_DEPS = {"python": {}, "js": {}, "packages": {}}


class TestAssemble:
    def test_deterministic_and_integrity_covers_everything(self, manifest_dict):
        request = _request(manifest_dict)
        files = dict(request.files)
        a, integrity_a = assemble_archive(request, files, b"registered", _DEPS)
        b, integrity_b = assemble_archive(request, files, b"registered", _DEPS)
        assert a == b and integrity_a == integrity_b
        assert set(integrity_a) == {
            "manifest.json", "README.md", "scripts/behaviors.js",
            "starters/note-kind/Default.js",
        }

    def test_bundle_sets_behavior_script(self, manifest_dict):
        request = _request(manifest_dict)
        archive, _ = assemble_archive(request, request.files, b"registered", _DEPS)
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        assert manifest["behaviorScript"] == "scripts/behaviors.js"
        assert zf.namelist()  # archive readable

    def test_declared_behavior_script_without_bundle_refused(self, manifest_dict):
        raw = _full_manifest(manifest_dict)
        raw["behaviorScript"] = "scripts/behaviors.js"
        request = parse_build_request({
            "mode": "create", "target": "ai.test.demo@1", "manifest": raw,
            "files": {"starters/note-kind/Default.js": {"text": "x"}},
        })
        with pytest.raises(PackagerError, match="compiled no bundle"):
            assemble_archive(request, request.files, None, _DEPS)

    def test_mismatched_behavior_script_refused(self, manifest_dict):
        raw = _full_manifest(manifest_dict)
        raw["behaviorScript"] = "scripts/other.js"
        request = parse_build_request({
            "mode": "create", "target": "ai.test.demo@1", "manifest": raw,
            "files": {"starters/note-kind/Default.js": {"text": "x"}},
        })
        with pytest.raises(PackagerError, match="does not match"):
            assemble_archive(request, request.files, b"registered", _DEPS)

    def test_builder_owned_files_refused(self, manifest_dict):
        request = _request(manifest_dict)
        with pytest.raises(PackagerError, match="builder-owned"):
            assemble_archive(request, {"manifest.json": b"{}"}, None, _DEPS)
        with pytest.raises(PackagerError, match="from the compiler"):
            assemble_archive(request, {"scripts/behaviors.js": b"x"}, b"y", _DEPS)

    def test_created_at_never_stamped_here(self, manifest_dict):
        raw = _full_manifest(manifest_dict)
        raw.pop("createdAt", None)
        request = parse_build_request({
            "mode": "create", "target": "ai.test.demo@1", "manifest": raw,
            "files": {"starters/note-kind/Default.js": {"text": "x"}},
        })
        archive, _ = assemble_archive(request, request.files, None, _DEPS)
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        assert "createdAt" not in manifest  # the installer stamps it on Apply


class TestValidateArchive:
    def test_valid_archive_loads_manifest(self, manifest_dict):
        request = _request(manifest_dict)
        archive, _ = assemble_archive(request, request.files, None, _DEPS)
        manifest = validate_archive(archive)
        assert manifest.dir_name == "ai.test.demo@1"

    def test_bad_zip_refused(self):
        with pytest.raises(PackagerError, match="install validation"):
            validate_archive(b"not-a-zip")

    def test_disallowed_layout_refused(self, manifest_dict):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("manifest.json", json.dumps(_full_manifest(manifest_dict)))
            zf.writestr("evil.exe", "boom")
        with pytest.raises(PackagerError, match="install validation"):
            validate_archive(buf.getvalue())


class TestManifestDependencies:
    def test_js_pins_locked_versions_python_keeps_constraints(self, manifest_dict):
        request = _request(manifest_dict,
                           dependencies={"packages": {"ai.test.base": "^1.0.0"}})
        report = _report(
            python=({"name": "pandas", "constraint": ">=2.0", "source": "declared",
                     "pinned": True},),
            js_lock={"marked": {"version": "12.0.0", "integrity": "sha512-x",
                                "resolved": "https://reg.test/m", "license": "MIT",
                                "requestedBy": "<draft>", "constraint": "*"}},
        )
        deps = manifest_dependencies_from_report(request, report)
        assert deps == {"python": {"pandas": ">=2.0"},
                        "js": {"marked": "12.0.0"},
                        "packages": {"ai.test.base": "^1.0.0"}}


class TestFinalize:
    def test_ready_result_with_provenance(self, tmp_curio, manifest_dict):
        request = _request(manifest_dict)
        plan = plan_create(request)
        report = _report()
        result = finalize_build(
            "guest", request, plan=plan, report=report,
            files=dict(request.files), bundle=b"registered",
            toolchain_version="esbuild/0.99.9-test", logs=("compiled",),
        )
        assert result.status == "ready"
        assert result.input_digest == request_digest(request)
        assert result.builder_version == f"{BUILDER_VERSION}+esbuild/0.99.9-test"
        assert result.archive_size > 0
        assert result.diff == plan.to_payload()
        assert result.dependencies["filesIntegrity"]["scripts/behaviors.js"]
        # The artifact is staged content-addressed and readable back.
        assert build_staging.has_artifact("guest", result.artifact_digest)
        staged = build_staging.read_artifact("guest", result.artifact_digest)
        assert validate_archive(staged).dir_name == "ai.test.demo@1"
        # Round-trips through the typed result contract.
        assert parse_build_result(result.to_payload()) == result

    def test_reproducible_artifact_digest(self, tmp_curio, manifest_dict):
        def _once():
            request = _request(manifest_dict)
            return finalize_build(
                "guest", request, plan=plan_create(request), report=_report(),
                files=dict(request.files), bundle=b"registered",
            ).artifact_digest

        assert _once() == _once()

    def test_blocked_report_refused(self, tmp_curio, manifest_dict):
        request = _request(manifest_dict)
        report = _report(findings=(Finding("block", "js-registry-missing", "no registry"),))
        with pytest.raises(PackagerError, match="policy blocked"):
            finalize_build("guest", request, plan=plan_create(request), report=report,
                           files=dict(request.files), bundle=None)

    def test_failed_result_carries_findings_no_artifact(self, manifest_dict):
        request = _request(manifest_dict)
        report = _report(findings=(Finding("block", "js-registry-missing", "no registry"),))
        result = failed_result(request, report, "dependency policy blocked the build",
                               toolchain_version="esbuild/0.99.9-test")
        assert result.status == "failed" and result.artifact_digest is None
        assert result.policy_findings == ("block:js-registry-missing: no registry",)
        assert "blocked" in result.warnings[0]
        assert parse_build_result(result.to_payload()) == result
