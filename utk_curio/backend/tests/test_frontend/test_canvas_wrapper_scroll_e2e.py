"""Playwright E2E: Tab onto a node past the canvas's edge leaves the canvas whole.

React Flow draws the canvas inside its own element, ``.react-flow``, whose
overflow is hidden, and pans by its viewport's transform. The browser still
scrolls that element to show what the keyboard focuses: a node past the
canvas's right edge that Tab reaches, a field in one. React Flow 11, which
Curio uses, never scrolls it back. From then on, until a reload, the dot grid,
the pane and the zoom buttons sat that far off the window, so the strip left
there neither panned nor zoomed, and every fit, the canvas's own Fit view among
them, drew each node that far off where it put it. #1533's test met it through
Playwright's scroll into view before a click.

The canvas now turns that scroll into the same pan and puts its element back
at 0,0 (``useFlowScrollAsPan``). Here the near node is framed and the far one,
first in the tab order, sits past the canvas's right edge. A person clicks an
empty spot of the canvas and presses Tab, which gives the far node the focus.
The test checks that React Flow's element reads 0,0 again with the far node in
the window, where the browser brought it, and that Fit view then draws every
node exactly where its viewport puts it.

Python nodes only, so it runs on any runner.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_canvas_wrapper_scroll_e2e.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .utils import (
    assert_in_view,
    frame_nodes,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    settled_viewport,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

FAR, NEAR = "scroll-far", "scroll-near"

#: How long the canvas may take to put its element back: the browser fires the
#: scroll only when it draws its next frame, which a loaded runner can hold
#: back for seconds.
PUT_BACK_TIMEOUT_MS = 15_000

#: How far, in pixels, a node may be drawn from where the viewport puts it:
#: sub-pixel rounding, nothing a person can see.
ROUNDING_PX = 0.5


def _node(node_id: str, x: int) -> dict:
    return {
        "id": node_id, "type": "curio.builtin/python-computation", "x": x, "y": 0,
        "content": "return 1", "in": "DEFAULT", "out": "DEFAULT", "goal": "",
        "metadata": {"keywords": []},
    }


def _spec() -> dict:
    """The far node first, so it comes first in the tab order, then the near one."""
    return {
        "dataflow": {
            "name": "Wrapper scroll", "task": "", "timestamp": 1789193389280,
            "provenance_id": "Wrapper scroll",
            "nodes": [_node(FAR, 2400), _node(NEAR, 0)],
            "edges": [],
        }
    }


# How far React Flow's element is scrolled, and where its pane is drawn.
_CANVAS_JS = """() => {
    const canvas = document.querySelector('.react-flow');
    const pane = canvas.querySelector('.react-flow__pane').getBoundingClientRect();
    const box = canvas.getBoundingClientRect();
    return {
        scrolled: { left: canvas.scrollLeft, top: canvas.scrollTop },
        pane: { left: pane.left, top: pane.top },
        canvas: { left: box.left, top: box.top },
    };
}"""

_UNSCROLLED_JS = """() => {
    const canvas = document.querySelector('.react-flow');
    return canvas.scrollLeft === 0 && canvas.scrollTop === 0;
}"""

# Each node's top left corner as it is drawn, and where React Flow's viewport
# puts it: the corner of React Flow's element, plus the viewport's offset, plus
# the node's place at the viewport's zoom.
_PLACED_JS = """(ids) => {
    const flow = window.__curio_reactFlow;
    const { x, y, zoom } = flow.getViewport();
    const canvas = document.querySelector('.react-flow').getBoundingClientRect();
    return Object.fromEntries(ids.map((id) => {
        const node = flow.getNode(id);
        const at = node.positionAbsolute || node.position;
        const drawn = document.querySelector(`.react-flow__node[data-id="${id}"]`).getBoundingClientRect();
        return [id, {
            drawn: [drawn.left, drawn.top],
            put: [canvas.left + x + at.x * zoom, canvas.top + y + at.y * zoom],
        }];
    }));
}"""

_BOX_JS = """(id) => {
    const r = document.querySelector(`.react-flow__node[data-id="${id}"]`).getBoundingClientRect();
    return { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
}"""

# A spot on an empty part of the canvas, right of the rail and left of the near
# node: the first point there where the pane itself is the element.
_EMPTY_SPOT_JS = """() => {
    const canvas = document.querySelector('.react-flow').getBoundingClientRect();
    const dock = document.getElementById('tools-palette-dock');
    const left = Math.max(canvas.left, dock ? dock.getBoundingClientRect().right : canvas.left);
    for (let y = canvas.top + canvas.height / 2; y < canvas.bottom - 80; y += 40) {
        for (let x = left + 30; x < canvas.right - 40; x += 40) {
            const el = document.elementFromPoint(x, y);
            if (el && el.classList.contains('react-flow__pane')) return [x, y];
        }
    }
    return null;
}"""

# What has the keyboard's focus: the node it is in, and whether it is the node.
_FOCUSED_JS = """() => {
    const el = document.activeElement;
    if (!el || el === document.body) return null;
    const node = el.closest('.react-flow__node');
    return {
        node: node ? node.getAttribute('data-id') : null,
        isTheNode: node === el,
        element: `<${el.tagName.toLowerCase()} class="${el.getAttribute('class') || ''}">`,
    };
}"""

# The element a press at a point lands on, or null when it is the one given.
_COVERED_JS = """([selector, x, y]) => {
    const target = document.querySelector(selector);
    const top = document.elementFromPoint(x, y);
    if (top && (top === target || target.contains(top))) return null;
    return top ? `<${top.tagName.toLowerCase()} class="${top.getAttribute('class') || ''}">` : 'nothing';
}"""

_FIT_VIEW = ".react-flow__controls-fitview"


def _off(placed: dict) -> dict:
    """How far each node is drawn from where the viewport puts it, across and down."""
    return {
        node_id: (round(at["drawn"][0] - at["put"][0], 2), round(at["drawn"][1] - at["put"][1], 2))
        for node_id, at in placed.items()
    }


def _where_put(off: dict) -> bool:
    return all(abs(across) <= ROUNDING_PX and abs(down) <= ROUNDING_PX for across, down in off.values())


def _press(page, selector: str, what: str) -> None:
    """Press *selector* with the mouse where it is drawn, as a person does: a
    locator's click would first scroll it into view, which is what this module
    is about."""
    box = page.locator(selector).bounding_box()
    assert box, f"{what} is not on the page"
    x, y = assert_in_view(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, what)
    covered = page.evaluate(_COVERED_JS, [selector, x, y])
    assert covered is None, f"{what} at ({x:.0f}, {y:.0f}) is under {covered}"
    page.mouse.click(x, y)


def test_tab_onto_a_node_past_the_canvas_edge_keeps_the_canvas_where_it_is_drawn(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Wrapper Scroll",
        username="canvas_wrapper_scroll_e2e",
        project_name="Wrapper scroll",
        project_spec=_spec(),
    )
    for node_id in (FAR, NEAR):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    require_owner_view(page)

    # The near node framed at 100%: the far one then sits past the right edge.
    frame_nodes(page, [NEAR])
    width = page.evaluate("() => window.innerWidth")
    far = page.evaluate(_BOX_JS, FAR)
    assert far["left"] >= width, (
        f"{FAR} is not past the canvas's right edge before the Tab, so this test proves nothing: "
        f"{far}, in a {width} px window"
    )
    framed = _off(page.evaluate(_PLACED_JS, [NEAR]))
    assert _where_put(framed), (
        f"before the Tab, {NEAR} is drawn {framed} off where the viewport puts it, so this test "
        "measures nothing"
    )

    # A person: a click on an empty spot of the canvas, then Tab.
    spot = page.evaluate(_EMPTY_SPOT_JS)
    assert spot, "no empty spot of the canvas to click, left of the near node"
    page.mouse.click(*assert_in_view(page, spot[0], spot[1], "the empty spot of the canvas"))
    page.keyboard.press("Tab")
    focused = page.evaluate(_FOCUSED_JS)
    assert focused is not None and focused["node"] == FAR and focused["isTheNode"], (
        f"Tab from an empty spot of the canvas gave the focus to {focused}, not to {FAR}'s node, "
        "so this test proves nothing"
    )

    # React Flow's element is back at 0,0, the far node in the window.
    try:
        page.wait_for_function(_UNSCROLLED_JS, polling=100, timeout=PUT_BACK_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        canvas = page.evaluate(_CANVAS_JS)
        placed = _off(page.evaluate(_PLACED_JS, [FAR, NEAR]))
        raise AssertionError(
            f"after Tab gave the focus to {FAR}'s node past the canvas's right edge, React Flow's "
            f"element stayed scrolled {canvas['scrolled']} for {PUT_BACK_TIMEOUT_MS} ms: its pane, its "
            f"dot grid and its buttons are drawn from {canvas['pane']} where the canvas starts at "
            f"{canvas['canvas']}, and the nodes are drawn this far off where the viewport puts them, "
            f"across and down: {placed}"
        ) from None
    far = page.evaluate(_BOX_JS, FAR)
    assert far["left"] < width and far["right"] > 0, (
        f"{FAR}'s node has the focus but is not in the window: {far}, in a {width} px window"
    )
    shown = _off(page.evaluate(_PLACED_JS, [FAR, NEAR]))
    assert _where_put(shown), (
        f"after the Tab, the nodes are drawn this far off where the viewport puts them, across and "
        f"down: {shown}"
    )

    # Fit view, pressed with the mouse, draws every node where its viewport puts it.
    _press(page, _FIT_VIEW, "Fit view")
    settled_viewport(page)
    fitted = _off(page.evaluate(_PLACED_JS, [FAR, NEAR]))
    canvas = page.evaluate(_CANVAS_JS)
    assert _where_put(fitted) and canvas["scrolled"] == {"left": 0, "top": 0}, (
        f"after Fit view, React Flow's element is scrolled {canvas['scrolled']} and the nodes are "
        f"drawn this far off where the viewport puts them, across and down: {fitted}"
    )
