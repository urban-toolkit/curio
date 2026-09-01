"""Scripted user journeys through Curio, each consumed twice.

A walkthrough is one short scripted path through the app that ends on a state
worth pinning: a chart that renders, a drawer that opens, a graph you can pan.

``test_walkthrough_videos.py`` runs them with :class:`tour.Tour` narrating and a
recorder attached, producing one screencast each.
``test_walkthrough_baselines.py`` runs the SAME functions silently and diffs a
committed screenshot at the point each one holds.

Keeping one definition is the point: a journey that drifts from the behaviour it
documents would otherwise keep recording a green video while the baseline it was
written beside quietly stopped testing anything.

Narration goes through ``ctx.say`` / ``ctx.click`` rather than the raw locator so
the caption, cursor and spotlight stay in step with the browser during a
recording -- and vanish entirely during a baseline capture, where an overlay
would poison every pixel.

Walkthroughs added to close a bug carry its number in ``refs``; that is metadata
for the report, not identity. The slug names the behaviour, so a journey outlives
the ticket that prompted it.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .utils import REPO_ROOT

EXAMPLES_DIR = os.path.join(REPO_ROOT, "docs", "examples")


# ---------------------------------------------------------------------------
# Narration
# ---------------------------------------------------------------------------

class Narrator(Protocol):
    """The slice of :class:`tour.Tour` a walkthrough uses.

    ``SilentNarrator`` implements the same calls with no overlay and no pacing,
    so a walkthrough reads identically in both modes.
    """

    def chapter(self, kicker: str, title: str, sub: str = "", hold: float | None = None) -> None: ...
    def say(self, title: str, sub: str = "", hold: float | None = None) -> None: ...
    def beat(self, ms: float = 700) -> None: ...
    def focus(self, locator, *, hold: float = 900, ring: bool = True): ...
    def click(self, locator, *, force: bool = False, dispatch: bool = False,
              hold: float = 700, ring: bool = True) -> None: ...
    def type_into(self, locator, text: str, *, delay: float = 55) -> None: ...
    def scroll(self, dy: float, *, steps: int = 6, hold: float = 90) -> None: ...
    def hush(self) -> None: ...


class SilentNarrator:
    """Drives the page with no overlay, for the baseline pass.

    Every method mirrors ``Tour``'s signature and drops the presentation. The
    interactions still happen -- a baseline of a screen nobody navigated to
    would be a baseline of the wrong screen.
    """

    def __init__(self, page) -> None:
        self.page = page

    def chapter(self, kicker: str, title: str, sub: str = "", hold: float | None = None) -> None:
        return None

    def say(self, title: str, sub: str = "", hold: float | None = None) -> None:
        return None

    def beat(self, ms: float = 700) -> None:
        # Kept, and deliberately short: journeys use beats to let the app settle
        # (a drawer transition, a re-render), not only for pacing.
        self.page.wait_for_timeout(min(ms, 150))

    def focus(self, locator, *, hold: float = 900, ring: bool = True):
        try:
            locator.wait_for(state="visible", timeout=10000)
        except Exception:
            return None
        return locator.bounding_box()

    def click(self, locator, *, force: bool = False, dispatch: bool = False,
              hold: float = 700, ring: bool = True) -> None:
        if dispatch:
            locator.dispatch_event("click")
        else:
            locator.click(force=force)
        self.beat(hold)

    def type_into(self, locator, text: str, *, delay: float = 55) -> None:
        locator.click()
        locator.fill(text)

    def scroll(self, dy: float, *, steps: int = 6, hold: float = 90) -> None:
        self.page.mouse.wheel(0, dy)
        self.beat(hold)

    def hush(self) -> None:
        return None


@dataclass
class Ctx:
    """What a walkthrough is handed."""
    page: object
    frontend: str
    backend: str
    narrator: Narrator
    recording: bool
    #: Pins an intermediate state as its own screenshot baseline. Supplied by
    #: the baseline suite; a no-op while recording, where the video already
    #: carries the whole journey.
    snapshot: Callable[[str], None] = lambda label: None

    def capture(self, label: str) -> None:
        """Pin the current screen as a baseline called *label*.

        For a journey whose point is a sequence -- reverting through a version
        history, stepping through a wizard -- the final frame is not the claim.
        Each step is, so each step gets its own committed PNG.
        """
        self.snapshot(label)

    # Convenience passthroughs so a walkthrough reads as prose.
    def say(self, title: str, sub: str = "", hold: float | None = None) -> None:
        self.narrator.say(title, sub, hold)

    def click(self, locator, **kw) -> None:
        self.narrator.click(locator, **kw)

    def focus(self, locator, **kw):
        return self.narrator.focus(locator, **kw)

    def beat(self, ms: float = 700) -> None:
        self.narrator.beat(ms)


@dataclass
class Walkthrough:
    """One journey through the app, plus how to capture it."""
    #: Kebab-case name for the behaviour. Names the video, the baseline PNG and
    #: the test id, so all three stay legible without a ticket to hand.
    slug: str
    title: str
    #: What the journey demonstrates, shown on the video's chapter card.
    premise: str
    run: Callable[[Ctx], None]
    #: What changed, for the report. Empty for a journey that documents
    #: behaviour rather than a fix.
    note: str = ""
    #: Regression tests that cover the same ground.
    tests: list[str] = field(default_factory=list)
    #: Issues this journey closes. Metadata, not identity.
    refs: list[int] = field(default_factory=list)
    #: Capture the whole page, or just the element under test. Clipping keeps
    #: the diff budget on the subject instead of on surrounding chrome.
    clip_selector: str | None = None
    #: ``False`` for pages with no canvas -- the helper otherwise spends its
    #: whole timeout waiting for a ``.react-flow__node`` that never arrives.
    fit_reactflow: bool = True
    #: Fraction of pixels allowed to differ. The helper's 0.20 default is blind
    #: to a restored 1.5px border or a button that grew one line, so the small
    #: visual fixes tighten it hard.
    max_diff_ratio: float = 0.20

    @property
    def stem(self) -> str:
        return self.slug


# ---------------------------------------------------------------------------
# Shared steps
# ---------------------------------------------------------------------------

def load_example_spec(name: str) -> dict:
    """One of the curated example dataflows, as a project spec."""
    with open(os.path.join(EXAMPLES_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def top_menu(page, label: str):
    """A top-bar dropdown trigger (``File`` , ``View`` , ``Provenance`` ...).

    The trigger's accessible name carries the caret, which is also what keeps it
    apart from the same-named row inside the dropdown it opens.
    """
    return page.get_by_role("button", name=f"{label} ⏷", exact=True)


def open_provenance(ctx: Ctx):
    """Open the Provenance modal from the top menu and return its dialog.

    Two clicks: the top-bar dropdown, then its single row. ``force`` on the
    first mirrors the tour - the canvas chrome overlaps the bar's hit box.
    """
    page = ctx.page
    ctx.click(top_menu(page, "Provenance"), force=True)
    ctx.click(page.get_by_role("button", name="Provenance", exact=True))
    dialog = page.get_by_role("dialog").filter(has_text="Provenance for")
    dialog.wait_for(state="visible", timeout=20000)
    # The graph lays out through dagre on mount; capture after it settles or the
    # baseline records nodes stacked at the origin.
    page.wait_for_selector(".react-flow__node", timeout=20000)
    ctx.beat(900)
    return dialog


# The provenance modal renders its own React Flow inside a portal on
# document.body, so a bare `.react-flow__node` count would mix the version graph
# in with the dataflow behind it. Everything below counts only what is OUTSIDE
# the modal - i.e. the canvas the user is reverting.
_CANVAS_COUNT_JS = """
(sel) => Array.from(document.querySelectorAll(sel))
    .filter((el) => !el.closest('[data-curio-modal-shell="true"]')).length
"""

_CANVAS_SETTLED_JS = """
([sel, want]) => Array.from(document.querySelectorAll(sel))
    .filter((el) => !el.closest('[data-curio-modal-shell="true"]')).length === want
"""


def canvas_graph(page) -> dict:
    """``{nodes, edges}`` currently on the dataflow canvas."""
    return {
        "nodes": page.evaluate(_CANVAS_COUNT_JS, ".react-flow__node"),
        "edges": page.evaluate(_CANVAS_COUNT_JS, ".react-flow__edge"),
    }


def await_canvas_nodes(page, want: int, *, timeout: float = 15000) -> None:
    """Wait for the canvas to hold *want* nodes.

    Reverting rebuilds the canvas through React state, so the count lands a tick
    or two after the click. Swallowing the timeout is deliberate: the assertion
    that follows reports the actual counts, which says far more than
    ``TimeoutError`` would.
    """
    try:
        page.wait_for_function(
            _CANVAS_SETTLED_JS, arg=[".react-flow__node", want], timeout=timeout,
        )
    except Exception:
        pass


def version_graph(version) -> dict:
    """``{nodes, edges}`` a version's thumbnail says it holds.

    DataflowThumbnail draws a background rect, two rects per node, and one line
    per edge whose endpoints it can resolve - so the drawing is a faithful
    read-out of the snapshot, which is what makes it usable as the expectation
    for what reverting to that version should put on the canvas.
    """
    marks = version.evaluate(
        "el => { const svg = el.querySelector('svg');"
        " return svg ? { lines: svg.querySelectorAll('line').length,"
        " rects: svg.querySelectorAll('rect').length } : null; }"
    ) or {"lines": 0, "rects": 0}
    return {"nodes": max(0, (marks["rects"] - 1) // 2), "edges": marks["lines"]}


WALKTHROUGHS: list[Walkthrough] = []


def walkthrough(**kw):
    """Register a walkthrough; the decorated function becomes its ``run``."""
    def wrap(fn):
        WALKTHROUGHS.append(Walkthrough(run=fn, **kw))
        return fn
    return wrap


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

PROVENANCE_EXAMPLE = "01-vega-lite-chained-transforms.json"


@walkthrough(
    slug="provenance-graph-of-a-loaded-dataflow",
    refs=[186],
    title="Loaded dataflows get a real provenance graph",
    premise="Open a saved dataflow, then read its version history.",
    note="loadParsedTrill now snapshots each version from the arrays it was handed, "
        "not from the React Flow store, which is one commit stale inside its own "
        "synchronous load loop.",
    tests=["src/tests/hook/useWorkflowOperations.loadProvenance.test.ts",
           "test_frontend/test_walkthrough_baselines.py"],
    clip_selector='[data-curio-modal-shell="true"]',
    fit_reactflow=False,
)
def provenance_graph_of_a_loaded_dataflow(ctx: Ctx) -> None:
    page = ctx.page
    spec = load_example_spec(PROVENANCE_EXAMPLE)["dataflow"]
    node_count, edge_count = len(spec["nodes"]), len(spec["edges"])

    ctx.say("An example dataflow, opened from the gallery",
            "Every node and edge came from the saved spec.")
    dialog = open_provenance(ctx)

    versions = dialog.locator(".react-flow__node")
    assert versions.count() == 1 + node_count + edge_count, (
        f"the graph has {versions.count()} versions; one per loaded node and "
        f"edge plus the initial one would be {1 + node_count + edge_count}"
    )

    ctx.say("One version per node, then one per connection",
            "Zoom in on the newest.")
    zoom_in = dialog.get_by_role("button", name="zoom in")
    for _ in range(3):
        ctx.click(zoom_in, hold=260)
    versions.last.scroll_into_view_if_needed()
    ctx.beat(900)

    # The load-bearing check. DataflowThumbnail draws one <line> per edge and two
    # <rect> per node, and SKIPS any edge whose endpoints are missing from the
    # same preview -- so a version captured from the stale React Flow store (one
    # node, no edges) renders a background rect and nothing else. That is what
    # made the boxes read as blank and isolated.
    marks = versions.last.evaluate(
        "el => { const svg = el.querySelector('svg');"
        " return svg ? { lines: svg.querySelectorAll('line').length,"
        " rects: svg.querySelectorAll('rect').length } : null; }"
    )
    assert marks, "the newest provenance version rendered no thumbnail at all"
    assert marks["lines"] == edge_count, (
        f"the newest version's thumbnail draws {marks['lines']} of the "
        f"dataflow's {edge_count} connections - its snapshot is missing the "
        f"nodes they run between, so they are dropped and the box reads as empty"
    )
    assert marks["rects"] >= 1 + 2 * node_count, (
        f"the newest version's thumbnail draws {(marks['rects'] - 1) // 2} of "
        f"the dataflow's {node_count} nodes"
    )

    ctx.say("Every version holds the whole graph",
            "The dataflow as it stood at that step, not one node from a stale "
            "snapshot.")
    ctx.focus(versions.last, hold=1600)


@walkthrough(
    slug="provenance-graph-navigation",
    refs=[187],
    title="The provenance graph pans and zooms",
    premise="Drag the version graph to reach a node below the fold.",
    note="ModalShell puts React Flow's own `nopan`/`nowheel` classes on the dialog, "
        "and React Flow matches them by ancestor. The inner graph now names "
        "opt-out classes nothing inside it carries.",
    tests=["src/tests/components/trillProvenanceWindowPan.test.tsx",
           "test_frontend/test_walkthrough_baselines.py"],
    clip_selector='[data-curio-modal-shell="true"]',
    fit_reactflow=False,
)
def provenance_graph_navigation(ctx: Ctx) -> None:
    page = ctx.page
    dialog = open_provenance(ctx)

    graph = dialog.locator(".react-flow__pane").first
    box = graph.bounding_box()
    assert box, "the provenance graph has no layout box"
    before = _viewport_transform(page)

    ctx.say("Drag the graph", "Reach the versions below the fold.")
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    for step in range(1, 13):
        page.mouse.move(
            box["x"] + box["width"] / 2 - step * 9,
            box["y"] + box["height"] / 2 - step * 11,
        )
        ctx.beat(40)
    page.mouse.up()
    ctx.beat(700)

    assert _viewport_transform(page) != before, (
        "the drag did not move the graph at all - the modal's own `nopan` class "
        "is an ancestor of the canvas, and React Flow matches it by ancestor, so "
        "every pan and wheel-zoom inside the dialog is refused"
    )
    ctx.say("The graph pans", "Versions past the fold are reachable.")


@walkthrough(
    slug="provenance-reverting-to-a-previous-version",
    refs=[195],
    title="Reverting a dataflow to an earlier version",
    premise="Step back through the version graph and watch the canvas follow.",
    note="onConnect resolved its target with `nodes.find(...) as Node` and never "
         "checked it, so reverting to a version whose edges named nodes it does "
         "not hold tore the canvas down. Such an edge is now dropped instead.",
    tests=["src/tests/providers/onConnectMissingEndpoint.test.tsx",
           "test_frontend/test_walkthrough_baselines.py"],
)
def provenance_reverting_to_a_previous_version(ctx: Ctx) -> None:
    page = ctx.page
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    saved = canvas_graph(page)
    ctx.say("The dataflow as saved",
            f"{saved['nodes']} nodes, {saved['edges']} connections.")

    dialog = open_provenance(ctx)
    versions = dialog.locator(".react-flow__node")
    count = versions.count()
    assert count > 1, f"the provenance graph offers {count} versions to revert to"

    # Newest-first, skipping the one already on the canvas, so the dataflow
    # visibly unwinds. Four is the floor: a single hop would not show that the
    # history is walkable, only that one click works.
    targets = list(range(count - 2, -1, -1))
    assert len(targets) >= 4, (
        f"only {len(targets)} earlier versions available; this walkthrough steps "
        f"back through at least four"
    )

    ctx.say("Revert by clicking a version",
            "The canvas becomes exactly what that version holds.")

    for index in targets:
        version = versions.nth(index)
        expected = version_graph(version)
        ctx.click(version, hold=520)
        await_canvas_nodes(page, expected["nodes"])
        actual = canvas_graph(page)

        assert not errors, (
            f"reverting to version {index + 1} threw, and with no error boundary "
            f"in the app React tears down the whole canvas: "
            f"{errors[0].splitlines()[0]}"
        )
        assert actual == expected, (
            f"reverting to version {index + 1} of {count} left {actual['nodes']} "
            f"nodes and {actual['edges']} connections on the canvas, but that "
            f"version holds {expected['nodes']} and {expected['edges']}"
        )
        ctx.capture(f"reverted-to-v{index + 1:02d}")

    ctx.say(f"Stepped back through {len(targets)} versions",
            "Each one put its own graph on the canvas.")

    # Forward to the newest, so the canvas ends where it started.
    ctx.click(versions.nth(count - 1), hold=520)
    await_canvas_nodes(page, saved["nodes"])
    restored = canvas_graph(page)
    assert restored == saved, (
        f"returning to the newest version left {restored} on the canvas, not the "
        f"saved dataflow's {saved}"
    )
    assert page.locator("#webpack-dev-server-client-overlay").count() == 0, (
        "the dev-server error overlay has taken the whole screen"
    )

    ctx.capture("returned-to-newest")

    ctx.click(page.get_by_role("button", name="Close").last)
    page.wait_for_selector(".react-flow__node", timeout=20000)
    ctx.beat(800)
    ctx.say("And forward again",
            "Back to the saved dataflow, with no runtime error anywhere in the walk.")


def _viewport_transform(page) -> str:
    return page.evaluate(
        "() => { const el = document.querySelector("
        "'[data-curio-modal-shell=\"true\"] .react-flow__viewport');"
        " return el ? getComputedStyle(el).transform : ''; }"
    )
