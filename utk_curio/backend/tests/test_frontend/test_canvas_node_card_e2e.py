"""Playwright E2E: a canvas node is drawn as a notebook cell is.

A node on the canvas is a card: Play first in its header, then its title, its
pills and its run status, then its tools (the editor's tabs, Save output, info,
pin, comments, delete and minimize), which show only while the pointer is over
the node or the node is selected. There is no row under the body: the body
reaches the node's bottom edge. The canvas keeps what a cell lacks: the node
still resizes and still minimizes.

What each test pins:

* Play, the title and the status are in the header, in that order, with the
  tools after them; nothing runs under the body, which fills the node;
* the tools are out of sight (opacity 0) until the pointer is over the node or
  the node is selected;
* the Code pill, now in the header, still switches the node's tabs;
* the resize handle still resizes the node and saves its size, and Minimize
  (among the tools) still folds the node into its chip, which a click opens
  again at the same size.

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

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .utils import (
    activate_header_icon,
    assert_vega_canvas_rendered,
    dismiss_toasts,
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
    const del = document.querySelector(`[id="${id}resizable"] [title="Delete node"]`);
    const tools = del && del.closest('.curio-node-tools');
    return tools ? Number(getComputedStyle(tools).opacity) : null;
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


def _stored_size(page, node_id: str) -> list:
    return page.evaluate(
        "(id) => { const d = window.__curio_reactFlow.getNodes().find((n) => n.id === id).data;"
        " return [d.nodeWidth, d.nodeHeight]; }",
        node_id,
    )


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


def test_the_code_pill_in_the_header_still_switches_tabs(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, prefix="card_tabs")
    _wait_for_header(page, PRODUCER)

    header = _header(page, PRODUCER)
    code_pill = header.locator('.nav-link[data-rr-ui-event-key="code"]')
    provenance_pill = header.locator('.nav-link[data-rr-ui-event-key="provenance"]')
    expect(code_pill).to_have_count(1)
    expect(provenance_pill).to_have_count(1)
    node = node_locator(page, PRODUCER)
    editor = node.locator(".monaco-editor").first
    expect(editor).to_be_visible(timeout=30000)

    provenance_pill.click()
    expect(provenance_pill).to_have_class(ACTIVE)
    expect(code_pill).not_to_have_class(ACTIVE)
    expect(editor).to_be_hidden()

    code_pill.click()
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
    minimize = _header(page, PRODUCER).locator('.curio-node-tools [title="Minimize"]')
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
