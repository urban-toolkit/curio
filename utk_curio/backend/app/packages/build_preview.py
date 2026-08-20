"""Sandboxed visual preview of built behavior bundles (memo dev/89 §3.7).

A compiled behavior is never executed inside the agent chat UI or the live
canvas before review. Instead the builder renders it in a DISPOSABLE preview
document inside the restricted build workspace, driven by the
deployment-pinned preview runner (``CURIO_BUILD_PREVIEW_RUNNER`` — a
headless-browser harness the operator installs, version-probed into
provenance like the compiler's toolchain). No runner configured = an honest
failed preview; a preview failure blocks Apply for custom behavior — never
"probably fine".

The generated document is the sandbox:

* a restrictive CSP (``default-src 'none'``; inline script/style only;
  ``img-src data:``) — no network, no external assets;
* hard guards that replace ``fetch`` / ``XMLHttpRequest`` / ``WebSocket`` /
  ``localStorage`` / ``window.open`` / navigation with loud throwers, so a
  behavior that tries to reach credentials, storage, or the network fails
  the preview instead of silently succeeding;
* a stub ``window.curio`` runtime that CAPTURES ``registerBehavior`` calls
  (the report proves the expected behavior keys registered) and exposes a
  refusing ``backendUrl`` — live services are never called from preview;
* SYNTHETIC bounded fixtures for the five contract states — ``empty``,
  ``loading``, ``success``, ``malformed-input``, ``error`` — inlined as data.

The runner writes ``preview/report.json`` plus one screenshot per
template/state into the workspace output; :func:`run_preview` validates the
report (registration, per-state console errors, rendered dimensions,
screenshot presence) and returns a :class:`PreviewResult` whose payload the
review card renders — the captured artifact, not re-executed code.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Mapping

from utk_curio.backend.app.packages.build_models import PackageBuildRequest
from utk_curio.backend.app.packages.build_workspace import (
    BuildWorkspace,
    WorkerLimits,
    collect_outputs,
    run_worker,
)

log = logging.getLogger(__name__)

PREVIEW_CONTRACT_VERSION = "1"

#: The contract states every previewed template must survive (dev/89 §3.7).
PREVIEW_STATES = ("empty", "loading", "success", "malformed-input", "error")

# Rendered-dimension sanity bounds: a 0×0 render means the behavior drew
# nothing; anything beyond the cap is a runaway layout.
MIN_RENDER_PX = 1
MAX_RENDER_PX = 4000

_MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024
_REPORT_PATH = "preview/report.json"


class PreviewError(ValueError):
    """Raised on preview-runner misuse (bad arguments, malformed plans)."""


@dataclass(frozen=True)
class PreviewRunner:
    """The deployment-pinned preview harness (operator-installed)."""

    runner_path: str
    version: str


def runner_from_env() -> PreviewRunner | None:
    """Resolve the pinned runner from ``CURIO_BUILD_PREVIEW_RUNNER``, probing
    its version for provenance. None when unconfigured or unusable."""
    path = (os.environ.get("CURIO_BUILD_PREVIEW_RUNNER") or "").strip()
    if not path:
        return None
    try:
        probe = subprocess.run(  # noqa: S603 — operator-pinned binary, fixed argv
            [path, "--version"],
            capture_output=True, text=True, timeout=10,
            env={"PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("CURIO_BUILD_PREVIEW_RUNNER %r is not runnable: %s", path, exc)
        return None
    version = (probe.stdout or probe.stderr or "").strip().splitlines()[:1]
    if probe.returncode != 0 or not version:
        log.warning("CURIO_BUILD_PREVIEW_RUNNER %r failed the version probe", path)
        return None
    return PreviewRunner(runner_path=path, version=f"preview-runner/{version[0]}")


def preview_policy_from_env() -> str:
    """dev/90 A9: ``CURIO_BUILD_PREVIEW_POLICY`` — ``required`` (default) or
    ``skip``. ``skip`` is an OPERATOR DECLARATION for deployments without a
    pinned runner (local dev): a custom behavior then reaches review
    UNPREVIEWED, and the result says so in its provenance — declared and
    loud, never silent (the DEC-057 declaration posture). Unknown values
    read as ``required`` (fail closed)."""
    value = (os.environ.get("CURIO_BUILD_PREVIEW_POLICY") or "required").strip().lower()
    return value if value in ("required", "skip") else "required"


def synthetic_fixtures(template_id: str) -> dict[str, Any]:
    """Deterministic bounded fixture inputs, one per contract state.

    Synthetic by design (dev/89 §3.7): no project data, no transcripts, no
    live endpoints — the preview proves the behavior's states render, not
    that real data exists.
    """
    return {
        "empty": {"content": ""},
        "loading": {"content": None, "loading": True},
        "success": {
            "content": (
                f"# Preview of {template_id}\n\n"
                "Representative **Markdown** body with a [link](https://example.test), "
                "a list:\n\n- one\n- two\n\nand a short paragraph of findings text."
            ),
        },
        "malformed-input": {"content": {"unexpected": ["shape", 42]}},
        "error": {"content": "", "error": "synthetic preview error"},
    }


def _inline_json(value: Any) -> str:
    """JSON safe to inline inside a ``<script>`` element."""
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _inline_script(code: str) -> str:
    return code.replace("</script", "<\\/script")


_SANDBOX_GUARDS = """
(function () {
  'use strict';
  var refused = function (name) {
    return function () {
      window.__curioPreview.violations.push(name);
      throw new Error(name + ' is disabled in the preview sandbox');
    };
  };
  window.__curioPreview = { registered: [], errors: [], violations: [] };
  window.fetch = refused('fetch');
  window.XMLHttpRequest = refused('XMLHttpRequest');
  window.WebSocket = refused('WebSocket');
  window.EventSource = refused('EventSource');
  window.open = refused('window.open');
  try {
    Object.defineProperty(window, 'localStorage', { get: refused('localStorage') });
    Object.defineProperty(window, 'sessionStorage', { get: refused('sessionStorage') });
    Object.defineProperty(window, 'indexedDB', { get: refused('indexedDB') });
  } catch (e) { /* already locked down by the harness */ }
  window.addEventListener('error', function (e) {
    window.__curioPreview.errors.push(String(e.message || e.error || 'error'));
  });
  window.addEventListener('unhandledrejection', function (e) {
    window.__curioPreview.errors.push('unhandledrejection: ' + String(e.reason));
  });
  window.curio = {
    registerBehavior: function (key, hook) {
      window.__curioPreview.registered.push(String(key));
      window.__curioPreviewBehaviors = window.__curioPreviewBehaviors || {};
      window.__curioPreviewBehaviors[String(key)] = hook;
    },
    backendUrl: 'about:blank',
    request: refused('curio.request'),
  };
})();
"""


def build_preview_document(
    request: PackageBuildRequest,
    bundle: bytes,
    template_id: str,
) -> str:
    """One self-contained sandboxed HTML document for *template_id*.

    The harness provides React/ReactDOM/ReactFlow (the same versioned host
    runtime Curio ships) and drives the states; everything else — CSP,
    guards, the captured registry, the bundle, the fixtures — is inline
    here, deterministic for identical inputs.
    """
    fixtures = synthetic_fixtures(template_id)
    behavior_key = _behavior_key(request, template_id)
    return (
        "<!doctype html>\n"
        "<html><head>\n"
        '<meta charset="utf-8">\n'
        '<meta http-equiv="Content-Security-Policy" content="'
        "default-src 'none'; script-src 'unsafe-inline'; "
        "style-src 'unsafe-inline'; img-src data:\">\n"
        f"<title>curio preview {template_id}</title>\n"
        f"<script>{_SANDBOX_GUARDS}</script>\n"
        "</head><body>\n"
        '<div id="curio-preview-root"></div>\n'
        "<script>window.__curioPreviewPlan = "
        f"{_inline_json({'contract': PREVIEW_CONTRACT_VERSION, 'templateId': template_id, 'behaviorKey': behavior_key, 'states': fixtures})};"
        "</script>\n"
        f"<script>{_inline_script(bundle.decode('utf-8', errors='replace'))}</script>\n"
        "</body></html>\n"
    )


def _behavior_key(request: PackageBuildRequest, template_id: str) -> str:
    for template in request.manifest.get("templates") or []:
        if isinstance(template, dict) and template.get("id") == template_id:
            key = template.get("behavior")
            if isinstance(key, str) and key.strip():
                return key
            raise PreviewError(
                f"preview template {template_id!r} declares no behavior key — "
                "a custom-behavior template must name the hook it renders with"
            )
    raise PreviewError(f"preview template {template_id!r} is not in the draft manifest")


@dataclass(frozen=True)
class PreviewResult:
    """The captured preview outcome. ``ok`` gates Apply for custom behavior;
    ``skipped`` is legal only when the build ships no behavior bundle."""

    status: str  # "ok" | "failed" | "skipped"
    runner_version: str = ""
    reasons: tuple[str, ...] = ()
    states: dict[str, Any] = field(default_factory=dict)  # templateId -> state payloads
    registered: dict[str, tuple[str, ...]] = field(default_factory=dict)
    screenshots: dict[str, bytes] = field(default_factory=dict)  # "tpl/state" -> png

    def to_payload(self) -> dict[str, Any]:
        """JSON-safe payload for the result/provenance — screenshots by
        digest+size only; the caller owns byte storage."""
        import hashlib

        return {
            "contract": PREVIEW_CONTRACT_VERSION,
            "status": self.status,
            "runnerVersion": self.runner_version,
            "reasons": list(self.reasons),
            "states": self.states,
            "registered": {k: list(v) for k, v in sorted(self.registered.items())},
            "screenshots": {
                key: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                for key, data in sorted(self.screenshots.items())
            },
        }


def _validate_template_report(
    template_id: str,
    behavior_key: str,
    template_report: Any,
    outputs: Mapping[str, bytes],
    reasons: list[str],
    screenshots: dict[str, bytes],
) -> dict[str, Any]:
    states_out: dict[str, Any] = {}
    if not isinstance(template_report, dict):
        reasons.append(f"{template_id}: report entry is not an object")
        return states_out
    registered = template_report.get("registered")
    if not isinstance(registered, list) or behavior_key not in registered:
        reasons.append(
            f"{template_id}: behavior key {behavior_key!r} was never registered "
            "by the bundle"
        )
    raw_states = template_report.get("states")
    if not isinstance(raw_states, dict):
        reasons.append(f"{template_id}: report has no states object")
        return states_out
    for state in PREVIEW_STATES:
        entry = raw_states.get(state)
        if not isinstance(entry, dict):
            reasons.append(f"{template_id}/{state}: state was never exercised")
            continue
        state_out: dict[str, Any] = {}
        console_errors = entry.get("consoleErrors") or []
        if not isinstance(console_errors, list):
            console_errors = ["<malformed consoleErrors>"]
        state_out["consoleErrors"] = [str(e)[:300] for e in console_errors[:10]]
        if console_errors:
            # Even the 'error' state renders an error UI — it never throws.
            reasons.append(
                f"{template_id}/{state}: runtime/console errors: "
                + "; ".join(state_out["consoleErrors"][:3])
            )
        width, height = entry.get("width"), entry.get("height")
        state_out["width"], state_out["height"] = width, height
        if not (isinstance(width, int) and isinstance(height, int)
                and MIN_RENDER_PX <= width <= MAX_RENDER_PX
                and MIN_RENDER_PX <= height <= MAX_RENDER_PX):
            reasons.append(
                f"{template_id}/{state}: rendered dimensions {width}×{height} are "
                f"outside [{MIN_RENDER_PX}, {MAX_RENDER_PX}]"
            )
        shot_rel = entry.get("screenshot")
        shot = outputs.get(shot_rel) if isinstance(shot_rel, str) else None
        if not shot_rel or not isinstance(shot_rel, str) or not shot_rel.startswith("preview/"):
            reasons.append(f"{template_id}/{state}: no screenshot path in the report")
        elif shot is None or not shot:
            reasons.append(f"{template_id}/{state}: screenshot {shot_rel!r} was not produced")
        elif len(shot) > _MAX_SCREENSHOT_BYTES:
            reasons.append(f"{template_id}/{state}: screenshot exceeds the size cap")
        else:
            screenshots[f"{template_id}/{state}"] = shot
            state_out["screenshot"] = shot_rel
        states_out[state] = state_out
    return states_out


def run_preview(
    workspace: BuildWorkspace,
    request: PackageBuildRequest,
    bundle: bytes | None,
    *,
    runner: PreviewRunner | None,
    limits: WorkerLimits | None = None,
    cancel: threading.Event | None = None,
) -> PreviewResult:
    """Render every requested preview template through the pinned runner.

    Returns ``skipped`` only when there is no bundle (nothing custom to
    prove). With a bundle: no runner, no declared preview templates, a
    runner failure, or any state/registration/screenshot violation all
    return ``failed`` — and a failed preview blocks Apply (dev/89 §3.7).
    """
    if bundle is None:
        return PreviewResult(status="skipped",
                             reasons=("no behavior bundle — preview not required",))
    if runner is None:
        if preview_policy_from_env() == "skip":
            # dev/90 A9: the operator declared preview-less operation — the
            # draft reaches review UNPREVIEWED and its provenance says so.
            return PreviewResult(
                status="skipped",
                reasons=(
                    "preview SKIPPED BY OPERATOR POLICY "
                    "(CURIO_BUILD_PREVIEW_POLICY=skip; no pinned runner is "
                    "configured) — this custom behavior was NOT rendered "
                    "before review",
                ),
            )
        return PreviewResult(
            status="failed",
            reasons=(
                "no pinned preview runner is configured for this deployment "
                "(CURIO_BUILD_PREVIEW_RUNNER) — custom behavior cannot be "
                "previewed, and an unpreviewed custom behavior never applies "
                "(operators without a runner may declare "
                "CURIO_BUILD_PREVIEW_POLICY=skip; the skip is recorded in the "
                "draft's provenance)",
            ),
        )
    if not request.preview_templates:
        return PreviewResult(
            status="failed", runner_version=runner.version,
            reasons=(
                "a build with custom behavior must declare previewTemplates — "
                "every custom look is previewed before review",
            ),
        )

    preview_dir = workspace.work_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    plan_templates = []
    behavior_keys: dict[str, str] = {}
    for template_id in request.preview_templates:
        behavior_keys[template_id] = _behavior_key(request, template_id)
        doc = build_preview_document(request, bundle, template_id)
        doc_path = preview_dir / f"{template_id}.html"
        doc_path.write_text(doc, encoding="utf-8")
        plan_templates.append({
            "templateId": template_id,
            "behaviorKey": behavior_keys[template_id],
            "document": f"preview/{template_id}.html",
            "states": list(PREVIEW_STATES),
        })
    plan_path = preview_dir / "plan.json"
    plan_path.write_text(json.dumps({
        "contract": PREVIEW_CONTRACT_VERSION,
        "templates": plan_templates,
        "report": _REPORT_PATH,
    }, indent=2), encoding="utf-8")

    worker = run_worker(
        workspace, [runner.runner_path, str(plan_path)],
        limits=limits or WorkerLimits(),
        cancel=cancel,
    )
    if worker.status != "ok":
        return PreviewResult(
            status="failed", runner_version=runner.version,
            reasons=(f"preview runner {worker.status} (exit {worker.exit_code}): "
                     f"{worker.stderr_tail or worker.stdout_tail}",),
        )

    outputs = collect_outputs(workspace)
    raw_report = outputs.get(_REPORT_PATH)
    if raw_report is None:
        return PreviewResult(
            status="failed", runner_version=runner.version,
            reasons=("preview runner exited 0 but wrote no preview/report.json",),
        )
    try:
        report = json.loads(raw_report.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return PreviewResult(
            status="failed", runner_version=runner.version,
            reasons=(f"preview report is not valid JSON: {exc}",),
        )

    reasons: list[str] = []
    screenshots: dict[str, bytes] = {}
    states: dict[str, Any] = {}
    registered: dict[str, tuple[str, ...]] = {}
    template_reports = report.get("templates") if isinstance(report, dict) else None
    if not isinstance(template_reports, dict):
        reasons.append("preview report has no templates object")
        template_reports = {}
    for template_id in request.preview_templates:
        entry = template_reports.get(template_id)
        if entry is None:
            reasons.append(f"{template_id}: missing from the preview report")
            continue
        states[template_id] = _validate_template_report(
            template_id, behavior_keys[template_id], entry, outputs, reasons, screenshots,
        )
        raw_registered = entry.get("registered") if isinstance(entry, dict) else None
        if isinstance(raw_registered, list):
            registered[template_id] = tuple(str(k) for k in raw_registered[:20])

    return PreviewResult(
        status="failed" if reasons else "ok",
        runner_version=runner.version,
        reasons=tuple(reasons),
        states=states,
        registered=registered,
        screenshots=screenshots,
    )
