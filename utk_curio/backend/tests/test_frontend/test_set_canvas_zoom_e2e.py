"""Playwright E2E: ``set_canvas_zoom`` returns once the canvas shows the zoom.

A test that drops at a point of the window zooms the canvas out first with
``set_canvas_zoom`` (``utils/canvas_authoring.py``), then checks or uses that
point. React Flow's ``setViewport`` moves the view through a d3 transition even
with no duration, and the transition only advances on animation frames, so the
zoom lands a frame or two after the call. When frames come late, a point read
right after the call is read on the old view: the saved-output test in
``test_drawer_mouse_drags_e2e.py`` found its drop point on the producer's code
editor (``div.view-line``), and its failure screenshot showed the zoom applied.

This test holds the page's animation frames back while it zooms, and the page
lets them go a few seconds later, as a page that draws no frame for that long
does. Right after ``set_canvas_zoom`` returns, React Flow and the page must
both show the zoom, and a point that was on the node before must be empty
canvas. An init script, installed before the app loads, defers every
``requestAnimationFrame`` callback while it is switched on, so d3's timers,
which take that function when the app loads, wait as they do on a runner that
draws no frame.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_set_canvas_zoom_e2e.py -v
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from .utils import (
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    set_canvas_zoom,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

NODE = "zoomed"
#: Where the node sits on the canvas: off the window until the load's fit
#: frames it, and below the window at ZOOM with the view at the origin.
AT = (2400, 1600)
ZOOM = 0.5
#: How long the page holds animation frames back once the zoom is asked for.
HOLD_MS = 4000

# Before the app's own scripts, so what takes requestAnimationFrame when the
# app loads (d3's timers, which move React Flow's viewport) goes through it.
# Switched on, it keeps every callback until it is switched off, as a page that
# draws no frame does; switched off, it hands them to the next frame.
_HOLD_FRAMES_JS = """(() => {
    const request = window.requestAnimationFrame.bind(window);
    const cancel = window.cancelAnimationFrame.bind(window);
    let held = null;
    let nextId = -1;
    window.requestAnimationFrame = (callback) => {
        if (!held) return request(callback);
        const id = nextId--;
        held.set(id, callback);
        return id;
    };
    window.cancelAnimationFrame = (id) => {
        if (held && held.delete(id)) return;
        cancel(id);
    };
    window.__curioTestHoldFrames = (on) => {
        if (on) {
            held = held || new Map();
            return;
        }
        const deferred = held ? [...held.values()] : [];
        held = null;
        deferred.forEach((callback) => request(callback));
    };
})();"""

# A frame asked for now: whether it ran tells whether frames are held.
_ASK_FOR_A_FRAME_JS = """() => {
    window.__curioTestFrameRan = false;
    window.requestAnimationFrame(() => { window.__curioTestFrameRan = true; });
}"""

_NODE_IN_WINDOW_JS = """(id) => {
    const el = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.left >= 0 && r.top >= 0 && r.right <= window.innerWidth && r.bottom <= window.innerHeight;
}"""

_NODE_CENTER_JS = """(id) => {
    const r = document.querySelector(`.react-flow__node[data-id="${id}"]`).getBoundingClientRect();
    return [r.left + r.width / 2, r.top + r.height / 2];
}"""

# What a pointer at a client point reaches (the node, or empty canvas as
# test_drawer_mouse_drags_e2e.py judges it), and what the canvas shows: React
# Flow's viewport, and the transform the page draws for it.
_VIEW_AND_POINT_JS = """([x, y, id]) => {
    const hit = document.elementFromPoint(x, y);
    const label = hit && hit.getAttribute("aria-label");
    const cls = hit && typeof hit.className === "string" ? hit.className.split(" ")[0] : "";
    const flow = window.__curio_reactFlow;
    const viewport = document.querySelector(".curio-canvas-drop-target .react-flow__viewport");
    const drawn = viewport && new DOMMatrixReadOnly(getComputedStyle(viewport).transform);
    return {
        onNode: !!hit && !!hit.closest(`.react-flow__node[data-id="${id}"]`),
        onCanvas: !!hit && !!hit.closest(".curio-canvas-drop-target") && !hit.closest(".react-flow__node"),
        hit: hit ? hit.tagName.toLowerCase() + (label ? `[aria-label="${label}"]` : cls ? `.${cls}` : "") : "nothing",
        viewport: flow ? flow.getViewport() : null,
        drawn: drawn ? { x: drawn.e, y: drawn.f, zoom: drawn.a } : null,
    };
}"""


def _rounded(view: dict | None) -> dict | None:
    return {key: round(value, 6) for key, value in view.items()} if view else view


def test_set_canvas_zoom_returns_once_the_canvas_shows_the_zoom(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.context.add_init_script(_HOLD_FRAMES_JS)
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Zoom User",
        username=f"zoom_{uuid.uuid4().hex[:10]}",
        project_name="Canvas zoom",
        project_spec={"dataflow": {
            "name": "Canvas zoom", "task": "", "edges": [], "nodes": [{
                "id": NODE, "type": "curio.builtin/computation-analysis", "x": AT[0], "y": AT[1],
                "content": "return 1\n", "in": "DEFAULT", "out": "DEFAULT", "goal": "",
                "metadata": {"keywords": []},
            }],
        }},
    )
    require_owner_view(page)
    node_locator(page, NODE).wait_for(state="visible", timeout=45000)
    # The load's own fit frames the node, and fits again 75 ms later: let both
    # land before anything is measured.
    page.wait_for_function(_NODE_IN_WINDOW_JS, arg=NODE, polling=100, timeout=30000)
    page.wait_for_timeout(1000)
    assert page.evaluate("() => typeof window.__curioTestHoldFrames === 'function'"), (
        "the init script that holds animation frames back is not in the page"
    )

    # A point on the node as the load framed it, which the zoom leaves on
    # empty canvas: at ZOOM the node lies below the window.
    probe = page.evaluate(_NODE_CENTER_JS, NODE)
    before = page.evaluate(_VIEW_AND_POINT_JS, [*probe, NODE])
    assert before["onNode"], f"{probe} is not on the node before the zoom but on {before['hit']}"

    page.evaluate("() => window.__curioTestHoldFrames(true)")
    try:
        page.evaluate(_ASK_FOR_A_FRAME_JS)
        page.wait_for_timeout(500)
        assert not page.evaluate("() => window.__curioTestFrameRan"), (
            "an animation frame ran while frames were held back, so this test proves nothing"
        )
        # Python waits inside set_canvas_zoom, so the page lets the frames go.
        page.evaluate(
            "(ms) => { setTimeout(() => window.__curioTestHoldFrames(false), ms); }", HOLD_MS
        )
        set_canvas_zoom(page, ZOOM)
        after = page.evaluate(_VIEW_AND_POINT_JS, [*probe, NODE])
    finally:
        page.evaluate("() => window.__curioTestHoldFrames(false)")

    target = {"x": 0, "y": 0, "zoom": ZOOM}
    assert (_rounded(after["viewport"]), _rounded(after["drawn"]), after["onCanvas"]) == (
        target, target, True,
    ), (
        f"set_canvas_zoom({ZOOM}) returned with React Flow at {after['viewport']} and the page "
        f"drawing {after['drawn']}, so {probe} is not on empty canvas but on {after['hit']}"
    )
    # Frames come again once released: the hold was real.
    page.wait_for_function("() => window.__curioTestFrameRan === true", polling=100, timeout=10000)
