"""Steps the scenes share: opening an example, finding a node in it, menus,
the provenance drawer, and counting what the canvas holds.
"""
from __future__ import annotations

import json
import os
import re

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ..utils import REPO_ROOT, frame_node, wait_for_drawer_closed
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


#: The provenance drawer, over the dataflow canvas on the right.
PROVENANCE_DRAWER = '[data-curio-provenance-drawer="true"]'
#: Its panel, which a capture of the drawer clips to.
PROVENANCE_PANEL = f'{PROVENANCE_DRAWER} [role="dialog"]'
#: A version in the drawer: a row of the List, a box of the Graph.
PROVENANCE_ITEM = f"{PROVENANCE_DRAWER} [data-provenance-item]"
#: A line of the Graph, from a version to the next one or to a branch.
PROVENANCE_LINK = f"{PROVENANCE_DRAWER} [data-provenance-link]"


def open_provenance(ctx: Ctx, *, view: str = "list"):
    """Open the provenance drawer from the View menu and return its panel.

    Returns once the drawer rests against the right edge, on *view* ("list" or
    "graph"; the drawer opens on the one picked last), with its history drawn.
    """
    page = ctx.page
    ctx.click(page.get_by_role("button", name="View menu", exact=True))
    # Found by its test id: a node's header also has a Provenance button.
    ctx.click(page.get_by_test_id("provenance-menu-item"))
    panel = page.locator(PROVENANCE_PANEL)
    panel.wait_for(state="visible", timeout=20000)
    await_drawer_at_rest(page)
    switch = panel.get_by_role("button", name="Graph" if view == "graph" else "List", exact=True)
    if switch.get_attribute("aria-pressed") != "true":
        ctx.click(switch)
    await_provenance_history(page)
    ctx.beat(900)
    return panel


_DRAWER_AT_REST_JS = """(sel) => {
    const root = document.querySelector(sel);
    const panel = root && root.querySelector('[role="dialog"]');
    if (!panel || root.getAttribute('aria-hidden') !== 'false') return false;
    const box = panel.getBoundingClientRect();
    return box.width > 0 && Math.abs(box.right - window.innerWidth) < 1;
}"""


def await_drawer_at_rest(page, *, timeout: float = 20000) -> None:
    """Wait until the provenance drawer has slid all the way in from the right,
    so a capture never records it part way."""
    page.wait_for_function(_DRAWER_AT_REST_JS, arg=PROVENANCE_DRAWER, timeout=timeout)


_PROVENANCE_COUNTS_JS = """([item, link]) => {
    const links = Array.from(document.querySelectorAll(link));
    return {
        items: document.querySelectorAll(item).length,
        links: links.length,
        drawn: links.filter((g) => {
            const path = g.querySelector('path');
            return path && path.getTotalLength() > 0;
        }).length,
    };
}"""

_PROVENANCE_DRAWN_JS = """([item, link]) => {
    const items = document.querySelectorAll(item).length;
    if (items === 0) return false;
    const view = document.querySelector('[data-provenance-view]');
    if (!view || view.getAttribute('data-provenance-view') !== 'graph') return true;
    const links = Array.from(document.querySelectorAll(link));
    return links.length === items - 1 && links.every((g) => {
        const path = g.querySelector('path');
        return path && path.getTotalLength() > 0;
    });
}"""


def provenance_counts(page) -> dict:
    """``{items, links, drawn}`` the provenance drawer shows now: its versions,
    the Graph's lines, and how many of those have a length."""
    return page.evaluate(_PROVENANCE_COUNTS_JS, [PROVENANCE_ITEM, PROVENANCE_LINK])


def await_provenance_history(page, *, timeout: float = 20000) -> dict:
    """Wait until the provenance drawer shows its history.

    The List is drawn with the drawer. The Graph draws its lines once its boxes
    have landed, and every version but the first is made from one other, so a
    one-chain Graph is drawn when it shows a line with a length into every
    version after the first. Returns ``{items, links, drawn}``.
    """
    try:
        page.wait_for_function(_PROVENANCE_DRAWN_JS, arg=[PROVENANCE_ITEM, PROVENANCE_LINK], timeout=timeout)
    except PlaywrightTimeoutError:
        counts = provenance_counts(page)
        raise AssertionError(
            f"the provenance drawer did not show its history within "
            f"{timeout / 1000:.0f} s: {counts['items']} versions and "
            f"{counts['links']} lines, {counts['drawn']} of them drawn, where "
            f"the Graph draws a line into every version after the first"
        ) from None
    return provenance_counts(page)


_OPENED = re.compile(r"^(Put this version on the canvas|On the canvas now)$")


def open_version(page, version, *, click=None) -> None:
    """Open *version* in the drawer, as a click on it does, and wait for its
    details. *click* is the scene's own click (``ctx.click``), if any."""
    head = version.locator("button").first
    if head.get_attribute("aria-expanded") != "true":
        (click or (lambda target: target.click()))(head)
    version.get_by_text(_OPENED).wait_for(state="visible", timeout=10000)


def put_version_on_canvas(ctx: Ctx, version) -> None:
    """Press an opened version's own button, the only thing that restores it."""
    ctx.click(version.get_by_role("button", name="Put this version on the canvas", exact=True), hold=520)


def close_provenance(ctx: Ctx) -> None:
    """Close the provenance drawer with its close button and wait until it is gone."""
    page = ctx.page
    ctx.click(page.get_by_role("button", name="Close Dataflow provenance", exact=True))
    wait_for_drawer_closed(page, PROVENANCE_DRAWER)


# A dialog over the canvas (a ModalShell) can render a React Flow of its own
# in a portal on document.body, so a bare `.react-flow__node` count would mix
# it in with the dataflow behind it. Everything below counts only what is
# OUTSIDE one - i.e. the canvas. The provenance drawer draws no React Flow.
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
