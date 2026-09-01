"""Recording harness for the Curio stress tour.

``tour.py`` knows how to make a screencast look like a screencast: a synthetic
cursor, a spotlight ring, captions paced to their own word count, and a webm at
the end. What it does not do is *notice things going wrong* - the feature tour
shows each feature's happy path once and fails at the end naming the scenes that
raised.

A stress run is the other shape. It drives every surface, deliberately including
the paths that are supposed to refuse (an invalid connection, a node that
raises, a re-imported archive), and its primary deliverable is a list of
defects, each pointing at the second of video where it happened. So this module
adds three things on top of ``tour.py``:

``Probe``
    Passive listeners for everything the app says without being asked: console
    errors, uncaught page errors, failed requests, 4xx/5xx responses, and the
    toasts, which are caught with a MutationObserver because ``showToast``
    removes each one after five seconds.

``StressRun.step``
    A context manager around every interaction. It timestamps the step against
    the start of the recording, lets it raise without ending the chapter, writes
    a screenshot of the moment it broke, and attributes whatever the probe heard
    to that step.

``EXPECTED``
    An allowlist of documented-by-design outcomes. A stress run that reports the
    package re-import 400 as a bug is a stress run nobody reads twice.

The UI helpers at the bottom are lifted from ``test_feature_tour_video.py`` so
both recorders share one copy.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect

from .tour import REPO_ROOT, VIDEO_SIZE, Tour, finalize_video
from .utils import (
    CANVAS_DROP_TARGET,
    _DRAG_TO_CANVAS_JS,
    canvas_nodes,
    dismiss_toasts,
    node_locator,
)

__all__ = [
    "REPO_ROOT",
    "VIDEO_SIZE",
    "Tour",
    "Issue",
    "Probe",
    "StressRun",
    "out_dir",
    "speed",
    "log",
    "write_report",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, ".curio", "stress")


def out_dir() -> str:
    """Where videos, screenshots and the report land (``.curio/`` is ignored)."""
    path = os.environ.get("CURIO_STRESS_OUT") or DEFAULT_OUT_DIR
    os.makedirs(path, exist_ok=True)
    return path


def speed() -> float:
    """Pacing multiplier; >1 is faster.

    A stress run is much longer than the feature tour and nobody watches it for
    the prose, so it defaults to 1.6x rather than the tour's 1.0.
    """
    try:
        value = float(os.environ.get("CURIO_STRESS_SPEED", "1.6"))
    except ValueError:
        return 1.6
    return value if value > 0 else 1.6


def log(message: str) -> None:
    """Print without letting a cp1252 stdout turn a traceback into a codec error.

    Curio's menu labels carry the chevron glyph and its toasts carry typographic
    quotes, so an unencodable character in a quoted locator message would
    otherwise replace the failure it was meant to report.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(message.encode(encoding, "replace").decode(encoding, "replace"), flush=True)


def _slug(text: str, limit: int = 48) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (cleaned[:limit] or "step").strip("-")


def _clock(seconds: float) -> str:
    seconds = max(0.0, seconds)
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


# ---------------------------------------------------------------------------
# What is not a defect
# ---------------------------------------------------------------------------
#
# Every entry here is behaviour the app is documented to have. They are still
# exercised and still recorded - the point is that the *report* stays readable,
# because a list where nine of ten rows are known-good is a list that gets
# skimmed and then ignored.

EXPECTED: tuple[tuple[re.Pattern, str], ...] = (
    (
        re.compile(r"HTTP 400 POST \S*/api/packages/(import|upload)", re.I),
        "re-importing an installed coordinate is refused by design: onPickArchive "
        "never sets replace, so a fork has to rename the manifest id "
        "(test_frontend/README.md, 'Catalog surfaces')",
    ),
    (
        re.compile(r"HTTP 501 (POST|DELETE) \S*/api/packages/libraries", re.I),
        "JS library install/uninstall is deliberately unimplemented; JS nodes "
        "resolve against <repo_root>/node_modules (README, 'Libraries')",
    ),
    (
        re.compile(r"HTTP 40[13] (GET|POST) \S*/api/(auth/(signin|signup|me)|projects)", re.I),
        "auth probe: the signed-out landing state and the deliberate "
        "wrong-password attempt both answer 401/403",
    ),
    (
        re.compile(r"HTTP 401 GET \S*/api/packages\b", re.I),
        "index.tsx fires refreshPackageRegistry() at boot before anyone is "
        "signed in; loadInstalledPackages swallows the 401 by design "
        "('Anonymous boots are no-ops until sign-in')",
    ),
    (re.compile(r"favicon\.ico", re.I), "favicon is not served in dev"),
    # webpack-dev-server chatter. None of it is the application talking.
    (
        re.compile(r"\[HMR\]|\[webpack-dev-server\]|hot-update|sockjs-node", re.I),
        "webpack dev-server hot-reload chatter",
    ),
    (re.compile(r"Download the React DevTools", re.I), "React's own dev nag"),
    (
        re.compile(r"willReadFrequently", re.I),
        "Chrome's advice about repeated getImageData - raised by the harness's "
        "own assert_vega_canvas_rendered probe, not by the app's rendering",
    ),
    (
        re.compile(r"DevTools failed to load source ?map", re.I),
        "missing source map for a third-party bundle",
    ),
)


def _expected_reason(text: str) -> str | None:
    for pattern, why in EXPECTED:
        if pattern.search(text):
            return why
    return None


# ---------------------------------------------------------------------------
# Issue records
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    """One anomaly, addressed to whoever watches the video afterwards."""

    chapter: str
    step: str
    at: str                 # mm:ss into this chapter's recording
    at_seconds: float
    severity: str           # blocker | error | warning | note
    kind: str               # step | pageerror | console | http | toast | node
    message: str
    detail: str = ""
    screenshot: str = ""    # path relative to the stress output directory

    def as_dict(self) -> dict:
        return asdict(self)


_SEVERITY_ORDER = {"blocker": 0, "error": 1, "warning": 2, "note": 3}


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


_TOAST_WATCH_JS = r"""() => {
    if (window.__curioStress) return 'already';
    // Runs at document-start, where documentElement can still be null and
    // MutationObserver.observe would throw "parameter 1 is not of type 'Node'"
    // - a page error the probe would then dutifully report against the app.
    if (!document.documentElement) return 'deferred';
    const api = { toasts: [] };
    window.__curioStress = api;
    const seen = new WeakSet();
    const scan = () => {
        const region = document.querySelector('[aria-label="Notifications"]');
        if (!region) return;
        region.querySelectorAll('.toast').forEach((el) => {
            if (seen.has(el)) return;
            seen.add(el);
            const head = el.querySelector('.toast-header strong');
            const body = el.querySelector('.toast-body');
            api.toasts.push({
                variant: (head ? head.textContent : '').trim().toLowerCase(),
                message: (body ? body.textContent : '').trim(),
            });
        });
    };
    // The region is portaled into <body> and re-created on navigation, so the
    // observer watches the document element rather than the region itself.
    new MutationObserver(scan).observe(document.documentElement, {
        childList: true, subtree: true,
    });
    scan();
    return 'ok';
}"""


class Probe:
    """Everything the page says without being asked.

    Entries accumulate into one buffer that :meth:`StressRun.step` drains and
    attributes. Nothing here raises: a probe that can break the run it is
    observing is worse than no probe.
    """

    def __init__(self, page) -> None:
        self.page = page
        self.buffer: list[dict] = []
        page.add_init_script(f"({_TOAST_WATCH_JS})();")
        page.on("console", self._on_console)
        page.on("pageerror", self._on_pageerror)
        page.on("requestfailed", self._on_requestfailed)
        page.on("response", self._on_response)

    # -- listeners --------------------------------------------------------

    def _push(self, kind: str, severity: str, message: str, detail: str = "") -> None:
        self.buffer.append({
            "kind": kind,
            "severity": severity,
            "message": " ".join(str(message).split())[:600],
            "detail": str(detail)[:2000],
        })

    def _on_console(self, message) -> None:
        try:
            kind = message.type
            if kind not in ("error", "warning"):
                return
            text = message.text or ""
            # The browser's own "Failed to load resource: ... 401" line carries
            # no URL, so it is strictly worse than the `response` listener's
            # entry for the same request - and reporting both doubles the noise
            # for every 4xx.
            if text.startswith("Failed to load resource"):
                return
            self._push(
                "console",
                "error" if kind == "error" else "warning",
                message.text,
                detail=str(getattr(message, "location", "") or ""),
            )
        except Exception:  # noqa: BLE001 - never let observation break the run
            pass

    def _on_pageerror(self, error) -> None:
        try:
            self._push("pageerror", "error", str(error), detail=str(error))
        except Exception:  # noqa: BLE001
            pass

    def _on_requestfailed(self, request) -> None:
        try:
            failure = getattr(request, "failure", None)
            # Aborted navigations and cancelled preloads are normal in an SPA.
            if failure and "ERR_ABORTED" in str(failure):
                return
            self._push(
                "http", "error",
                f"request failed {request.method} {request.url}",
                detail=str(failure or ""),
            )
        except Exception:  # noqa: BLE001
            pass

    def _on_response(self, response) -> None:
        try:
            status = response.status
            if status < 400:
                return
            request = response.request
            self._push(
                "http",
                "error" if status >= 500 else "warning",
                f"HTTP {status} {request.method} {response.url}",
            )
        except Exception:  # noqa: BLE001
            pass

    # -- draining ---------------------------------------------------------

    def drain(self) -> list[dict]:
        """Take everything heard since the last drain, toasts included."""
        entries = self.buffer
        self.buffer = []
        try:
            # Re-install if the init script deferred (document-start had no
            # documentElement) or a navigation dropped the observer.
            toasts = self.page.evaluate(
                f"""() => {{
                    ({_TOAST_WATCH_JS})();
                    const api = window.__curioStress;
                    if (!api) return [];
                    const out = api.toasts;
                    api.toasts = [];
                    return out;
                }}"""
            ) or []
        except Exception:  # noqa: BLE001 - page may be navigating or closed
            toasts = []
        for toast in toasts:
            variant = (toast.get("variant") or "").lower()
            if variant not in ("error", "warning"):
                continue
            entries.append({
                "kind": "toast",
                "severity": "error" if variant == "error" else "warning",
                "message": f"{variant} toast: {toast.get('message', '')}"[:600],
                "detail": "",
            })
        return entries


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


class StressRun:
    """One chapter: a recording, a probe, and the issues it turned up."""

    def __init__(self, chapter: str, page, tour: Tour, *, frontend: str, backend: str):
        self.chapter = chapter
        self.page = page
        self.tour = tour
        self.frontend = frontend
        self.backend = backend
        self.probe = Probe(page)
        self.issues: list[Issue] = []
        self.state: dict = {}
        self.steps = 0
        self.failed_steps = 0
        self.t0 = time.monotonic()
        self.shot_dir = os.path.join(out_dir(), chapter)
        os.makedirs(self.shot_dir, exist_ok=True)

    # -- timing -----------------------------------------------------------

    def mark_recording_start(self) -> None:
        """Zero the clock. Called once the recorded page exists."""
        self.t0 = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    # -- evidence ---------------------------------------------------------

    def _screenshot(self, label: str) -> str:
        name = f"{self.steps:03d}-{_slug(label)}.png"
        path = os.path.join(self.shot_dir, name)
        try:
            self.page.screenshot(path=path)
        except Exception:  # noqa: BLE001
            return ""
        return os.path.relpath(path, out_dir()).replace("\\", "/")

    def add(
        self,
        severity: str,
        kind: str,
        message: str,
        *,
        step: str = "",
        detail: str = "",
        screenshot: str = "",
    ) -> None:
        self.issues.append(Issue(
            chapter=self.chapter,
            step=step or "(chapter)",
            at=_clock(self.elapsed),
            at_seconds=round(self.elapsed, 1),
            severity=severity,
            kind=kind,
            message=" ".join(str(message).split())[:600],
            detail=str(detail)[:4000],
            screenshot=screenshot,
        ))

    # -- the wrapper every interaction goes through -----------------------

    @contextmanager
    def step(self, label: str, *, allow: tuple[str, ...] = (), may_fail: bool = False):
        """Run one interaction, recording rather than raising.

        *allow* is a tuple of regexes for noise this particular step is expected
        to produce - a node that is meant to raise, a request that is meant to
        404. *may_fail* says the step itself is allowed to blow up (a surface
        that may legitimately not exist in this configuration); it is recorded
        as a note instead of a blocker.
        """
        self.steps += 1
        self.probe.drain()          # attribute only what happens from here on
        try:
            self.tour.say(label, hold=500)
        except Exception:  # noqa: BLE001 - the overlay is cosmetic
            pass
        log(f"[stress:{self.chapter}] {self.steps:03d} {label}")
        try:
            yield self
        except Exception as exc:  # noqa: BLE001 - a bad step must not end the take
            shot = self._screenshot(label)
            if not may_fail:
                self.failed_steps += 1
            self.add(
                "note" if may_fail else "blocker",
                "step",
                f"{label}: {type(exc).__name__}: {exc}",
                step=label,
                detail=traceback.format_exc(),
                screenshot=shot,
            )
            log(f"[stress:{self.chapter}] FAILED {label}: {exc}")
            # Leave the UI somewhere the next step can start from.
            for recover in (self.tour.hush, lambda: self.page.keyboard.press("Escape")):
                try:
                    recover()
                except Exception:  # noqa: BLE001
                    pass
        finally:
            self._collect(label, allow)

    def _collect(self, label: str, allow: tuple[str, ...]) -> None:
        allowed = [re.compile(pattern, re.I) for pattern in allow]
        for entry in self.probe.drain():
            text = entry["message"]
            if any(pattern.search(text) for pattern in allowed):
                continue
            reason = _expected_reason(text)
            if reason:
                # Kept out of the report, but visible in the log so a rule that
                # silently swallows a real regression can be spotted.
                log(f"[stress:{self.chapter}] expected: {text}  ({reason})")
                continue
            self.add(
                entry["severity"], entry["kind"], text,
                step=label, detail=entry.get("detail", ""),
            )

    # -- deliberate observations ------------------------------------------

    def snap(self, label: str) -> str:
        """Screenshot on purpose, for a surface worth having a still of."""
        return self._screenshot(label)

    def note(self, message: str, *, step: str = "", severity: str = "note") -> None:
        """Record something the probe cannot see, e.g. a missing affordance."""
        self.add(severity, "observation", message, step=step)

    # -- output -----------------------------------------------------------

    def write(self) -> str:
        """Persist this chapter's issues so the merged report can find them."""
        path = os.path.join(self.shot_dir, "issues.json")
        payload = {
            "chapter": self.chapter,
            "steps": self.steps,
            "failed_steps": self.failed_steps,
            "duration_seconds": round(self.elapsed, 1),
            "video": f"curio-stress-{self.chapter}.webm",
            "issues": [issue.as_dict() for issue in self.issues],
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        return path

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.severity] = counts.get(issue.severity, 0) + 1
        parts = [f"{counts[s]} {s}" for s in _SEVERITY_ORDER if s in counts]
        return (
            f"{self.chapter}: {self.steps} steps, {self.failed_steps} failed, "
            + (", ".join(parts) if parts else "nothing flagged")
        )


# ---------------------------------------------------------------------------
# The merged report
# ---------------------------------------------------------------------------


def write_report() -> str:
    """Merge every chapter's ``issues.json`` into ``ISSUES.md`` + ``issues.json``."""
    root = out_dir()
    chapters: list[dict] = []
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry, "issues.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                chapters.append(json.load(handle))
        except (OSError, ValueError) as exc:
            log(f"[stress] skipping unreadable {path}: {exc}")

    merged = os.path.join(root, "issues.json")
    with open(merged, "w", encoding="utf-8") as handle:
        json.dump({"chapters": chapters}, handle, indent=2)

    total = sum(len(c["issues"]) for c in chapters)
    lines = [
        "# Curio stress run - raw findings",
        "",
        "Machine-generated by `test_stress_tour_video.py`. Every row is a *lead*, not",
        "a verified defect: the probe reports what the app said, and some of it will",
        "turn out to be the harness, the environment, or behaviour that is correct on",
        "closer reading. Each row carries the offset into that chapter's recording so",
        "the moment can be watched rather than reconstructed.",
        "",
        f"{total} entries across {len(chapters)} chapters.",
        "",
        "| Chapter | Steps | Failed | Blockers | Errors | Warnings | Video |",
        "|---|---|---|---|---|---|---|",
    ]
    for chapter in chapters:
        issues = chapter["issues"]
        counted = {
            s: sum(1 for i in issues if i["severity"] == s) for s in _SEVERITY_ORDER
        }
        lines.append(
            f"| {chapter['chapter']} | {chapter['steps']} | {chapter['failed_steps']} "
            f"| {counted['blocker']} | {counted['error']} | {counted['warning']} "
            f"| `{chapter['video']}` |"
        )
    lines.append("")

    for chapter in chapters:
        lines += [f"## {chapter['chapter']}", ""]
        issues = sorted(
            chapter["issues"],
            key=lambda i: (_SEVERITY_ORDER.get(i["severity"], 9), i["at_seconds"]),
        )
        if not issues:
            lines += ["Nothing flagged.", ""]
            continue
        for issue in issues:
            lines.append(f"### `{issue['severity']}` {issue['at']} - {issue['step']}")
            lines += ["", f"- **{issue['kind']}**: {issue['message']}"]
            if issue["screenshot"]:
                lines.append(f"- shot: `{issue['screenshot']}`")
            if issue["detail"] and issue["kind"] == "step":
                tail = issue["detail"].strip().splitlines()[-6:]
                lines += ["", "```", *tail, "```"]
            lines.append("")

    report = os.path.join(root, "ISSUES.md")
    with open(report, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return report


def finalize_chapter_video(page, *, chapter: str) -> dict[str, str]:
    """Save this chapter's recording into the stress output directory.

    ``tour.finalize_video`` writes into ``tour.out_dir()``, so the tour's output
    variable is pointed here for the duration of the call rather than copying
    its ffmpeg handling.
    """
    previous = os.environ.get("CURIO_TOUR_OUT")
    os.environ["CURIO_TOUR_OUT"] = out_dir()
    try:
        return finalize_video(page, stem=f"curio-stress-{chapter}")
    finally:
        if previous is None:
            os.environ.pop("CURIO_TOUR_OUT", None)
        else:
            os.environ["CURIO_TOUR_OUT"] = previous


# ---------------------------------------------------------------------------
# Shared UI helpers
# ---------------------------------------------------------------------------
#
# Lifted from test_feature_tour_video.py so the two recorders share one copy of
# the knowledge about how to drive this canvas.


DRAWER_DATA = '[data-curio-dataset-catalog-drawer="true"]'
DRAWER_NODES = '[data-curio-node-catalog-drawer="true"]'
DRAWER_AGENTS = '[data-curio-agent-catalog-drawer="true"]'

#: Built-in palette tiles carry an ``id`` only when their manifest declares a
#: ``tutorialId`` (ToolsMenu.DraggableTool sets ``id={tutorialID}``), which four
#: of the twelve do not. The rest are addressed by their position in the
#: built-in stack, which follows PALETTE_GROUPS ([data, flow], [computation],
#: [vis_grammar, vis_simple]) with each group in manifest paletteOrder.
BUILTIN_TILES: tuple[tuple[str, str | None], ...] = (
    ("data-loading", "step-loading"),
    ("data-export", None),
    ("data-transformation", "step-transformation"),
    ("spatial-join", None),
    ("merge-flow", "step-merge"),
    ("data-pool", "step-pool"),
    ("computation-analysis", "step-analysis"),
    ("data-summary", None),
    ("js-computation", None),
    ("autk-grammar", "step-utk"),
    ("vis-vega", "step-vega"),
    ("vis-simple", "step-image"),
)

_TILE_INDEX = {name: i for i, (name, _) in enumerate(BUILTIN_TILES)}
_TILE_ANCHOR = dict(BUILTIN_TILES)


def builtin_tile(page, template_id: str):
    """A locator for one built-in palette tile, by manifest template id."""
    anchor = _TILE_ANCHOR.get(template_id)
    if anchor:
        return page.locator(f"#{anchor}")
    index = _TILE_INDEX.get(template_id)
    if index is None:
        raise KeyError(f"unknown built-in template {template_id!r}")
    # The built-in stack is the first child of #tools-menu; the three catalog
    # palettes and the run-all row follow it and also contain draggables.
    return page.locator("#tools-menu > div").first.locator("[draggable]").nth(index)


def package_row(page, template_id: str):
    """A draggable row in the left-rail Node Catalog palette."""
    return page.locator(f'#packages-palette [data-pkg-template-id="{template_id}"]')


def fit_view(page, padding: float = 0.22) -> None:
    """Frame the whole graph, the same way the screenshot helper does."""
    page.evaluate(
        """(padding) => {
            const fit = window.__curio_fitViewWithMenuOffset;
            if (typeof fit === 'function') {
                fit({ padding, duration: 600, includeHiddenNodes: true });
            }
        }""",
        padding,
    )
    page.wait_for_timeout(700)


def reset_zoom(page) -> None:
    """Put the pane back to zoom 1 before dropping nodes.

    ``drag_to_canvas`` positions drops in screen pixels, so the canvas-space gap
    between two drops depends on the current zoom, and the geometry the offsets
    were chosen for (525x350 nodes, ~610px apart) only holds at zoom 1.
    """
    page.evaluate(
        """() => {
            const rf = window.__curio_reactFlow;
            if (!rf) return;
            const vp = rf.getViewport();
            if (Math.abs(vp.zoom - 1) < 0.01) return;
            rf.setViewport({ x: vp.x, y: vp.y, zoom: 1 }, { duration: 300 });
        }"""
    )
    page.wait_for_timeout(350)


def menu(page, label: str):
    """Top-bar dropdown trigger (``File``, ``View``, ``Data``, ...)."""
    return page.get_by_role("button", name=f"{label} ⏷", exact=True)


def load_example(run: "StressRun", path: str, *, expected_nodes: int,
                 timeout: float = 90000) -> None:
    """File > Load dataflow, on camera.

    Deliberately not ``utils.upload_workflow``: that helper hides the left tool
    rail so it cannot drift into a screenshot baseline, which is exactly the
    chrome a viewer needs to see here.
    """
    page, tour = run.page, run.tour
    tour.click(menu(page, "File"), force=True)
    load = page.get_by_role("button", name="Load dataflow", exact=True)
    load.wait_for(state="visible", timeout=15000)
    tour.focus(load, hold=350)
    with page.expect_file_chooser() as chooser:
        page.get_by_text("Load dataflow").click()
    chooser.value.set_files(path)
    page.wait_for_function(
        "(n) => document.querySelectorAll('.react-flow__node').length >= n",
        arg=expected_nodes,
        timeout=timeout,
    )
    tour.beat(700)
    fit_view(page)


def play_all(run: "StressRun", *, timeout_ms: int = 300000) -> list[str]:
    """Press the rail's Run-all button and wait for every node to settle.

    The button sits at the foot of the left rail, under three catalog dropdowns,
    and the rail does not scroll. Fall back to a dispatched click rather than
    lose the step if the rail ever grows past the frame - the same synthetic
    route ``utils.play_node`` already uses for per-node play buttons.
    """
    page, tour = run.page, run.tour
    button = page.locator('#tools-menu button[title="Run all nodes"]')
    try:
        tour.click(button, force=True, hold=300)
    except PlaywrightError as exc:
        if "outside of the viewport" not in str(exc):
            raise
        log("[stress] Run-all is below the fold; dispatching the click instead.")
        tour.click(button, dispatch=True, hold=300)
    # Wait for the run to go quiet, not for every node to have executed.
    # `playAllNodes` walks the graph in topological order, so a node with no
    # upstream input - a Data Pool nobody wired, a Simple View on its own - is
    # never scheduled and stays `idle` forever. Requiring every node to reach
    # done/error therefore cannot succeed on a canvas that has any, and the
    # timeout says nothing about whether the run worked.
    page.wait_for_function(
        """() => {
            const nodes = [...document.querySelectorAll('.react-flow__node')];
            if (!nodes.length) return false;
            const running = nodes.filter((n) => {
                const el = n.querySelector('[data-curio-node-status]');
                return el && el.getAttribute('data-curio-node-status') === 'running';
            });
            if (running.length) return false;
            // Give the first node a moment to pick the baton up, so "nothing is
            // running" cannot be satisfied by the instant before anything starts.
            return nodes.some((n) => {
                const el = n.querySelector('[data-curio-node-status]');
                const s = el && el.getAttribute('data-curio-node-status');
                return s === 'done' || s === 'error';
            });
        }""",
        timeout=timeout_ms,
    )
    page.wait_for_timeout(1500)
    idle = [
        node_id for node_id, status in node_statuses(page).items()
        if status not in ("done", "error")
    ]
    if idle:
        log(f"[stress] play-all left {len(idle)} node(s) unscheduled (idle): {idle}")
    return idle


def frame_nodes(page, node_ids, *, padding: float = 0.25) -> None:
    """Fit the viewport to just these nodes.

    A node is 525 wide, so a pair dropped at screen x=150 and x=760 puts the
    right-hand node's *output* handle at x~1285 - past the 1280 frame, where
    ``elementFromPoint`` returns nothing and ``connect_nodes`` cannot even
    attempt the drag. Framing the pair first makes the geometry independent of
    wherever the canvas happened to be panned to.
    """
    page.evaluate(
        """({ ids, padding }) => {
            const rf = window.__curio_reactFlow;
            if (!rf || !rf.fitView) return;
            rf.fitView({ nodes: ids.map((id) => ({ id })), padding, duration: 400 });
        }""",
        {"ids": list(node_ids), "padding": padding},
    )
    page.wait_for_timeout(700)


def node_statuses(page) -> dict[str, str]:
    """``{node id: status}`` for everything on the canvas."""
    return page.evaluate(
        """() => {
            const out = {};
            document.querySelectorAll('.react-flow__node').forEach((n) => {
                const el = n.querySelector('[data-curio-node-status]');
                out[n.getAttribute('data-id')] =
                    el ? el.getAttribute('data-curio-node-status') : 'unknown';
            });
            return out;
        }"""
    )


def report_errored_nodes(run: "StressRun", step: str, *,
                         severity: str = "error") -> list[str]:
    """Record every node sitting in ``error`` as an issue, and return their ids.

    Pass ``severity="note"`` where red nodes are the expected outcome - a
    hand-built canvas full of deliberately unwired nodes always has some, and
    reporting those as defects buries the ones that matter.
    """
    errored = [
        node_id for node_id, status in node_statuses(run.page).items()
        if status == "error"
    ]
    for node_id in errored:
        text = ""
        try:
            text = (node_locator(run.page, node_id).inner_text() or "")[:400]
        except Exception:  # noqa: BLE001
            pass
        run.add(severity, "node", f"node {node_id} finished in error", step=step,
                detail=text)
    return errored


def node_ids_by_type(page, node_type: str) -> list[str]:
    fragment = node_type.rsplit("/", 1)[-1]
    return [n["id"] for n in canvas_nodes(page) if fragment in (n["nodeType"] or "")]


def center_on(page, node_id: str, *, zoom: float = 0.9) -> None:
    """Pan the canvas so one node fills the frame."""
    page.evaluate(
        """({ nodeId, zoom }) => {
            const rf = window.__curio_reactFlow;
            if (!rf) return;
            const node = rf.getNodes().find((n) => n.id === nodeId);
            if (!node) return;
            const w = node.width || node.measured?.width || 525;
            const h = node.height || node.measured?.height || 350;
            rf.setCenter(node.position.x + w / 2, node.position.y + h / 2, {
                zoom, duration: 600,
            });
        }""",
        {"nodeId": node_id, "zoom": zoom},
    )
    page.wait_for_timeout(800)


AI_FIELDS = {
    "Base URL": "#ai-settings-base-url",
    "API Key": "#ai-settings-api-key",
    "Model": "#ai-settings-model",
    "HuggingFace token": "#ai-settings-hf-token",
}


def ai_field(page, label: str):
    return page.locator(AI_FIELDS[label])


def wait_for_drawer_presented(page, selector: str, *, timeout: float = 25000) -> None:
    """Wait until a catalog drawer has actually slid into frame.

    Neither obvious gate works for all three. ``to_be_visible()`` is not one:
    the drawers sit off-screen behind ``transform: translate3d(100%, 0, 0)``,
    which keeps a full bounding box. ``aria-hidden="false"`` is the presented
    signal for the Data and Agent drawers, but the Node Catalog drawer never
    sets the attribute at all (it toggles a CSS class only), so gating on it
    there waits forever.

    Measuring where the panel *is* works for all three and cannot drift.
    """
    page.wait_for_function(
        """(selector) => {
            const root = document.querySelector(selector);
            if (!root) return false;
            const panel = root.querySelector('[role="dialog"]') || root;
            const box = panel.getBoundingClientRect();
            if (!box.width || !box.height) return false;
            // Closed, translate3d(100%) parks the left edge at the viewport's
            // right edge; presented, it covers the right-hand side.
            return box.left < window.innerWidth - 120;
        }""",
        arg=selector,
        timeout=timeout,
    )
    page.wait_for_timeout(400)


def drawer_presentation_signals(page, selector: str) -> dict:
    """What a drawer root advertises about being presented, for the record."""
    return page.evaluate(
        """(selector) => {
            const root = document.querySelector(selector);
            if (!root) return null;
            const panel = root.querySelector('[role="dialog"]');
            return {
                rootAriaHidden: root.getAttribute('aria-hidden'),
                panelAriaModal: panel ? panel.getAttribute('aria-modal') : null,
                panelRole: panel ? panel.getAttribute('role') : null,
                inDom: true,
            };
        }""",
        selector,
    )


def open_agent_drawer(run: "StressRun"):
    """Data > Agent Catalog, returning the drawer dialog.

    ``exact=True`` on the menu row is load-bearing: the left rail's palette
    trigger is also named "Agent Catalog", so a substring match is ambiguous and
    Playwright's strict mode fails the step.
    """
    page, tour = run.page, run.tour
    tour.click(menu(page, "Data"), force=True)
    tour.click(page.get_by_role("button", name="Agent Catalog", exact=True))
    root = page.locator(DRAWER_AGENTS)
    root.wait_for(state="attached", timeout=15000)
    wait_for_drawer_presented(page, DRAWER_AGENTS)
    drawer = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Agent Catalog", exact=True)
    )
    expect(drawer).to_be_visible(timeout=10000)
    return drawer


def open_node_drawer(run: "StressRun"):
    """Data > Node Catalog, returning the drawer dialog."""
    page, tour = run.page, run.tour
    tour.click(menu(page, "Data"), force=True)
    tour.click(page.get_by_role("button", name="Node Catalog", exact=True))
    root = page.locator(DRAWER_NODES)
    root.wait_for(state="attached", timeout=15000)
    wait_for_drawer_presented(page, DRAWER_NODES)
    return page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Node Catalog", exact=True)
    )


def open_data_drawer(run: "StressRun"):
    """Data > Data Catalog, returning the drawer dialog."""
    page, tour = run.page, run.tour
    tour.click(menu(page, "Data"), force=True)
    tour.click(page.get_by_role("button", name="Data Catalog", exact=True))
    root = page.locator(DRAWER_DATA)
    root.wait_for(state="attached", timeout=15000)
    wait_for_drawer_presented(page, DRAWER_DATA)
    return page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )


def close_drawer(page, selector: str, name: str) -> None:
    drawer = page.locator(selector)
    if not drawer.count():
        return
    button = drawer.locator("header").get_by_role("button", name=f"Close {name}")
    if button.count():
        button.first.click()
    else:
        page.keyboard.press("Escape")
    try:
        expect(drawer).to_have_count(0, timeout=8000)
    except AssertionError:
        page.keyboard.press("Escape")


def agent_row(page, coord: str):
    """A row in the left-rail Agent palette - the thing you drag to attach."""
    return page.locator(f'#agents-palette [data-agent-coord="{coord}"]')


def drag_agent_to(run: "StressRun", coord: str, point) -> None:
    """Drag an agent palette row onto a point and dispatch the drop.

    The drop is always dispatched on the canvas pane, because that is where
    ``handleDrop`` lives; what decides node vs connection vs canvas is the
    *coordinate*, hit-tested by ``pickNodeAtPoint`` (flow space) and then
    ``pickEdgeAtPoint`` (``elementFromPoint``, screen space).

    *point* may be an ``(x, y)`` pair or a zero-argument callable returning one.
    Pass a callable for anything whose position depends on the current layout:
    this helper scrolls the palette row into view before it drops, and a
    coordinate measured before that can be stale by the time it is used - which
    does not raise, it just attaches the agent somewhere else.
    """
    page, tour = run.page, run.tour
    row = agent_row(page, coord)
    row.wait_for(state="visible", timeout=20000)
    row.scroll_into_view_if_needed()
    tour.focus(row, hold=400)
    resolved = point() if callable(point) else point
    assert resolved, "no drop point resolved for the agent drag"
    client_x, client_y = resolved
    tour.point_at(client_x, client_y, hold=320)
    result = page.evaluate(
        _DRAG_TO_CANVAS_JS,
        {
            "source": row.element_handle(),
            "targetSelector": CANVAS_DROP_TARGET,
            "clientX": client_x,
            "clientY": client_y,
        },
    )
    assert result == "ok", f"agent drag failed: {result}"


def expect_attach_toast(run: "StressRun", where: str) -> None:
    """Wait for an attach toast and assert it names *where*.

    Which toast appears is exactly what distinguishes the three drop targets.
    Reading the region rather than matching the success wording matters: the
    failure path is ``showToast(e?.message || "Attach failed.")``, so a rejected
    attach carries the *server's* message, which no pattern written from the
    happy path would match - and the assertion would then die of a timeout that
    says nothing.
    """
    page, tour = run.page, run.tour
    # Sweep first. Three attaches happen within a few seconds and a toast lives
    # for five, so without this the read can return the PREVIOUS attach's toast
    # - which looks exactly like the drop having hit the wrong target.
    toast = page.locator('[aria-label="Notifications"] .toast').first
    toast.wait_for(state="visible", timeout=45000)
    actual = " ".join((toast.text_content() or "").split())
    assert f"attached to {where}." in actual, (
        f"expected an attach to {where}, but the app said: {actual!r}"
    )
    tour.beat(700)
    dismiss_toasts(page)


def node_client_point(page, node_id: str) -> tuple[float, float]:
    """The centre of a node in viewport coordinates."""
    box = node_locator(page, node_id).bounding_box()
    assert box, f"node {node_id} has no layout box"
    return (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def empty_canvas_point(page) -> tuple[float, float] | None:
    """A visibly empty spot on the pane, in viewport coordinates.

    "Empty" has to mean empty to the viewer as well as to ``handleDrop``: a
    point under an open palette would still attach to the canvas, but on camera
    it reads as dropping the agent onto the palette it came from.
    """
    point = page.evaluate(
        """() => {
            const pane = document.querySelector('.curio-canvas-drop-target');
            if (!pane) return null;
            const box = pane.getBoundingClientRect();
            const xs = [0.62, 0.72, 0.52, 0.82];
            const ys = [0.82, 0.74, 0.88, 0.66];
            for (const fy of ys) {
                for (const fx of xs) {
                    const x = box.left + box.width * fx;
                    const y = box.top + box.height * fy;
                    const hit = document.elementFromPoint(x, y);
                    if (!hit || !hit.closest) continue;
                    if (hit.closest('.react-flow__node')) continue;
                    if (hit.closest('.react-flow__edge')) continue;
                    if (!hit.closest('.react-flow')) continue;
                    return [x, y];
                }
            }
            return null;
        }"""
    )
    return (point[0], point[1]) if point else None


def edge_client_point(page) -> tuple[float, float] | None:
    """A point that ``pickEdgeAtPoint`` will actually resolve to an edge.

    A bezier's bounding-box centre is usually empty space, so the point comes
    from ``getPointAtLength`` on the path itself; and because ``handleDrop``
    runs ``pickNodeAtPoint`` first, a point that is visually on the curve still
    attaches to a NODE if it falls inside that node's generous box.
    """
    found = page.evaluate(
        """() => {
            const path = document.querySelector(
                '.react-flow__edge .react-flow__edge-interaction'
            ) || document.querySelector('.react-flow__edge path');
            if (!path || !path.getPointAtLength) return null;
            const total = path.getTotalLength();
            if (!total) return null;
            const svg = path.ownerSVGElement;
            const ctm = path.getScreenCTM();
            const rf = window.__curio_reactFlow;
            if (!svg || !ctm || !rf) return null;
            const toFlow = (x, y) => (
                rf.screenToFlowPosition
                    ? rf.screenToFlowPosition({ x, y })
                    : rf.project({ x, y })
            );
            const nodes = rf.getNodes();
            const insideANode = (flow) => nodes.some((n) => {
                const o = n.positionAbsolute ?? n.position;
                if (!o) return false;
                const w = n.width ?? 0;
                const h = n.height ?? 0;
                return flow.x >= o.x && flow.x <= o.x + w
                    && flow.y >= o.y && flow.y <= o.y + h;
            });
            const fractions = [
                0.5, 0.48, 0.52, 0.45, 0.55, 0.42, 0.58, 0.4, 0.6, 0.35, 0.65,
            ];
            for (const f of fractions) {
                const at = path.getPointAtLength(total * f);
                const pt = svg.createSVGPoint();
                pt.x = at.x;
                pt.y = at.y;
                const screen = pt.matrixTransform(ctm);
                const hit = document.elementFromPoint(screen.x, screen.y);
                if (!hit || !hit.closest) continue;
                if (!hit.closest('.react-flow__edge')) continue;
                if (insideANode(toFlow(screen.x, screen.y))) continue;
                return [screen.x, screen.y];
            }
            return null;
        }"""
    )
    return (found[0], found[1]) if found else None
