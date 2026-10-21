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

The wait reads the viewport in the page, so a long task on the page's main
thread leaves it no time to read. In #932 (runs 38663620211 and 38762616708)
decoding SCOUT's 2592x2064 flood grid did that: the wait gave up after its
10 s with the fit, React Flow's viewport and the drawn transform all equal,
the page having made fewer than the four reads a pass needs. One test keeps
the page busy for 11 s in the fit's first call and checks that ``frame_nodes``
still frames the node; a guard moves the viewport every 50 ms and checks that
the wait still fails, in well under a minute.

A page can also open with no frame at all. CI's Chrome draws its first frame
only once its GPU process is up, and a freshly launched one on a GPU that four
test jobs shared took more than 10 s (#1012: main run 39272081028 and run
39035184553). React Flow measures a node it has just drawn only in its
ResizeObserver's callback, which the browser runs only when it draws a frame,
so until then no node is measured and no fit can be set: the wait gave up with
no fit set after 99 re-fits. The test above holds frames back only once the
nodes are measured. One test holds animation frames and ResizeObserver
callbacks back from the page's first script, and checks that the viewport wait
frames every node before the first frame.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_frame_nodes_e2e.py -v
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .utils import (
    _wait_for_reactflow_ready,
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

#: How long the fit's first call keeps the page busy: one long task, longer
#: than the 10 s the viewport wait allowed before #932.
BUSY_MS = 11_000

#: The longest a viewport wait may take to give up on a viewport that never
#: holds. It used to give up after 10 s.
GIVE_UP_WITHIN_S = 60

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

# Before the app's own scripts, and on from the page's first script until the
# test lets frames come: keeps what the browser runs only when it draws a
# frame, animation frame callbacks and ResizeObserver callbacks, as on a page
# whose first frame has not come yet. React Flow measures a node it has just
# drawn only in its ResizeObserver's callback, and shows it once measured.
_NO_FRAME_YET_JS = """(() => {
    const request = window.requestAnimationFrame.bind(window);
    const cancel = window.cancelAnimationFrame.bind(window);
    const Observer = window.ResizeObserver;
    let held = new Map();
    let nextId = -1;
    window.requestAnimationFrame = (callback) => {
        if (!held) return request(callback);
        const id = nextId--;
        held.set(id, () => request(callback));
        return id;
    };
    window.cancelAnimationFrame = (id) => {
        if (held && held.delete(id)) return;
        cancel(id);
    };
    window.ResizeObserver = class extends Observer {
        constructor(callback) {
            super((entries, observer) => {
                if (!held) {
                    callback(entries, observer);
                    return;
                }
                held.set(nextId--, () => callback(entries, observer));
            });
        }
    };
    window.__curioTestLetFramesCome = () => {
        const deferred = held ? [...held.values()] : [];
        held = null;
        deferred.forEach((run) => run());
    };
})();"""

# Every node on the canvas with its package's body, not the placeholder drawn
# until the package's descriptor arrives (#683), whose size a fit would frame,
# nor the card of a type its package no longer has (#1048).
_NODES_DRAWN_JS = """(count) => {
    const nodes = [...document.querySelectorAll('.react-flow__node')];
    return nodes.length === count && nodes.every((node) =>
        node.querySelector('[data-curio-node-status]') !== null
        && node.querySelector(
            '[data-testid="unresolved-node"], [data-testid="removed-node-type"]') === null);
}"""

# The nodes React Flow has measured, or null before the canvas is up.
_MEASURED_JS = """() => window.__curio_reactFlow
    ? window.__curio_reactFlow.getNodes()
        .filter((node) => node.width > 0 && node.height > 0)
        .map((node) => node.id)
    : null"""

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

# The fit the viewport wait calls, wrapped so its first call keeps the page's
# main thread busy for *ms* before it fits, as one long task (a raster decode)
# does: the page reads nothing until it ends. It records how long it was busy.
_BUSY_FIRST_FIT_JS = """(ms) => {
    const fit = window.__curio_fitViewWithMenuOffset;
    window.__curioTestFit = fit;
    window.__curioTestBusyMs = null;
    window.__curio_fitViewWithMenuOffset = (options) => {
        if (window.__curioTestBusyMs === null) {
            const start = performance.now();
            while (performance.now() - start < ms) { /* one long task */ }
            window.__curioTestBusyMs = performance.now() - start;
        }
        return fit(options);
    };
}"""

_RESTORE_FIT_JS = """() => {
    if (window.__curioTestFit) window.__curio_fitViewWithMenuOffset = window.__curioTestFit;
}"""

# Moves the viewport every *ms*, framing *ids* in turn through the fit hook,
# which sets the viewport at once, with no animation frame. Counts its moves.
_KEEP_MOVING_JS = """({ ids, ms }) => {
    const fit = window.__curio_fitViewWithMenuOffset;
    window.__curioTestMoves = 0;
    window.__curioTestMover = setInterval(() => {
        const id = ids[window.__curioTestMoves % ids.length];
        fit({ nodes: [{ id }], padding: 0.2, duration: 0, includeHiddenNodes: true, maxZoom: 1 });
        window.__curioTestMoves += 1;
    }, ms);
}"""

_STOP_MOVING_JS = """() => {
    clearInterval(window.__curioTestMover);
    return window.__curioTestMoves;
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
                node(MIDDLE, "curio.builtin/computation-analysis", 2400, "return input_0\n"),
                node(FAR, "curio.builtin/computation-analysis", 4800, "return input_0\n"),
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


def _open_dataflow(page, frontend_url: str, backend_url: str, *, username: str) -> None:
    """Open the three-node dataflow and let the load's own fit finish."""
    spec = _spec()
    stub_login_and_enter_workflow(
        page,
        frontend_url=frontend_url,
        backend_url=backend_url,
        name="Frame Nodes",
        username=username,
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


def test_frame_nodes_brings_a_node_into_view_while_the_page_draws_no_frame(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.context.add_init_script(_HOLD_FRAMES_JS)
    _open_dataflow(page, app_frontend.base_url, current_server, username="frame_nodes_e2e")
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


def test_the_viewport_wait_frames_the_nodes_before_the_page_draws_its_first_frame(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.context.add_init_script(_NO_FRAME_YET_JS)
    spec = _spec()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Frame Nodes",
        username="frame_nodes_first_frame_e2e",
        project_name="Frame nodes",
        project_spec=spec,
    )
    require_owner_view(page)
    assert page.evaluate("() => typeof window.__curioTestLetFramesCome === 'function'"), (
        "the init script that holds frames back is not in the page"
    )
    node_ids = [node["id"] for node in spec["dataflow"]["nodes"]]
    try:
        # React Flow keeps a node it has not measured hidden, so wait for the
        # nodes in the page, not for them to be visible.
        page.wait_for_function(_NODES_DRAWN_JS, arg=len(node_ids), polling=100, timeout=45000)
        page.evaluate(_ASK_FOR_A_FRAME_JS)
        page.wait_for_timeout(500)
        assert not page.evaluate("() => window.__curioTestFrameRan"), (
            "an animation frame ran before frames were let come, so this test proves nothing"
        )
        measured = page.evaluate(_MEASURED_JS)
        assert measured == [], (
            f"React Flow had measured {measured} although the page had drawn no frame, so this "
            "test proves nothing"
        )

        started = time.monotonic()
        try:
            _wait_for_reactflow_ready(page)
        except AssertionError as error:
            raise AssertionError(
                f"the viewport wait gave up after {time.monotonic() - started:.1f} s on a page that "
                f"had drawn no frame yet, so React Flow had measured none of its nodes: {error}"
            ) from None
        boxes = {node_id: _box(page, node_id) for node_id in node_ids}
        outside = {node_id: box for node_id, box in boxes.items() if not _in_window(box)}
        assert not outside, f"the viewport wait returned with {outside} outside the window"
        assert not page.evaluate("() => window.__curioTestFrameRan"), (
            "an animation frame ran during the wait, so it did not frame the nodes without one"
        )
    finally:
        page.evaluate("() => window.__curioTestLetFramesCome()")
    # Frames come once let: the hold was real.
    page.wait_for_function("() => window.__curioTestFrameRan === true", polling=100, timeout=10000)


def test_frame_nodes_frames_a_node_after_a_long_task_keeps_the_page_from_reading(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    _open_dataflow(page, app_frontend.base_url, current_server, username="frame_nodes_busy_e2e")
    frame_nodes(page, [NEAR])
    box = _box(page, FAR)
    assert not _in_window(box), f"{FAR} is already in the window before it is framed: {box}"

    # Nothing moves the viewport here: only the first fit is slow to return.
    page.evaluate(_BUSY_FIRST_FIT_JS, BUSY_MS)
    started = time.monotonic()
    try:
        try:
            frame_nodes(page, [FAR])
        except AssertionError as error:
            raise AssertionError(
                f"frame_nodes gave up after {time.monotonic() - started:.1f} s, although nothing "
                "moved the viewport and the page was busy only in the first fit, for "
                f"{page.evaluate('() => window.__curioTestBusyMs')} ms: {error}"
            ) from None
        took = time.monotonic() - started
    finally:
        page.evaluate(_RESTORE_FIT_JS)
    busy_ms = page.evaluate("() => window.__curioTestBusyMs")
    assert busy_ms is not None and busy_ms > 10_000, (
        f"the first fit kept the page busy for {busy_ms} ms, no longer than the 10 s the "
        "viewport wait used to allow, so this test proves nothing"
    )
    box = _box(page, FAR)
    assert _in_window(box), (
        f"frame_nodes returned after {took:.1f} s with {FAR} at {box}, outside the window"
    )


def test_frame_nodes_still_fails_while_the_viewport_keeps_moving(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    _open_dataflow(page, app_frontend.base_url, current_server, username="frame_nodes_moving_e2e")

    page.evaluate(_KEEP_MOVING_JS, {"ids": [NEAR, MIDDLE], "ms": 50})
    started = time.monotonic()
    try:
        with pytest.raises(AssertionError, match="did not hold where the fit set it") as failure:
            frame_nodes(page, [FAR])
    finally:
        moves = page.evaluate(_STOP_MOVING_JS)
    took = time.monotonic() - started
    assert moves >= 20, (
        f"the viewport moved only {moves} times in the {took:.1f} s frame_nodes waited, so this "
        "test proves nothing"
    )
    assert took < GIVE_UP_WITHIN_S, (
        f"frame_nodes took {took:.1f} s to give up on a viewport that never held, not under "
        f"{GIVE_UP_WITHIN_S} s: {failure.value}"
    )
