"""Playwright E2E: the notebook view shows a dataflow as a column of cells.

The canvas bar's Canvas | Notebook switch shows the same nodes one under the
other, in dataflow order, like a Jupyter notebook: each cell across the page
and as tall as its code and its output, Play at its top left, its other tools
showing under the pointer. The connections run in a bar to the right of the
cells, between dots on each cell's right edge. The graph is changed on the
canvas only: the notebook view has no rail, accepts no drop, its dots do not
connect, and it deletes neither a cell nor a connection; a cell's code is
edited and run there. Nothing about the view is saved: the dataflow keeps its
canvas layout, and the view lives in the address (``?view=notebook``).

What each test pins:

* the switch lays the cells out in one column, in dataflow order, every cell
  spanning the page to the bar and as tall as its content, GAP apart and none
  overlapping, an editor as tall as its lines, one arc per connection in the
  bar, no rail and no (+), a Run all button, no resize handle on any cell, no
  dot that connects, no Delete node tool in any cell, and the tools hidden
  until the pointer is over the cell;
* a run shows a Python cell's code and output, and a Vega-Lite cell's spec and
  chart, together; the output grows its cell, the cells below move down by as
  much, and each arc still runs between its two dots;
* the wheel scrolls the page over a cell's editor and over its output;
* in the notebook view a drag between dots connects nothing, an arc takes no
  click, and select plus Delete removes neither the arc nor a cell, while
  Delete inside a cell's editor still edits its code; on the canvas the same
  presses remove the connection and the node, and the two connect again;
* the notebook view adds no node: a drop on its page adds nothing and
  Duplicate selection is off, while the canvas's rail adds one;
* back on the canvas every node is where it was and the size it was, a save
  writes the canvas layout, and a reload keeps the view the address names.

The dataflow is built here rather than borrowed from ``docs/examples``: four
Python and Vega-Lite nodes, no datasets, so a failure is about this feature.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_notebook_view_e2e.py -v
"""
from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .utils import (
    api_json,
    assert_vega_canvas_rendered,
    connect_nodes,
    dismiss_toasts,
    drag_to_canvas,
    frame_nodes,
    node_locator,
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

BAR = "header[data-curio-menu-bar]"
SCROLLER = ".curio-flow-scroller"
SCREENSHOT_STEM = "notebook-view"

PRODUCER = "nbv-producer"
EXTRA = "nbv-extra"
TRANSFORM = "nbv-transform"
CHART = "nbv-chart"

#: Where each node sits on the canvas. EXTRA reads from nothing and feeds
#: nothing, so it comes after PRODUCER's chain.
CANVAS = {
    PRODUCER: (0, 0),
    TRANSFORM: (700, 0),
    CHART: (1400, 0),
    EXTRA: (700, 600),
}
#: Dataflow order: each node nothing feeds, in the spec's order, followed by
#: the chain it feeds.
ORDER = [PRODUCER, TRANSFORM, CHART, EXTRA]

#: Space between two cells, in pixels, which holds the (+) that adds a cell.
GAP = 24
#: The page's left margin and the bar on its right: the cells span between them.
MARGIN = 24
BAR_WIDTH = 176

#: Six lines, against EXTRA's one: PRODUCER's cell is the taller.
PRODUCER_CODE = (
    "import pandas as pd\n"
    "\n"
    "categories = ['a', 'b', 'c']\n"
    "counts = [3, 7, 5]\n"
    "\n"
    "return pd.DataFrame({'category': categories, 'count': counts})\n"
)
#: Prints the frame, several lines, so a run grows the cell.
TRANSFORM_CODE = "print(len(arg))\nprint(arg)\nreturn arg\n"
EXTRA_CODE = "return 1\n"
CHART_SPEC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": "bar",
    "encoding": {
        "x": {"field": "category", "type": "nominal"},
        "y": {"field": "count", "type": "quantitative"},
    },
}, indent=2)


def _node(node_id: str, node_type: str, content: str) -> dict:
    x, y = CANVAS[node_id]
    return {
        "id": node_id,
        "type": node_type,
        "x": x,
        "y": y,
        "in": "DEFAULT",
        "out": "DEFAULT",
        "goal": "",
        "metadata": {"keywords": []},
        "content": content,
    }


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "Notebook view e2e",
            "task": "",
            "description": "",
            "packages": [],
            "datasets": [],
            "nodes": [
                _node(PRODUCER, "curio.builtin/data-loading", PRODUCER_CODE),
                _node(TRANSFORM, "curio.builtin/computation-analysis", TRANSFORM_CODE),
                _node(CHART, "curio.builtin/vis-vega", CHART_SPEC),
                _node(EXTRA, "curio.builtin/computation-analysis", EXTRA_CODE),
            ],
            "edges": [
                {"id": f"reactflow__edge-{PRODUCER}out-{TRANSFORM}in", "source": PRODUCER, "target": TRANSFORM},
                {"id": f"reactflow__edge-{TRANSFORM}out-{CHART}in", "source": TRANSFORM, "target": CHART},
            ],
        },
    }


# ---------------------------------------------------------------------------
# Steps shared by the scenarios
# ---------------------------------------------------------------------------

def _enter(page, app_frontend, current_server, *, prefix: str) -> dict:
    """Sign in as a fresh owner, on the canvas of a fresh copy of the dataflow."""
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Notebook Owner",
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        project_name="Notebook view e2e",
        project_spec=_spec(),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    return session


def _positions(page) -> dict:
    """Each node's position and its stamped canvas spot, from React Flow's store."""
    return page.evaluate(
        """() => Object.fromEntries(window.__curio_reactFlow.getNodes().map((n) => [n.id, {
            x: n.position.x,
            y: n.position.y,
            canvas: (n.data && n.data.workflowPosition) || null,
        }]))"""
    )


def _boxes(page) -> dict:
    """Each node as the page draws it: its box's own size, where it sits on the
    screen, and its editor's size."""
    return page.evaluate(
        """() => Object.fromEntries(window.__curio_reactFlow.getNodes().map((n) => {
            const node = document.querySelector(`.react-flow__node[data-id="${n.id}"]`);
            const box = document.getElementById(`${n.id}resizable`);
            const editor = node && node.querySelector('.monaco-editor');
            const rect = node ? node.getBoundingClientRect() : null;
            return [n.id, {
                box: box ? [box.offsetWidth, box.offsetHeight] : null,
                screen: rect ? [rect.x, rect.y, rect.width, rect.height] : null,
                editor: editor ? [editor.offsetWidth, editor.offsetHeight] : null,
            }];
        }))"""
    )


def _settled_boxes(page, *, timeout_ms: int = 15000) -> dict:
    """``_boxes`` once two reads a few hundred milliseconds apart agree. React
    Flow measures a node, and Monaco lays out its editor, frames after a switch."""
    last = _boxes(page)
    waited = 0
    while waited < timeout_ms:
        page.wait_for_timeout(300)
        waited += 300
        now = _boxes(page)
        if now == last:
            return now
        last = now
    raise AssertionError(f"the nodes kept changing size or place: last read {last}")


def _show(page, view: str) -> None:
    """Pick a view on the bar's switch and wait until the nodes are laid out for it."""
    radio = page.locator(BAR).get_by_role("radio", name=f"{view.capitalize()} view", exact=True)
    radio.click()
    expect(radio).to_have_attribute("aria-checked", "true")
    if view == "notebook":
        page.wait_for_function(
            """(count) => {
                const nodes = window.__curio_reactFlow.getNodes();
                return nodes.length === count
                    && new Set(nodes.map((n) => n.position.x)).size === 1;
            }""",
            arg=len(CANVAS),
            timeout=20000,
        )
    else:
        page.wait_for_function(
            "() => window.__curio_reactFlow.getNodes().every((n) => !n.data || !n.data.workflowPosition)",
            timeout=20000,
        )


#: Each cell as the page draws it: where it is on the screen, and its own box's
#: width, with where the page's left edge is and how wide a cell spanning it to
#: the bar is. Null for a cell not drawn yet.
_CELLS_JS = """([ids, margin, bar]) => {
    const page = document.querySelector('.curio-flow-scroller');
    const left = page ? page.getBoundingClientRect().left : 0;
    const span = page ? page.clientWidth - bar - margin : 0;
    return ids.map((id) => {
        const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
        const box = document.getElementById(`${id}resizable`);
        if (!node || !box) return null;
        const r = node.getBoundingClientRect();
        return {id, x: r.x - left, top: r.top, bottom: r.bottom, height: r.height, width: box.offsetWidth, span};
    });
}"""

#: The cells as one column in the order given, spanning the page from its left
#: margin to the bar, each GAP below the one above, so none overlaps another.
_COLUMN_HOLDS_JS = (
    "([ids, margin, bar, gap]) => { const cells = (" + _CELLS_JS + ")([ids, margin, bar]);"
    " return cells.every((c) => !!c) && cells.every((c, k) =>"
    " Math.abs(c.width - c.span) <= 1 && c.height > 0 && Math.abs(c.x - margin) <= 1"
    " && (k === 0 || Math.abs(c.top - cells[k - 1].bottom - gap) <= 1)); }"
)


def _cells(page, ids: list[str]) -> list[dict]:
    return page.evaluate(_CELLS_JS, [ids, MARGIN, BAR_WIDTH])


def _wait_for_column(page, ids: list[str], *, timeout_ms: int = 20000) -> list[dict]:
    """The cells once they stand in one column across the page, each GAP below
    the one above. React Flow measures a cell a frame or more after it changes,
    and the column follows the measurement, so the relation is waited for, not
    read once."""
    try:
        page.wait_for_function(_COLUMN_HOLDS_JS, arg=[ids, MARGIN, BAR_WIDTH, GAP], timeout=timeout_ms)
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"the cells never stood in one column from the page's {MARGIN}px margin to the "
            f"{BAR_WIDTH}px bar, {GAP}px apart, in the order {ids}: {_cells(page, ids)}"
        ) from None
    return _cells(page, ids)


#: How visible a cell's tools (its tabs, Save output, info, pin, comments) are:
#: the computed opacity of its header's group of tools.
_TOOLS_OPACITY_JS = """(id) => {
    const tools = document.querySelector(`[id="${id}resizable"] > .curio-node-header > .curio-node-tools`);
    return tools ? Number(getComputedStyle(tools).opacity) : null;
}"""

#: The empty stretch of a cell's header, between its title and its status or
#: tools: where a click selects the node and does nothing else. ``onHeader``
#: says the pointer would land on the header there, not on app chrome over it.
_HEADER_GAP_JS = """(id) => {
    const header = document.querySelector(`[id="${id}resizable"] > .curio-node-header`);
    if (!header) return null;
    const rects = Array.from(header.children)
        .map((k) => k.getBoundingClientRect())
        .filter((r) => r.width > 0)
        .sort((a, b) => a.left - b.left);
    let best = null;
    for (let k = 1; k < rects.length; k++) {
        const gap = rects[k].left - rects[k - 1].right;
        if (!best || gap > best.gap) best = {gap, x: (rects[k].left + rects[k - 1].right) / 2};
    }
    if (!best || best.gap <= 12) return null;
    const box = header.getBoundingClientRect();
    const y = box.top + box.height / 2;
    const hit = document.elementFromPoint(best.x, y);
    return {x: best.x, y, onHeader: !!hit && header.contains(hit)};
}"""

#: Where a connection's path is halfway along, on the screen: on its lane in
#: the bar in the notebook view (the lane is most of a bracket's length), and
#: between its two nodes on the canvas. Null when it is not drawn.
_PATH_MIDPOINT_JS = """(id) => {
    const path = document.querySelector(
        `.react-flow__edge[data-testid="rf__edge-${id}"] path.react-flow__edge-path`);
    if (!path) return null;
    const p = path.getPointAtLength(path.getTotalLength() / 2);
    const m = path.getScreenCTM();
    return {x: p.x * m.a + p.y * m.c + m.e, y: p.x * m.b + p.y * m.d + m.f};
}"""

#: Whether a click at the point lands on the connection: what the pointer hits
#: there is part of its edge.
_HITS_EDGE_JS = """([point, id]) => {
    const hit = document.elementFromPoint(point.x, point.y);
    return !!hit && !!hit.closest(`.react-flow__edge[data-testid="rf__edge-${id}"]`);
}"""

#: Whether React Flow holds the connection as selected.
_EDGE_SELECTED_JS = """(id) => {
    const edge = window.__curio_reactFlow.getEdges().find((e) => e.id === id);
    return !!(edge && edge.selected);
}"""

#: Put the caret at the start of a cell's code editor through Monaco's own API
#: (a click lands on Monaco's view-line layer); true once the focus is in it.
_CARET_AT_START_JS = """(id) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const el = node && node.querySelector('.monaco-editor');
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const editor = el && editors.find((e) => el.contains(e.getDomNode()));
    if (!editor) return false;
    editor.focus();
    editor.setPosition({lineNumber: 1, column: 1});
    return el.contains(document.activeElement);
}"""

#: What a cell's code editor holds.
_EDITOR_VALUE_JS = """(id) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const el = node && node.querySelector('.monaco-editor');
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const editor = el && editors.find((e) => el.contains(e.getDomNode()));
    return editor ? editor.getValue() : null;
}"""


#: A code cell's Monaco editor: its lines, the ones it shows, and whether its
#: content is taller than the editor (an inner scroll).
_EDITOR_JS = """(id) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const el = node && node.querySelector('.monaco-editor');
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const editor = el && editors.find((e) => el.contains(e.getDomNode()));
    if (!editor) return null;
    const ranges = editor.getVisibleRanges();
    return {
        lines: editor.getModel().getLineCount(),
        first: ranges.length ? ranges[0].startLineNumber : 0,
        last: ranges.length ? ranges[ranges.length - 1].endLineNumber : 0,
        scrollHeight: editor.getScrollHeight(),
        height: editor.getLayoutInfo().height,
    };
}"""

#: Each cell's top in the flow (React Flow's store) and its drawn height.
_EXTENTS_JS = """(ids) => Object.fromEntries(ids.map((id) => {
    const n = window.__curio_reactFlow.getNodes().find((node) => node.id === id);
    const el = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    return [id, n && el ? {y: n.position.y, height: el.offsetHeight} : null];
}))"""

#: Where the arc from *source* to *target* starts and ends on the screen, and
#: where the two dots it joins are: React Flow joins a right-side dot at the
#: middle of its right edge.
_ARC_ENDS_JS = """([source, target]) => {
    const edge = window.__curio_reactFlow.getEdges().find((e) => e.source === source && e.target === target);
    const path = edge && document.querySelector(
        `.react-flow__edge[data-testid="rf__edge-${edge.id}"] path.react-flow__edge-path`);
    const dot = (id, handle) => document.querySelector(
        `.react-flow__node[data-id="${id}"] .react-flow__handle[data-handleid="${handle}"]`);
    const out = dot(source, edge && edge.sourceHandle ? edge.sourceHandle : 'out');
    const inp = dot(target, edge && edge.targetHandle ? edge.targetHandle : 'in');
    if (!path || !out || !inp) return null;
    const m = path.getScreenCTM();
    const at = (len) => {
        const p = path.getPointAtLength(len);
        return [p.x * m.a + p.y * m.c + m.e, p.x * m.b + p.y * m.d + m.f];
    };
    const joint = (el) => { const r = el.getBoundingClientRect(); return [r.right, r.top + r.height / 2]; };
    return {start: at(0), end: at(path.getTotalLength()), out: joint(out), in: joint(inp)};
}"""

_ARC_ON_ITS_DOTS_JS = (
    "(args) => { const a = (" + _ARC_ENDS_JS + ")(args); if (!a) return false;"
    " const near = (p, q) => Math.abs(p[0] - q[0]) <= 2 && Math.abs(p[1] - q[1]) <= 2;"
    " return near(a.start, a.out) && near(a.end, a.in); }"
)


def _scroll_to(page, y: float) -> None:
    page.locator(SCROLLER).evaluate("(el, top) => { el.scrollTop = top; }", y)
    page.wait_for_function(
        "([sel, top]) => Math.abs(document.querySelector(sel).scrollTop - top) < 2"
        " || document.querySelector(sel).scrollTop + document.querySelector(sel).clientHeight"
        " >= document.querySelector(sel).scrollHeight - 1",
        arg=[SCROLLER, y],
        timeout=10000,
    )


def _scroll_top(page) -> float:
    return page.locator(SCROLLER).evaluate("(el) => el.scrollTop")


def _settled_viewport(page, *, timeout_ms: int = 15000) -> dict:
    """React Flow's viewport once nothing moves it: two equal reads a few
    hundred milliseconds apart. React Flow 11 sets a view through a d3
    transition, so a view set by a switch or a fit lands a frame or two later."""
    read = "() => window.__curio_reactFlow.getViewport()"
    last = page.evaluate(read)
    waited = 0
    while waited < timeout_ms:
        page.wait_for_timeout(300)
        waited += 300
        now = page.evaluate(read)
        if all(abs(now[key] - last[key]) < 0.01 for key in ("x", "y", "zoom")):
            return now
        last = now
    raise AssertionError(f"the canvas viewport kept moving: last read {last}")


def _save(page) -> None:
    """Save through the status icon and wait until the dataflow is on disk."""
    page.locator("[data-curio-save-state]").first.click(force=True)
    page.wait_for_function(
        "() => document.querySelector('[data-curio-save-state]')"
        "?.getAttribute('data-curio-save-state') === 'saved'",
        timeout=30000,
    )


def _project(current_server: str, token: str, project_id: str) -> dict:
    return api_json(f"{current_server}/api/projects/{project_id}", token)


def _wheel_over(page, locator, delta_y: float) -> None:
    box = locator.bounding_box()
    assert box, "nothing to put the pointer on"
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + min(box["height"] / 2, 60))
    page.mouse.wheel(0, delta_y)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def test_the_switch_shows_the_dataflow_as_a_column_of_cells(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="nbv_column")
    _show(page, "notebook")
    assert "view=notebook" in page.url, page.url

    placed = _positions(page)
    ys = [placed[node_id]["y"] for node_id in ORDER]
    assert ys == sorted(ys) and len(set(ys)) == len(ys), (
        f"the cells are not in dataflow order {ORDER}: {placed}"
    )
    for node_id, (x, y) in CANVAS.items():
        assert placed[node_id]["canvas"] == {"x": x, "y": y}, (
            f"{node_id} lost its canvas spot: {placed[node_id]}"
        )

    # No rail down the left edge: the cells take the page's width.
    expect(page.locator("#tools-palette-dock")).to_have_count(0)
    # One column, in dataflow order, every cell spanning the page and as tall
    # as its content, GAP apart, none over another.
    cells = {c["id"]: c for c in _wait_for_column(page, ORDER)}
    assert cells[EXTRA]["height"] < cells[PRODUCER]["height"], (
        f"EXTRA's one-line cell is not shorter than PRODUCER's six-line one: {cells}"
    )
    # PRODUCER's editor is as tall as its lines: it shows every one of them,
    # with nothing left to scroll to inside it.
    try:
        page.wait_for_function(
            "(id) => { const e = (" + _EDITOR_JS + ")(id);"
            " return !!e && e.first === 1 && e.last >= e.lines && e.scrollHeight <= e.height + 1; }",
            arg=PRODUCER,
            timeout=15000,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"PRODUCER's editor does not show all its lines: {page.evaluate(_EDITOR_JS, PRODUCER)}"
        ) from None

    for node_id in ORDER:
        cell = node_locator(page, node_id)
        expect(cell.locator(".react-flow__handle-left")).to_have_count(0)
        expect(cell.locator(".react-flow__handle-top")).to_have_count(0)
        expect(page.locator(f'[id="{node_id}resizer"]')).to_have_count(0)

    # Nodes are added, connected and deleted on the canvas: no (+) between the
    # cells, no dot that starts or takes a connection, and no cell with a
    # Delete node tool among its header's tools. Run all stays on the page.
    expect(page.locator("[data-curio-add-after]")).to_have_count(0)
    expect(page.locator(".react-flow__node .react-flow__handle")).not_to_have_count(0)
    expect(page.locator(".react-flow__node .react-flow__handle.connectable")).to_have_count(0)
    expect(page.locator(".react-flow__node .curio-node-header > .curio-node-tools")).to_have_count(len(ORDER))
    expect(page.locator('.react-flow__node [title="Delete node"]')).to_have_count(0)
    expect(page.locator("#notebook-run-all").get_by_role("button", name="Run all nodes")).to_be_visible()

    # One arc per connection, all of it in the bar right of the cells.
    cells_right = page.locator(f'[id="{PRODUCER}resizable"]').bounding_box()
    edges = page.locator(".react-flow__edge")
    expect(edges).to_have_count(2)
    for i in range(2):
        arc = edges.nth(i).bounding_box()
        assert arc and arc["x"] >= cells_right["x"] + cells_right["width"] - 1, (
            f"an arc is drawn over the cells rather than in the bar: {arc}"
        )

    _scroll_to(page, 0)
    save_workflow_test_screenshot(
        page, SCREENSHOT_STEM, test_name="notebook_view__top", fit_reactflow=False,
    )

    # A cell's tools stay out of sight until the pointer is over the cell: Play,
    # the title and the status always show, the rest only then.
    assert page.evaluate(_TOOLS_OPACITY_JS, EXTRA) == 0, "EXTRA's tools show while nothing points at it"
    # EXTRA is the last cell: bring it well into view, clear of the title.
    _scroll_to(page, max(0, _positions(page)[EXTRA]["y"] - 250))
    header = page.locator(f'[id="{EXTRA}resizable"] .curio-node-header')
    box = header.bounding_box()
    assert box, "EXTRA's cell has no header"
    page.mouse.move(box["x"] + box["width"] / 3, box["y"] + box["height"] / 2)
    try:
        page.wait_for_function(f"() => ({_TOOLS_OPACITY_JS})({EXTRA!r}) === 1", timeout=5000)
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"EXTRA's tools did not show under the pointer: opacity {page.evaluate(_TOOLS_OPACITY_JS, EXTRA)}"
        ) from None
    expect(page.locator(f'[id="{EXTRA}resizable"] svg.fa-circle-play')).to_be_visible()


def test_a_run_shows_each_cells_input_and_output_together(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="nbv_run")
    _show(page, "notebook")
    _wait_for_column(page, ORDER)
    before = page.evaluate(_EXTENTS_JS, [TRANSFORM, CHART])

    node_locator(page, CHART).scroll_into_view_if_needed()
    play_node(page, CHART)
    wait_for_node_done(page, CHART, node_type="vis-vega", timeout_ms=180000)
    assert_vega_canvas_rendered(page, CHART, timeout=60000)

    # TRANSFORM's output grows its cell, and CHART, below it, moves down by as
    # much: it stays GAP under TRANSFORM.
    try:
        page.wait_for_function(
            "([ids, was, gap]) => { const now = (" + _EXTENTS_JS + ")(ids);"
            " const t = now[ids[0]], c = now[ids[1]];"
            " return !!t && !!c && t.height > was && Math.abs(c.y - (t.y + t.height) - gap) <= 1; }",
            arg=[[TRANSFORM, CHART], before[TRANSFORM]["height"], GAP],
            timeout=30000,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"the run did not grow TRANSFORM's cell with CHART {GAP}px under it: "
            f"{before} -> {page.evaluate(_EXTENTS_JS, [TRANSFORM, CHART])}"
        ) from None
    after = page.evaluate(_EXTENTS_JS, [TRANSFORM, CHART])
    grew = (after[TRANSFORM]["y"] + after[TRANSFORM]["height"]) - (before[TRANSFORM]["y"] + before[TRANSFORM]["height"])
    moved = after[CHART]["y"] - before[CHART]["y"]
    assert grew > 0 and abs(moved - grew) <= 1, (
        f"TRANSFORM's bottom moved {grew}px but CHART moved {moved}px: {before} -> {after}"
    )
    # The arc between them still runs from TRANSFORM's output dot to CHART's
    # input dot: the dots follow the cells, and the arc follows the dots.
    try:
        page.wait_for_function(_ARC_ON_ITS_DOTS_JS, arg=[TRANSFORM, CHART], timeout=15000)
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"the TRANSFORM to CHART arc is off its dots: {page.evaluate(_ARC_ENDS_JS, [TRANSFORM, CHART])}"
        ) from None

    # The chart's spec and its chart, at once.
    chart = node_locator(page, CHART)
    expect(chart.locator(".monaco-editor").first).to_be_visible()
    expect(page.locator(f'[id="vega{CHART}"]')).to_be_visible()

    # The transform's code and its output box, at once; the run filled the box
    # (its Jupyter-style counter reads [n]:, not [ ]:).
    transform = node_locator(page, TRANSFORM)
    transform.scroll_into_view_if_needed()
    expect(transform.locator(".monaco-editor").first).to_be_visible()
    expect(transform.locator("[data-curio-node-output]").first).to_contain_text(
        re.compile(r"\[\d+\]:"), timeout=30000,
    )

    # The chart's cell where the first cell sits on the page's top, below the
    # bar, the title and its chips, as the app scrolls to a cell.
    first_top, chart_top = page.evaluate(
        "(ids) => ids.map((id) => window.__curio_reactFlow.getNodes().find((n) => n.id === id).position.y)",
        [PRODUCER, CHART],
    )
    _scroll_to(page, chart_top - first_top)
    save_workflow_test_screenshot(
        page, SCREENSHOT_STEM, test_name="notebook_view__chart", fit_reactflow=False,
    )


def test_the_wheel_scrolls_the_page_over_editors_and_outputs(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="nbv_wheel")
    _show(page, "notebook")

    _scroll_to(page, 0)
    _wheel_over(page, node_locator(page, PRODUCER).locator(".monaco-editor").first, 400)
    page.wait_for_function(f"() => document.querySelector('{SCROLLER}').scrollTop > 0", timeout=10000)

    mount = page.locator(f'[id="vega{CHART}"]')
    mount.scroll_into_view_if_needed()
    before = _scroll_top(page)
    assert before > 0, "the chart's cell is not below the fold, so this proves nothing"
    _wheel_over(page, mount, -300)
    page.wait_for_function(
        f"(top) => document.querySelector('{SCROLLER}').scrollTop < top", arg=before, timeout=10000,
    )


def _dot(page, node_id: str, handle: str):
    return page.locator(f'.react-flow__node[data-id="{node_id}"] .react-flow__handle[data-handleid="{handle}"]')


def _midpoint_in_window(page, edge_id: str, where: str) -> dict:
    """Where the connection is halfway along, checked to be in the window,
    below the bar."""
    point = page.evaluate(_PATH_MIDPOINT_JS, edge_id)
    assert point, f"the connection {edge_id} has no path {where}"
    bar = page.locator(BAR).bounding_box()
    viewport = page.viewport_size
    assert 0 <= point["x"] < viewport["width"] and bar["y"] + bar["height"] < point["y"] < viewport["height"], (
        f"the connection's midpoint {point} is not in the window {where}"
    )
    return point


def _select_by_header(page, node_id: str) -> None:
    """Click the node's header where it holds no control, as a user selects a
    node, and wait until React Flow has it selected."""
    spot = page.evaluate(_HEADER_GAP_JS, node_id)
    assert spot and spot["onHeader"], f"{node_id}'s header has no free spot under the pointer: {spot}"
    page.mouse.click(spot["x"], spot["y"])
    expect(node_locator(page, node_id)).to_have_class(re.compile(r"\bselected\b"), timeout=10000)


#: A node tile dropped on the page as the rail's drag would drop it, straight
#: on the drop target, so it needs no rail to drag from.
_DROP_TILE_JS = """(nodeType) => {
    const target = document.querySelector('.curio-canvas-drop-target');
    if (!target) return false;
    const r = target.getBoundingClientRect();
    const dataTransfer = new DataTransfer();
    dataTransfer.setData('application/reactflow', nodeType);
    const at = {bubbles: true, cancelable: true, dataTransfer,
                clientX: r.left + r.width / 2, clientY: r.top + r.height / 2};
    target.dispatchEvent(new DragEvent('dragover', at));
    target.dispatchEvent(new DragEvent('drop', at));
    return true;
}"""


def test_connections_and_cells_are_made_and_removed_on_the_canvas_only(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="nbv_connect")
    _show(page, "notebook")
    _wait_for_column(page, ORDER)
    count = len(_positions(page))

    # A drag from PRODUCER's output dot to TRANSFORM's free circle connects
    # nothing: in the notebook view the dots do not connect.
    box = _dot(page, PRODUCER, "out").bounding_box()
    assert box, "the cell has no output dot"
    _scroll_to(page, max(0, _scroll_top(page) + box["y"] - 300))
    start = _dot(page, PRODUCER, "out").bounding_box()
    end = _dot(page, TRANSFORM, "in_1").bounding_box()
    assert start and end, f"the dots to drag between are not drawn: {start} {end}"
    page.mouse.move(start["x"] + start["width"] / 2, start["y"] + start["height"] / 2)
    page.mouse.down()
    page.mouse.move(end["x"] + end["width"] / 2, end["y"] + end["height"] / 2, steps=12)
    page.mouse.up()
    page.wait_for_timeout(1000)
    expect(page.locator(".react-flow__edge")).to_have_count(2)

    # Nor is anything removed there. The PRODUCER to TRANSFORM arc takes no
    # click where it runs along its lane (halfway along its path), so the click
    # selects nothing; TRANSFORM's cell, selected by a click on its header,
    # stays selected; and Delete after each removes neither.
    edge_id = page.evaluate(
        "([s, t]) => window.__curio_reactFlow.getEdges().find((e) => e.source === s && e.target === t).id",
        [PRODUCER, TRANSFORM],
    )
    arc = page.locator(f'.react-flow__edge[data-testid="rf__edge-{edge_id}"]')
    point = _midpoint_in_window(page, edge_id, "in the notebook view")
    takes_click = page.evaluate(_HITS_EDGE_JS, [point, edge_id])
    page.mouse.click(point["x"], point["y"])
    # Time for a selection to reach the store, as it does on the canvas.
    page.wait_for_timeout(500)
    arc_selected = page.evaluate(_EDGE_SELECTED_JS, edge_id)
    page.keyboard.press("Delete")
    _select_by_header(page, TRANSFORM)
    page.keyboard.press("Delete")
    page.wait_for_timeout(1000)
    outcome = {
        "the arc takes the click": takes_click,
        "the click selected the arc": arc_selected,
        "PRODUCER to TRANSFORM arcs": arc.count(),
        "arcs": page.locator(".react-flow__edge").count(),
        "cells": len(_positions(page)),
    }
    assert outcome == {
        "the arc takes the click": False,
        "the click selected the arc": False,
        "PRODUCER to TRANSFORM arcs": 1,
        "arcs": 2,
        "cells": count,
    }, f"select plus Delete changed the graph in the notebook view: {outcome}"

    # Delete inside a cell's code editor still edits the code, not the graph.
    before = page.evaluate(_EDITOR_VALUE_JS, TRANSFORM)
    assert before, f"TRANSFORM's editor holds no code: {before!r}"
    assert page.evaluate(_CARET_AT_START_JS, TRANSFORM), "could not put the caret in TRANSFORM's code editor"
    page.keyboard.press("Delete")
    try:
        page.wait_for_function(
            "([id, want]) => (" + _EDITOR_VALUE_JS + ")(id) === want", arg=[TRANSFORM, before[1:]], timeout=10000,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"Delete in TRANSFORM's editor did not delete the character after the caret: "
            f"{before!r} -> {page.evaluate(_EDITOR_VALUE_JS, TRANSFORM)!r}"
        ) from None
    assert len(_positions(page)) == count, f"Delete in a cell's editor removed a cell: {_positions(page)}"
    expect(page.locator(".react-flow__edge")).to_have_count(2)

    # On the canvas the node has its Delete node tool, and the same presses
    # remove the connection, which takes the click there, then the node with
    # both its connections, once the two nodes are connected again.
    _show(page, "canvas")
    frame_nodes(page, [PRODUCER, TRANSFORM])
    expect(node_locator(page, TRANSFORM).get_by_title("Delete node")).to_have_count(1)
    point = _midpoint_in_window(page, edge_id, "on the canvas")
    assert page.evaluate(_HITS_EDGE_JS, [point, edge_id]), (
        f"a click at the connection's midpoint {point} on the canvas lands elsewhere"
    )
    page.mouse.click(point["x"], point["y"])
    page.keyboard.press("Delete")
    expect(arc).to_have_count(0, timeout=10000)
    expect(page.locator(".react-flow__edge")).to_have_count(1)

    connect_nodes(page, PRODUCER, TRANSFORM)
    expect(page.locator(".react-flow__edge")).to_have_count(2)

    _select_by_header(page, TRANSFORM)
    page.keyboard.press("Delete")
    expect(node_locator(page, TRANSFORM)).to_have_count(0, timeout=10000)
    expect(page.locator(".react-flow__edge")).to_have_count(0)
    assert len(_positions(page)) == count - 1, f"Delete on the canvas did not remove TRANSFORM alone: {_positions(page)}"


def test_nodes_are_added_on_the_canvas_only(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="nbv_add")
    _show(page, "notebook")
    _wait_for_column(page, ORDER)
    count = len(_positions(page))

    # No rail and no (+) to add a node from.
    expect(page.locator("#tools-palette-dock")).to_have_count(0)
    expect(page.locator("[data-curio-add-after]")).to_have_count(0)

    # A node dropped on the page is not added.
    assert page.evaluate(_DROP_TILE_JS, "curio.builtin/data-transformation@1"), "no drop target on the page"
    page.wait_for_timeout(1500)
    assert len(_positions(page)) == count, f"a drop on the notebook page added a node: {_positions(page)}"

    # Duplicate selection and Duplicate as scenario, which add copies, are off.
    page.get_by_role("button", name="View menu").click()
    expect(page.get_by_role("button", name="Duplicate selection")).to_be_disabled()
    expect(page.get_by_role("button", name="Duplicate as scenario")).to_be_disabled()
    page.get_by_role("button", name="View menu").click()

    # On the canvas the rail adds one.
    _show(page, "canvas")
    new_id = drag_to_canvas(page, page.locator("#tile-data-transformation"))
    page.wait_for_function(
        "(id) => !!window.__curio_reactFlow.getNodes().find((n) => n.id === id)", arg=new_id, timeout=10000,
    )
    assert len(_positions(page)) == count + 1


def test_back_on_the_canvas_every_node_is_where_it_was(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    session = _enter(page, app_frontend, current_server, prefix="nbv_back")
    project_id = session["project"]["id"]
    # The load's fit frames these nodes below zoom 1. It can wait for the node
    # packages first, so the view to bring back is taken once it has moved.
    page.wait_for_function("() => window.__curio_reactFlow.getViewport().zoom < 1", timeout=20000)
    viewport = _settled_viewport(page)
    before = _positions(page)
    drawn = _settled_boxes(page)

    _show(page, "notebook")
    _show(page, "canvas")
    assert "view=" not in page.url, page.url

    after = _positions(page)
    for node_id in CANVAS:
        assert (after[node_id]["x"], after[node_id]["y"]) == (before[node_id]["x"], before[node_id]["y"]), (
            f"{node_id} moved on the canvas: {before[node_id]} -> {after[node_id]}"
        )
        assert after[node_id]["canvas"] is None, f"{node_id} kept a notebook stamp"
    restored = _settled_viewport(page)
    for key in ("x", "y", "zoom"):
        assert abs(restored[key] - viewport[key]) < 0.5, f"the canvas viewport moved: {viewport} -> {restored}"

    # What the owner sees: every node at its own size and on the same spot of
    # the screen as before, not grown to the cell's size over its neighbours.
    redrawn = _settled_boxes(page)
    for node_id in CANVAS:
        was, now = drawn[node_id], redrawn[node_id]
        assert was["box"] and now["box"] == was["box"], (
            f"{node_id} came back {now['box']} instead of its canvas size {was['box']}"
        )
        assert now["screen"] and all(abs(a - b) <= 1 for a, b in zip(now["screen"], was["screen"])), (
            f"{node_id} is drawn elsewhere on the screen: {was['screen']} -> {now['screen']}"
        )
        if was["editor"] is not None:
            assert now["editor"] == was["editor"], (
                f"{node_id}'s editor came back {now['editor']} instead of {was['editor']}"
            )

    # A save from the notebook view writes the canvas layout: the positions the
    # nodes had on the canvas, read from the store before the switch.
    _show(page, "notebook")
    _save(page)
    nodes = _project(current_server, session["token"], project_id)["spec"]["dataflow"]["nodes"]
    saved = {n["id"]: (n["x"], n["y"]) for n in nodes}
    expected = {node_id: (spot["x"], spot["y"]) for node_id, spot in before.items()}
    assert saved == expected, f"the save wrote the cells' positions: {saved}, not {expected}"

    # The address keeps the view across a reload.
    page.reload()
    page.wait_for_selector(".react-flow__node", timeout=45000)
    expect(page.locator(BAR).get_by_role("radio", name="Notebook view", exact=True)).to_have_attribute(
        "aria-checked", "true", timeout=20000,
    )
    page.wait_for_function(
        "() => { const ns = window.__curio_reactFlow.getNodes();"
        " return ns.length > 0 && new Set(ns.map((n) => n.position.x)).size === 1; }",
        timeout=20000,
    )

    # A call that frames the canvas while the notebook view is on, like the
    # load's own fit, leaves the page where it is.
    page.evaluate("() => window.__curio_fitViewWithMenuOffset({ padding: 0.2 })")
    held = _settled_viewport(page)
    assert (held["x"], held["y"], held["zoom"]) == (0, 0, 1), f"a fit moved the notebook view: {held}"
