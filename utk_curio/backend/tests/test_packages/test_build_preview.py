"""Tests for :mod:`utk_curio.backend.app.packages.build_preview` (dev/89 commit 6):
sandbox document generation (CSP, guards, escaping), pinned-runner
resolution, the five contract states, report validation (registration,
console errors, dimensions, screenshots), and honest failure modes.

The "preview runner" here is a deterministic fake harness that reads the
plan, inspects marker comments inlined with the bundle, and writes the
report + screenshots the way the operator-installed headless harness would.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.packages.build_models import parse_build_request
from utk_curio.backend.app.packages.build_preview import (
    PREVIEW_STATES,
    PreviewError,
    build_preview_document,
    run_preview,
    runner_from_env,
    synthetic_fixtures,
)
from utk_curio.backend.app.packages.build_workspace import (
    create_workspace,
    destroy_workspace,
)

_FAKE_RUNNER = r'''#!/usr/bin/env python3
import json, os, sys

if "--version" in sys.argv:
    print("0.1.0-test")
    raise SystemExit(0)

plan = json.load(open(sys.argv[1], encoding="utf-8"))
out = os.environ["CURIO_BUILD_OUTPUT_DIR"]
report = {"contract": "1", "templates": {}}
doc = ""
for tpl in plan["templates"]:
    doc = open(tpl["document"], encoding="utf-8").read()
    if "//RUNNER-CRASH" in doc:
        sys.stderr.write("harness crashed\n")
        raise SystemExit(2)
    entry = {
        "registered": [] if "//NO-REGISTER" in doc else [tpl["behaviorKey"]],
        "states": {},
    }
    for state in tpl["states"]:
        if "//SKIP-STATE" in doc and state == "error":
            continue
        s = {
            "consoleErrors": (["TypeError: boom"]
                              if "//CONSOLE-ERROR" in doc and state == "success" else []),
            "width": 0 if "//ZERO-DIMS" in doc else 320,
            "height": 300,
            "screenshot": f"preview/{tpl['templateId']}/{state}.png",
        }
        if not ("//NO-SHOT" in doc and state == "empty"):
            p = os.path.join(out, "preview", tpl["templateId"], state + ".png")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(f"PNG:{tpl['templateId']}:{state}".encode())
        entry["states"][state] = s
    report["templates"][tpl["templateId"]] = entry

if "//NO-REPORT" not in doc:
    p = os.path.join(out, "preview", "report.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(report, open(p, "w"))
'''


@pytest.fixture()
def runner(tmp_path, monkeypatch):
    tool = tmp_path / "fake-preview-runner"
    tool.write_text(_FAKE_RUNNER, encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("CURIO_BUILD_PREVIEW_RUNNER", str(tool))
    resolved = runner_from_env()
    assert resolved is not None
    return resolved


def _request(preview_templates=("note-kind",), templates=None):
    return parse_build_request({
        "mode": "create",
        "target": "ai.test.demo@1",
        "manifest": {
            "id": "ai.test.demo", "compatibility": {"major": 1},
            "templates": templates or [{"id": "note-kind", "behavior": "note-postit"}],
        },
        "files": {"sources/a.tsx": {"text": "//A\n"}},
        "behaviorEntries": ["sources/a.tsx"],
        "previewTemplates": list(preview_templates),
    })


def _preview(request, bundle, runner):
    ws = create_workspace("preview-test")
    try:
        return run_preview(ws, request, bundle, runner=runner)
    finally:
        destroy_workspace(ws)


class TestRunnerResolution:
    def test_unconfigured_is_none(self, monkeypatch):
        monkeypatch.delenv("CURIO_BUILD_PREVIEW_RUNNER", raising=False)
        assert runner_from_env() is None

    def test_probe_records_version(self, runner):
        assert runner.version == "preview-runner/0.1.0-test"


class TestDocument:
    def test_sandbox_document_contents(self):
        request = _request()
        doc = build_preview_document(request, b"registerBehavior('note-postit')", "note-kind")
        assert "Content-Security-Policy" in doc and "default-src 'none'" in doc
        for guard in ("fetch", "XMLHttpRequest", "WebSocket", "localStorage",
                      "window.open"):
            assert guard in doc  # loud throwers, not silent stubs
        assert "'note-postit'" in doc or '"note-postit"' in doc
        assert "registerBehavior" in doc

    def test_bundle_script_escape(self):
        request = _request()
        doc = build_preview_document(request, b"var s = '</script><img src=x>'", "note-kind")
        assert "</script><img" not in doc  # escaped, cannot break out

    def test_deterministic(self):
        request = _request()
        a = build_preview_document(request, b"//A", "note-kind")
        b = build_preview_document(request, b"//A", "note-kind")
        assert a == b

    def test_fixtures_cover_contract_states(self):
        fixtures = synthetic_fixtures("note-kind")
        assert set(fixtures) == set(PREVIEW_STATES)
        assert fixtures["empty"]["content"] == ""
        assert fixtures["loading"]["loading"] is True
        assert "Markdown" in fixtures["success"]["content"]

    def test_fixtures_carry_both_content_spellings(self):
        """dev/90 A15: the runtime's canonical field is data.code; these
        fixtures taught 'content'. Both spellings ride every fixture so the
        preview exercises whichever one a behavior reads."""
        fixtures = synthetic_fixtures("note-kind")
        for state, fixture in fixtures.items():
            assert "code" in fixture and "content" in fixture, state
            assert fixture["code"] == fixture["content"], state

    def test_template_without_behavior_key_refused(self):
        request = _request(templates=[{"id": "note-kind"}])
        with pytest.raises(PreviewError, match="no behavior key"):
            build_preview_document(request, b"//A", "note-kind")

    def test_unknown_template_refused(self):
        request = _request()
        with pytest.raises(PreviewError, match="not in the draft manifest"):
            build_preview_document(request, b"//A", "ghost-kind")


class TestRunPreview:
    def test_skipped_without_bundle(self, runner):
        result = _preview(_request(), None, runner)
        assert result.status == "skipped"

    def test_no_runner_fails_honestly(self):
        result = _preview(_request(), b"//A", None)
        assert result.status == "failed"
        assert "CURIO_BUILD_PREVIEW_RUNNER" in result.reasons[0]
        assert "never applies" in result.reasons[0]

    def test_bundle_without_preview_templates_fails(self, runner):
        result = _preview(_request(preview_templates=()), b"//A", runner)
        assert result.status == "failed"
        assert "previewTemplates" in result.reasons[0]

    def test_happy_preview(self, runner):
        result = _preview(_request(), b"//A", runner)
        assert result.status == "ok", result.reasons
        assert result.registered["note-kind"] == ("note-postit",)
        assert set(result.screenshots) == {f"note-kind/{s}" for s in PREVIEW_STATES}
        assert result.states["note-kind"]["success"]["width"] == 320
        payload = result.to_payload()
        assert payload["status"] == "ok"
        assert payload["screenshots"]["note-kind/success"]["bytes"] > 0
        json.dumps(payload)  # provenance/review-card safe

    def test_multiple_templates(self, runner):
        request = _request(
            preview_templates=("note-kind", "card-kind"),
            templates=[{"id": "note-kind", "behavior": "note-postit"},
                       {"id": "card-kind", "behavior": "card-face"}],
        )
        result = _preview(request, b"//A", runner)
        assert result.status == "ok", result.reasons
        assert set(result.states) == {"note-kind", "card-kind"}
        assert len(result.screenshots) == 2 * len(PREVIEW_STATES)


class TestFailureModes:
    def test_runner_crash(self, runner):
        result = _preview(_request(), b"//RUNNER-CRASH", runner)
        assert result.status == "failed"
        assert "harness crashed" in result.reasons[0]

    def test_missing_report(self, runner):
        result = _preview(_request(), b"//NO-REPORT", runner)
        assert result.status == "failed"
        assert "no preview/report.json" in result.reasons[0]

    def test_console_errors_fail_the_state(self, runner):
        result = _preview(_request(), b"//CONSOLE-ERROR", runner)
        assert result.status == "failed"
        assert any("note-kind/success" in r and "TypeError: boom" in r
                   for r in result.reasons)

    def test_missing_state_fails(self, runner):
        result = _preview(_request(), b"//SKIP-STATE", runner)
        assert result.status == "failed"
        assert any("note-kind/error" in r and "never exercised" in r
                   for r in result.reasons)

    def test_unregistered_behavior_key_fails(self, runner):
        result = _preview(_request(), b"//NO-REGISTER", runner)
        assert result.status == "failed"
        assert any("never registered" in r for r in result.reasons)

    def test_zero_dimensions_fail(self, runner):
        result = _preview(_request(), b"//ZERO-DIMS", runner)
        assert result.status == "failed"
        assert any("dimensions" in r for r in result.reasons)

    def test_missing_screenshot_fails(self, runner):
        result = _preview(_request(), b"//NO-SHOT", runner)
        assert result.status == "failed"
        assert any("note-kind/empty" in r and "not produced" in r
                   for r in result.reasons)
        # The other states' screenshots still surfaced for the review card.
        assert "note-kind/success" in result.screenshots


class TestOperatorPreviewPolicy:
    """dev/90 A9 — the declared preview skip for runner-less deployments:
    explicit, recorded in provenance, never the silent default."""

    def test_default_stays_fail_closed(self, monkeypatch):
        monkeypatch.delenv("CURIO_BUILD_PREVIEW_POLICY", raising=False)
        result = _preview(_request(), b"//A", None)
        assert result.status == "failed"
        assert "CURIO_BUILD_PREVIEW_POLICY=skip" in result.reasons[0]

    def test_declared_skip_reaches_review_unpreviewed_and_says_so(self, monkeypatch):
        monkeypatch.setenv("CURIO_BUILD_PREVIEW_POLICY", "skip")
        result = _preview(_request(), b"//A", None)
        assert result.status == "skipped"
        assert "SKIPPED BY OPERATOR POLICY" in result.reasons[0]
        assert "NOT rendered" in result.reasons[0]
        payload = result.to_payload()
        assert payload["status"] == "skipped"  # provenance carries the skip

    def test_a_configured_runner_always_wins_over_the_policy(self, monkeypatch, runner):
        monkeypatch.setenv("CURIO_BUILD_PREVIEW_POLICY", "skip")
        result = _preview(_request(), b"//A", runner)
        assert result.status == "ok"  # rendered for real — policy irrelevant

    def test_unknown_policy_values_read_as_required(self, monkeypatch):
        monkeypatch.setenv("CURIO_BUILD_PREVIEW_POLICY", "yolo")
        result = _preview(_request(), b"//A", None)
        assert result.status == "failed"
