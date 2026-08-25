"""memo dev/98 — the reference preview runner (REAL Playwright/Chromium; the
A9 real-toolchain rule). Environment-guarded with an honest skip reason: the
runner is an operator tool, and machines without playwright/chromium skip
these instead of faking a browser."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from utk_curio.backend.app.packages.build_models import parse_build_request
from utk_curio.backend.app.packages.build_preview import run_preview, runner_from_env
from utk_curio.backend.app.packages.build_workspace import (
    WorkerLimits,
    create_workspace,
    destroy_workspace,
)
from utk_curio.tools import install_preview_runner as installer

#: Chromium startup dominates; generous wall, honest CPU.
PREVIEW_LIMITS = WorkerLimits(wall_time_seconds=90.0, cpu_seconds=60)


def _require_browser() -> None:
    pytest.importorskip(
        "playwright.sync_api",
        reason="reference-runner E2E needs the playwright package")
    try:
        installer._browsers_path()
    except SystemExit as exc:
        pytest.skip(f"reference-runner E2E skipped: {exc}")


@pytest.fixture()
def wrapper(tmp_path) -> Path:
    _require_browser()
    return installer.generate(tmp_path / "preview-runner")


def _preview_request():
    return parse_build_request({
        "mode": "create",
        "manifest": {
            "id": "ai.test.preview", "version": "1.0.0", "name": "P",
            "publisher": "t", "description": "d", "compatibility": {"major": 1},
            "permissions": [], "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [{
                "id": "note-kind", "label": "Note", "category": "visualization",
                "engine": "javascript", "editor": "none", "hasCode": False,
                "behavior": "note-behavior", "inputPorts": [], "outputPorts": [],
            }],
        },
        "files": {"sources/note.tsx": {"text": "// source\n"}},
        "behaviorEntries": ["sources/note.tsx"],
        "previewTemplates": ["note-kind"],
    })


_GOOD_BUNDLE = b"""
(function(){
  var R = window.React;
  window.curio.registerBehavior('note-behavior', function(data, nodeState){
    var text = data && (data.content !== undefined ? data.content : data.code);
    if (data && data.loading) text = 'loading...';
    else if (data && data.error) text = 'error: ' + data.error;
    else if (text === null || text === undefined || text === '') text = 'empty note';
    else text = String(text);
    var color = (nodeState && nodeState.appearance
                 && nodeState.appearance.backgroundColor) || '#fef3c0';
    return {contentComponent: R.createElement('div',
      {style: {padding: '16px', width: '280px', background: color}}, text)};
  });
})();
"""

#: Explodes exactly in the 'error' contract state — the failure twin.
_THROWING_BUNDLE = b"""
(function(){
  var R = window.React;
  window.curio.registerBehavior('note-behavior', function(data, nodeState){
    if (data && data.error) { throw new Error('render exploded'); }
    return {contentComponent: R.createElement('div',
      {style: {padding: '16px'}}, 'fine')};
  });
})();
"""


class TestGenerator:
    def test_wrapper_bakes_every_path_and_probes(self, wrapper):
        text = wrapper.read_text(encoding="utf-8")
        assert "PLAYWRIGHT_BROWSERS_PATH=" in text
        assert "react.production.min.js" in text
        assert "react-dom.production.min.js" in text
        assert sys.executable in text
        assert os.access(wrapper, os.X_OK)
        # The scrubbed-env probe — exactly what runner_from_env runs.
        probe = subprocess.run(
            [str(wrapper), "--version"], capture_output=True, text=True,
            timeout=30, env={"PATH": "/usr/bin:/bin"})
        assert probe.returncode == 0
        assert "curio-preview-runner/1 playwright/" in probe.stdout

    def test_missing_umd_refuses_naming_the_fix(self, tmp_path, monkeypatch):
        _require_browser()
        monkeypatch.setattr(installer, "_node_modules", lambda: tmp_path / "ghost")
        with pytest.raises(SystemExit) as exc:
            installer.generate(tmp_path / "w")
        assert "React's UMD build" in str(exc.value)
        assert "npm install" in str(exc.value)
        assert not (tmp_path / "w").exists()  # never a wrapper that lies later

    def test_missing_browser_cache_refuses_naming_the_install(
            self, tmp_path, monkeypatch):
        pytest.importorskip("playwright.sync_api")
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "empty"))
        with pytest.raises(SystemExit) as exc:
            installer.generate(tmp_path / "w")
        assert "playwright install chromium" in str(exc.value)

    def test_runner_from_env_probes_the_wrapper(self, wrapper, monkeypatch):
        monkeypatch.setenv("CURIO_BUILD_PREVIEW_RUNNER", str(wrapper))
        runner = runner_from_env()
        assert runner is not None
        assert "curio-preview-runner/1" in runner.version


class TestRealPreview:
    def _run(self, wrapper, bundle, monkeypatch):
        monkeypatch.setenv("CURIO_BUILD_PREVIEW_RUNNER", str(wrapper))
        workspace = create_workspace("ref-runner-test")
        try:
            return run_preview(workspace, _preview_request(), bundle,
                               runner=runner_from_env(), limits=PREVIEW_LIMITS)
        finally:
            destroy_workspace(workspace)

    def test_five_states_render_with_real_dimensions_and_screenshots(
            self, wrapper, monkeypatch):
        result = self._run(wrapper, _GOOD_BUNDLE, monkeypatch)
        assert result.status == "ok", result.reasons
        assert result.registered == {"note-kind": ("note-behavior",)}
        states = result.states["note-kind"]
        assert sorted(states) == ["empty", "error", "loading",
                                  "malformed-input", "success"]
        for state, payload in states.items():
            assert payload["consoleErrors"] == [], (state, payload)
            assert payload["width"] >= 1 and payload["height"] >= 1  # MEASURED
        # Real PNGs, one per state, collected through the validator.
        assert sorted(result.screenshots) == [
            f"note-kind/{s}" for s in sorted(states)]
        for shot in result.screenshots.values():
            assert shot.startswith(b"\x89PNG")
        assert "curio-preview-runner/1" in result.runner_version

    def test_a_state_that_throws_fails_the_preview_naming_it(
            self, wrapper, monkeypatch):
        result = self._run(wrapper, _THROWING_BUNDLE, monkeypatch)
        assert result.status == "failed"
        joined = " | ".join(result.reasons)
        assert "note-kind/error" in joined
        assert "render exploded" in joined
        # The healthy states still rendered honestly.
        assert result.states["note-kind"]["success"]["consoleErrors"] == []

    def test_unregistered_behavior_key_fails(self, wrapper, monkeypatch):
        result = self._run(wrapper, b"// registers nothing\n", monkeypatch)
        assert result.status == "failed"
        assert any("never registered" in r for r in result.reasons)


class TestSchemaAgreementWithTheFake:
    def test_reference_report_satisfies_the_fake_pinned_shape(
            self, wrapper, monkeypatch, tmp_path):
        # One schema, two runners (the A15 rule): drive the REAL runner over
        # a plan directly and assert the report parses under the exact keys
        # the test fake (_FAKE_RUNNER) encodes.
        _ = monkeypatch
        workspace = create_workspace("ref-schema-test")
        try:
            from utk_curio.backend.app.packages.build_preview import (
                build_preview_document,
            )

            request = _preview_request()
            preview_dir = workspace.work_dir / "preview"
            preview_dir.mkdir(parents=True)
            (preview_dir / "note-kind.html").write_text(
                build_preview_document(request, _GOOD_BUNDLE, "note-kind"),
                encoding="utf-8")
            plan = {"contract": "1", "templates": [{
                "templateId": "note-kind", "behaviorKey": "note-behavior",
                "document": "preview/note-kind.html",
                "states": ["empty", "success"],
            }], "report": "preview/report.json"}
            (preview_dir / "plan.json").write_text(json.dumps(plan),
                                                   encoding="utf-8")
            from utk_curio.backend.app.packages.build_workspace import run_worker

            worker = run_worker(
                workspace,
                [str(wrapper), str(preview_dir / "plan.json")],
                limits=PREVIEW_LIMITS)
            assert worker.status == "ok", (worker.stderr_tail, worker.stdout_tail)
            report = json.loads(
                (workspace.output_dir / "preview" / "report.json").read_text())
            entry = report["templates"]["note-kind"]
            assert entry["registered"] == ["note-behavior"]
            for state in ("empty", "success"):
                s = entry["states"][state]
                assert set(s) >= {"consoleErrors", "width", "height", "screenshot"}
                assert s["screenshot"].startswith("preview/")
                assert (workspace.output_dir / s["screenshot"]).is_file()
        finally:
            destroy_workspace(workspace)
