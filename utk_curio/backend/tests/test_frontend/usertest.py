"""Driver for exploratory, recorded user-test sessions.

Not a test module (no ``test_`` prefix, so pytest does not collect it). It is the
counterpart to :mod:`tour`: that module exists to make a *good* recording, this
one exists to make a *truthful* one.

The difference is ``UserSession.step``. A tour scene asserts nothing and its
failures are swallowed so the take still ships. A step here is an experiment with
a stated expectation, and everything that happens inside it is evidence:

* the exception, if it raised - a locator that never appeared, a timeout, a
  failed assertion;
* every ``console.error`` and every uncaught ``pageerror`` that arrived while it
  ran, attributed to that step rather than to the run as a whole;
* the *absence* of a failure in a step that was supposed to fail - deliberately
  wiring two incompatible ports and getting an edge anyway is a finding, and one
  that a pass/fail suite structurally cannot express.

A step never aborts the session. A real user who hits a bug keeps using the
application, and the interesting findings are usually downstream of the first
one, so the session carries on and the finding is filed with the wall-clock
offset into the video that shows it.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field

from .tour import REPO_ROOT, Tour, finalize_video, speed

#: Where videos, stills and the findings report land. ``.curio/`` is gitignored.
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, ".curio", "usertest")


def out_dir() -> str:
    path = os.environ.get("CURIO_STRESS_OUT") or DEFAULT_OUT_DIR
    os.makedirs(path, exist_ok=True)
    return path


def _print(message: str) -> None:
    """Print without letting the console's codec fail the run.

    Findings quote the application's own text back - dataset titles carry
    ``↑``, error messages carry smart quotes - and a cp1252 stdout raises
    ``UnicodeEncodeError`` on those. That exception surfaced inside a ``step()``,
    where it looked exactly like an application failure and, worse, skipped the
    rest of the step body: a drawer that step meant to close stayed open and
    occluded the next step's canvas. One bad ``print`` cost two false findings,
    which is why this is not merely cosmetic.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(
        message.encode(encoding, "replace").decode(encoding, "replace"),
        flush=True,
    )


# ---------------------------------------------------------------------------
# Console classification
# ---------------------------------------------------------------------------
#
# A webpack dev build is chatty, and a report that files every line of it is a
# report nobody reads. These are the messages that are known noise rather than
# evidence: they are emitted by the toolchain or by third-party libraries on a
# healthy page, and none of them is under Curio's control.

_CONSOLE_NOISE = re.compile(
    "|".join(
        [
            r"\[webpack-dev-server\]",
            r"\[HMR\]",
            r"Download the React DevTools",
            r"react-devtools",
            r"DevTools failed to load source ?map",
            r"Autofocus processing was blocked",
            r"was preloaded using link preload but not used",
            r"Could not find source file",
            r"findDOMNode is deprecated",
            r"Support for defaultProps will be removed",
        ]
    ),
    re.I,
)

#: Console text worth surfacing even at ``warning`` level, because in this
#: application each one names a real broken contract rather than a style
#: preference.
_CONSOLE_INTERESTING_WARNING = re.compile(
    "|".join(
        [
            r"Each child in a list should have a unique",
            r"Cannot update a component",
            r"unmounted component",
            r"validateDOMNesting",
            r"Maximum update depth",
            r"non-passive event listener",
            r"WebGL|WebGPU",
            r"Failed to fetch|NetworkError|ERR_",
            r"Uncaught",
        ]
    ),
    re.I,
)


#: Uncaught page exceptions that this harness causes and Curio does not.
#:
#: ``Tour.__init__`` installs the narration overlay through
#: ``page.add_init_script``, which runs at document-start - before ``document.body``
#: *or* ``document.documentElement`` exists. ``_INSTALL_OVERLAY_JS`` ends with
#: ``(document.body || document.documentElement).appendChild(root)``, so on every
#: navigation that init script throws exactly this once, from the recorder rather
#: than from the application. Filed as a harness note in ``UserSession.__init__``
#: so it is visible rather than silently dropped, then excluded from the findings.
_PAGEERROR_NOISE = re.compile(
    r"Cannot read propert(y|ies) of null \(reading 'appendChild'\)"
    r"|null is not an object \(evaluating '.*appendChild'\)",
    re.I,
)


@dataclass
class Finding:
    """One thing that went wrong, or one thing that suspiciously did not."""

    session: str
    step: str
    severity: str  # bug | error | warning | note
    kind: str  # exception | console | pageerror | node-error | absent | slow | a11y
    detail: str
    video_offset_ms: int
    duration_ms: int = 0
    still: str = ""
    console_tail: list[str] = field(default_factory=list)


@dataclass
class StepRecord:
    session: str
    step: str
    expectation: str
    outcome: str  # ok | failed | failed-as-expected | unexpectedly-ok
    video_offset_ms: int
    duration_ms: int


class UserSession:
    """One recorded session: a persona, a page, and a list of findings."""

    def __init__(self, page, *, name: str, frontend: str, backend: str,
                 pace: float | None = None) -> None:
        self.page = page
        self.name = name
        self.frontend = frontend
        self.backend = backend
        self.tour = Tour(page, pace=pace if pace is not None else speed())
        self.findings: list[Finding] = []
        self.steps: list[StepRecord] = []
        #: Scratch space for a session body to thread ids between its steps.
        #: Pre-created so a step that failed before assigning does not turn every
        #: later step into an AttributeError finding that hides the real cause.
        self.state: dict = {}
        self._t0 = time.monotonic()
        self._console: list[dict] = []
        self._still_seq = 0
        self._harness_pageerrors = 0
        self._http_failures: list[dict] = []
        self._current_step = "(setup)"
        page.on("console", self._on_console)
        page.on("pageerror", self._on_pageerror)
        page.on("response", self._on_response)

    # -- clock ------------------------------------------------------------

    def offset_ms(self) -> int:
        """Milliseconds since the session started, i.e. into the video."""
        return int((time.monotonic() - self._t0) * 1000)

    def stamp(self) -> str:
        ms = self.offset_ms()
        return f"{ms // 60000:02d}:{(ms // 1000) % 60:02d}"

    # -- browser sinks ----------------------------------------------------

    def _on_console(self, msg) -> None:
        try:
            text = msg.text
            kind = msg.type
        except Exception:
            return
        self._console.append(
            {"type": kind, "text": text, "at": self.offset_ms(),
             "step": self._current_step}
        )

    def _on_response(self, response) -> None:
        """Keep every 4xx/5xx, so a console error can be traced to a request.

        Chromium logs "Failed to load resource: the server responded with a
        status of 401" with no URL attached, which is unactionable on its own -
        an expected probe for a session cookie and a genuinely broken call read
        identically.
        """
        try:
            status = response.status
            if status < 400:
                return
            self._http_failures.append(
                {"status": status, "url": response.url,
                 "method": response.request.method, "at": self.offset_ms(),
                 "step": self._current_step}
            )
        except Exception:
            return

    def _on_pageerror(self, error) -> None:
        detail = str(error)
        self._console.append(
            {"type": "pageerror", "text": detail, "at": self.offset_ms(),
             "step": self._current_step}
        )
        if _PAGEERROR_NOISE.search(detail):
            # The recorder's own overlay, not the application. Counted so the
            # report can say how often, but not filed as a Curio defect.
            self._harness_pageerrors += 1
            return
        first = detail.splitlines()[0] if detail else "unknown"
        self.record(
            "pageerror",
            f"uncaught exception in the page: {first}",
            severity="bug",
            detail_full=detail,
        )

    # -- findings ---------------------------------------------------------

    def still(self, tag: str) -> str:
        """Screenshot the current viewport and return its path."""
        self._still_seq += 1
        safe = re.sub(r"[^a-z0-9]+", "-", f"{self.name}-{tag}".lower()).strip("-")
        path = os.path.join(out_dir(), f"still-{self._still_seq:02d}-{safe}.png")
        try:
            self.page.screenshot(path=path)
        except Exception:
            return ""
        return path

    def record(self, kind: str, summary: str, *, severity: str = "bug",
               detail_full: str | None = None, step: str | None = None,
               still: bool = True, duration_ms: int = 0) -> Finding:
        finding = Finding(
            session=self.name,
            step=step or self._current_step,
            severity=severity,
            kind=kind,
            detail=detail_full or summary,
            video_offset_ms=self.offset_ms(),
            duration_ms=duration_ms,
            still=self.still(f"{kind}-{summary[:30]}") if still else "",
            console_tail=[
                f"[{c['type']}] {c['text'][:400]}" for c in self._console[-8:]
            ],
        )
        self.findings.append(finding)
        _print(
            f"  ! [{severity}/{kind}] {self.stamp()} {self._current_step}: {summary}"
        )
        return finding

    def note(self, summary: str, **kw) -> Finding:
        """A usability observation: not broken, worth writing down."""
        kw.setdefault("severity", "note")
        kw.setdefault("still", False)
        return self.record("observation", summary, **kw)

    # -- the step ---------------------------------------------------------

    @contextmanager
    def step(self, title: str, sub: str = "", *, expect: str = "ok",
             chapter: str | None = None, quiet_console: bool = False):
        """Run one experiment, narrate it, and file whatever it produced.

        *expect* is the contract:

        ``ok``      the step should complete; an exception is a bug.
        ``error``   the step should be *refused* by the application; it
                    completing without incident is the bug. Use this for the
                    deliberate misuse - an illegal edge, a cycle, a syntax error
                    the user is supposed to be told about.
        ``either``  genuinely exploratory; record what happened, judge nothing.

        *quiet_console* suppresses console-derived findings for steps that are
        expected to log errors (a node that fails on purpose prints a traceback
        the app itself surfaces, and filing that twice is noise).
        """
        self._current_step = title
        console_mark = len(self._console)
        started = time.monotonic()
        offset = self.offset_ms()
        if chapter:
            self.tour.chapter(self.name, chapter, title)
        self.tour.say(title, sub)
        raised: BaseException | None = None
        try:
            yield self
        except BaseException as exc:  # noqa: BLE001 - a step never aborts a session
            raised = exc
        duration = int((time.monotonic() - started) * 1000)

        if raised is not None and expect == "ok":
            text = str(raised)
            first = text.splitlines()[0] if text else type(raised).__name__
            self.record(
                "exception",
                f"{type(raised).__name__}: {first[:200]}",
                severity="bug",
                detail_full="".join(
                    traceback.format_exception(
                        type(raised), raised, raised.__traceback__
                    )
                ),
                duration_ms=duration,
            )
            outcome = "failed"
        elif raised is not None and expect == "error":
            text = str(raised).splitlines()[0] if str(raised) else type(raised).__name__
            self.note(f"refused as it should be: {text[:160]}", duration_ms=duration)
            outcome = "failed-as-expected"
        elif raised is not None:
            text = str(raised).splitlines()[0] if str(raised) else ""
            self.note(
                f"raised (exploratory): {type(raised).__name__}: {text[:160]}",
                duration_ms=duration,
            )
            outcome = "failed"
        elif expect == "error":
            self.record(
                "absent",
                "the application accepted something it should have refused",
                severity="bug",
                duration_ms=duration,
            )
            outcome = "unexpectedly-ok"
        else:
            outcome = "ok"

        if not quiet_console:
            self._file_console_since(console_mark, duration_ms=duration)

        self.steps.append(
            StepRecord(
                session=self.name, step=title, expectation=expect,
                outcome=outcome, video_offset_ms=offset, duration_ms=duration,
            )
        )
        self.tour.hush()
        self._current_step = "(between steps)"

    def _file_console_since(self, mark: int, *, duration_ms: int = 0) -> None:
        """Turn this step's console output into findings, deduplicated."""
        seen: dict[str, int] = {}
        for entry in self._console[mark:]:
            kind, text = entry["type"], entry["text"]
            if kind == "pageerror":
                continue  # already filed by the listener
            if _CONSOLE_NOISE.search(text):
                continue
            if kind == "error":
                severity = "error"
            elif kind == "warning" and _CONSOLE_INTERESTING_WARNING.search(text):
                severity = "warning"
            else:
                continue
            key = text[:180]
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                continue
            detail = text
            if "failed to load resource" in text.lower():
                recent = [
                    f"{f['status']} {f['method']} {f['url']}"
                    for f in self._http_failures[-6:]
                ]
                joined = "\n  ".join(recent) if recent else "(none captured)"
                detail = (
                    f"{text}\n\nHTTP failures seen around this step:\n  {joined}"
                )
            self.record(
                "console",
                f"console.{kind}: {key}",
                severity=severity,
                detail_full=detail,
                still=False,
                duration_ms=duration_ms,
            )

    # -- reporting --------------------------------------------------------

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return {
            "session": self.name,
            "duration_ms": self.offset_ms(),
            "steps": [asdict(s) for s in self.steps],
            "findings": [asdict(f) for f in self.findings],
            "counts": counts,
        }


# ---------------------------------------------------------------------------
# Palette tiles
# ---------------------------------------------------------------------------
#
# ToolsMenu.tsx renders each built-in tile as ``<div id={tutorialID}>`` - and
# packages/curio.builtin@1/manifest.json gives no ``tutorialId`` to data-export,
# data-summary, js-computation or spatial-join. Those four tiles are therefore an
# icon div with a hover tooltip and no id, no aria-label and no accessible name,
# which is both why they have to be reached positionally here and a finding in
# its own right.
#
# The rail is three group containers (PALETTE_GROUPS in ToolsMenu.tsx) whose
# children are ordered by ``paletteOrder`` (getPaletteNodeTypes sorts on it), so
# an anchor id plus an index is stable.

#: template id -> (anchor tile id, index within that anchor's group container)
PALETTE_TILES: dict[str, tuple[str, int]] = {
    # group: data + flow
    "data-loading": ("#step-loading", 0),
    "data-export": ("#step-loading", 1),
    "data-transformation": ("#step-loading", 2),
    "spatial-join": ("#step-loading", 3),
    "merge-flow": ("#step-loading", 4),
    "data-pool": ("#step-loading", 5),
    # group: computation
    "computation-analysis": ("#step-analysis", 0),
    "data-summary": ("#step-analysis", 1),
    "js-computation": ("#step-analysis", 2),
    # group: vis
    "autk-grammar": ("#step-utk", 0),
    "vis-vega": ("#step-utk", 1),
    "vis-simple": ("#step-utk", 2),
}

#: The tooltip each tile should show, from the manifest's ``label``. Used to
#: prove a positional lookup landed on the tile the caller meant.
PALETTE_LABELS: dict[str, str] = {
    "data-loading": "Data Loading",
    "data-export": "Data Export",
    "data-transformation": "Data Transformation",
    "spatial-join": "Spatial Join",
    "merge-flow": "Merge Flow",
    "data-pool": "Data Pool",
    "computation-analysis": "Python Computation",
    "data-summary": "Data Summary",
    "js-computation": "JS Computation",
    "autk-grammar": "Autark",
    "vis-vega": "Vega-Lite",
    "vis-simple": "Simple View",
}


def palette_tile(page, template_id: str):
    """A locator for one built-in palette tile, by manifest template id.

    Uses the tile's own id where the manifest gave it a ``tutorialId``, and falls
    back to its position inside the group container otherwise.
    """
    try:
        anchor, index = PALETTE_TILES[template_id]
    except KeyError:
        raise ValueError(
            f"unknown built-in template {template_id!r}; "
            f"known: {sorted(PALETTE_TILES)}"
        ) from None
    group = page.locator(anchor).locator("xpath=..")
    return group.locator("> div").nth(index)


#: The FontAwesome class each tile's svg must carry, derived from the manifest's
#: ``iconRef`` (``fa-solid:upload`` -> ``fa-upload``). This is how a positional
#: lookup is proved to have landed on the tile the caller meant.
#:
#: Deliberately not the hover tooltip: the React Flow pane overlaps the rail, so
#: ``Locator.hover`` fails its actionability check and times out - which is how
#: the first run of this file "found" a bug that was only the harness.
PALETTE_ICON_CLASS: dict[str, str] = {
    "data-loading": "fa-upload",
    "data-export": "fa-download",
    "data-transformation": "fa-database",
    "data-pool": "fa-server",
    "computation-analysis": "fa-python",
    "data-summary": "fa-rectangle-list",
    "js-computation": "fa-js",
    "vis-vega": "fa-chart-line",
    "vis-simple": "fa-table",
    "autk-grammar": "fa-city",
    "spatial-join": "fa-object-group",
    "merge-flow": "fa-code-merge",
}


def palette_tile_identity(page, template_id: str) -> dict:
    """What the rail exposes about one tile, without touching it.

    Returns ``{found, iconOk, icon, id, ariaLabel, title, accessibleText}``.
    ``iconOk`` is the check that the positional lookup landed correctly; the
    remaining fields are the evidence for whether the tile is identifiable to
    anything other than a sighted user with a mouse.
    """
    tile = palette_tile(page, template_id)
    if not tile.count():
        return {"found": False}
    return tile.evaluate(
        """(el, expected) => {
            const svg = el.querySelector('svg');
            const cls = svg ? (svg.getAttribute('class') || '') : '';
            const icon = (cls.match(/\\bfa-[a-z0-9-]+\\b/g) || [])
                .filter((c) => c !== 'fa-fw' && c !== 'fa-solid' && c !== 'fa-brands');
            return {
                found: true,
                icon: icon,
                iconOk: cls.split(/\\s+/).includes(expected),
                id: el.getAttribute('id'),
                ariaLabel: el.getAttribute('aria-label'),
                title: el.getAttribute('title'),
                role: el.getAttribute('role'),
                accessibleText: (el.textContent || '').trim(),
            };
        }""",
        PALETTE_ICON_CLASS[template_id],
    )


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------


_SEVERITY_ORDER = {"bug": 0, "error": 1, "warning": 2, "note": 3}


def collect_sessions() -> tuple[list[dict], dict[str, dict]]:
    """Every session summary written to the output dir, and its video.

    Read off disk rather than out of the running process: a session that takes
    the interpreter down with it (a browser crash, an OOM) must not cost the
    report for the sessions that already finished, and re-running one session on
    its own must not erase the others. ``session-<id>.json`` and
    ``curio-usertest-<id>.webm`` share the id, which is what pairs them.
    """
    directory = out_dir()
    sessions: list[dict] = []
    videos: dict[str, dict] = {}
    for name in sorted(os.listdir(directory)):
        if not (name.startswith("session-") and name.endswith(".json")):
            continue
        session_id = name[len("session-"):-len(".json")]
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                summary = json.load(fh)
        except (OSError, ValueError):
            continue
        sessions.append(summary)
        for ext in ("webm", "mp4"):
            video = os.path.join(directory, f"curio-usertest-{session_id}.{ext}")
            if os.path.exists(video):
                videos.setdefault(summary.get("session", session_id), {})[ext] = video
    return sessions, videos


def write_report(sessions: list[dict], *, videos: dict[str, dict]) -> str:
    """Write findings.json and FINDINGS.md; return the markdown path."""
    payload = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "videos": videos,
        "sessions": sessions,
    }
    json_path = os.path.join(out_dir(), "findings.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    findings = [f for s in sessions for f in s["findings"]]
    findings.sort(
        key=lambda f: (
            _SEVERITY_ORDER.get(f["severity"], 9),
            f["session"],
            f["video_offset_ms"],
        )
    )

    lines = ["# Curio user-test findings", ""]
    lines.append(
        f"Generated {payload['generatedAt']}. "
        f"{len(sessions)} session(s), {len(findings)} finding(s)."
    )
    lines.append("")
    lines.append("## Videos")
    lines.append("")
    if videos:
        lines.append("| Session | File |")
        lines.append("| --- | --- |")
        for session, paths in videos.items():
            for kind, path in paths.items():
                lines.append(f"| {session} | `{os.path.basename(path)}` ({kind}) |")
    else:
        lines.append("_No video was written._")
    lines.append("")

    lines.append("## Sessions")
    lines.append("")
    lines.append("| Session | Steps | ok | failed | unexpectedly ok | bugs | errors |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for s in sessions:
        outcomes = [st["outcome"] for st in s["steps"]]
        lines.append(
            f"| {s['session']} | {len(outcomes)} "
            f"| {outcomes.count('ok') + outcomes.count('failed-as-expected')} "
            f"| {outcomes.count('failed')} "
            f"| {outcomes.count('unexpectedly-ok')} "
            f"| {s['counts'].get('bug', 0)} | {s['counts'].get('error', 0)} |"
        )
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    if not findings:
        lines.append("_Nothing was recorded._")
    for i, f in enumerate(findings, 1):
        ms = f["video_offset_ms"]
        lines.append(
            f"### {i}. [{f['severity']}/{f['kind']}] {f['session']} - {f['step']}"
        )
        lines.append("")
        lines.append(f"- **Video offset**: {ms // 60000:02d}:{(ms // 1000) % 60:02d}")
        if f.get("still"):
            lines.append(f"- **Still**: `{os.path.basename(f['still'])}`")
        lines.append("")
        lines.append("```")
        lines.append(f["detail"].strip()[:4000])
        lines.append("```")
        lines.append("")

    md_path = os.path.join(out_dir(), "FINDINGS.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return md_path


__all__ = [
    "Finding",
    "PALETTE_LABELS",
    "PALETTE_TILES",
    "UserSession",
    "collect_sessions",
    "finalize_video",
    "out_dir",
    "palette_tile",
    "PALETTE_ICON_CLASS",
    "palette_tile_identity",
    "write_report",
]
