"""Tests for :mod:`utk_curio.backend.app.packages.build_pipeline` (dev/89 commit 7):
phase composition over commits 2–6, failure provenance, digest idempotency,
extend-mode preservation, and stale-base fast failure.

Reuses the deterministic fake esbuild / preview-runner harnesses and the
fake registry fetcher from the sibling test modules.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from utk_curio.backend.app.packages import build_jobs, build_staging
from utk_curio.backend.app.packages.build_compiler import toolchain_from_env
from utk_curio.backend.app.packages.build_deps import DependencyPolicy
from utk_curio.backend.app.packages.build_extension import installed_package_digest
from utk_curio.backend.app.packages.build_models import parse_build_request
from utk_curio.backend.app.packages.build_pipeline import run_build
from utk_curio.backend.app.packages.build_preview import runner_from_env
from utk_curio.backend.tests.test_packages.test_build_compiler import _FAKE_ESBUILD
from utk_curio.backend.tests.test_packages.test_build_deps import FakeFetcher
from utk_curio.backend.tests.test_packages.test_build_preview import _FAKE_RUNNER


@pytest.fixture(autouse=True)
def _fresh_jobs():
    build_jobs.reset_registry()
    yield
    build_jobs.reset_registry()


@pytest.fixture()
def toolchain(tmp_path, monkeypatch):
    tool = tmp_path / "fake-esbuild"
    tool.write_text(_FAKE_ESBUILD, encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("CURIO_BUILD_ESBUILD", str(tool))
    return toolchain_from_env()


@pytest.fixture()
def preview_runner(tmp_path, monkeypatch):
    tool = tmp_path / "fake-preview-runner"
    tool.write_text(_FAKE_RUNNER, encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("CURIO_BUILD_PREVIEW_RUNNER", str(tool))
    return runner_from_env()


def _plain_kind(template_id: str = "demo-kind") -> dict:
    return {
        "id": template_id, "label": "Demo", "category": "computation",
        "engine": "python", "editor": "code", "hasCode": True,
        "hasWidgets": False, "hasGrammar": False,
        "inputPorts": [], "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
        "templateDir": f"starters/{template_id}",
        "defaultTemplate": f"starters/{template_id}/Default.py",
    }


def _note_kind() -> dict:
    return {
        "id": "note-kind", "label": "Research note", "category": "visualization",
        "engine": "javascript", "editor": "code", "behavior": "note-postit",
        "hasCode": True, "hasWidgets": False, "hasGrammar": False,
        "inputPorts": [], "outputPorts": [],
        "templateDir": "starters/note-kind",
        "defaultTemplate": "starters/note-kind/Default.js",
    }


def _manifest(manifest_dict, kinds, version="1.0.0"):
    return manifest_dict(kinds=kinds, version=version)


def _plain_request(manifest_dict):
    return parse_build_request({
        "mode": "create", "target": "ai.test.demo@1",
        "manifest": _manifest(manifest_dict, [_plain_kind()]),
        "files": {"starters/demo-kind/Default.py": {"text": "return arg\n"}},
    })


def _behavior_request(manifest_dict, *, marker: str = "//A"):
    return parse_build_request({
        "mode": "create", "target": "ai.test.demo@1",
        "manifest": _manifest(manifest_dict, [_note_kind()]),
        "files": {
            "starters/note-kind/Default.js": {"text": "return arg\n"},
            "sources/note.tsx": {"text": f'import {{marked}} from "marked"\n{marker}\n'},
        },
        "behaviorEntries": ["sources/note.tsx"],
        "dependencies": {"js": {"marked": "12.0.0"}},
        "previewTemplates": ["note-kind"],
    })


class TestCreatePipeline:
    def test_plain_package_skips_compile_and_preview(self, tmp_curio, manifest_dict):
        job = run_build("guest", _plain_request(manifest_dict),
                        toolchain=None, preview_runner=None)
        assert job.phase == "ready", job.to_payload()
        phases = [e["phase"] for e in job.events]
        assert "compiling" not in phases and "previewing" not in phases
        assert job.result.status == "ready" and job.result.preview is None
        assert build_staging.has_artifact("guest", job.result.artifact_digest)

    def test_full_behavior_pipeline(self, tmp_curio, manifest_dict, toolchain,
                                    preview_runner):
        fetcher = FakeFetcher({"marked": {"12.0.0": {}}})
        job = run_build("guest", _behavior_request(manifest_dict),
                        fetcher=fetcher, policy=DependencyPolicy(),
                        toolchain=toolchain, preview_runner=preview_runner)
        assert job.phase == "ready", job.to_payload()
        phases = [e["phase"] for e in job.events]
        assert phases == ["queued", "resolving", "compiling", "previewing",
                          "packaging", "ready"]
        result = job.result
        assert result.preview["status"] == "ok"
        assert result.dependencies["sbom"]["js"]["lock"]["marked"]["version"] == "12.0.0"
        assert "esbuild/0.99.9-test" in result.builder_version
        archive = build_staging.read_artifact("guest", result.artifact_digest)
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            names = set(zf.namelist())
        assert "scripts/behaviors.js" in names
        assert "sources/note.tsx" in names  # behavior SOURCE ships too

    def test_idempotent_by_digest(self, tmp_curio, manifest_dict):
        first = run_build("guest", _plain_request(manifest_dict),
                          toolchain=None, preview_runner=None)
        second = run_build("guest", _plain_request(manifest_dict),
                           toolchain=None, preview_runner=None)
        assert second is first and second.phase == "ready"


class TestFailureProvenance:
    def test_blocked_dependencies_fail_with_result(self, tmp_curio, manifest_dict):
        job = run_build("guest", _behavior_request(manifest_dict),
                        fetcher=None, policy=DependencyPolicy(),
                        toolchain=None, preview_runner=None)
        assert job.phase == "failed"
        assert job.result is not None and job.result.status == "failed"
        assert any("js-registry-missing" in f for f in job.result.policy_findings)

    def test_compile_failure(self, tmp_curio, manifest_dict, toolchain, preview_runner):
        fetcher = FakeFetcher({"marked": {"12.0.0": {}}})
        job = run_build("guest", _behavior_request(manifest_dict, marker="//FAIL"),
                        fetcher=fetcher, policy=DependencyPolicy(),
                        toolchain=toolchain, preview_runner=preview_runner)
        assert job.phase == "failed"
        assert job.result.status == "failed"
        assert any("compile failed" in w for w in job.result.warnings)

    def test_no_toolchain_fails_honestly(self, tmp_curio, manifest_dict, preview_runner):
        fetcher = FakeFetcher({"marked": {"12.0.0": {}}})
        job = run_build("guest", _behavior_request(manifest_dict),
                        fetcher=fetcher, policy=DependencyPolicy(),
                        toolchain=None, preview_runner=preview_runner)
        assert job.phase == "failed"
        assert any("CURIO_BUILD_ESBUILD" in w or "toolchain" in w
                   for w in job.result.warnings)

    def test_preview_failure(self, tmp_curio, manifest_dict, toolchain, preview_runner):
        fetcher = FakeFetcher({"marked": {"12.0.0": {}}})
        job = run_build("guest", _behavior_request(manifest_dict, marker="//NO-REGISTER"),
                        fetcher=fetcher, policy=DependencyPolicy(),
                        toolchain=toolchain, preview_runner=preview_runner)
        assert job.phase == "failed"
        assert any("preview failed" in w for w in job.result.warnings)


class TestExtendPipeline:
    def _base(self, install_packageage, manifest_dict):
        manifest = _manifest(manifest_dict, [_plain_kind()])
        install_packageage("guest", manifest=manifest,
                           sources={"demo-kind": {"Default.py": "def run():\n    return {}\n"}})
        return manifest

    def test_extend_preserves_base_files(self, tmp_curio, install_packageage,
                                         manifest_dict):
        base_manifest = self._base(install_packageage, manifest_dict)
        base_digest = installed_package_digest("guest", "ai.test.demo@1")
        draft = dict(base_manifest, version="1.1.0",
                     templates=list(base_manifest["templates"]) + [dict(_plain_kind("extra-kind"))])
        request = parse_build_request({
            "mode": "extend", "target": "ai.test.demo@1",
            "baseDigest": base_digest, "manifest": draft,
            "files": {"starters/extra-kind/Default.py": {"text": "return 2\n"}},
        })
        job = run_build("guest", request, toolchain=None, preview_runner=None)
        assert job.phase == "ready", job.to_payload()
        archive = build_staging.read_artifact("guest", job.result.artifact_digest)
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            names = set(zf.namelist())
            preserved = zf.read("starters/demo-kind/Default.py")
        assert "starters/extra-kind/Default.py" in names
        assert preserved == b"def run():\n    return {}\n"
        assert job.result.diff["files"]["preserved"] == ["starters/demo-kind/Default.py"]

    def test_stale_base_fails_before_expensive_work(self, tmp_curio,
                                                    install_packageage, manifest_dict):
        base_manifest = self._base(install_packageage, manifest_dict)
        draft = dict(base_manifest, version="1.1.0")
        request = parse_build_request({
            "mode": "extend", "target": "ai.test.demo@1",
            "baseDigest": "e" * 64, "manifest": draft, "files": {},
        })
        job = run_build("guest", request, toolchain=None, preview_runner=None)
        assert job.phase == "failed"
        assert any("stale" in e["message"] for e in job.events)
