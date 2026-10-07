"""Playwright E2E: framing nodes needs no animation frame.

``frame_nodes`` frames the nodes a test is about to point at or capture,
through ``_wait_for_reactflow_ready`` (``utils/capture_waits.py``). On a loaded
GPU runner Chromium can go tens of seconds without drawing a frame. In the runs
where that wait ran out of its 10 s (main run 37646800743, and 37647204443,
37650699374 and 37651316760), Playwright's own checks for a stable element
waited 27 and 30 s for one in the same jobs. The wait needed about five frames:
its fit went through React Flow's ``setViewport``, whose d3 transition lands on
a later animation frame even with no duration, and it then read the viewport
once a frame until three reads agreed.

The test holds the page's animation frames back while it frames a node far off
the window, and checks that ``frame_nodes`` returns with that node in the
window. An init script, installed before the app loads, defers every
``requestAnimationFrame`` callback while it is switched on, so d3's timers,
which take that function when the app loads, wait as they do on a runner that
draws no frame.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_frame_nodes_e2e.py -v
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .utils import (
    frame_nodes,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

NEAR = "frame-near"
MIDDLE = "frame-middle"
FAR = "frame-far"

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

_NODE_BOX_JS = """(id) => {
    const r = document.querySelector(`.react-flow__node[data-id="${id}"]`).getBoundingClientRect();
    return {
        left: r.left, top: r.top, right: r.right, bottom: r.bottom,
        width: window.innerWidth, height: window.innerHeight,
    };
}"""

_IN_WINDOW_JS = """(id) => {
    const r = document.querySelector(`.react-flow__node[data-id="${id}"]`).getBoundingClientRect();
    return r.left >= 0 && r.top >= 0 && r.right <= window.innerWidth && r.bottom <= window.innerHeight;
}"""


def _spec() -> dict:
    node = lambda node_id, node_type, x, content: {  # noqa: E731
        "id": node_id, "type": node_type, "x": x, "y": 0, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }
    return {
        "dataflow": {
            "name": "Frame nodes",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Frame nodes",
            "nodes": [
                node(NEAR, "curio.builtin/data-loading", 0, "return 1\n"),
                node(MIDDLE, "curio.builtin/computation-analysis", 2400, "return arg\n"),
                node(FAR, "curio.builtin/computation-analysis", 4800, "return arg\n"),
            ],
            "edges": [],
        }
    }


def _box(page, node_id: str) -> dict:
    return page.evaluate(_NODE_BOX_JS, node_id)


def _in_window(box: dict) -> bool:
    return (
        box["left"] >= 0 and box["top"] >= 0
        and box["right"] <= box["width"] and box["bottom"] <= box["height"]
    )


def test_frame_nodes_brings_a_node_into_view_while_the_page_draws_no_frame(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.context.add_init_script(_HOLD_FRAMES_JS)
    spec = _spec()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Frame Nodes",
        username="frame_nodes_e2e",
        project_name="Frame nodes",
        project_spec=spec,
    )
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    require_owner_view(page)
    # The load's own fit frames every node, and fits again 75 ms later. Let it
    # finish first, or it would reframe the canvas after the near node is framed.
    page.wait_for_function(_IN_WINDOW_JS, arg=FAR, polling=100, timeout=30000)
    page.wait_for_timeout(1000)
    assert page.evaluate("() => typeof window.__curioTestHoldFrames === 'function'"), (
        "the init script that holds animation frames back is not in the page"
    )

    # Frames drawn as usual: the near node framed, the far one off the window.
    frame_nodes(page, [NEAR])
    box = _box(page, FAR)
    assert not _in_window(box), f"{FAR} is already in the window before it is framed: {box}"

    page.evaluate("() => window.__curioTestHoldFrames(true)")
    try:
        page.evaluate(_ASK_FOR_A_FRAME_JS)
        page.wait_for_timeout(500)
        assert not page.evaluate("() => window.__curioTestFrameRan"), (
            "an animation frame ran while frames were held back, so this test proves nothing"
        )
        started = time.monotonic()
        try:
            frame_nodes(page, [FAR])
        except PlaywrightTimeoutError as error:
            raise AssertionError(
                f"frame_nodes did not finish in {time.monotonic() - started:.1f} s while the page "
                f"drew no animation frame: {error}"
            ) from None
        took = time.monotonic() - started
        box = _box(page, FAR)
        assert _in_window(box), (
            f"frame_nodes returned after {took:.1f} s with {FAR} at {box}, outside the window: "
            "the fit it asked for had not landed, for want of an animation frame"
        )
    finally:
        page.evaluate("() => window.__curioTestHoldFrames(false)")
    # Frames come again once released: the hold was real.
    page.wait_for_function("() => window.__curioTestFrameRan === true", polling=100, timeout=10000)
