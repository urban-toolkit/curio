"""Steps the scenes share: opening an example, finding a node in it, menus,
the Provenance window, and counting what the canvas holds.
"""
from __future__ import annotations

import json
import os

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ..utils import REPO_ROOT, frame_node
from .framework import Ctx


EXAMPLES_DIR = os.path.join(REPO_ROOT, "docs", "examples")


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

    The trigger is named ``<label> menu``, which is also what keeps it apart
    from the same-named row inside the dropdown it opens.
    """
    return page.get_by_role("button", name=f"{label} menu", exact=True)


_ON_TOP_JS = """(el) => {
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return !!hit && (hit === el || el.contains(hit));
}"""


def frame_until_on_top(page, node_id: str, target, *, attempts: int = 6) -> None:
    """Frame *node_id* until *target*, a control in it, is what a click would hit.

    Example 01's top chart sits under the menu bar at fit zoom (#493). One
    framing is not enough after a load: the canvas fits itself again once its
    nodes are measured, which can land after the framing and undo it.
    """
    target.wait_for(state="visible", timeout=15000)
    for _ in range(attempts):
        frame_node(page, node_id)
        if target.evaluate(_ON_TOP_JS):
            return
    raise AssertionError(
        f"{target} stayed covered after {attempts} framings of node {node_id}"
    )


def open_provenance(ctx: Ctx):
    """Open the Provenance modal from the top menu and return its dialog.

    Two clicks: the top-bar dropdown, then its single row. ``force`` on the
    first mirrors the tour - the canvas chrome overlaps the bar's hit box.
    """
    page = ctx.page
    # A button on the bar, not a menu: the node editor also has a tab named
    # "Provenance", so it is found by its test id.
    ctx.click(page.get_by_test_id("provenance-btn"))
    dialog = page.get_by_role("dialog").filter(has_text="Provenance for")
    dialog.wait_for(state="visible", timeout=20000)
    # The graph lays out through dagre on mount and draws its edges once the
    # cards are measured; capture after both or the baseline records a graph
    # half drawn.
    await_provenance_graph(page)
    ctx.beat(900)
    return dialog


#: The Provenance window. It opens over the dataflow canvas, whose own React
#: Flow nodes and edges a bare selector would count too.
PROVENANCE_MODAL = '[data-curio-modal-shell="true"]'
PROVENANCE_CARD = f"{PROVENANCE_MODAL} .react-flow__node"
PROVENANCE_EDGE_PATH = f"{PROVENANCE_MODAL} .react-flow__edges path.react-flow__edge-path"

_PROVENANCE_COUNTS_JS = """([card, edge]) => ({
    cards: document.querySelectorAll(card).length,
    edges: document.querySelectorAll(edge).length,
})"""

_PROVENANCE_DRAWN_JS = """([card, edge]) => {
    const cards = document.querySelectorAll(card).length;
    return cards > 0 && document.querySelectorAll(edge).length === cards - 1;
}"""


def provenance_graph_counts(page) -> dict:
    """``{cards, edges}`` the Provenance window's version graph shows now."""
    return page.evaluate(_PROVENANCE_COUNTS_JS, [PROVENANCE_CARD, PROVENANCE_EDGE_PATH])


def await_provenance_graph(page, *, timeout: float = 20000) -> dict:
    """Wait until the Provenance window has drawn its whole version graph.

    React Flow draws an edge only once both of its cards are measured, and
    every version but the first has one parent edge, so the graph is drawn when
    it shows one edge per card after the first. Returns ``{cards, edges}``.
    """
    try:
        page.wait_for_function(
            _PROVENANCE_DRAWN_JS, arg=[PROVENANCE_CARD, PROVENANCE_EDGE_PATH],
            timeout=timeout,
        )
    except PlaywrightTimeoutError:
        counts = provenance_graph_counts(page)
        raise AssertionError(
            f"the Provenance window did not draw its version graph within "
            f"{timeout / 1000:.0f} s: {counts['cards']} versions and "
            f"{counts['edges']} edges, where a drawn graph has one edge per "
            f"version after the first"
        ) from None
    return provenance_graph_counts(page)


def show_every_version(ctx: Ctx, dialog) -> None:
    """Frame the whole version chain, the way a user reaches an old version.

    The window opens on the selected version at a readable zoom (#507), so the
    rest of the chain is off screen until it is panned to or fitted.
    """
    ctx.click(dialog.get_by_role("button", name="fit view"))
    ctx.beat(600)


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
