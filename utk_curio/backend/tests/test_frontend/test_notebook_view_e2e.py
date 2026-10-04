"""Playwright E2E: the notebook view shows a dataflow as a column of cells.

The canvas bar's Canvas | Notebook switch shows the same nodes one under the
other, in dataflow order, each the same size, with its input (code or grammar)
and its output together. The connections run in a bar to the right of the
cells, between dots on each cell's right edge. Everything the canvas allows
works there, and nothing about the view is saved: the dataflow keeps its canvas
layout, and the view lives in the address (``?view=notebook``).

What each test pins:

* the switch lays the cells out in one column, in dataflow order, with one arc
  per connection in the bar and no resize handle on any cell;
* a run shows a Python cell's code and output, and a Vega-Lite cell's spec and
  chart, together;
* the wheel scrolls the page over a cell's editor and over its output;
* dragging between dots connects two cells, and select plus Delete removes the
  connection;
* a tile dropped on the notebook becomes a cell, placed on the canvas past the
  others and scrolled into view;
* back on the canvas every node is where it was, a save writes the canvas
  layout, and a reload keeps the view the address names.

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

from playwright.sync_api import expect

from .utils import (
    api_json,
    assert_vega_canvas_rendered,
    connect_nodes,
    dismiss_toasts,
    drag_to_canvas,
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

#: Where each node sits on the canvas. EXTRA reads from nothing, so it is the
#: second cell (after the other node nothing feeds) until a test connects it.
CANVAS = {
    PRODUCER: (0, 0),
    TRANSFORM: (700, 0),
    CHART: (1400, 0),
    EXTRA: (700, 600),
}
#: Dataflow order: the nodes nothing feeds, in the spec's order, then the rest.
ORDER = [PRODUCER, EXTRA, TRANSFORM, CHART]

CELL_WIDTH = 880
CELL_HEIGHT = 560

PRODUCER_CODE = (
    "import pandas as pd\n\n"
    "return pd.DataFrame({'category': ['a', 'b', 'c'], 'count': [3, 7, 5]})\n"
)
TRANSFORM_CODE = "print(len(arg))\nreturn arg\n"
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

    for node_id in ORDER:
        box = page.locator(f'[id="{node_id}resizable"]').bounding_box()
        assert box and abs(box["width"] - CELL_WIDTH) < 1 and abs(box["height"] - CELL_HEIGHT) < 1, (
            f"{node_id} is not a {CELL_WIDTH}x{CELL_HEIGHT} cell: {box}"
        )
        cell = node_locator(page, node_id)
        expect(cell.locator(".react-flow__handle-left")).to_have_count(0)
        expect(cell.locator(".react-flow__handle-top")).to_have_count(0)
        expect(page.locator(f'[id="{node_id}resizer"]')).to_have_count(0)

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


def test_a_run_shows_each_cells_input_and_output_together(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="nbv_run")
    _show(page, "notebook")

    node_locator(page, CHART).scroll_into_view_if_needed()
    play_node(page, CHART)
    wait_for_node_done(page, CHART, node_type="vis-vega", timeout_ms=180000)
    assert_vega_canvas_rendered(page, CHART, timeout=60000)

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

    chart_top = page.evaluate(
        "(id) => window.__curio_reactFlow.getNodes().find((n) => n.id === id).position.y",
        CHART,
    )
    _scroll_to(page, max(0, chart_top - 120))
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


def test_connections_are_made_and_removed_in_the_bar(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="nbv_connect")
    _show(page, "notebook")

    # EXTRA's output dot and the next cell's free input circle (TRANSFORM is
    # wired on circle 0), both in view and clear of the bar fixed over the top
    # of the page. Feeding TRANSFORM a second input leaves the order as it is,
    # so neither cell moves while the test works on them.
    out_dot = page.locator(f'.react-flow__node[data-id="{EXTRA}"] .react-flow__handle[data-handleid="out"]')
    box = out_dot.bounding_box()
    assert box, "the cell has no output dot"
    _scroll_to(page, max(0, _scroll_top(page) + box["y"] - 300))

    edge_id = connect_nodes(page, EXTRA, TRANSFORM, target_handle="in_1")
    arc = page.locator(f'.react-flow__edge[data-testid="rf__edge-{edge_id}"]')
    expect(arc).to_have_count(1)
    expect(page.locator(".react-flow__edge")).to_have_count(3)
    placed = _positions(page)
    assert [placed[n]["y"] for n in ORDER] == sorted(placed[n]["y"] for n in ORDER), (
        f"connecting moved the cells out of {ORDER}: {placed}"
    )

    # Select the arc where it runs along its lane: halfway along the path is on
    # the lane, since the lane is most of a bracket's length. Then delete it.
    point = page.evaluate(
        """(id) => {
            const path = document.querySelector(
                `.react-flow__edge[data-testid="rf__edge-${id}"] path.react-flow__edge-path`);
            if (!path) return null;
            const p = path.getPointAtLength(path.getTotalLength() / 2);
            const m = path.getScreenCTM();
            return { x: p.x * m.a + p.y * m.c + m.e, y: p.x * m.b + p.y * m.d + m.f };
        }""",
        edge_id,
    )
    assert point, "the new connection has no path"
    bar_bottom = page.locator(BAR).bounding_box()["y"] + page.locator(BAR).bounding_box()["height"]
    viewport = page.viewport_size
    assert 0 <= point["x"] < viewport["width"] and bar_bottom < point["y"] < viewport["height"], (
        f"the arc's midpoint {point} is not in the window"
    )
    page.mouse.click(point["x"], point["y"])
    page.keyboard.press("Delete")
    expect(arc).to_have_count(0, timeout=10000)
    expect(page.locator(".react-flow__edge")).to_have_count(2)


def test_a_tile_dropped_on_the_notebook_becomes_a_cell_in_view(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="nbv_drop")
    _show(page, "notebook")

    new_id = drag_to_canvas(page, page.locator("#tile-data-transformation"))

    # The node exists once the drop lands; it becomes a cell, stamped and
    # moved into the column, on the next pass.
    page.wait_for_function(
        """([id, column]) => {
            const n = window.__curio_reactFlow.getNodes().find((node) => node.id === id);
            const col = window.__curio_reactFlow.getNodes().find((node) => node.id === column);
            return !!n && !!col && !!(n.data && n.data.workflowPosition) && n.position.x === col.position.x;
        }""",
        arg=[new_id, PRODUCER],
        timeout=10000,
    )
    # Placed on the canvas past every other node, as a drop with no point would be.
    placed = _positions(page)[new_id]
    max_x = max(x for x, _ in CANVAS.values())
    max_y = max(y for _, y in CANVAS.values())
    assert placed["canvas"] == {"x": max_x + 800, "y": max_y}, placed
    # Scrolled into view below the bar.
    page.wait_for_function(
        """(id) => {
            const el = document.querySelector(`.react-flow__node[data-id="${id}"]`);
            const bar = document.querySelector('header[data-curio-menu-bar]');
            if (!el || !bar) return false;
            const top = el.getBoundingClientRect().top;
            return top >= bar.getBoundingClientRect().bottom - 1 && top < window.innerHeight - 100;
        }""",
        arg=new_id,
        timeout=10000,
    )


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
