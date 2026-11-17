"""Playwright E2E: Tab onto a node off the canvas brings it into sight and
leaves the canvas whole.

React Flow draws the canvas inside its own element, ``.react-flow``, whose
overflow is hidden, and pans by its viewport's transform. The browser still
scrolls that element to show what the keyboard focuses: a node past the
canvas's right edge that Tab reaches, a field in one. React Flow 11, which
Curio uses, never scrolls it back. From then on, until a reload, the dot grid,
the pane and the zoom buttons sat that far off the window, so the strip left
there neither panned nor zoomed, and every fit, the canvas's own Fit view among
them, drew each node that far off where it put it. #1533's test met it through
Playwright's scroll into view before a click. And the browser cannot scroll the
element to a negative offset, so a node left of the view or above it stayed
out of sight when Tab reached it.

The canvas now turns such a scroll into the same pan and puts its element back
at 0,0, and pans a node the keyboard reaches into the part of the canvas the
rail, the bar and the dataflow's title leave in sight (``useFlowInSight``).
Here the near node is framed, and the node Tab reaches, first in the tab order,
sits past the canvas's right edge, wholly left of the view, or above it with
its header off the window. A person clicks an empty spot of the canvas and
presses Tab, which gives that node the focus. The test checks that React
Flow's element reads 0,0, that the node is in sight, and that Fit view then
draws every node exactly where its viewport puts it.

Python nodes only, so it runs on any runner.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_canvas_wrapper_scroll_e2e.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
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

TARGET, NEAR = "scroll-target", "scroll-near"

#: Where the node Tab reaches sits, from the near node at 0,0, once the near
#: node is framed: past the canvas's right edge, wholly left of the view, or
#: just above the near node, its header off the window and its body under the
#: bar and the title.
PLACES = {"right": (2400, 0), "left": (-2400, 0), "above": (0, -380)}

#: How long the canvas may take to put its element back: the browser fires the
#: scroll only when it draws its next frame, which a loaded runner can hold
#: back for seconds.
PUT_BACK_TIMEOUT_MS = 15_000

#: How far, in pixels, a node may be drawn from where the viewport puts it:
#: sub-pixel rounding, nothing a person can see.
ROUNDING_PX = 0.5


def _node(node_id: str, x: int, y: int) -> dict:
    return {
        "id": node_id, "type": "curio.builtin/python-computation", "x": x, "y": y,
        "content": "return 1", "in": "DEFAULT", "out": "DEFAULT", "goal": "",
        "metadata": {"keywords": []},
    }


def _spec(place: str) -> dict:
    """The node Tab reaches first, so it comes first in the tab order, then the near one."""
    x, y = PLACES[place]
    return {
        "dataflow": {
            "name": "Wrapper scroll", "task": "", "timestamp": 1789193389280,
            "provenance_id": "Wrapper scroll",
            "nodes": [_node(TARGET, x, y), _node(NEAR, 0, 0)],
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

_IN_WINDOW_JS = """(id) => {
    const r = document.querySelector(`.react-flow__node[data-id="${id}"]`).getBoundingClientRect();
    return r.left >= 0 && r.top >= 0 && r.right <= window.innerWidth && r.bottom <= window.innerHeight;
}"""

# The part of the canvas in sight: right of the rail, below the bar, the
# dataflow's title and its chips, as the canvas's fit measures it.
_SIGHT_JS = """() => {
    const pane = document.querySelector('.react-flow').getBoundingClientRect();
    const dock = document.getElementById('tools-palette-dock');
    let top = pane.top;
    const overlays = '[data-curio-menu-bar], [data-curio-canvas-title], '
        + '[data-curio-canvas-title] [data-curio-category-chips]';
    for (const el of document.querySelectorAll(overlays)) {
        top = Math.max(top, el.getBoundingClientRect().bottom);
    }
    return {
        left: Math.max(pane.left, dock ? dock.getBoundingClientRect().right : pane.left),
        top, right: pane.right, bottom: pane.bottom,
    };
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


def _in_sight(box: dict, sight: dict) -> bool:
    return (
        box["left"] >= sight["left"] - ROUNDING_PX and box["top"] >= sight["top"] - ROUNDING_PX
        and box["right"] <= sight["right"] + ROUNDING_PX and box["bottom"] <= sight["bottom"] + ROUNDING_PX
    )


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


@pytest.mark.parametrize("place", list(PLACES))
def test_tab_onto_a_node_off_the_canvas_brings_it_into_sight_and_keeps_the_canvas_whole(
    app_frontend: "FrontendPage", current_server: str, page, place: str,
):
    require_project_page()
    require_user_auth()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Wrapper Scroll",
        username=f"canvas_wrapper_scroll_{place}_e2e",
        project_name="Wrapper scroll",
        project_spec=_spec(place),
    )
    for node_id in (TARGET, NEAR):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    require_owner_view(page)
    # The load's own fit frames both nodes, and fits again 75 ms later. Let it
    # finish first, or it would reframe the canvas after the near node is
    # framed (as test_frame_nodes_e2e.py's _open_dataflow does).
    page.wait_for_function(_IN_WINDOW_JS, arg=TARGET, polling=100, timeout=30000)
    page.wait_for_timeout(1000)

    # The near node framed at 100%: the other one is then out of sight.
    frame_nodes(page, [NEAR])
    sight = page.evaluate(_SIGHT_JS)
    before = page.evaluate(_BOX_JS, TARGET)
    assert not _in_sight(before, sight), (
        f"{TARGET} is in sight before the Tab, so this test proves nothing: {before}, the sight {sight}"
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
    assert focused is not None and focused["node"] == TARGET and focused["isTheNode"], (
        f"Tab from an empty spot of the canvas gave the focus to {focused}, not to {TARGET}'s node, "
        "so this test proves nothing"
    )

    # React Flow's element is back at 0,0, and the node is in sight.
    try:
        page.wait_for_function(_UNSCROLLED_JS, polling=100, timeout=PUT_BACK_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        canvas = page.evaluate(_CANVAS_JS)
        placed = _off(page.evaluate(_PLACED_JS, [TARGET, NEAR]))
        raise AssertionError(
            f"after Tab gave the focus to {TARGET}'s node ({place}), React Flow's element stayed "
            f"scrolled {canvas['scrolled']} for {PUT_BACK_TIMEOUT_MS} ms: its pane, its dot grid and "
            f"its buttons are drawn from {canvas['pane']} where the canvas starts at "
            f"{canvas['canvas']}, and the nodes are drawn this far off where the viewport puts them, "
            f"across and down: {placed}"
        ) from None
    shown = page.evaluate(_BOX_JS, TARGET)
    assert _in_sight(shown, sight), (
        f"{TARGET}'s node ({place}) has the focus but is not in sight: it is drawn at {shown}, "
        f"from {before} before the Tab, and the sight is {sight}"
    )
    drawn = _off(page.evaluate(_PLACED_JS, [TARGET, NEAR]))
    assert _where_put(drawn), (
        f"after the Tab, the nodes are drawn this far off where the viewport puts them, across and "
        f"down: {drawn}"
    )

    # Fit view, pressed with the mouse, draws every node where its viewport puts it.
    _press(page, _FIT_VIEW, "Fit view")
    settled_viewport(page)
    fitted = _off(page.evaluate(_PLACED_JS, [TARGET, NEAR]))
    canvas = page.evaluate(_CANVAS_JS)
    assert _where_put(fitted) and canvas["scrolled"] == {"left": 0, "top": 0}, (
        f"after Fit view, React Flow's element is scrolled {canvas['scrolled']} and the nodes are "
        f"drawn this far off where the viewport puts them, across and down: {fitted}"
    )
