"""Playwright E2E: the stacked-views scene frames its narrowed node while the page draws no frame (#1167).

The walkthrough ``multi-view-vega-chart-is-reachable`` runs example 05's stacked
views chart, drags the node's corner from the 1075x1000 box the example gives it
down to 525x350, and frames the node for its captures. Twice on CI (e2e-desktop
(13), runs 40055185466 and 40266610100) it then waited 15 s for React Flow's
store to hold the narrowed size and timed out (``walkthroughs/layout.py``), while
the screenshot taken at the failure showed the node drawn at 525x350.

React Flow measures a node again only in its ResizeObserver callback, which the
browser runs only when it draws a frame, and a browser on a loaded runner can go
tens of seconds without drawing one.

This test plays such a page. An init script, installed before the app loads,
holds the page's ResizeObserver and animation frame callbacks from the press on
the node's corner until the test lets them go. The test runs the scene itself
(``walkthroughs/layout.py``), without its captures, while they are held. Then it
lets them go and checks that the node is framed whole: centred in the canvas,
with the view React Flow holds drawn.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_narrowed_chart_framing_e2e.py -v
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .utils import (
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)
from .walkthroughs import Ctx, SilentNarrator, load_example_spec
from .walkthroughs.layout import (
    MULTI_VIEW_EXAMPLE,
    NARROWED_NODE,
    multi_view_vega_chart_is_reachable,
)
from .walkthroughs.steps import first_node_of_type

if TYPE_CHECKING:
    from .utils import FrontendPage

#: How far, in screen pixels, the framed node's centre may sit from the canvas's.
CENTRE_SLACK_PX = 2

# Before the app's own scripts, so React Flow's ResizeObserver and whatever takes
# requestAnimationFrame go through it. A press on the node's corner handle, seen
# before the handle's own listener, starts the hold: from then on the page runs
# none of the callbacks the browser runs only when it draws a frame, as on a page
# that draws none, until the test calls ``window.__curioTestRelease()``. Then it
# runs them, in the order they came. The browser still delivers its observations;
# only their callbacks wait. The ids of the canvas nodes in the held observations
# are kept, to show that React Flow's own measure of the node was among them.
_HOLD_FROM_THE_CORNER_JS = """((handleId) => {
    const request = window.requestAnimationFrame.bind(window);
    const cancel = window.cancelAnimationFrame.bind(window);
    const Observer = window.ResizeObserver;
    let held = null;
    let nextId = -1;
    window.__curioTestHolds = 0;
    window.__curioTestHeldNodeIds = [];
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
                entries.forEach((entry) => {
                    const id = entry.target.getAttribute && entry.target.getAttribute('data-id');
                    if (id) window.__curioTestHeldNodeIds.push(id);
                });
                held.set(nextId--, () => callback(entries, observer));
            });
        }
    };
    window.__curioTestRelease = () => {
        const deferred = held ? [...held.values()] : [];
        held = null;
        deferred.forEach((run) => run());
    };
    document.addEventListener('mousedown', (event) => {
        const target = event.target instanceof Element ? event.target : null;
        if (held || !target || target.id !== handleId) return;
        held = new Map();
        window.__curioTestHolds += 1;
    }, true);
})"""

# The node's size as React Flow holds it and as the page draws it, and what the
# hold has kept back.
_NODE_STATE_JS = """(id) => {
    const flow = window.__curio_reactFlow;
    const stored = flow ? flow.getNodes().find((n) => n.id === id) : null;
    const box = Array.from(document.querySelectorAll('.react-flow__node'))
        .filter((el) => !el.closest('[data-curio-modal-shell="true"]'))
        .find((el) => el.getAttribute('data-id') === id);
    return {
        stored: stored ? [stored.width ?? null, stored.height ?? null] : null,
        drawn: box ? [box.offsetWidth, box.offsetHeight] : null,
        holds: window.__curioTestHolds,
        heldNodeIds: Array.from(new Set(window.__curioTestHeldNodeIds || [])),
    };
}"""

# Where the canvas shows the node: how far its box's centre sits from the centre
# of the pane React Flow centres on, whether the box is whole on the pane, and the
# view React Flow holds beside the one the page draws.
_FRAMING_JS = """(id) => {
    const flow = window.__curio_reactFlow;
    const box = Array.from(document.querySelectorAll('.react-flow__node'))
        .filter((el) => !el.closest('[data-curio-modal-shell="true"]'))
        .find((el) => el.getAttribute('data-id') === id);
    const wrapper = box ? box.closest('.react-flow') : null;
    const pane = wrapper ? wrapper.querySelector('.react-flow__renderer') : null;
    const viewport = wrapper ? wrapper.querySelector('.react-flow__viewport') : null;
    if (!flow || !box || !pane || !viewport) return null;
    const at = flow.getViewport();
    const drawn = new DOMMatrixReadOnly(getComputedStyle(viewport).transform);
    const rect = box.getBoundingClientRect();
    const sight = pane.getBoundingClientRect();
    return {
        dx: rect.left + rect.width / 2 - (sight.left + sight.width / 2),
        dy: rect.top + rect.height / 2 - (sight.top + sight.height / 2),
        whole: rect.left >= sight.left && rect.top >= sight.top
            && rect.right <= sight.right && rect.bottom <= sight.bottom,
        held: [at.x, at.y, at.zoom],
        drawn: [drawn.e, drawn.f, drawn.a],
        box: [rect.left, rect.top, rect.width, rect.height],
        pane: [sight.left, sight.top, sight.width, sight.height],
    };
}"""

# Whether the node is framed whole: centred on the pane, every edge of it on the
# pane, and the view React Flow holds the one the page draws.
_FRAMED_JS = (
    "([id, slack]) => { const f = (" + _FRAMING_JS + ")(id);"
    " return !!f && Math.abs(f.dx) <= slack && Math.abs(f.dy) <= slack && f.whole"
    " && Math.abs(f.held[0] - f.drawn[0]) < 0.5 && Math.abs(f.held[1] - f.drawn[1]) < 0.5"
    " && Math.abs(f.held[2] - f.drawn[2]) < 1e-4; }"
)


def _hold_script(node_id: str) -> str:
    """The hold, started by a press on *node_id*'s corner handle."""
    return f"{_HOLD_FROM_THE_CORNER_JS}({json.dumps(node_id + 'resizer')});"


def _near(size, want, slack: float = 8) -> bool:
    return bool(size) and all(
        got is not None and abs(got - goal) <= slack for got, goal in zip(size, want)
    )


def test_the_stacked_views_scene_frames_its_narrowed_node_on_a_page_that_draws_no_frame(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()

    node_id = first_node_of_type(MULTI_VIEW_EXAMPLE, "vis-vega", containing="vconcat")
    page.emulate_media(reduced_motion="reduce")
    page.context.add_init_script(_hold_script(node_id))
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Walkthrough",
        username="walk_narrowed_no_frame",
        project_name="A multi-view chart is not cut off",
        project_spec=load_example_spec(MULTI_VIEW_EXAMPLE),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    assert page.evaluate("() => window.__curioTestHolds") == 0, (
        "the init script that holds frame callbacks from the press on the node's "
        "corner is not in the page"
    )
    ctx = Ctx(
        page=page,
        frontend=app_frontend.base_url,
        backend=current_server,
        narrator=SilentNarrator(page),
        recording=False,
    )

    try:
        # The scene itself, its captures left out (``Ctx.snapshot`` does nothing).
        try:
            multi_view_vega_chart_is_reachable(ctx)
        except PlaywrightTimeoutError as err:
            raise AssertionError(
                f"the scene timed out on a page that ran no frame callback since the "
                f"press on the node's corner: {page.evaluate(_NODE_STATE_JS, node_id)}"
            ) from err
        state = page.evaluate(_NODE_STATE_JS, node_id)
        assert state["holds"] == 1, (
            f"the press on the node's corner started {state['holds']} holds, not 1"
        )
        assert node_id in state["heldNodeIds"], (
            f"no ResizeObserver callback for the narrowed node was held, so React "
            f"Flow's measure of it was not kept back and this test proves nothing: {state}"
        )
        assert not _near(state["stored"], NARROWED_NODE), (
            f"React Flow held the node at its narrowed size while the page ran no "
            f"frame callback, so this test proves nothing: {state}"
        )
    finally:
        page.evaluate("() => window.__curioTestRelease && window.__curioTestRelease()")

    # The page runs its frame callbacks again: the view the scene set lands.
    try:
        page.wait_for_function(
            _FRAMED_JS, arg=[node_id, CENTRE_SLACK_PX], polling=100, timeout=15000,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"once the page drew frames again, the scene had not framed the narrowed "
            f"node whole, centred on the canvas: {page.evaluate(_FRAMING_JS, node_id)}"
        ) from None
