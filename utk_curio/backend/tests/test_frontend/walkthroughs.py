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
import re
import uuid
from dataclasses import dataclass, field
from typing import Callable, Protocol

from playwright.sync_api import expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .utils import (
    REPO_ROOT,
    accept_confirm_dialog,
    api_json,
    assert_vega_canvas_rendered,
    canvas_nodes,
    close_tools_palette,
    connect_nodes,
    drag_to_canvas,
    frame_node,
    node_locator,
    open_tools_palette,
    play_node,
    require_owner_view,
    run_node_and_wait,
    set_node_code,
    wait_for_node_done,
    signup_e2e_user,
    wait_for_projects_page,
)

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

    def __init__(self, page, *, beat_cap: float | None = 150) -> None:
        self.page = page
        #: Longest a single beat may last, in ms. The baseline pass caps them
        #: hard - it only needs the app to settle before a capture, and every
        #: extra millisecond is dead time in CI. A recording passes ``None`` to
        #: honour the full beat, so the video moves at a watchable pace without
        #: any narration to supply one.
        self.beat_cap = beat_cap

    def chapter(self, kicker: str, title: str, sub: str = "", hold: float | None = None) -> None:
        return None

    def say(self, title: str, sub: str = "", hold: float | None = None) -> None:
        return None

    def beat(self, ms: float = 700) -> None:
        # Beats are how a journey lets the app settle (a drawer transition, a
        # re-render), not only how it paces itself.
        self.page.wait_for_timeout(ms if self.beat_cap is None else min(ms, self.beat_cap))

    def focus(self, locator, *, hold: float = 900, ring: bool = True):
        try:
            locator.wait_for(state="visible", timeout=10000)
        except Exception:
            return None
        box = locator.bounding_box()
        # No ring and no cursor - but a recording still pauses on the subject,
        # which is the only pacing left once the captions are gone.
        self.beat(hold)
        return box

    def click(self, locator, *, force: bool = False, dispatch: bool = False,
              hold: float = 700, ring: bool = True) -> None:
        if dispatch:
            locator.dispatch_event("click")
        else:
            locator.click(force=force)
        self.beat(hold)

    def focus_hold(self, ms: float) -> None:
        self.beat(ms)

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
    #:
    #: Also ``False`` for a scene that aims its own camera: the helper fitViews
    #: immediately before every capture, so a ``frame_node`` call is undone
    #: between the framing and the screenshot and the image comes out as the
    #: whole dataflow regardless.
    fit_reactflow: bool = True
    #: Fraction of pixels allowed to differ. The helper's 0.20 default is blind
    #: to a restored 1.5px border or a button that grew one line, so the small
    #: visual fixes tighten it hard.
    max_diff_ratio: float = 0.20
    #: The example dataflow to open the journey on, by filename under
    #: ``docs/examples``. ``None`` means an EMPTY dataflow.
    #:
    #: It used to default to one particular example, so every recording opened
    #: on "Vega-Lite chained transforms" whether or not the journey had anything
    #: to do with it - which reads as if that dataflow were part of the subject.
    #: A catalog scene needs no dataflow at all; one about a chart or a wide
    #: table cannot demonstrate itself without the right one. So each scene says
    #: what it needs, and says nothing when it needs nothing.
    example: str | None = None
    #: Needs the stack seeded with the example dataflows. The scene then carries
    #: the ``examples`` marker, so an ordinary run skips it honestly instead of
    #: asserting against an empty gallery and blaming the seed.
    needs_examples: bool = False

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


def first_node_of_type(example: str, node_type: str, *, containing: str = "") -> str:
    """The id of the first node of *node_type* in an example dataflow.

    Nodes are addressed in the DOM by React Flow's ``data-id``; their Curio type
    is not on the element, so a scene that needs "the Autark node" resolves its
    id from the spec it was opened on rather than guessing from display text.

    ``containing`` narrows further by a substring of the node's authored spec
    (its ``content``). Type alone is often too coarse: 07-autark-gpu-shader has
    four ``autk-grammar`` nodes and only one of them declares a ``map``, so the
    WebGPU guard - which fires only for map/plot/compute specs - would never be
    reached on the first match.
    """
    spec = load_example_spec(example)
    for node in spec.get("dataflow", {}).get("nodes", []):
        if node_type not in str(node.get("type") or node.get("nodeType") or ""):
            continue
        if containing and containing not in str(node.get("content") or ""):
            continue
        return str(node["id"])
    raise AssertionError(
        f"{example} contains no {node_type} node"
        + (f" whose spec contains {containing!r}" if containing else "")
        + ", so this walkthrough is pointed at the wrong example"
    )


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
    example=PROVENANCE_EXAMPLE,
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
    example=PROVENANCE_EXAMPLE,
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
    example=PROVENANCE_EXAMPLE,
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


# ---------------------------------------------------------------------------
# Agent Catalog
# ---------------------------------------------------------------------------

AGENT_DRAWER_ROOT = '[data-curio-agent-catalog-drawer="true"]'

#: The catalog PAGES' detail drawer (/catalog/data, /catalog/nodes,
#: /catalog/agents). Distinct from the canvas drawers above: the account-level
#: actions live here, not on a card and not in the canvas.
BROWSE_DRAWER_ROOT = '[data-curio-browse-drawer="true"]'


def open_agent_drawer(ctx: Ctx):
    """Data menu -> Agent Catalog, returning the drawer dialog."""
    page = ctx.page
    ctx.click(top_menu(page, "Data"), force=True)
    # "Agent Catalog" also labels the left-rail palette trigger, whose
    # accessible name carries a count; exact=True picks the menu row.
    ctx.click(page.get_by_role("button", name="Agent Catalog", exact=True))
    page.locator(AGENT_DRAWER_ROOT).wait_for(state="attached", timeout=15000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Agent Catalog", exact=True)
    )
    dialog.wait_for(state="visible", timeout=15000)
    ctx.beat(600)
    return dialog


def fits_on_one_line(button) -> dict:
    """Whether a button's label stays inside its box.

    ``scrollHeight`` beyond ``clientHeight`` is the wrap; ``scrollWidth`` beyond
    ``clientWidth`` is the ellipsis. Reported together so a failure says which.
    """
    return button.evaluate(
        "el => ({ text: el.textContent.trim(),"
        " clientH: el.clientHeight, scrollH: el.scrollHeight,"
        " clientW: el.clientWidth, scrollW: el.scrollWidth,"
        " fontSize: getComputedStyle(el).fontSize })"
    )


@walkthrough(
    slug="agent-catalog-adding-to-an-unsaved-dataflow",
    refs=[190, 199],
    title="Adding an agent to a dataflow you have not saved",
    premise="Open the Agent Catalog on a fresh dataflow and add an agent to it.",
    note="The Add button was disabled whenever `projectId` was null, which is "
         "the ordinary state of a dataflow you just made. It now resolves the "
         "dataflow at click time through the shared `ensureProjectId`, the way "
         "the Data and Node catalogs already did.",
    tests=["src/tests/catalog/AgentCatalogDrawer.test.tsx",
           "test_frontend/test_walkthrough_baselines.py"],
    clip_selector=AGENT_DRAWER_ROOT,
    fit_reactflow=False,
    max_diff_ratio=0.03,
)
def agent_catalog_adding_to_an_unsaved_dataflow(ctx: Ctx) -> None:
    page = ctx.page

    # The harness seeds a SAVED project, and on one of those the button was
    # never disabled - so this journey has to leave it. `/dataflow/new` is the
    # route a brand-new dataflow sits on until something persists it, and
    # `projectId` is null for exactly that long.
    page.goto(f"{ctx.frontend}/dataflow/new")
    page.wait_for_url("**/dataflow/new", timeout=20000)
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
    # Narrate after the navigation, not before: captioning "a brand-new
    # dataflow" over the previous one is a recording that argues with itself.
    ctx.say("A brand-new dataflow", "Nothing has saved it yet.")
    assert page.url.rstrip("/").endswith("/dataflow/new"), (
        f"expected to be on an unsaved dataflow, but the URL is {page.url} - "
        f"something saved it and this journey would prove nothing"
    )
    ctx.beat(700)

    # The save indicator states what is on disk, so it is most worth reading
    # exactly here - where the answer is "nothing". It used to be absent on a
    # never-saved dataflow, which is how this went unnoticed.
    disk = page.locator("[data-curio-save-state]")
    disk.wait_for(state="visible", timeout=15000)
    assert disk.get_attribute("data-curio-save-state") == "unsaved", (
        f"the save indicator reads "
        f"{disk.get_attribute('data-curio-save-state')!r} on a dataflow that "
        f"has never been saved"
    )
    ctx.focus(disk, hold=1100)
    ctx.say("Nothing is on disk yet", "The save indicator is orange.")

    dialog = open_agent_drawer(ctx)

    ctx.say("The Agent Catalog", "Open on a dataflow that has never been saved.")
    # The unsaved-dataflow banner was removed from all three catalogs: it only
    # ever appeared on an unsaved dataflow, so it read as a state the other
    # surfaces did not have, and the add already explains itself twice over -
    # the confirmation says what it will do, the save indicator shows it done.
    assert not dialog.get_by_text("isn't saved yet", exact=False).count(), (
        "the unsaved-dataflow banner is back; it was removed for repeating "
        "what the confirmation and the save indicator already say"
    )

    add = dialog.get_by_role("button", name="Add to project").first
    add.wait_for(state="visible", timeout=15000)
    assert add.is_enabled(), (
        "Add to project is disabled on an unsaved dataflow - the drawer is "
        "still gating on a project id instead of creating one on the click"
    )
    ctx.capture("add-enabled")

    ctx.say("Add it", "The dataflow is saved first, then the agent goes in.")
    ctx.click(add)

    # Adding confirms first now (#196), the way all three catalogs do.
    accept_confirm_dialog(
        ctx.page, title=re.compile(r"^Add "), button="Add to project"
    )

    installed = dialog.get_by_role("button", name="Remove from project").first
    installed.wait_for(state="visible", timeout=30000)

    # The save really happened: the route carries a project id now.
    page.wait_for_url(lambda url: "/dataflow/new" not in url, timeout=20000)
    assert "/dataflow/new" not in page.url, (
        f"the agent was added but the dataflow was never saved (still at "
        f"{page.url})"
    )
    ctx.capture("agent-added")

    # And the indicator agrees: the add wrote the dataflow to disk.
    page.wait_for_function(
        "() => document.querySelector('[data-curio-save-state]')"
        "?.getAttribute('data-curio-save-state') === 'saved'",
        timeout=20000,
    )
    ctx.say("Added, and the dataflow saved itself",
            "The URL carries a real id now, and the indicator has gone green.")


@walkthrough(
    slug="agent-catalog-account-agent-on-an-unsaved-dataflow",
    refs=[190, 199],
    title="An agent you already have, on a dataflow you have not saved",
    premise="Add an agent to every project, then open the Agent Catalog on a new dataflow.",
    note="The sibling scene covers a fresh account, where every card offers Add. "
         "An account that already holds the agent takes the other branch: "
         "`inThisDataflow` counts it as present, so the card renders Remove - and "
         "Remove was still gated on `hasProject`, which is null until the first "
         "save. The result was a disabled control and nothing else, which is the "
         "symptom #190 and #199 both report, reached through a different door. "
         "Remove now creates the dataflow on the click, exactly as Add does.",
    tests=["src/tests/catalog/AgentCatalogDrawer.test.tsx",
           "test_frontend/test_walkthrough_baselines.py"],
    clip_selector=AGENT_DRAWER_ROOT,
    fit_reactflow=False,
    max_diff_ratio=0.03,
)
def agent_catalog_account_agent_on_an_unsaved_dataflow(ctx: Ctx) -> None:
    page = ctx.page

    # Put the agent in the ACCOUNT first, through the UI. "Add to all projects"
    # on the catalog page posts /api/agents/imports, which is what sets
    # `imported` - the flag the drawer then reads to decide Add versus Remove.
    ctx.say("Add an agent to every project", "An account-level decision, made on the catalog page.")
    page.goto(f"{ctx.frontend}/catalog/agents")
    page.wait_for_load_state("domcontentloaded")
    browse_drawer = page.locator(BROWSE_DRAWER_ROOT)
    browse_drawer.wait_for(state="visible", timeout=30000)

    add_to_all = browse_drawer.get_by_role("button", name="Add to all projects")
    if add_to_all.count():
        ctx.click(add_to_all.first)
        browse_drawer.get_by_role(
            "button", name="Remove from all projects"
        ).first.wait_for(state="visible", timeout=30000)
    coord = page.locator("article[data-agent-coord]").first.get_attribute(
        "data-agent-coord"
    )
    assert coord, "no agent card to read a coordinate from"

    # Now a dataflow that has never been saved.
    ctx.say("A brand-new dataflow", "Nothing has saved it yet.")
    page.goto(f"{ctx.frontend}/dataflow/new")
    page.wait_for_url("**/dataflow/new", timeout=20000)
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
    disk = page.locator("[data-curio-save-state]")
    disk.wait_for(state="visible", timeout=15000)
    assert disk.get_attribute("data-curio-save-state") == "unsaved", (
        f"the save indicator reads "
        f"{disk.get_attribute('data-curio-save-state')!r} on a dataflow that "
        f"has never been saved"
    )

    dialog = open_agent_drawer(ctx)
    card = dialog.locator(f'article[data-agent-coord="{coord}"]')
    card.wait_for(state="visible", timeout=30000)

    # THE POINT: the account already holds it, so this card shows Remove - and
    # that control has to be usable. It was disabled, with a tooltip telling the
    # user to go and save first, on a surface whose Add button saves for them.
    remove = card.get_by_role("button", name="Remove from project", exact=True)
    remove.wait_for(state="visible", timeout=30000)
    assert remove.is_enabled(), (
        "Remove from project is disabled on an unsaved dataflow, so an agent "
        "the account already holds offers no usable control at all - the drawer "
        "is still gating on a project id instead of creating one on the click"
    )
    ctx.focus(remove, hold=1200)
    ctx.capture("remove-enabled-on-unsaved-dataflow")

    ctx.say("Remove it", "The dataflow is saved first, then the agent comes out.")
    ctx.click(remove)
    accept_confirm_dialog(page, title=re.compile(r"^Remove "), button="Remove")

    # The save really happened, and the card flipped to the other branch.
    page.wait_for_url(lambda url: "/dataflow/new" not in url, timeout=30000)
    card.get_by_role("button", name=re.compile(r"^Add to project")).first.wait_for(
        state="visible", timeout=30000
    )
    page.wait_for_function(
        "() => document.querySelector('[data-curio-save-state]')"
        "?.getAttribute('data-curio-save-state') === 'saved'",
        timeout=20000,
    )
    ctx.capture("removed-and-saved")
    ctx.say("Removed, and the dataflow saved itself",
            "The same one-click save the Add path already did.")


@walkthrough(
    slug="agent-catalog-action-labels-fit",
    refs=[191],
    title="Agent action labels fit their button",
    premise="Read the account-level actions on an agent, where the longest label lives.",
    note="The reported overflow was on the agent drawer's card column, pinned at "
         "140px, where \"Remove from all projects\" wrapped inside a 30px box and "
         "spilled out. That control has since moved: account-level actions are "
         "decisions about an item, not about one dataflow, so they live on the "
         "Agent Catalog page's detail drawer now. This scene follows the label - "
         "the claim is unchanged, only its address.",
    tests=["src/tests/styles/agentDrawerButtonGeometry.test.ts",
           "test_frontend/test_walkthrough_baselines.py"],
    clip_selector=BROWSE_DRAWER_ROOT,
    fit_reactflow=False,
    # The claim above is asserted in code; the PNG only documents it. The
    # Linux runner antialiases text differently from the machine that captured
    # the baseline (5.1% of pixels on CI, run to run stable), so the pin
    # must leave room for that without waving through a real change.
    max_diff_ratio=0.10,
)
def agent_catalog_action_labels_fit(ctx: Ctx) -> None:
    page = ctx.page

    ctx.say("The Agent Catalog page", "Where the account-level actions live.")
    page.goto(f"{ctx.frontend}/catalog/agents")
    page.wait_for_load_state("domcontentloaded")

    # The page auto-selects the first card so the drawer arrives populated.
    drawer = page.locator(BROWSE_DRAWER_ROOT)
    drawer.wait_for(state="visible", timeout=30000)

    # "Remove from all projects" is the longest label in the product, and it
    # only renders once the agent is in the account. Whether it already is
    # depends on leftover per-user state, so reach the state rather than assume
    # it: `primaryAction` toggles on `agent.imported`.
    add = drawer.get_by_role("button", name="Add to all projects")
    if add.count():
        ctx.say("Add it to every project", "That is what puts the long label on screen.")
        ctx.click(add.first)

    remove = drawer.get_by_role("button", name="Remove from all projects").first
    remove.wait_for(state="visible", timeout=30000)
    ctx.focus(remove, hold=1200)

    box = fits_on_one_line(remove)
    assert box["scrollH"] <= box["clientH"] + 1, (
        f"\"{box['text']}\" wraps inside its button at {box['fontSize']}: "
        f"content is {box['scrollH']}px tall in a {box['clientH']}px box, so it "
        f"spills past the border"
    )
    assert box["scrollW"] <= box["clientW"] + 1, (
        f"\"{box['text']}\" is clipped at {box['fontSize']}: content is "
        f"{box['scrollW']}px wide in a {box['clientW']}px box"
    )

    # Every button in the drawer's action bar, not just the reported one.
    for name in ("Remove from all projects", "Add to all projects", "View details"):
        button = drawer.get_by_role("button", name=name).first
        if not button.count():
            continue
        metrics = fits_on_one_line(button)
        assert metrics["scrollH"] <= metrics["clientH"] + 1, (
            f"\"{metrics['text']}\" overflows its button: {metrics}"
        )

    ctx.capture("labels-fit")
    ctx.say("Every label inside its button",
            "The longest one in the product, on the surface that now owns it.")


# ---------------------------------------------------------------------------
# Cross-catalog consistency (#196, #197, #198)
# ---------------------------------------------------------------------------

DATA_DRAWER_ROOT = '[data-curio-dataset-catalog-drawer="true"]'
NODE_DRAWER_ROOT = '[data-curio-node-catalog-drawer="true"]'

#: The toast region ToastProvider portals into. Clipping to it keeps a 0.02
#: budget spent on the toast rather than on the whole canvas behind it.
TOAST_REGION = '[aria-label="Notifications"]'


def open_data_drawer(ctx: Ctx):
    """Data menu -> Data Catalog, returning the drawer dialog."""
    page = ctx.page
    ctx.click(top_menu(page, "Data"), force=True)
    ctx.click(page.get_by_role("button", name="Data Catalog", exact=True))
    root = page.locator(DATA_DRAWER_ROOT)
    root.wait_for(state="attached", timeout=15000)
    # aria-hidden IS the presented signal: until the rAF flips it, every role
    # query inside the subtree returns zero matches.
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )
    dialog.wait_for(state="visible", timeout=15000)
    ctx.beat(600)
    return dialog


def confirm_modal(ctx: Ctx, title):
    """The open ConfirmDialog, by accessible name.

    A bare ``get_by_role("dialog")`` cannot be used while a drawer is open:
    the drawers carry ``role="dialog"`` too, so the query matches both.
    ConfirmDialog wires its heading through ``aria-labelledby``, which makes
    the name unique.
    """
    modal = ctx.page.get_by_role("dialog", name=title)
    modal.wait_for(state="visible", timeout=15000)
    return modal


@walkthrough(
    slug="catalog-add-is-confirmed",
    refs=[196],
    title="Adding from a catalog asks first",
    premise="Add a dataset and an agent, and read the confirmation each one raises.",
    note="Only the Node catalog confirmed an add, through its permissions "
         "dialog; Data and Agent committed a lockfile write on a single "
         "click with nothing to cancel. Both now raise a ConfirmDialog, and "
         "the agent one lists the dependencies the add will pull in with it.",
    tests=["src/tests/catalog/useDatasetCatalogDrawer.import.test.ts",
           "src/tests/catalog/AgentCatalogDrawer.test.tsx",
           "test_frontend/test_walkthrough_baselines.py"],
    fit_reactflow=False,
    max_diff_ratio=0.03,
)
def catalog_add_is_confirmed(ctx: Ctx) -> None:
    page = ctx.page

    ctx.say("The Data Catalog", "Adding a dataset used to commit on one click.")
    drawer = open_data_drawer(ctx)

    add = drawer.get_by_role("button", name="Add to project", exact=True).first
    add.wait_for(state="visible", timeout=20000)
    ctx.click(add)

    modal = confirm_modal(ctx, re.compile(r"^Add "))
    ctx.focus(modal, hold=1400)
    ctx.say("It asks first", "Cancel leaves the dataflow exactly as it was.")
    ctx.capture("data-add-confirm")

    # Cancel really cancels: the card still offers Add afterwards.
    ctx.click(modal.get_by_role("button", name="Cancel", exact=True))
    expect(modal).to_have_count(0, timeout=10000)
    expect(
        drawer.get_by_role("button", name="Add to project", exact=True).first
    ).to_be_visible(timeout=10000)

    close = drawer.get_by_role("button", name="Close Data Catalog drawer")
    if close.count():
        ctx.click(close.first)
        page.locator(DATA_DRAWER_ROOT).wait_for(state="detached", timeout=10000)

    ctx.say("The Agent Catalog", "The same question, and it discloses more.")
    agent_drawer = open_agent_drawer(ctx)
    agent_add = agent_drawer.get_by_role(
        "button", name=re.compile(r"^Add to project")
    ).first
    agent_add.wait_for(state="visible", timeout=20000)
    ctx.click(agent_add)

    agent_modal = confirm_modal(ctx, re.compile(r"^Add "))
    ctx.focus(agent_modal, hold=1400)
    ctx.say("Dependencies are named before the click commits",
            "An agent that requires another says so here, not afterwards.")
    ctx.capture("agent-add-confirm")

    ctx.click(agent_modal.get_by_role("button", name="Cancel", exact=True))
    expect(agent_modal).to_have_count(0, timeout=10000)


@walkthrough(
    slug="catalog-remove-is-an-app-dialog",
    refs=[197],
    title="Removing uses the app's own dialog",
    premise="Remove an agent from the dataflow and read the confirmation.",
    note="Every confirmation in the catalogs was a native `window.confirm`: "
         "unstyled, unthemed, outside the app's modal stack, and carrying the "
         "browser's own chrome and origin line. They are ConfirmDialogs now, "
         "built on the same ModalShell as every other modal, so Escape and "
         "the backdrop cancel and the drawer behind stays put.",
    tests=["src/tests/components/ConfirmDialog.test.tsx",
           "src/tests/catalog/canvasDrawerParity.test.ts",
           "test_frontend/test_walkthrough_baselines.py"],
    fit_reactflow=False,
    max_diff_ratio=0.03,
)
def catalog_remove_is_an_app_dialog(ctx: Ctx) -> None:
    page = ctx.page

    drawer = open_agent_drawer(ctx)

    # Put one in the dataflow first, so there is something to remove.
    add = drawer.get_by_role("button", name=re.compile(r"^Add to project")).first
    add.wait_for(state="visible", timeout=20000)
    ctx.click(add)
    accept_confirm_dialog(page, title=re.compile(r"^Add "), button="Add to project")

    remove = drawer.get_by_role("button", name="Remove from project", exact=True).first
    remove.wait_for(state="visible", timeout=30000)

    ctx.say("Remove it again", "This is where the browser's own box used to appear.")
    ctx.click(remove)

    modal = confirm_modal(ctx, re.compile(r"^Remove "))
    ctx.focus(modal, hold=1500)
    ctx.say("The app's dialog, not the browser's",
            "Same shell, same theme, same Escape-to-cancel as every other modal.")
    ctx.capture("remove-confirm")

    ctx.click(modal.get_by_role("button", name="Remove", exact=True))
    expect(modal).to_have_count(0, timeout=10000)
    expect(
        drawer.get_by_role("button", name=re.compile(r"^Add to project")).first
    ).to_be_visible(timeout=30000)
    ctx.say("Removed", "And the drawer behind it never went anywhere.")


@walkthrough(
    slug="catalog-add-reports-success",
    refs=[198],
    title="A completed add says so",
    premise="Add an agent and watch the catalog confirm it landed.",
    note="Only the Data catalog reported an add. The Node and Agent catalogs "
         "finished in silence, which on a slow install reads as nothing "
         "having happened. All three now toast the same two sentences, and "
         "ask for the success variant explicitly - showToast defaults to "
         "error, so an omitted variant painted a successful add red.",
    tests=["src/tests/catalog/useAgentCatalogDrawer.test.ts",
           "src/tests/catalog/catalogDrawerParity.test.ts",
           "test_frontend/test_walkthrough_baselines.py"],
    clip_selector=TOAST_REGION,
    fit_reactflow=False,
    # The claim above is asserted in code; the PNG only documents it. The
    # Linux runner antialiases text differently from the machine that captured
    # the baseline (5.8% of pixels on CI, run to run stable), so the pin
    # must leave room for that without waving through a real change.
    max_diff_ratio=0.10,
)
def catalog_add_reports_success(ctx: Ctx) -> None:
    page = ctx.page

    drawer = open_agent_drawer(ctx)
    add = drawer.get_by_role("button", name=re.compile(r"^Add to project")).first
    add.wait_for(state="visible", timeout=20000)

    ctx.say("Add an agent", "The Agent catalog used to finish in silence.")
    ctx.click(add)
    accept_confirm_dialog(page, title=re.compile(r"^Add "), button="Add to project")

    toast = page.locator(TOAST_REGION).get_by_text(
        re.compile(r"^Added .+ to this project\.$")
    )
    toast.first.wait_for(state="visible", timeout=30000)
    ctx.focus(toast.first, hold=1500)
    ctx.say("It says so now",
            "The same sentence the Data catalog has always used.")
    ctx.capture("add-toast")


# ---------------------------------------------------------------------------
# Examples for registered accounts (#200)
# ---------------------------------------------------------------------------

#: A couple of the curated examples, by the ``dataflow.name`` the seeder uses as
#: the project title. Named rather than counted, so adding a twelfth example
#: does not break the scene and a gallery full of something else still fails.
EXAMPLE_TITLES = [
    "Vega-Lite chained transforms",
    "Vega-Lite spatial density",
]


@walkthrough(
    slug="examples-are-seeded-for-a-new-account",
    needs_examples=True,
    refs=[200],
    title="A new account arrives to a gallery of examples",
    premise="Create an account and read what is waiting on the projects page.",
    note="The examples were seeded to exactly one user - the shared guest - "
         "and project listing is a plain owner filter, so under `--auth` every "
         "account signed in to an empty gallery; `--deploy` carried the same "
         "defect. Each account now gets its own copies, seeded at sign-up and "
         "back-filled on first listing for anyone who registered earlier.",
    tests=["tests/test_projects/test_example_seed_for_registered_users.py",
           "tests/test_projects/test_routes.py",
           "test_frontend/test_examples_for_registered_users_e2e.py"],
    fit_reactflow=False,
)
def examples_are_seeded_for_a_new_account(ctx: Ctx) -> None:
    """Needs a stack started with ``--with-examples``.

    The runner has already stub-logged-in a walkthrough user on a canvas; this
    scene deliberately leaves that session and signs up a brand new account,
    because "what a new account sees" is the whole claim.
    """
    page = ctx.page

    ctx.say("Create an account", "The reporter's own path: sign up, then look.")
    # The runner has already stub-logged-in a walkthrough user, and the app
    # redirects an authenticated visitor away from /auth/signup - so the form
    # never appears and the scene would read the WRONG account's gallery. Drop
    # the session first; the token is the `session_token` cookie (utils/authApi).
    page.context.clear_cookies()
    page.evaluate("() => { try { localStorage.clear(); } catch (e) {} }")

    username = f"examples_{uuid.uuid4().hex[:10]}"
    signup_e2e_user(page, ctx.frontend, name="New User", username=username)
    wait_for_projects_page(page, timeout=30000)
    ctx.beat(900)

    # Wait for each title rather than counting once. Seeding eleven dataflows
    # and their datasets happens on the signup request, and the gallery fetches
    # them after the route renders, so a bare `count()` a beat later is a race
    # the scene loses on a cold store - it read zero while the seed was still
    # landing. The sibling e2e (`test_examples_for_registered_users_e2e`) has
    # always waited; this scene was the one asserting on a snapshot in time.
    missing = []
    for title in EXAMPLE_TITLES:
        try:
            page.get_by_text(title, exact=True).first.wait_for(
                state="visible", timeout=30000,
            )
        except PlaywrightTimeoutError:
            missing.append(title)
    if missing:
        # Distinguish the two ways this scene can fail: a stack booted without
        # the flag has nothing to show and is a harness problem, not the bug.
        raise AssertionError(
            f"the gallery is missing {missing}. If every example is absent, the "
            "stack was started without --with-examples (pass --with-examples to "
            "pytest); if only some are, the seed is at fault."
        )

    for title in EXAMPLE_TITLES:
        ctx.focus(page.get_by_text(title, exact=True).first, hold=900)

    ctx.say("Eleven example dataflows, owned by this account",
            "Not the guest's copies - this account's own, ready to open.")
    ctx.capture("examples-gallery")


# ---------------------------------------------------------------------------
# Robustness (#192, #201)
# ---------------------------------------------------------------------------

#: The lightest curated example that actually contains Autark nodes. The
#: default (a Vega-Lite dataflow) has none, so the scene would have nothing to
#: run and would fail for a reason unrelated to the fix.
AUTARK_EXAMPLE = "07-autark-gpu-shader.json"


def open_view_menu_dashboard(ctx: Ctx) -> None:
    """View -> Dashboard. ``force`` because the canvas chrome overlaps the bar."""
    page = ctx.page
    ctx.click(top_menu(page, "View"), force=True)
    ctx.click(page.get_by_text("Dashboard Mode", exact=True).first)


@walkthrough(
    slug="dashboard-mode-refuses-a-blank-screen",
    example=PROVENANCE_EXAMPLE,
    refs=[192],
    title="Dashboard Mode says what it needs",
    premise="Enter Dashboard Mode with nothing pinned, then with one node pinned.",
    note="Entering with nothing pinned hid every node and every edge, and "
         "`{!dashboardOn && <UpMenu>}` took the top bar with them - so the "
         "screen went blank with only the dashboard panel's close button left. "
         "The menu also ran the toggle twice per click, because MainCanvas "
         "passed the same handler to two props and UpMenu called both.",
    tests=["src/tests/providers/dashboardModeGuard.test.tsx"],
)
def dashboard_mode_refuses_a_blank_screen(ctx: Ctx) -> None:
    page = ctx.page

    ctx.say("Dashboard Mode, with nothing pinned",
            "This used to empty the screen with no way back but one ✕.")
    open_view_menu_dashboard(ctx)

    toast = page.locator(TOAST_REGION).get_by_text(
        "Pin at least one node to the dashboard first.", exact=True
    )
    toast.first.wait_for(state="visible", timeout=15000)
    ctx.focus(toast.first, hold=1600)

    # The canvas is untouched: still here, still showing its nodes.
    nodes = page.locator(".react-flow__node")
    assert nodes.count() > 0, "the canvas emptied despite the refusal"
    expect(page.locator("#tools-menu")).to_be_visible()
    ctx.capture("refused-with-nothing-pinned")

    # RUN a node that renders, and pin that one. `.react-flow__node.first` is
    # the Data Loading node, which has no visual output and, unrun, no output
    # at all - so Dashboard Mode laid out an empty tile and the capture was a
    # flat grey box that would still be a flat grey box if the mode broke.
    # `play_node` runs the not-yet-successful ancestors too, so playing the
    # chart at the tail runs the chain behind it.
    ctx.say("Run the chart", "Dashboard Mode needs something to lay out.")
    node_id = first_node_of_type(PROVENANCE_EXAMPLE, "vis-vega")
    node = node_locator(page, node_id)
    node.wait_for(state="visible", timeout=45000)
    node.scroll_into_view_if_needed()
    # Not `run_node_and_wait`: that returns the output text and so waits for
    # `[data-curio-node-output]`, the code node's text pane, which a chart node
    # does not have. Wait on the status attribute, then on drawn marks.
    play_node(page, node_id)
    wait_for_node_done(page, node_id, node_type="vis-vega", timeout_ms=180000)
    assert_vega_canvas_rendered(page, node_id, timeout=60000)

    ctx.say("Pin it", "Now the mode has something to show.")
    pin = node.get_by_role("button", name="Pin to dashboard")
    pin.wait_for(state="visible", timeout=15000)
    ctx.click(pin.first)
    ctx.beat(700)

    ctx.say("And it opens", "One pinned node, laid out on its own.")
    open_view_menu_dashboard(ctx)
    page.wait_for_timeout(1200)
    # The pinned node is the subject, so prove the chart came with it rather
    # than photographing whatever the panel put on screen. Scoped to the Vega
    # mount (`"vega" + nodeId`, the convention useVega.ts owns) - a bare
    # `canvas` locator finds Monaco's hidden decorationsOverviewRuler first.
    dash_canvas = page.locator(f"#vega{node_id} canvas").first
    dash_canvas.wait_for(state="visible", timeout=45000)
    assert dash_canvas.evaluate("c => c.width > 0 && c.height > 0"), (
        "Dashboard Mode laid out the pinned node but its chart drew nothing"
    )
    ctx.capture("entered-with-one-pin")


@walkthrough(
    slug="autark-without-webgpu-says-so",
    refs=[201],
    title="An Autark node on a browser without WebGPU",
    premise="Run an Autark node where WebGPU is unavailable, and read the node.",
    note="Nothing asked whether the browser had WebGPU. The library swallows "
         "its own init failure and carries on until the layer loader reaches "
         "`this._renderer.device.createShaderModule`, throwing a TypeError - "
         "and with no error boundary anywhere, that throw unmounted the whole "
         "React root and left a blank page. The node now checks first, says "
         "what is missing and what to do about it, and the canvas survives.",
    tests=["src/tests/adapters/node/autkGrammarWebgpuFallback.test.tsx",
           "src/tests/components/errorBoundary.test.tsx"],
    example=AUTARK_EXAMPLE,
    max_diff_ratio=0.05,
)
def autark_without_webgpu_says_so(ctx: Ctx) -> None:
    page = ctx.page

    # Take WebGPU away in the page itself. `add_init_script` would need to run
    # before navigation and the runner has already navigated, so the property is
    # redefined in place - the probe reads it at run time, not at load time.
    page.evaluate(
        "() => Object.defineProperty(navigator, 'gpu',"
        " { configurable: true, value: undefined })"
    )
    ctx.say("A browser with no WebGPU",
            "Firefox and Safari today; Chrome on a blocklisted driver.")

    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    # Resolved from the spec: a node's Curio type is not on the DOM element,
    # only React Flow's data-id, so display text would be a guess.
    # Must be a node whose spec declares a map/plot/compute - those are the
    # only ones that need a GPU, and so the only ones the guard fires for.
    node_id = first_node_of_type(AUTARK_EXAMPLE, "autk-grammar", containing='"map"')
    autark = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    autark.wait_for(state="visible", timeout=45000)
    autark.scroll_into_view_if_needed()
    ctx.focus(autark, hold=1000)

    ctx.say("Run it", "The old failure was a TypeError from inside the shader loader.")
    # The play control is a FontAwesome <svg>, not a named button, and React
    # Flow's transformed viewport can swallow a real click - `play_node` is the
    # helper that already deals with both.
    play_node(page, node_id)

    fallback = autark.locator('[role="alert"]')
    fallback.first.wait_for(state="visible", timeout=45000)
    ctx.focus(fallback.first, hold=1800)
    ctx.say("It says what is missing, and what to do",
            "Named cause, named remedy - and the canvas is still here.")
    ctx.capture("webgpu-fallback")

    # THE POINT: the app is alive. Before, the root had unmounted.
    assert page.locator(".react-flow__node").count() > 1, (
        "the canvas lost its nodes, so the throw was not contained"
    )
    expect(page.locator("#tools-menu")).to_be_visible()
    assert not errors, f"an uncaught page error escaped: {errors}"


# ---------------------------------------------------------------------------
# Layout and data shape (#193, #202, #203)
# ---------------------------------------------------------------------------

MULTI_VIEW_EXAMPLE = "05-vega-lite-multi-view-drilldown.json"

#: A Data Pool without Autark alongside it, so the scene needs no WebGPU.
DATA_POOL_EXAMPLE = "02-vega-lite-spatial-density.json"


@walkthrough(
    slug="catalog-tag-chips-are-plain",
    refs=[193],
    title="Tag chips read the same everywhere",
    premise="Compare the tag chips on a catalog card and in its detail drawer.",
    note="Four policies at once: the Data card tinted the LAST chip by file "
         "format - positional, not semantic, so a `2023` chip turned green "
         "because the file was GeoJSON; the Agent card tinted the last chip by "
         "category; the Package card tinted every chip; the detail drawer "
         "tinted none. All chips are plain now. Nothing is lost - the coloured "
         "card strip and the tinted avatar already carry format and category.",
    tests=["src/tests/catalog/tagChipsArePlain.test.ts",
           "src/tests/catalog/datasetFormatStyles.test.ts"],
    fit_reactflow=False,
    # The claim above is asserted in code; the PNG only documents it. The
    # Linux runner antialiases text differently from the machine that captured
    # the baseline (2.0% of pixels on CI, run to run stable), so the pin
    # must leave room for that without waving through a real change.
    max_diff_ratio=0.05,
)
def catalog_tag_chips_are_plain(ctx: Ctx) -> None:
    """The tints lived on the BROWSE PAGE cards, not the canvas drawer cards.

    `/catalog/data`, `/catalog/agents` and `/catalog/nodes` render
    `DataCatalogBrowseCard` / `AgentCatalogBrowseCard` / `PackageBrowseCard`,
    and those three were the ones with three different tinting policies. The
    canvas drawer uses `DatasetCard`, which never tinted - so a scene that
    opened the drawer was looking at the one surface the bug was not on.
    """
    page = ctx.page

    for kind, route, card_sel in (
        ("Data", "/catalog/data", "article[data-dataset-id]"),
        ("Agent", "/catalog/agents", "article[data-agent-coord]"),
        ("Node", "/catalog/nodes", "article[data-pkg-dir]"),
    ):
        ctx.say(f"The {kind} catalog",
                "Chips here used to take a colour from the format or category.")
        page.goto(f"{ctx.frontend}{route}")
        page.wait_for_load_state("domcontentloaded")

        card = page.locator(card_sel).first
        card.wait_for(state="visible", timeout=30000)
        card.scroll_into_view_if_needed()
        ctx.focus(card, hold=1200)

        # Every chip on one card resolves to the same background, so none of
        # them is carrying a colour the others are not.
        backgrounds = card.locator("[data-curio-tag-chip]").evaluate_all(
            "els => els.map(e => getComputedStyle(e).backgroundColor)"
        )
        assert backgrounds, f"the {kind} card rendered no tag chips"
        assert len(set(backgrounds)) == 1, (
            f"the chips on one {kind} card still differ in colour: "
            f"{sorted(set(backgrounds))}"
        )
        ctx.capture(f"plain-chips-{kind.lower()}")

    ctx.say("Every chip the same grey, on all three",
            "The coloured strip and the avatar are what carry the category.")


@walkthrough(
    slug="multi-view-vega-chart-is-reachable",
    refs=[202],
    title="A multi-view chart is not cut off",
    premise="Open a Vega-Lite chart with stacked sub-views and scroll to the bottom one.",
    note="Two independent defects, either alone enough to clip. The output "
         "container could not scroll - the pane is overflow:hidden and the "
         "mount div was height:100% with default overflow and no `nowheel`. "
         "And `width`/`height: \"container\"` was injected unconditionally, "
         "which vega-lite discards for vconcat/hconcat/facet/repeat, leaving "
         "`autosize: pad` - so ~750px of chart was authoritative inside a "
         "~292px pane and the ResizeObserver could not help.",
    tests=["src/tests/hook/vegaSpecSizing.test.ts",
           "src/tests/components/nodeEditorOutputScroll.test.tsx"],
    example=MULTI_VIEW_EXAMPLE,
    # The scene frames the chart node itself (see `frame_node` below); leaving
    # this True would have the capture helper fitView the whole 28-node
    # dataflow again immediately before each screenshot and undo it.
    fit_reactflow=False,
    max_diff_ratio=0.05,
)
def multi_view_vega_chart_is_reachable(ctx: Ctx) -> None:
    page = ctx.page

    ctx.say("A chart with stacked views",
            "Two sub-views, 650x400 and 650x300, in a ~292px pane.")

    # Resolved from the spec rather than `[id^=vega].first`: that picked
    # whichever mount happened to be first in DOM order, which is not
    # necessarily a node whose editor has mounted its output pane.
    # The example has nine vis-vega nodes and only some are the stacked ones;
    # the first is a single small view, which fits its pane and demonstrates
    # nothing. Pick the node whose spec is actually a vconcat.
    node_id = first_node_of_type(
        MULTI_VIEW_EXAMPLE, "vis-vega", containing="vconcat",
    )
    node = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    node.wait_for(state="visible", timeout=45000)
    node.scroll_into_view_if_needed()

    # RUN it. The mount div exists from first render, so the scene could scroll
    # an EMPTY container and still pass every assertion below - which is what it
    # did: the recording showed a scrollbar moving over blank space and no
    # chart. A clipped chart is the whole subject, so there has to be one.
    ctx.say("Run it", "The chart is drawn from the node's own output.")
    play_node(page, node_id)

    mount = page.locator(f'#vega{node_id}')
    mount.wait_for(state="attached", timeout=45000)

    # Vega renders to a <canvas> inside the mount; wait for it, and for it to
    # be taller than the pane, or there is nothing to demonstrate.
    page.wait_for_function(
        "(id) => { const el = document.getElementById(id);"
        " const c = el && el.querySelector('canvas');"
        " return !!c && c.getBoundingClientRect().height > 0; }",
        arg=f"vega{node_id}",
        timeout=180000,
    )
    # Frame the node before capturing. The subject is a chart inside a 525x350
    # node; at the harness's fit zoom this example's 28 nodes make it a ~90x60
    # thumbnail, and both captures came out as the same canvas wallpaper.
    frame_node(page, node_id, zoom=1.1)
    ctx.focus(node, hold=1400)

    metrics = mount.evaluate(
        "el => ({ id: el.id, scrollH: el.scrollHeight, clientH: el.clientHeight,"
        " overflow: getComputedStyle(el).overflow,"
        " inlineStyle: el.getAttribute('style'),"
        " cls: el.getAttribute('class'),"
        " nowheel: el.classList.contains('nowheel') })"
    )
    # Report the whole measurement on failure: if this ever disagrees with
    # `nodeEditorOutputScroll.test.tsx` - which pins the same div at the unit
    # layer - the difference is what tells you which of the two is wrong.
    assert metrics["overflow"] == "auto", (
        f"the chart container does not scroll: {metrics}"
    )
    # `nowheel` is what stops React Flow zooming the canvas instead.
    assert metrics["nowheel"], "the container scrolls but the wheel zooms the canvas"

    # The claim only means something if the chart is actually taller than its
    # pane - otherwise there is nothing being clipped and nothing to scroll to.
    assert metrics["scrollH"] > metrics["clientH"] + 8, (
        f"the chart fits inside its pane ({metrics['scrollH']}px of content in "
        f"{metrics['clientH']}px), so this scene cannot show #202 - the node "
        f"probably rendered a single small view instead of the stacked ones"
    )
    ctx.capture("chart-clipped-at-the-fold")

    ctx.say("Scroll down to the second view",
            "It was there all along; there was simply no way to reach it.")
    mount.evaluate("el => el.scrollTo({ top: el.scrollHeight })")
    page.wait_for_timeout(900)
    assert mount.evaluate("el => el.scrollTop") > 0, (
        "the container reports overflow but would not scroll"
    )
    ctx.capture("scrolled-to-bottom-view")


@walkthrough(
    slug="data-pool-scrolls-sideways",
    refs=[203],
    title="A wide table can be read to its last column",
    premise="Open a Data Pool on a wide frame and scroll it right.",
    note="There WAS an x-overflow owner - MUI TableContainer's default "
         "`overflowX: auto` - but on the wrong element: it takes no height, so "
         "its box was as tall as the rows (~3000px) and its scrollbar was "
         "painted at the bottom of that, reachable only after scrolling to the "
         "last row. It also absorbed the overflow, so the node's own scroller "
         "never got one. Nothing set a min-width on the table either, so the "
         "browser crushed the columns instead of overflowing.",
    tests=["src/tests/components/tables/TabularPreviewTable.test.tsx",
           "src/tests/adapters/node/components/DataPoolContent.test.tsx"],
    example=DATA_POOL_EXAMPLE,
    # The claim above is asserted in code; the PNG only documents it. The
    # Linux runner antialiases text differently from the machine that captured
    # the baseline (6.4% of pixels on CI, run to run stable), so the pin
    # must leave room for that without waving through a real change.
    max_diff_ratio=0.10,
)
def data_pool_scrolls_sideways(ctx: Ctx) -> None:
    page = ctx.page

    # The scroller only exists once the pool has rendered a table, so the node
    # has to have RUN. Locating by the scroller attribute alone therefore found
    # nothing and looked like "no Data Pool in this dataflow".
    node_id = first_node_of_type(DATA_POOL_EXAMPLE, "data-pool")
    pool = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    pool.wait_for(state="visible", timeout=45000)
    pool.scroll_into_view_if_needed()

    ctx.say("Run the pool", "It needs a table before there is anything to scroll.")
    play_node(page, node_id)

    scroller = pool.locator('[data-curio-datapool-scroll="true"]').first
    scroller.wait_for(state="visible", timeout=120000)
    ctx.focus(pool, hold=1200)
    metrics = scroller.evaluate(
        "el => ({ scrollW: el.scrollWidth, clientW: el.clientWidth,"
        " overflow: getComputedStyle(el).overflow })"
    )
    assert metrics["overflow"] == "auto", (
        f"the content area does not own both axes: overflow is {metrics['overflow']!r}"
    )

    ctx.say("Scroll right", "The last column used to be unreachable.")
    scroller.evaluate("el => el.scrollTo({ left: el.scrollWidth })")
    page.wait_for_timeout(900)

    moved = scroller.evaluate("el => el.scrollLeft")
    assert moved > 0 or metrics["scrollW"] <= metrics["clientW"], (
        "the table overflows but the content area would not scroll to it"
    )
    ctx.say("The right-hand columns, in place",
            "One scroller owns both axes now.")
    ctx.capture("scrolled-right")


# ---------------------------------------------------------------------------
# #218-#227: the visual claims of this batch
# ---------------------------------------------------------------------------
#
# Baselines are for defects whose symptom is what the SCREEN looks like. The
# behavioural halves of these issues are asserted in jest and in the plain e2e
# suites, which say what happened rather than what it looked like; what is left
# here is the part only a picture settles -- a control that should not be there,
# a field cropped mid-word, a body that renders nothing at all.
#
# Every one of these tightens ``max_diff_ratio`` well below the 0.20 default:
# at 0.20 a restyle could remove a button or re-crop a field and still pass,
# which for these particular claims is the whole thing.


def _canvas_node(ctx: Ctx, index: int = 0):
    """The nth node element on the canvas."""
    node = ctx.page.locator(".react-flow__node").nth(index)
    node.wait_for(state="visible", timeout=30000)
    return node


def _add_builtin_node(ctx: Ctx, tile_id: str, at):
    """Drag a built-in palette tile onto the canvas, returning its LOCATOR.

    The scene opens on an example dataflow (the baseline harness waits for a
    node before handing over), so the canvas already has nodes and ``.nth(0)``
    would be one of those. ``drag_to_canvas`` hands back the id of the node it
    created, which is the only way to address the one this scene is about.
    """
    from .utils import drag_to_canvas, node_locator

    # The built-in tiles live in the left rail and are present without opening
    # a palette -- the Packages dropdown lists third-party packages only.
    node_id = drag_to_canvas(ctx.page, ctx.page.locator(tile_id), at=at)
    return node_locator(ctx.page, node_id)


@walkthrough(
    slug="node-settings-reads-plainly",
    refs=[219],
    title="Node settings say what they mean",
    premise="Open a node's settings and read the capability boxes and the port editor.",
    note="The capability checkboxes rendered their own field names - hasCode, "
         "hasWidgets, hasGrammar - and because each input is wrapped in its "
         "label, the internal identifier was the accessible name too. The port "
         "types were a single free-text field whose placeholder was the only "
         "statement of both the vocabulary and the separator, so a typo passed "
         "the editor and was dropped on the way into the registry.",
    tests=["src/tests/components/nodeTemplateConfigModal.test.tsx",
           "src/tests/constants/supportedPortTypes.test.ts"],
    clip_selector='[data-curio-modal-shell="true"]',
    fit_reactflow=False,
    max_diff_ratio=0.03,
    example="01-vega-lite-chained-transforms.json",
)
def node_settings_reads_plainly(ctx: Ctx) -> None:
    from .utils import activate_header_icon

    page = ctx.page

    ctx.say("Node settings", "The capability boxes used to read hasCode.")
    node = _canvas_node(ctx)
    node.scroll_into_view_if_needed()
    cog = node.locator('button[aria-label^="Node settings for"]')
    cog.wait_for(state="visible", timeout=20000)
    # The gear activates on pointerdown/pointerup and swallows the native
    # click (useHeaderIconDragClick), so a plain click does nothing.
    activate_header_icon(cog)
    expect(page.get_by_role("heading", name="Node settings")).to_be_visible(timeout=15000)
    ctx.beat(600)

    # The claim, stated as an assertion as well as a picture: a baseline alone
    # would pass on a dialog that had merely moved the old labels around.
    for name in ("Code", "Widgets", "Grammar"):
        expect(page.get_by_label(name, exact=True)).to_be_visible()
    # Output rather than input: a kind may declare no input ports, but the
    # config always carries an output (a synthetic JSON one when the descriptor
    # has none), so this row is there for any node the scene might open on.
    expect(page.locator('[aria-label="Output ports port 1 type 1"]')).to_be_visible()

    ctx.capture("capability-labels")

    # The port editor is below the fold of the modal, so the shot above proves
    # only the labels half of the claim.
    ctx.say("And the ports", "A type is chosen from the list, one per row.")
    page.locator('[aria-label="Output ports port 1 type 1"]').scroll_into_view_if_needed()
    ctx.beat(400)
    ctx.capture("port-rows")


@walkthrough(
    slug="package-pill-only-on-package-nodes",
    refs=[218],
    title="The PACKAGE pill only where it leads somewhere",
    premise="Look at the header of a built-in node.",
    note="Every palette node comes from a package now, curio.builtin "
         "included, so source === 'package' was true for all of them and the "
         "pill rendered everywhere. Its whole effect is to reveal its package "
         "in the Packages palette, which lists third-party packages only - so "
         "on a built-in it was a control for an action that could not happen.",
    tests=["src/tests/components/packageMetaHeader.test.tsx"],
    # Exactly one element: the scene opens on an example with six nodes and
    # ``_capture_element`` is strict about its selector.
    clip_selector=".react-flow__node >> nth=0",
    max_diff_ratio=0.03,
    example="dataflows/DefaultWorkflow.json",
)
def package_pill_only_on_package_nodes(ctx: Ctx) -> None:
    node = _canvas_node(ctx)

    ctx.say("A built-in node", "It used to carry a PACKAGE pill that led nowhere.")
    node.scroll_into_view_if_needed()
    ctx.focus(node, hold=1000)

    # The category chip stays - it is informational. Only the button goes.
    expect(
        node.get_by_role("button", name=re.compile("Open package .* in Packages palette"))
    ).to_have_count(0)
    # And the controls that shared its gate survive, which is the trap: the
    # one-line version of this fix takes renaming and the cog with it.
    expect(node.locator('button[aria-label^="Node settings for"]')).to_be_visible()

    ctx.capture("builtin-header")
    ctx.say("No pill, and the cog still there",
            "Renaming and settings shared the pill's old gate.")


@walkthrough(
    slug="empty-nodes-say-why",
    refs=[224],
    title="An empty node says which kind of empty",
    premise="Drop a Simple View with nothing connected to it.",
    note="Data Pool and Simple View rendered a blank area, so an unconnected "
         "node, one whose upstream had not run, and a broken one all looked "
         "identical. Four states need four different things from the user, so "
         "they now say which one this is and what to do about it.",
    tests=["src/tests/utils/nodeEmptyState.test.ts",
           "src/tests/adapters/node/components/DataPoolContent.test.tsx"],
    # The node carrying the empty body: unambiguous (only one has the
    # attribute) and with enough around it to be legible, where clipping to the
    # message alone captured ~90px of unreadable text.
    clip_selector=".react-flow__node:has([data-curio-node-empty])",
    max_diff_ratio=0.03,
    # The baseline harness waits for ``.react-flow__node`` before handing over
    # (test_walkthrough_baselines), so a scene cannot open on an empty canvas
    # even when it brings its own node.
    example="dataflows/DefaultWorkflow.json",
)
def empty_nodes_say_why(ctx: Ctx) -> None:
    ctx.say("A Simple View with nothing wired in", "This used to be a blank box.")
    # vis-simple's tutorialId is ``step-image`` -- the tile predates the
    # node being renamed Simple View.
    node = _add_builtin_node(ctx, "#step-image", (260, 200))
    node.scroll_into_view_if_needed()
    ctx.focus(node, hold=1000)

    # The reason is derived, so the picture and the assertion agree on which of
    # the four states this is.
    expect(node.locator('[data-curio-node-empty="disconnected"]')).to_be_visible(timeout=20000)

    ctx.capture("simple-view-disconnected")
    ctx.say("It names the state and the next step",
            "Connect a node to this input.")


@walkthrough(
    slug="spatial-join-explains-itself",
    refs=[225],
    title="A node can explain itself",
    premise="Add a Spatial Join and open its info.",
    note="The help text already existed - the builtin manifest documents the "
         "two input handles, the join direction and the output columns - and "
         "DescriptionModal was already implemented and already mounted for "
         "every node. Nothing opened it, so every kind's documentation shipped "
         "unreachable.",
    tests=["src/tests/utils/nodeDescription.test.ts",
           "backend/tests/test_packages/test_builtin_descriptions.py"],
    clip_selector='[data-curio-modal-shell="true"]',
    fit_reactflow=False,
    max_diff_ratio=0.03,
    # The baseline harness waits for ``.react-flow__node`` before handing over
    # (test_walkthrough_baselines), so a scene cannot open on an empty canvas
    # even when it brings its own node.
    example="01-vega-lite-chained-transforms.json",
)
def spatial_join_explains_itself(ctx: Ctx) -> None:
    from .utils import activate_header_icon

    page = ctx.page

    ctx.say("Spatial Join", "What goes in each handle was not stated anywhere.")
    node = _add_builtin_node(ctx, "#step-spatial-join", (300, 220))
    node.scroll_into_view_if_needed()
    # A noContent node has no header band, so its info button lives on the
    # minimized chip and is revealed on hover.
    node.hover()
    ctx.beat(400)
    info = node.locator('button[title^="About"]')
    info.wait_for(state="visible", timeout=20000)
    activate_header_icon(info)

    expect(page.get_by_role("heading", name="Description")).to_be_visible(timeout=15000)
    ctx.beat(600)
    ctx.capture("spatial-join-description")
    ctx.say("Both handles, the direction, the output",
            "Straight from the package manifest.")


@walkthrough(
    slug="data-export-is-one-button",
    refs=[226],
    title="Data Export names the file it will give you",
    premise="Drop a Data Export node and read its control.",
    note="It asked for a format in a dropdown and then wrote every file as "
         "data_export whatever the input was, so three exports from one "
         "dataflow collided under one name. The payload already declares its "
         "shape and the input already has a name, so the node decides both and "
         "shows the result.",
    tests=["src/tests/utils/dataExportTarget.test.ts"],
    # The one node carrying a Download button, so the clip cannot land on one
    # of the example's six.
    clip_selector='.react-flow__node:has(button[aria-label^="Download"])',
    max_diff_ratio=0.03,
    # The baseline harness waits for ``.react-flow__node`` before handing over
    # (test_walkthrough_baselines), so a scene cannot open on an empty canvas
    # even when it brings its own node.
    example="dataflows/DefaultWorkflow.json",
)
def data_export_is_one_button(ctx: Ctx) -> None:
    ctx.say("Data Export", "An Export format dropdown, and a run, for one file.")
    node = _add_builtin_node(ctx, "#step-export", (260, 200))
    node.scroll_into_view_if_needed()
    ctx.focus(node, hold=1000)

    # The control lives in the widgets pane, and the kind declares
    # ``editor: "code"``, so the code tab is the one selected on arrival. The
    # tabs are icon-only, hence the event key rather than a name.
    ctx.click(node.locator('[data-rr-ui-event-key="widgets"]'), hold=400)

    # Unconnected: one button, disabled, saying why rather than offering a
    # format for data that is not there.
    expect(node.get_by_role("button", name=re.compile("^Download"))).to_be_visible(timeout=20000)
    expect(node.get_by_text("Connect a dataset to export it")).to_be_visible()

    # Park the pointer off the node: the tab click leaves a hover tooltip over
    # the footer, and a tooltip that may or may not have faded is 3% of a 3%
    # budget.
    ctx.page.mouse.move(5, 5)
    ctx.beat(400)
    ctx.capture("data-export-unconnected")
    ctx.say("One button", "It names the file once something is connected.")


@walkthrough(
    slug="dataflow-goal-is-readable",
    refs=[227],
    title="The dataflow goal is readable, and says what it is",
    premise="Read the field that appears when an agent is attached.",
    note="Reported as a cropped placeholder plus 'which agent answers a "
         "question typed here'. The second rests on a misreading: nothing is "
         "sent from this field. It is a persisted property of the dataflow, "
         "handed to every agent that reads it - and it looked like a chat box "
         "because it sat among the agent chips with no label except a "
         "placeholder too long to fit.",
    tests=["src/tests/attach/AgentDock.test.tsx"],
    clip_selector='[role="toolbar"][aria-label="Canvas agents"]',
    fit_reactflow=False,
    # The baseline harness waits for ``.react-flow__node`` before handing over
    # (test_walkthrough_baselines), so a scene cannot open on an empty canvas
    # even when it brings its own node.
    example="01-vega-lite-chained-transforms.json",
    # The tightest in the batch on purpose: this claim IS the pixels. At the
    # 0.20 default the text could clip again and the baseline would still pass.
    max_diff_ratio=0.02,
)
def dataflow_goal_is_readable(ctx: Ctx) -> None:
    page = ctx.page

    # The dock renders the goal field only once something is ATTACHED
    # (``showGoal={ctx.attachments.length > 0}``), and attaching is not the same
    # as adding an agent to the project: the catalog's "Add to project" writes
    # the agent lockfile, while an attachment binds one to the canvas. So this
    # is a precondition of the scene rather than part of its claim, and it goes
    # over HTTP -- the drag that would do it in the UI belongs to a different
    # journey.
    token = page.evaluate(
        "() => (document.cookie.match(/(?:^|; )session_token=([^;]*)/) || [])[1] || ''"
    )
    assert token, "no session cookie; the scene cannot attach an agent"
    project_id = page.url.rstrip("/").rsplit("/", 1)[-1]
    base = f"{ctx.backend}/api/agents/projects/{project_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    coord = "agent.dataflow-builder@1.0.0"

    installed = page.request.post(f"{base}/install", headers=headers, data={"coord": coord})
    assert installed.ok, f"install failed: {installed.status} {installed.text()[:200]}"
    attached = page.request.post(
        f"{base}/attachments",
        headers=headers,
        data={"coord": coord, "target": {"kind": "canvas"}},
    )
    assert attached.ok, f"attach failed: {attached.status} {attached.text()[:200]}"

    # The dock is rendered from the attachment list the page fetches, so reload
    # rather than wait for a push that may never come.
    page.reload()
    require_owner_view(page)
    ctx.beat(800)

    ctx.say("The dataflow goal", "Its placeholder used to be cut off mid-sentence.")
    goal = page.get_by_label("Dataflow goal")
    expect(goal).to_be_visible(timeout=30000)
    # A standing label, so the field keeps its name once a value is typed -
    # which is exactly when the placeholder used to stop carrying it.
    expect(page.get_by_text("Goal", exact=True)).to_be_visible()
    ctx.capture("goal-empty")

    # ``type_into`` is on the Narrator, not on Ctx (which passes through only
    # say / click / focus / beat).
    goal.fill("Find heat islands in Chicago")
    # Blur so the field scrolls back to the start: the caret sits at the end
    # after a fill, which hides the beginning of the very value this scene is
    # about.
    goal.blur()
    ctx.beat(500)
    ctx.capture("goal-filled")
    ctx.say("Named, and readable end to end",
            "Who sees it is on the tooltip, not in the width budget.")


@walkthrough(
    slug="project-drawer-offers-delete",
    refs=[221],
    title="A project can be deleted from its own drawer",
    premise="Select an unarchived project and read the actions offered.",
    note="The drawer offered Archive only, and revealed Delete forever after "
         "the project was archived - while the right-click menu offered "
         "deletion to anything. The same project was told two different things "
         "about what could be done to it. Both surfaces render one list now.",
    tests=["src/tests/pages/projectActions.test.ts",
           "src/tests/pages/projectsPageChrome.test.tsx"],
    fit_reactflow=False,
    max_diff_ratio=0.03,
    # The baseline harness waits for ``.react-flow__node`` before handing over
    # (test_walkthrough_baselines), so a scene cannot open on an empty canvas
    # even when it brings its own node.
    example="01-vega-lite-chained-transforms.json",
)
def project_drawer_offers_delete(ctx: Ctx) -> None:
    page = ctx.page

    ctx.say("The projects list", "Its drawer offered Archive and nothing else.")
    page.goto(f"{ctx.frontend}/projects")
    wait_for_projects_page(page)

    card = page.locator("[data-project-id]").first
    card.wait_for(state="visible", timeout=30000)
    ctx.click(card)

    expect(page.get_by_role("button", name="Archive", exact=True)).to_be_visible(timeout=15000)
    expect(page.get_by_role("button", name="Delete forever", exact=True)).to_be_visible()
    ctx.capture("drawer-actions")

    ctx.say("Both, on an unarchived project",
            "The confirm is what makes deleting deliberate.")


# ---------------------------------------------------------------------------
# Dataflow identity
# ---------------------------------------------------------------------------

@walkthrough(
    slug="renaming-a-dataflow-renames-it-everywhere",
    example=PROVENANCE_EXAMPLE,
    refs=[230],
    title="A renamed dataflow is renamed on the projects page too",
    premise="Rename a dataflow on the canvas, save it, then go and look at the list.",
    note="The name is stored twice - the project row the Projects list renders, "
         "and `spec.dataflow.name` the canvas title renders. Committing the "
         "title wrote only the second, and the save sent `projectName`, which "
         "only loading ever set - so the save re-sent the name the dataflow was "
         "opened under. The reverse direction was broken too: a name-only PUT, "
         "which is what the list's own rename sends, never reached the spec.",
    tests=["src/tests/hook/useWorkflowOperations.rename.test.ts",
           "src/tests/components/upMenuRename.test.ts",
           "tests/test_projects/test_routes.py",
           "test_frontend/test_project_save_load.py"],
    fit_reactflow=False,
    max_diff_ratio=0.03,
)
def renaming_a_dataflow_renames_it_everywhere(ctx: Ctx) -> None:
    """Three captures because the bug spans two pages and two directions.

    A canvas-only shot cannot show the symptom at all - the canvas was the one
    surface that always looked right.
    """
    page = ctx.page

    ctx.say("Rename it on the canvas", "Click the title, type, press Enter.")
    title = page.locator("h1").first
    title.wait_for(state="visible", timeout=30000)
    ctx.click(title)

    box = page.locator("input[type='text']").last
    box.wait_for(state="visible", timeout=10000)
    box.fill("Renamed Dataflow")
    box.press("Enter")

    disk = page.locator("[data-curio-save-state]")
    state = disk.get_attribute("data-curio-save-state")
    assert state == "unsaved", (
        f"the rename left the indicator reading {state!r}; a rename diverges "
        f"from disk and has to say so, or the user is told their edit is saved"
    )
    ctx.focus(disk, hold=900)
    ctx.say("Unsaved, as it should be", "The rename is an edit like any other.")
    ctx.capture("renamed-on-canvas")

    ctx.say("Save it", "")
    ctx.click(disk)
    page.wait_for_function(
        "() => document.querySelector('[data-curio-save-state]')"
        "?.getAttribute('data-curio-save-state') === 'saved'",
        timeout=30000,
    )

    ctx.say("Now the projects page", "This is where the old name used to survive.")
    page.goto(f"{ctx.frontend}/projects")
    page.get_by_text("Renamed Dataflow").first.wait_for(state="visible", timeout=30000)
    ctx.focus(page.get_by_text("Renamed Dataflow").first, hold=1200)
    ctx.capture("renamed-in-the-list")

    ctx.say("And back the other way",
            "Renaming from the list has to reach the canvas title too.")
    # Straight through the API: the subject is what the canvas reads back, not
    # the context menu that gets there. The token is the `session_token` cookie
    # the app itself authenticates with (utils/authApi), read off the live
    # context rather than threaded through Ctx, which the video runner shares.
    token = next(
        c["value"] for c in page.context.cookies() if c["name"] == "session_token"
    )
    listed = api_json(f"{ctx.backend}/api/projects", token)
    target = next(p for p in listed if p["name"] == "Renamed Dataflow")
    api_json(
        f"{ctx.backend}/api/projects/{target['id']}",
        token,
        method="PUT",
        payload={"name": "Renamed From The List"},
    )

    page.goto(f"{ctx.frontend}/dataflow/{target['id']}")
    heading = page.locator("h1").filter(has_text="Renamed From The List")
    heading.wait_for(state="visible", timeout=30000)
    ctx.focus(heading, hold=1200)
    ctx.say("The canvas title followed", "Both stores hold one name now.")
    ctx.capture("canvas-follows-a-list-rename")


@walkthrough(
    slug="a-loaded-dataflow-is-not-dirty",
    example=PROVENANCE_EXAMPLE,
    refs=[229],
    title="Opening a saved dataflow leaves nothing to save",
    premise="Open a dataflow you already saved and read the save indicator.",
    note="`loadParsedTrill` replays every persisted edge through the same "
         "`onConnect` a user drag goes through, and onConnect marks the project "
         "dirty - rightly, for a real connection. So any dataflow with even one "
         "edge came back from disk reading 'Unsaved changes', and the 30s "
         "auto-save then rewrote it for nothing, which is what made the disk "
         "turn green a while after opening.",
    tests=["src/tests/hook/useWorkflowOperations.dirtyOnLoad.test.ts",
           "src/tests/components/loadPathsMarkDirty.test.ts",
           "test_frontend/test_project_dirty_guard.py"],
    clip_selector="[data-curio-save-state]",
    max_diff_ratio=0.02,
)
def a_loaded_dataflow_is_not_dirty(ctx: Ctx) -> None:
    """Two captures, clipped to the disk: the subject is one glyph's colour.

    At the suite's default 0.20 an amber disk and a green one are the same
    picture, so a single wide shot could document the fix without ever being
    able to police it. The pair is what makes the two states legible in review.

    The runner has already entered `/dataflow/<id>` through the real
    ProjectLoader path, so this scene only has to read the result.
    """
    page = ctx.page

    # The edge is what the replay processes; before it renders, the bug has not
    # had its chance to happen.
    page.locator(".react-flow__edge").first.wait_for(state="visible", timeout=45000)

    disk = page.locator("[data-curio-save-state]")
    state = disk.get_attribute("data-curio-save-state")
    assert state == "saved", (
        f"a freshly loaded dataflow reads {state!r} with no edits made - #229"
    )

    ctx.say("Just opened, nothing edited", "The disk is green: what you see is on disk.")
    ctx.focus(disk, hold=1200)
    ctx.capture("loaded")

    ctx.say("Now add a node", "A real edit still has to register.")
    # `drag_to_canvas`, the suite's proven drop path, rather than a raw mouse drag
    # of an existing node: the drag is what would be flaky here, and adding a node
    # is just as much a real edit for the purpose of the claim.
    before = len(canvas_nodes(page))
    drag_to_canvas(page, page.locator("#step-analysis"), at=(150, 150))
    assert len(canvas_nodes(page)) == before + 1, "the drop created no node"

    page.wait_for_function(
        "() => document.querySelector('[data-curio-save-state]')"
        "?.getAttribute('data-curio-save-state') === 'unsaved'",
        timeout=15000,
    )
    ctx.focus(disk, hold=1200)
    ctx.say("Amber, as it should be",
            "The guard covers the load's own replay, not the user's edits.")
    ctx.capture("after-an-edit")


# ---------------------------------------------------------------------------
# Catalog chrome (#236)
# ---------------------------------------------------------------------------

@walkthrough(
    slug="catalog-details-clear-the-version-badge",
    refs=[236],
    title="The details panel leaves the version badge alone",
    premise="Open a catalog item's details panel and read the bottom-right corner.",
    note="The badge is `position: fixed` at bottom-right with a bare z-index of "
         "9999, and nothing between it and the page makes a stacking context - "
         "so it painted ON TOP of the details drawer, grey monospace over the "
         "drawer's dark primary button. The height chain to the drawer is "
         "unbroken to the viewport (.pageShell is 100vh, .browseDrawer is "
         "height:100%), so nothing reserved the corner. The shell now does, "
         "once, for every catalog and both drawers, and the badge sits on the "
         "documented z-scale instead of above everything.",
    tests=["src/tests/styles/zLayerScale.test.ts",
           "test_frontend/test_walkthrough_baselines.py"],
    # The scene leaves for /catalog immediately and has nothing to do with this
    # dataflow. It is named only because the runner waits for a canvas node
    # before handing over, and an empty dataflow never produces one.
    example=PROVENANCE_EXAMPLE,
    fit_reactflow=False,
    # A restored 30px gutter is a small number of pixels; the 0.20 default
    # would not notice it going away again.
    max_diff_ratio=0.05,
)
def catalog_details_clear_the_version_badge(ctx: Ctx) -> None:
    page = ctx.page

    ctx.say("Open the Node Catalog", "Any catalog will do - they share one shell.")
    page.goto(f"{ctx.frontend}/catalog/nodes")
    page.wait_for_load_state("networkidle")

    # The first card, whatever it is: the claim is about the drawer's geometry,
    # not about any particular package. `article[data-pkg-dir]` is the card's
    # own hook (PackageBrowseCard), not a hashed CSS-module class.
    card = page.locator("article[data-pkg-dir]").first
    card.wait_for(state="visible", timeout=30000)
    ctx.click(card)

    drawer = page.locator('[data-curio-browse-drawer="true"]').first
    drawer.wait_for(state="visible", timeout=30000)

    ctx.say("Scroll to the bottom of the details",
            "This is where the two used to collide.")
    drawer.evaluate("el => el.scrollTo({ top: el.scrollHeight })")
    page.wait_for_timeout(600)

    badge = page.locator("span[title]").filter(has_text=re.compile("isolated", re.I))
    if badge.count() == 0:
        raise AssertionError(
            "no version badge on /catalog - the scene cannot show #236. The "
            "badge only renders once GET /version answers, so this usually "
            "means the backend is unreachable rather than that the badge moved."
        )

    badge_box = badge.first.bounding_box()
    drawer_box = drawer.bounding_box()
    assert badge_box and drawer_box, "could not measure the badge or the drawer"

    # The whole fix is that the drawer stops short of the badge. Overlap is
    # measured rather than eyeballed, so a failure says which way it went.
    overlap = (
        badge_box["x"] < drawer_box["x"] + drawer_box["width"]
        and badge_box["x"] + badge_box["width"] > drawer_box["x"]
        and badge_box["y"] < drawer_box["y"] + drawer_box["height"]
        and badge_box["y"] + badge_box["height"] > drawer_box["y"]
    )
    assert not overlap, (
        f"the details drawer still runs under the version badge: "
        f"badge={badge_box}, drawer={drawer_box}"
    )

    ctx.focus(badge.first, hold=1200)
    ctx.say("The corner is its own", "The drawer ends above it, not behind it.")
    ctx.capture("details-panel-and-version-badge")


# ---------------------------------------------------------------------------
# The Column Filter reads a real DataFrame (#194)
# ---------------------------------------------------------------------------

#: The package the Column Filter ships in, and the node body that feeds it.
EXAMPLE_UI_PKG = "curio.example-ui@1"
COLUMN_FILTER_CODE = (
    "import pandas as pd\n"
    "df = pd.DataFrame({'population': [2746, 8804, 1200],"
    " 'name': ['Chicago', 'NYC', 'Peoria']})\n"
    "return df\n"
)


@walkthrough(
    slug="column-filter-reads-a-dataframe",
    refs=[194],
    title="A packaged node reads the frame wired into it",
    premise="Wire Data Loading into the Column Filter and watch it react.",
    note="`asFrame` required the row-map encoding pandas' bare `to_dict()` "
         "produces and explicitly rejected arrays - but Curio serialises with "
         "`to_dict(orient='list')`, so every real DataFrame arrived as arrays, "
         "`asFrame` returned null, and the node sat there asking to be "
         "connected to the thing it was already connected to. Nothing threw and "
         "nothing logged, which is why it read as 'the node does nothing'.",
    tests=["src/tests/adapters/node/exampleUiColumnFilter.test.tsx",
           "sandbox/tests/test_dataframe_wire_shape.py",
           "test_frontend/test_package_refresh_e2e.py"],
    fit_reactflow=False,
    max_diff_ratio=0.05,
)
def column_filter_reads_a_dataframe(ctx: Ctx) -> None:
    page = ctx.page

    ctx.say("Add the example package", "The Column Filter ships inside it.")
    page.get_by_text("NODE CATALOG").click()
    page.get_by_role("button", name=re.compile("Browse Node Catalog")).click()
    drawer = page.locator('[data-curio-node-catalog-drawer="true"]')
    drawer.wait_for(state="attached", timeout=15000)
    expect(drawer).to_have_attribute("aria-hidden", "false", timeout=10000)

    card = page.locator(f'article[data-pkg-dir="{EXAMPLE_UI_PKG}"]')
    if card.count() == 0:
        card = page.locator("article").filter(has_text="Example: Custom UI Node").first
    ctx.click(card.first.get_by_role("button", name=re.compile(r"^Add to project")))
    # NOT `accept_confirm_dialog`. The Node catalog is the one that asks through
    # `InstallPermissionsDialog` rather than the shared `ConfirmDialog` — it has
    # permissions and conflicts to show, which is exactly the asymmetry #196
    # documented — so there is no dialog named "Add …" to wait for here.
    page.get_by_role("dialog").last.get_by_role(
        "button", name=re.compile(r"^(Add|Install)")
    ).last.click()
    expect(
        page.locator(f'article[data-pkg-dir="{EXAMPLE_UI_PKG}"]').first.get_by_role(
            "button", name="Remove from project"
        )
    ).to_be_visible(timeout=120000)
    page.keyboard.press("Escape")

    ctx.say("A node that outputs a frame", "Three rows, one numeric column.")
    loading = drag_to_canvas(page, page.locator("#step-loading"), at=(220, 200))
    set_node_code(page, loading, COLUMN_FILTER_CODE)

    ctx.say("And the Column Filter beside it")
    open_tools_palette(page, "packages")
    row = page.locator(f'#packages-palette [data-pkg-palette-coords~="{EXAMPLE_UI_PKG}"]')
    expect(row).to_have_count(1, timeout=30000)
    filter_node = drag_to_canvas(page, row, at=(760, 220))
    close_tools_palette(page, "packages")

    node = node_locator(page, filter_node)
    ctx.focus(node, hold=1000)
    # Before the frame arrives the node is honest about what it is waiting for;
    # capturing it here is what makes the next frame mean something.
    ctx.capture("waiting-for-a-frame")

    ctx.say("Wire them together, and run the loader",
            "This is the moment the node used to ignore.")
    connect_nodes(page, loading, filter_node)
    run_node_and_wait(page, loading, node_type="curio.builtin/data-loading")

    # THE POINT: the node read the frame. It names the numeric column it found
    # and counts the rows that match, neither of which it could do from the
    # payload it used to reject.
    body = node_locator(page, filter_node)
    expect(body).to_contain_text("population", timeout=60000)
    expect(body).to_contain_text(re.compile(r"\d+ of \d+ rows match"), timeout=60000)
    text = " ".join((body.text_content() or "").split())
    assert "Connect a DataFrame upstream" not in text, (
        "the Column Filter still says it has no frame after one was wired in "
        f"and run, so `asFrame` is rejecting the payload again: {text[:200]}"
    )
    ctx.focus(body, hold=1400)
    ctx.capture("reading-the-frame")
    ctx.say("It found the column and counted the rows",
            "The same payload it used to reject.")
