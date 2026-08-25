"""The reference preview runner (memo dev/98) — Playwright/Chromium behind
the ``CURIO_BUILD_PREVIEW_RUNNER`` seam dev/89 §3.7 designed.

Speaks EXACTLY the plan/report contract the build service already enforces
(and the test suite's fake runner pins): argv[1] is ``preview/plan.json``;
for every template the runner loads its CSP-locked document, injects the
HOST GLOBALS the document deliberately omits (React/ReactDOM — and ReactFlow
when baked — the same versioned runtime Curio ships), drives the five
contract states by rendering the captured behavior hook's
``contentComponent`` over each fixture, MEASURES the real bounding box,
screenshots the element, and writes
``$CURIO_BUILD_OUTPUT_DIR/preview/report.json`` plus one PNG per state.
Dimensions and screenshots are measured, never fabricated — a state that
fails to mount reports its console error and omits them, and the EXISTING
validator does the refusing (this file changes nothing under ``app/``).

Runs inside the build workspace's scrubbed worker env, so every location is
baked by the wrapper ``install_preview_runner`` generates:
``CURIO_PREVIEW_REACT_UMD`` / ``CURIO_PREVIEW_REACT_DOM_UMD``
(required), ``CURIO_PREVIEW_REACTFLOW_UMD`` (optional), and
``PLAYWRIGHT_BROWSERS_PATH``. The state driver passes
``nodeState = {appearance: data.appearance}`` so previews exercise BOTH
documented spellings (dev/90 A15) exactly as the live runtime provides them.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RUNNER_VERSION = "curio-preview-runner/1"

#: Injected before any document script: the per-state driver the runner
#: calls via page.evaluate. Render errors come back as data — the report
#: stays honest, the validator refuses.
_DRIVER_JS = """
window.__curioDrive = function (stateName) {
  var plan = window.__curioPreviewPlan || {};
  var hooks = window.__curioPreviewBehaviors || {};
  var hook = hooks[plan.behaviorKey];
  if (typeof hook !== 'function') {
    return { error: 'behavior key ' + plan.behaviorKey + ' is not registered' };
  }
  var fixture = (plan.states || {})[stateName];
  var root = document.getElementById('curio-preview-root');
  var R = window.React, RD = window.ReactDOM;
  if (!R || !RD) return { error: 'host React globals are missing' };
  var failure = null;
  var Probe = function () {
    var res;
    try {
      // dev/90 A15: nodeState carries the appearance spelling the live
      // runtime provides; the fixture itself carries code AND content.
      res = hook(fixture, { appearance: fixture && fixture.appearance });
    } catch (e) { failure = String(e); return null; }
    return (res && res.contentComponent) || null;
  };
  try {
    if (!window.__curioPreviewRoot) {
      window.__curioPreviewRoot = RD.createRoot(root);
    }
    RD.flushSync(function () {
      window.__curioPreviewRoot.render(R.createElement(Probe));
    });
  } catch (e) { return { error: String(e) }; }
  if (failure) return { error: failure };
  var rect = root.getBoundingClientRect();
  return { width: Math.round(rect.width), height: Math.round(rect.height) };
};
"""


def _version_line() -> str:
    try:
        from importlib.metadata import version as _dist_version

        pw_version = _dist_version("playwright")
    except Exception:  # pragma: no cover — the probe still answers
        pw_version = "unavailable"
    return f"{RUNNER_VERSION} playwright/{pw_version}"


def _required_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value or not Path(value).is_file():
        raise SystemExit(
            f"{name} is missing or does not point at a file — regenerate the "
            "wrapper: python -m utk_curio.tools.install_preview_runner"
        )
    return value


def main(argv: list[str]) -> int:
    if "--version" in argv:
        print(_version_line())
        return 0
    if len(argv) < 2:
        print("usage: preview_runner.py <plan.json>", file=sys.stderr)
        return 2
    plan_path = Path(argv[1])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    out_dir = Path(os.environ["CURIO_BUILD_OUTPUT_DIR"])

    react_src = Path(_required_env("CURIO_PREVIEW_REACT_UMD")).read_text(encoding="utf-8")
    react_dom_src = Path(_required_env("CURIO_PREVIEW_REACT_DOM_UMD")).read_text(encoding="utf-8")
    reactflow_path = (os.environ.get("CURIO_PREVIEW_REACTFLOW_UMD") or "").strip()
    reactflow_src = (
        Path(reactflow_path).read_text(encoding="utf-8")
        if reactflow_path and Path(reactflow_path).is_file() else None
    )

    from playwright.sync_api import sync_playwright

    report: dict = {"contract": str(plan.get("contract") or "1"), "templates": {}}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for template in plan.get("templates") or []:
                template_id = template["templateId"]
                page = browser.new_page(viewport={"width": 800, "height": 600})
                console_errors: list[str] = []
                page.on(
                    "console",
                    lambda msg: console_errors.append(msg.text)
                    if msg.type == "error" else None,
                )
                page.on("pageerror", lambda err: console_errors.append(str(err)))
                # The host globals the document deliberately omits, then the
                # driver — init scripts run before every document script.
                page.add_init_script(react_src)
                page.add_init_script(react_dom_src)
                if reactflow_src is not None:
                    page.add_init_script(reactflow_src)
                page.add_init_script(_DRIVER_JS)
                doc_path = Path(template["document"]).resolve()
                page.goto(doc_path.as_uri())

                registered = page.evaluate(
                    "() => (window.__curioPreview || {}).registered || []")
                entry: dict = {"registered": list(registered), "states": {}}
                guard_error_count = page.evaluate(
                    "() => ((window.__curioPreview || {}).errors || []).length")
                for state in template.get("states") or []:
                    errors_before = len(console_errors)
                    outcome = page.evaluate("(s) => window.__curioDrive(s)", state)
                    page.wait_for_timeout(30)  # let async errors surface
                    guard_errors = page.evaluate(
                        "() => ((window.__curioPreview || {}).errors || [])")
                    new_guard = list(guard_errors[guard_error_count:])
                    guard_error_count = len(guard_errors)
                    state_errors = console_errors[errors_before:] + new_guard
                    if isinstance(outcome, dict) and outcome.get("error"):
                        state_errors.append(str(outcome["error"]))
                    state_out: dict = {
                        "consoleErrors": [str(e)[:300] for e in state_errors[:10]],
                    }
                    if isinstance(outcome, dict) and "width" in outcome:
                        state_out["width"] = outcome.get("width")
                        state_out["height"] = outcome.get("height")
                        shot_rel = f"preview/{template_id}/{state}.png"
                        shot_path = out_dir / shot_rel
                        shot_path.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            element = page.query_selector("#curio-preview-root")
                            element.screenshot(path=str(shot_path))
                            state_out["screenshot"] = shot_rel
                        except Exception as exc:  # zero-size etc. — honest omission
                            state_out["consoleErrors"].append(
                                f"screenshot failed: {exc}"[:300])
                    entry["states"][state] = state_out
                report["templates"][template_id] = entry
                page.close()
        finally:
            browser.close()

    report_path = out_dir / str(plan.get("report") or "preview/report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
