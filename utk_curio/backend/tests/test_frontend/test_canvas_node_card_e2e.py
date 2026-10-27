"""Playwright E2E: a canvas node is drawn as a notebook cell is.

A node on the canvas is a card: Play first in its header, then its title, its
pills and its run status, then its tools (the editor's tabs, Save output, info,
pin, minimize and delete), which show only while the pointer is over
the node or the node is selected. There is no row under the body: the body
reaches the node's bottom edge. The canvas keeps what a cell lacks: the node
still resizes and still minimizes.

What each test pins:

* Play, the title and the status are in the header, in that order, with the
  tools after them; nothing runs under the body, which fills the node;
* the tools are out of sight (opacity 0) until the pointer is over the node or
  the node is selected;
* Delete node is the last tool, with Minimize right before it; on a read-only
  canvas, which has no Delete node, Minimize is the last tool;
* the Code pill, now in the header, still switches the node's tabs;
* the resize handle still resizes the node and saves its size, and Minimize
  (among the tools) still folds the node into its chip, which a click opens
  again at the same size;
* a double-click where a press drags the node (its header) zooms the view onto
  the node, centered in what the bar, the title and the rail leave visible;
* a double-click inside the node's editor, which is not a drag region, leaves
  the view where it was;
* the zoom is judged where it lands, even when the browser draws no frame
  halfway through it;
* on a read-only canvas (a visitor with no account on another user's dataflow),
  where nodes do not drag, the same two double-clicks do the same, and a drag
  from a node's corner leaves its size: only an owner resizes.

The dataflow is built here: a Python node feeding a Vega-Lite node, no
datasets, so a failure is about the node card.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_canvas_node_card_e2e.py -v
"""
from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .utils import (
    activate_header_icon,
    allow_guest_login_env,
    assert_vega_canvas_rendered,
    auth_enabled_env,
    dismiss_toasts,
    frame_nodes,
    node_locator,
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_db_user,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

SCREENSHOT_STEM = "canvas-node-card"

PRODUCER = "card-producer"
CHART = "card-chart"
NODES = [PRODUCER, CHART]

#: The kinds' titles, as the Node Catalog names them.
TITLES = {PRODUCER: "Data Loading", CHART: "Vega-Lite"}
#: The class of the tab pill that is switched on.
ACTIVE = re.compile(r"\bactive\b")

PRODUCER_CODE = (
    "import pandas as pd\n"
    "\n"
    "return pd.DataFrame({'category': ['a', 'b', 'c'], 'count': [3, 7, 5]})\n"
)
CHART_SPEC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": "bar",
    "encoding": {
        "x": {"field": "category", "type": "nominal"},
        "y": {"field": "count", "type": "quantitative"},
    },
}, indent=2)


def _node(node_id: str, node_type: str, x: int, content: str) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "x": x,
        "y": 0,
        "in": "DEFAULT",
        "out": "DEFAULT",
        "goal": "",
        "metadata": {"keywords": []},
        "content": content,
    }


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "Canvas node card e2e",
            "task": "",
            "description": "",
            "packages": [],
            "datasets": [],
            "nodes": [
                _node(PRODUCER, "curio.builtin/data-loading", 0, PRODUCER_CODE),
                _node(CHART, "curio.builtin/vis-vega", 700, CHART_SPEC),
            ],
            "edges": [
                {"id": f"reactflow__edge-{PRODUCER}out-{CHART}in", "source": PRODUCER, "target": CHART},
            ],
        },
    }


def _enter(page, app_frontend, current_server, *, prefix: str) -> dict:
    """Sign in as a fresh owner, on the canvas of a fresh copy of the dataflow,
    both nodes framed."""
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Card Owner",
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        project_name="Canvas node card e2e",
        project_spec=_spec(),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    frame_nodes(page, NODES)
    return session


#: A node's header as the page draws it: its children in order (Play, the title,
#: the status, the tools), and whether anything of the run controls sits
#: outside it. Null when the node has no card header.
_HEADER_JS = """(id) => {
    const box = document.getElementById(`${id}resizable`);
    const header = box && box.querySelector(':scope > .curio-node-header');
    if (!header) return null;
    const kids = Array.from(header.children);
    const plays = Array.from(box.querySelectorAll('svg.fa-circle-play'));
    const tools = header.querySelector(':scope > .curio-node-tools');
    const status = kids.find((k) => /^(Done|Error)$/.test((k.textContent || '').trim()));
    return {
        first: kids[0] ? kids[0].matches('svg.fa-circle-play') : false,
        title: kids[1] ? (kids[1].textContent || '').trim() : '',
        last: kids.length ? kids[kids.length - 1] === tools : false,
        status: status ? status.textContent.trim() : null,
        statusBeforeTools: !!status && !!tools
            && !!(status.compareDocumentPosition(tools) & Node.DOCUMENT_POSITION_FOLLOWING),
        playsInNode: plays.length,
        playsInHeader: plays.filter((p) => header.contains(p)).length,
        pillsInHeader: header.querySelectorAll('.nav-link[data-rr-ui-event-key]').length,
        pillsInBody: Array.from(box.querySelectorAll('.nav-link[data-rr-ui-event-key]'))
            .filter((p) => !header.contains(p)).length,
    };
}"""

#: How far the bottom of a node's panes is from the bottom of its box, in
#: screen pixels: the box's padding and border only, once no row sits under them.
_BODY_GAP_JS = """(id) => {
    const box = document.getElementById(`${id}resizable`);
    const panes = box && box.querySelector('.tab-content');
    if (!panes) return null;
    return box.getBoundingClientRect().bottom - panes.getBoundingClientRect().bottom;
}"""

#: How visible a node's tools are: the computed opacity of the group holding
#: its Delete button.
_TOOLS_OPACITY_JS = """(id) => {
    const del = document.querySelector(`[id="${id}resizable"] [data-tooltip="Delete node"]`);
    const tools = del && del.closest('.curio-node-tools');
    return tools ? Number(getComputedStyle(tools).opacity) : null;
}"""

#: A node's tools in the order they sit: the titles of their buttons, the
#: title of the group's last child, and how many Delete node buttons the node
#: has. Null when the node has no tools.
_TOOLS_ORDER_JS = """(id) => {
    const box = document.getElementById(`${id}resizable`);
    const tools = box && box.querySelector(':scope > .curio-node-header > .curio-node-tools');
    if (!tools) return null;
    const last = tools.lastElementChild;
    return {
        titles: Array.from(tools.querySelectorAll('button')).map((b) => b.getAttribute('data-tooltip') || ''),
        last: last ? (last.getAttribute('data-tooltip') || last.tagName.toLowerCase()) : null,
        deletes: box.querySelectorAll('[data-tooltip="Delete node"]').length,
    };
}"""


#: The empty stretch of a node's header, between its pills and its status or
#: tools: where a click selects the node and does nothing else (the title of a
#: package node is a button that edits it, and the hidden tools still take a
#: click). Null when there is no such stretch.
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
    // What the pointer would land on there: the header, not app chrome over it.
    const hit = document.elementFromPoint(best.x, y);
    return {x: best.x, y, onHeader: !!hit && header.contains(hit)};
}"""


def _header(page, node_id: str):
    return page.locator(f'[id="{node_id}resizable"] > .curio-node-header')


def _wait_for_header(page, node_id: str) -> dict:
    """The node's header once Play is in it: Play mounts when the editor does."""
    try:
        page.wait_for_function(
            f"(id) => !!(({_HEADER_JS})(id) || {{}}).first", arg=node_id, timeout=30000,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"{node_id} has no card header starting with Play: {page.evaluate(_HEADER_JS, node_id)}"
        ) from None
    return page.evaluate(_HEADER_JS, node_id)


def _header_spot(page, node_id: str) -> dict:
    """A point on the node's header that holds no control and that nothing
    covers: where the pointer can rest on the node, or click to select it."""
    spot = page.evaluate(_HEADER_GAP_JS, node_id)
    assert spot and spot["onHeader"], (
        f"{node_id}'s header has no free spot under the pointer: {spot}, header {page.evaluate(_HEADER_JS, node_id)}"
    )
    return spot


def _point_at(page, node_id: str) -> None:
    spot = _header_spot(page, node_id)
    page.mouse.move(spot["x"], spot["y"])


def _pointer_off_the_nodes(page) -> None:
    """Put the pointer on the empty canvas under both nodes."""
    boxes = [node_locator(page, n).bounding_box() for n in NODES]
    bottom = max(b["y"] + b["height"] for b in boxes)
    viewport = page.viewport_size or {"width": 1280, "height": 720}
    page.mouse.move(viewport["width"] / 2, min(viewport["height"] - 20, bottom + 40))


def _wait_tools(page, node_id: str, opacity: int, why: str) -> None:
    try:
        page.wait_for_function(
            f"(id) => ({_TOOLS_OPACITY_JS})(id) === {opacity}", arg=node_id, timeout=5000,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"{node_id}'s tools should be at opacity {opacity} {why}: "
            f"{page.evaluate(_TOOLS_OPACITY_JS, node_id)}"
        ) from None


def _wait_tools_end_with(page, node_id: str, ending: list, canvas: str) -> dict:
    """The node's tools once their last buttons carry the titles in
    ``ending``, in that order, with nothing drawn after the last one."""
    condition = (
        "(id) => { const t = (" + _TOOLS_ORDER_JS + ")(id); if (!t) return false;"
        " const end = " + json.dumps(ending) + ";"
        " return t.last === end[end.length - 1]"
        " && end.every((title, k) => t.titles[t.titles.length - end.length + k] === title); }"
    )
    try:
        page.wait_for_function(condition, arg=node_id, timeout=10000)
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"{node_id}'s tools on {canvas} do not end with {ending}: "
            f"{page.evaluate(_TOOLS_ORDER_JS, node_id)}"
        ) from None
    return page.evaluate(_TOOLS_ORDER_JS, node_id)


def _selected(page, node_id: str) -> bool:
    return page.evaluate(
        "(id) => !!window.__curio_reactFlow.getNodes().find((n) => n.id === id)?.selected", node_id,
    )


def _box_size(page, node_id: str) -> list:
    return page.evaluate(
        "(id) => { const b = document.getElementById(`${id}resizable`);"
        " return b ? [b.offsetWidth, b.offsetHeight] : null; }",
        node_id,
    )


#: React Flow's viewport, and whether a move of it has yet to land. React Flow
#: moves the view through a d3 transition on the element it zooms, the
#: canvas's `.react-flow__renderer`, and d3 keeps the transitions scheduled or
#: running on an element in its `__transition` until they end.
_VIEWPORT_JS = """() => {
    const canvas = document.querySelector('.react-flow');
    const pane = canvas && canvas.querySelector('.react-flow__renderer');
    return {viewport: window.__curio_reactFlow.getViewport(), moving: !!(pane && pane.__transition)};
}"""


def _settled_viewport(page, *, timeout_ms: int = 30000) -> dict:
    """React Flow's viewport once its moves have landed: no d3 transition is
    left on the canvas, and two reads 250 ms apart agree.

    A zoom is a d3 transition, which moves only when the browser draws a
    frame. A loaded runner can draw none for longer than 250 ms, so two equal
    reads alone can catch a zoom halfway. Every read is on a timer, so the
    wait itself needs no frame."""
    last = None
    waited = 0
    while True:
        now = page.evaluate(_VIEWPORT_JS)
        if not now["moving"] and now["viewport"] == last:
            return last
        last = None if now["moving"] else now["viewport"]
        if waited >= timeout_ms:
            break
        page.wait_for_timeout(250)
        waited += 250
    raise AssertionError(
        f"the view did not land in {timeout_ms} ms: last read {now['viewport']}, "
        f"{'a move still under way' if now['moving'] else 'still moving'}"
    )


#: Where a node sits in the part of the pane nothing covers: below the bar and
#: the dataflow's title and chips, right of the node rail. Offsets of the
#: node's edges from that area's edges, and of its center from the area's.
_FRAMED_JS = """(id) => {
    const pane = document.querySelector('.react-flow').getBoundingClientRect();
    const tops = [...document.querySelectorAll('[data-curio-menu-bar], [data-curio-canvas-title], [data-curio-canvas-title] [data-curio-category-chips]')]
        .map((el) => el.getBoundingClientRect().bottom);
    const dock = document.getElementById('tools-palette-dock');
    const area = {
        left: Math.max(pane.left, dock ? dock.getBoundingClientRect().right : pane.left),
        top: Math.max(pane.top, ...tops),
        right: pane.right,
        bottom: pane.bottom,
    };
    const r = document.querySelector(`.react-flow__node[data-id="${id}"]`).getBoundingClientRect();
    return {
        inside: r.left >= area.left - 1 && r.top >= area.top - 1 && r.right <= area.right + 1 && r.bottom <= area.bottom + 1,
        dx: Math.round((r.left + r.right) / 2 - (area.left + area.right) / 2),
        dy: Math.round((r.top + r.bottom) / 2 - (area.top + area.bottom) / 2),
        node: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)],
        area: [Math.round(area.left), Math.round(area.top), Math.round(area.right), Math.round(area.bottom)],
    };
}"""


def _stored_size(page, node_id: str) -> list:
    return page.evaluate(
        "(id) => { const d = window.__curio_reactFlow.getNodes().find((n) => n.id === id).data;"
        " return [d.nodeWidth, d.nodeHeight]; }",
        node_id,
    )


#: How far past the zoom it starts from the view is when the hold below stops
#: the zoom: just past the 0.05 the double-click's own wait asks for, early on
#: the way from the 0.76 both nodes are framed at to the 1.31 the double-click
#: frames PRODUCER at, so the view stops far from where it lands.
_HELD_PAST_ZOOM = 0.06

#: How far the page's clock moves each frame from the double-click until the
#: hold below: the zoom (300 ms) is then read at 30, 60, 90 ms and so on of its
#: course, however far apart the runner draws its frames.
_STEP_MS = 30

#: How long the hold below keeps the zoom's next frame back: many of a
#: viewport wait's reads, 250 ms apart, even when the double-click's own wait
#: sees the zoom start only on a frame drawn late.
_HOLD_MS = 3000

# Before the app's own scripts, so d3's timer, which takes requestAnimationFrame
# and reads performance.now() to know how far a zoom has come, goes through
# them. Once armed with a zoom, from the double-click on (before the page's own
# handlers, so before the zoom starts) the page's clock moves *step* ms a frame
# and stands still between frames. Where the zoom stops then depends on frames
# counted, not on how far apart the runner draws them. d3's timer asks for its
# next frame from inside the frame callback that moved the view: the first such
# request made with the view's zoom past the armed zoom is kept back, so the
# zoom stops there, as on a loaded runner that draws no frame, and is handed
# on, on a timer, *ms* later. The clock runs on from where it stood. Every other
# frame callback goes through, so a wait that reads the zoom once a frame still
# sees it. It records the view while the zoom is held, where PRODUCER sits in
# sight then (read on a timer once React has drawn that view, which needs no
# frame), the view when the zoom goes on, how long it was held, and the frames
# the zoom ran on the stepped clock.
_HOLD_FRAMES_MID_ZOOM_JS = """(() => {
    const request = window.requestAnimationFrame.bind(window);
    const realNow = performance.now.bind(performance);
    const framed = () => (__FRAMED__)(__ID__);
    const view = () => window.__curio_reactFlow.getViewport();
    const record = {};
    let armed = null;
    // The page's clock: realNow() - offset, or `stepped` while it is stepped.
    let offset = 0;
    let stepped = null;
    let lastStamp = null;
    // The view's zoom when the frame callback running now began, while armed.
    let zoomAtStart = null;
    performance.now = () => (stepped !== null ? stepped : realNow() - offset);
    const hold = (callback) => {
        const ms = armed.ms;
        armed = null;
        offset = realNow() - stepped;
        stepped = null;
        record.heldAtMs = realNow();
        record.viewport = view();
        setTimeout(() => { record.framed = framed(); }, 100);
        setTimeout(() => {
            record.viewportAtRelease = view();
            record.heldForMs = realNow() - record.heldAtMs;
            request(callback);
        }, ms);
    };
    window.addEventListener('dblclick', () => {
        if (!armed || stepped !== null) return;
        stepped = realNow() - offset;
        record.steps = 0;
    }, true);
    window.requestAnimationFrame = (callback) => {
        if (armed && zoomAtStart !== null) {
            const zoom = view().zoom;
            if (zoom !== zoomAtStart && zoom > armed.zoom) {
                hold(callback);
                return 0;
            }
        }
        if (!armed) return request(callback);
        return request((stamp) => {
            if (stepped !== null && stamp !== lastStamp) {
                stepped += armed ? armed.step : 0;
                record.steps += 1;
            }
            lastStamp = stamp;
            zoomAtStart = window.__curio_reactFlow ? view().zoom : null;
            try {
                callback(stamp);
            } finally {
                zoomAtStart = null;
            }
        });
    };
    window.__curioTestHoldMidZoom = (zoom, step, ms) => {
        armed = { zoom, step, ms };
    };
    window.__curioTestMidZoomHold = record;
})();""".replace("__FRAMED__", _FRAMED_JS).replace("__ID__", json.dumps(PRODUCER))


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def test_play_the_title_and_the_status_are_in_the_header_with_no_bottom_row(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="card_header")

    for node_id in NODES:
        header = _wait_for_header(page, node_id)
        assert header["title"] == TITLES[node_id], f"{node_id}'s title is not right after Play: {header}"
        assert header["last"], f"{node_id}'s header does not end with its tools: {header}"
        assert header["playsInNode"] == 1 and header["playsInHeader"] == 1, (
            f"{node_id} has a Play outside its header: {header}"
        )
        assert header["pillsInHeader"] > 0 and header["pillsInBody"] == 0, (
            f"{node_id}'s tab pills are not all in its header: {header}"
        )
        # The panes reach the node's bottom edge: only the box's 5px padding
        # and 1px border are left under them, where a row of controls was.
        gap = page.evaluate(_BODY_GAP_JS, node_id)
        assert gap is not None and 0 <= gap <= 8, (
            f"{node_id}'s panes stop {gap}px above the node's bottom edge: room is still kept for a row"
        )

    play_node(page, CHART)
    wait_for_node_done(page, PRODUCER, node_type="data-loading", timeout_ms=180000)
    wait_for_node_done(page, CHART, node_type="vis-vega", timeout_ms=180000)
    assert_vega_canvas_rendered(page, CHART, timeout=60000)

    for node_id in NODES:
        try:
            page.wait_for_function(
                f"(id) => (({_HEADER_JS})(id) || {{}}).status === 'Done'", arg=node_id, timeout=15000,
            )
        except PlaywrightTimeoutError:
            raise AssertionError(
                f"{node_id}'s header does not read Done after the run: {page.evaluate(_HEADER_JS, node_id)}"
            ) from None
        header = page.evaluate(_HEADER_JS, node_id)
        assert header["statusBeforeTools"], f"{node_id}'s status is not before its tools: {header}"

    # The chart's card under the pointer, its tools showing, beside the
    # producer's at rest.
    frame_nodes(page, NODES)
    _point_at(page, CHART)
    _wait_tools(page, CHART, 1, "under the pointer")
    _wait_tools(page, PRODUCER, 0, "while nothing points at it")
    save_workflow_test_screenshot(page, SCREENSHOT_STEM, test_name="canvas_node_card__hover")


def test_the_tools_show_only_under_the_pointer_or_on_a_selected_node(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="card_tools")
    for node_id in NODES:
        _wait_for_header(page, node_id)

    _pointer_off_the_nodes(page)
    for node_id in NODES:
        assert not _selected(page, node_id), f"{node_id} is selected before anything was clicked"
        _wait_tools(page, node_id, 0, "while nothing points at it and it is not selected")
    # Play, the title and the status show at rest.
    expect(_header(page, PRODUCER).locator("svg.fa-circle-play")).to_be_visible()
    expect(_header(page, PRODUCER)).to_contain_text(TITLES[PRODUCER])

    _point_at(page, PRODUCER)
    _wait_tools(page, PRODUCER, 1, "under the pointer")
    _wait_tools(page, CHART, 0, "while the pointer is over the other node")

    _pointer_off_the_nodes(page)
    _wait_tools(page, PRODUCER, 0, "once the pointer leaves")

    # A click on the header's empty stretch selects the node, and its tools
    # stay after the pointer leaves.
    spot = _header_spot(page, PRODUCER)
    page.mouse.click(spot["x"], spot["y"])
    page.wait_for_function(
        "(id) => !!window.__curio_reactFlow.getNodes().find((n) => n.id === id)?.selected",
        arg=PRODUCER, timeout=5000,
    )
    _pointer_off_the_nodes(page)
    _wait_tools(page, PRODUCER, 1, "while it is selected")
    _wait_tools(page, CHART, 0, "while another node is selected")


def test_delete_node_is_the_last_tool_with_minimize_before_it(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="card_order")

    for node_id in NODES:
        _wait_for_header(page, node_id)
        tools = _wait_tools_end_with(page, node_id, ["Minimize", "Delete node"], "the owner's canvas")
        assert tools["deletes"] == 1, f"{node_id} should have one Delete node button: {tools}"


def test_the_pills_in_the_header_still_switch_tabs(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="card_tabs")
    _wait_for_header(page, CHART)

    header = _header(page, CHART)
    grammar_pill = header.locator('.nav-link[data-rr-ui-event-key="grammar"]')
    output_pill = header.locator('.nav-link[data-rr-ui-event-key="output"]')
    expect(grammar_pill).to_have_count(1)
    expect(output_pill).to_have_count(1)
    node = node_locator(page, CHART)
    editor = node.locator(".monaco-editor").first
    expect(editor).to_be_visible(timeout=30000)

    output_pill.click()
    expect(output_pill).to_have_class(ACTIVE)
    expect(grammar_pill).not_to_have_class(ACTIVE)
    expect(editor).to_be_hidden()

    grammar_pill.click()
    expect(grammar_pill).to_have_class(ACTIVE)
    expect(editor).to_be_visible()


def test_the_provenance_button_opens_the_nodes_runs_in_the_drawer(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="card_runs")
    _wait_for_header(page, PRODUCER)
    play_node(page, PRODUCER)
    wait_for_node_done(page, PRODUCER, node_type="data-loading", timeout_ms=180000)

    header = _header(page, PRODUCER)
    code_pill = header.locator('.nav-link[data-rr-ui-event-key="code"]')
    provenance = header.locator('.nav-link[data-rr-ui-event-key="provenance"]')
    expect(provenance).to_have_count(1)
    code_pill.click()
    editor = node_locator(page, PRODUCER).locator(".monaco-editor").first
    expect(editor).to_be_visible(timeout=30000)

    provenance.click()
    drawer = page.get_by_role("dialog", name="Node provenance")
    expect(drawer).to_be_visible(timeout=20000)
    expect(drawer.get_by_text(f"Runs of {TITLES[PRODUCER]}", exact=True)).to_be_visible()
    expect(drawer.locator("[data-provenance-item]")).to_have_count(1, timeout=20000)
    # Not a tab: the node keeps showing its code beside the drawer.
    expect(provenance).not_to_have_class(ACTIVE)
    expect(code_pill).to_have_class(ACTIVE)
    expect(editor).to_be_visible()

    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, '[data-curio-provenance-drawer="true"]')
    expect(code_pill).to_have_class(ACTIVE)
    expect(editor).to_be_visible()


def test_the_node_still_resizes_and_minimizes(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="card_resize")
    _wait_for_header(page, PRODUCER)

    # Resize: drag the handle at the node's bottom-right corner.
    before = _box_size(page, PRODUCER)
    handle = page.locator(f'[id="{PRODUCER}resizer"]')
    expect(handle).to_have_count(1)
    hb = handle.bounding_box()
    assert hb, "PRODUCER's resize handle is not drawn"
    x, y = hb["x"] + hb["width"] / 2, hb["y"] + hb["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 60, y + 40, steps=8)
    page.mouse.move(x + 120, y + 80, steps=8)
    page.mouse.up()
    after = _box_size(page, PRODUCER)
    assert after[0] - before[0] >= 100 and after[1] - before[1] >= 60, (
        f"dragging the handle 120x80 did not grow PRODUCER: {before} -> {after}"
    )
    try:
        page.wait_for_function(
            "([id, w, h]) => { const d = window.__curio_reactFlow.getNodes().find((n) => n.id === id).data;"
            " return d.nodeWidth === w && d.nodeHeight === h; }",
            arg=[PRODUCER, after[0], after[1]], timeout=5000,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"the node did not keep its new size {after}: stored {_stored_size(page, PRODUCER)}"
        ) from None

    # Minimize, among the tools that show under the pointer. Header icons act
    # on the pointer pair, which activate_header_icon sends.
    _point_at(page, PRODUCER)
    _wait_tools(page, PRODUCER, 1, "under the pointer")
    minimize = _header(page, PRODUCER).locator('.curio-node-tools [data-tooltip="Minimize"]')
    expect(minimize).to_have_count(1)
    activate_header_icon(minimize)
    expect(page.locator(f'[id="{PRODUCER}resizable"]')).to_be_hidden()
    chip = node_locator(page, PRODUCER).bounding_box()
    card = node_locator(page, CHART).bounding_box()
    assert chip and card and chip["width"] < card["width"] / 2 and chip["height"] < card["height"] / 2, (
        f"the minimized node is not a small chip beside the open one: {chip} vs {card}"
    )

    # A click on the chip opens the node again, at the size it was given.
    node_locator(page, PRODUCER).click()
    expect(page.locator(f'[id="{PRODUCER}resizable"]')).to_be_visible()
    try:
        page.wait_for_function(
            "([id, w, h]) => { const b = document.getElementById(`${id}resizable`);"
            " return !!b && b.offsetWidth === w && b.offsetHeight === h; }",
            arg=[PRODUCER, after[0], after[1]], timeout=5000,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"the node did not open at its size {after}: {_box_size(page, PRODUCER)}"
        ) from None


def _enter_read_only(page, app_frontend, current_server, *, prefix: str) -> None:
    """Open another user's copy of the dataflow as a visitor with no account:
    the shared guest's read-only canvas, where nodes do not drag, both nodes
    framed."""
    if auth_enabled_env() and not allow_guest_login_env():
        pytest.skip("A visitor with no account needs guest sign-in (ALLOW_GUEST_LOGIN)")
    owner = stub_db_user(
        current_server,
        name="Card Owner",
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        project_name="Canvas node card e2e",
        project_spec=_spec(),
    )
    page.goto(f"{app_frontend.base_url}/dataflow/{owner['project']['id']}", timeout=120000)
    page.wait_for_load_state("domcontentloaded")
    banner = page.get_by_test_id("shared-view-banner")
    banner.wait_for(state="visible", timeout=30000)
    assert "read-only" in (banner.inner_text() or "").lower(), banner.inner_text()
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    frame_nodes(page, NODES)


def _double_click_the_header_frames_the_node(page, canvas: str) -> None:
    """Double-click PRODUCER's header where a press drags the node (or would,
    on a read-only canvas), and expect the view zoomed onto PRODUCER."""
    _wait_for_header(page, PRODUCER)
    before = _settled_viewport(page)

    # The header's free stretch, where a press would drag the node.
    spot = _header_spot(page, PRODUCER)
    page.mouse.dblclick(spot["x"], spot["y"])
    try:
        page.wait_for_function(
            "(zoom) => window.__curio_reactFlow.getViewport().zoom > zoom + 0.05",
            arg=before["zoom"], timeout=5000,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"a double-click on PRODUCER's header on {canvas} did not zoom in: {before} -> "
            f"{page.evaluate('() => window.__curio_reactFlow.getViewport()')}"
        ) from None
    after = _settled_viewport(page)

    # Framed as the DATASET chip frames a node: whole, and centered in what the
    # bar, the title and the rail leave visible. React Flow's own double-click
    # zoom doubles the zoom at the pointer instead, leaving the node off center.
    framed = page.evaluate(_FRAMED_JS, PRODUCER)
    assert framed["inside"] and abs(framed["dx"]) <= 4 and abs(framed["dy"]) <= 4, (
        f"PRODUCER is not framed in the visible area on {canvas} after the zoom {before} -> {after} "
        f"(x{after['zoom'] / before['zoom']:.2f}): {framed}"
    )


def _double_click_the_editor_keeps_the_view(page, canvas: str) -> None:
    """Double-click inside PRODUCER's code editor, which is not a drag region,
    and expect the view exactly where it was."""
    _wait_for_header(page, PRODUCER)
    lines = node_locator(page, PRODUCER).locator(".monaco-editor .view-lines").first
    expect(lines).to_be_visible(timeout=30000)
    before = _settled_viewport(page)

    # The editor is not a drag region: a double-click there selects a word.
    box = lines.bounding_box()
    page.mouse.dblclick(box["x"] + 30, box["y"] + 8)
    page.wait_for_timeout(800)
    after = _settled_viewport(page)
    assert after == before, (
        f"a double-click in PRODUCER's editor moved the view on {canvas}: {before} -> {after}"
    )


def test_a_double_click_where_the_node_drags_zooms_onto_it(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="card_zoom")
    _double_click_the_header_frames_the_node(page, "the owner's canvas")


def test_a_double_click_inside_the_editor_leaves_the_view(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="card_nozoom")
    _double_click_the_editor_keeps_the_view(page, "the owner's canvas")


def test_on_a_read_only_canvas_a_double_click_where_the_node_would_drag_zooms_onto_it(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    _enter_read_only(page, app_frontend, current_server, prefix="card_ro_zoom")
    _double_click_the_header_frames_the_node(page, "a read-only canvas")


def test_on_a_read_only_canvas_the_zoom_is_judged_where_it_lands_though_frames_stop_mid_zoom(
    app_frontend: "FrontendPage", current_server, page,
):
    """The double-click's zoom is a d3 transition, which moves only when the
    browser draws a frame. Twice on CI the test above read the view on its way
    to where the app frames PRODUCER, and found PRODUCER off center: dx -42 on
    #1025's run 39352206012 (10-20) and dx -6 in run 40441039786 (10-27). The
    runner had drawn no frame for longer than the 250 ms between two reads,
    and the wait took two equal reads for a zoom that had landed; it now waits
    for React Flow's move to end. Here the zoom stops early, at a point set by
    frames counted on a stepped clock, for 3 s."""
    require_project_page()
    page.context.add_init_script(_HOLD_FRAMES_MID_ZOOM_JS)
    _enter_read_only(page, app_frontend, current_server, prefix="card_ro_held")
    assert page.evaluate("() => typeof window.__curioTestHoldMidZoom === 'function'"), (
        "the init script that holds frames back mid-zoom is not in the page"
    )
    _wait_for_header(page, PRODUCER)
    start = page.evaluate("() => window.__curio_reactFlow.getViewport().zoom")
    page.evaluate(
        "([zoom, step, ms]) => window.__curioTestHoldMidZoom(zoom, step, ms)",
        [start + _HELD_PAST_ZOOM, _STEP_MS, _HOLD_MS],
    )

    _double_click_the_header_frames_the_node(page, "a read-only canvas that drew no frame mid-zoom")

    hold = page.evaluate("() => window.__curioTestMidZoomHold")
    assert hold.get("heldAtMs") is not None and hold.get("steps", 0) >= 1, (
        f"the zoom was never held, or never ran on the stepped clock, so this test proves nothing: {hold}"
    )
    assert hold.get("viewportAtRelease") == hold["viewport"] and hold.get("heldForMs", 0) >= _HOLD_MS - 50, (
        f"the view moved while the zoom was held, or it was held for less than {_HOLD_MS} ms, so "
        f"this test proves nothing: {hold}"
    )
    framed = hold.get("framed")
    assert framed and (abs(framed["dx"]) > 4 or abs(framed["dy"]) > 4), (
        f"the zoom was held where PRODUCER is already framed, so a read then would pass: {hold}"
    )


def test_on_a_read_only_canvas_a_double_click_inside_the_editor_leaves_the_view(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    _enter_read_only(page, app_frontend, current_server, prefix="card_ro_nozoom")
    _double_click_the_editor_keeps_the_view(page, "a read-only canvas")


def test_on_a_read_only_canvas_minimize_is_the_last_tool(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    _enter_read_only(page, app_frontend, current_server, prefix="card_ro_order")

    for node_id in NODES:
        _wait_for_header(page, node_id)
        tools = _wait_tools_end_with(page, node_id, ["Minimize"], "a read-only canvas")
        assert tools["deletes"] == 0, f"{node_id} has a Delete node button on a read-only canvas: {tools}"


def test_on_a_read_only_canvas_a_corner_drag_leaves_the_node_size(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    _enter_read_only(page, app_frontend, current_server, prefix="card_ro_size")
    _wait_for_header(page, PRODUCER)
    before = _box_size(page, PRODUCER)
    stored = _stored_size(page, PRODUCER)

    # Drag from the node's bottom-right corner, where an owner's canvas draws
    # the resize handle over the browser's own grip, 120x80 as the owner's test
    # does; then the pointer moves on, which nothing left listening may follow.
    box = page.locator(f'[id="{PRODUCER}resizable"]').bounding_box()
    assert box, "PRODUCER's box is not drawn"
    x, y = box["x"] + box["width"] - 4, box["y"] + box["height"] - 4
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 60, y + 40, steps=8)
    page.mouse.move(x + 120, y + 80, steps=8)
    page.mouse.up()
    page.mouse.move(x - 150, y - 100, steps=8)
    page.wait_for_timeout(300)

    after = _box_size(page, PRODUCER)
    assert after == before, f"a corner drag resized PRODUCER on a read-only canvas: {before} -> {after}"
    assert _stored_size(page, PRODUCER) == stored, (
        f"a corner drag changed PRODUCER's stored size on a read-only canvas: "
        f"{stored} -> {_stored_size(page, PRODUCER)}"
    )
    # Only an owner resizes: no handle is drawn there.
    expect(page.locator(f'[id="{PRODUCER}resizer"]')).to_have_count(0)
