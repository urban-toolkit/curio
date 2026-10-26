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
the node's corner until the test lets them go. It does so in two ways
(``OBSERVATIONS``): the browser still delivers its observations and only their
callbacks wait, or the page's ResizeObservers stop observing for the hold, so the
browser delivers none, as on a runner that draws no frame at all. The test runs
the scene itself (``walkthroughs/layout.py``), without its captures, while they
are held. Then it lets them go, running them itself as the frame that ends the
stall would, and checks that the node is framed whole: centred in the canvas,
with the view React Flow holds drawn.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_narrowed_chart_framing_e2e.py -v
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
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

#: What the browser does with the page's ResizeObservers during the hold, by test
#: id: it delivers their observations and only the callbacks wait, or it delivers
#: none at all, as on a page that draws no frame. The second is what a CI runner
#: did once (our #1178's run 40375648529, attempt 1, e2e-desktop (11)).
OBSERVATIONS = {"observations-held": True, "no-observations": False}

# Before the app's own scripts, so React Flow's ResizeObserver and whatever takes
# requestAnimationFrame go through it. A press on the node's corner handle, seen
# before the handle's own listener, starts the hold: from then on the page runs
# none of the callbacks the browser runs only when it draws a frame, as on a page
# that draws none, until the test calls ``window.__curioTestRelease()``. With
# *observing*, the browser still delivers its observations and only their
# callbacks wait; the ids of the canvas nodes in the held observations are kept,
# to show that React Flow's own measure of the node was among them, and so is how
# many observations were held. Without it, every ResizeObserver stops observing
# for the hold, so the browser delivers none, and observes again on the release.
# The release plays the frame that ends the stall: the held animation frame
# callbacks, then the held observation callbacks, at once, each on its own as a
# frame runs them, so nothing after it waits for the browser to draw either.
_HOLD_FROM_THE_CORNER_JS = """((handleId, observing) => {
    const request = window.requestAnimationFrame.bind(window);
    const cancel = window.cancelAnimationFrame.bind(window);
    const Observer = window.ResizeObserver;
    const observe = Observer.prototype.observe;
    const disconnect = Observer.prototype.disconnect;
    const observers = new Set();
    let held = null;
    let nextId = -1;
    window.__curioTestHolds = 0;
    window.__curioTestHeldNodeIds = [];
    window.__curioTestHeldObservations = 0;
    window.requestAnimationFrame = (callback) => {
        if (!held) return request(callback);
        const id = nextId--;
        held.frames.set(id, callback);
        return id;
    };
    window.cancelAnimationFrame = (id) => {
        if (held && held.frames.delete(id)) return;
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
                window.__curioTestHeldObservations += entries.length;
                held.observations.push(() => callback(entries, observer));
            });
            // What it observes, so a hold that stops it can start it again.
            this.__curioTargets = new Map();
            observers.add(this);
        }
        observe(target, options) {
            this.__curioTargets.set(target, options);
            if (held && !observing) return;
            super.observe(target, options);
        }
        unobserve(target) {
            this.__curioTargets.delete(target);
            super.unobserve(target);
        }
        disconnect() {
            this.__curioTargets.clear();
            super.disconnect();
        }
    };
    window.__curioTestRelease = () => {
        if (!held) return;
        const { frames, observations } = held;
        held = null;
        if (!observing) {
            observers.forEach((o) => o.__curioTargets.forEach((options, target) => {
                observe.call(o, target, options);
            }));
        }
        const now = performance.now();
        [...frames.values()].map((callback) => () => callback(now))
            .concat(observations)
            .forEach((run) => {
                try {
                    run();
                } catch (error) {
                    window.reportError(error);
                }
            });
    };
    document.addEventListener('mousedown', (event) => {
        const target = event.target instanceof Element ? event.target : null;
        if (held || !target || target.id !== handleId) return;
        held = { frames: new Map(), observations: [] };
        window.__curioTestHolds += 1;
        if (!observing) observers.forEach((o) => disconnect.call(o));
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
        heldObservations: window.__curioTestHeldObservations || 0,
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


def _hold_script(node_id: str, observing: bool) -> str:
    """The hold, started by a press on *node_id*'s corner handle."""
    args = f"{json.dumps(node_id + 'resizer')}, {json.dumps(observing)}"
    return f"{_HOLD_FROM_THE_CORNER_JS}({args});"


def _near(size, want, slack: float = 8) -> bool:
    return bool(size) and all(
        got is not None and abs(got - goal) <= slack for got, goal in zip(size, want)
    )


@pytest.mark.parametrize("observing", list(OBSERVATIONS.values()), ids=list(OBSERVATIONS))
def test_the_stacked_views_scene_frames_its_narrowed_node_on_a_page_that_draws_no_frame(
    app_frontend: "FrontendPage", current_server: str, page, observing: bool,
):
    require_project_page()
    require_user_auth()

    node_id = first_node_of_type(MULTI_VIEW_EXAMPLE, "vis-vega", containing="vconcat")
    page.emulate_media(reduced_motion="reduce")
    page.context.add_init_script(_hold_script(node_id, observing))
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
        assert not _near(state["stored"], NARROWED_NODE), (
            f"React Flow held the node at its narrowed size while the page ran no "
            f"frame callback, so this test proves nothing: {state}"
        )
        # React Flow's measure of the node was kept back: the hold held its
        # callback for the node, or the browser delivered no observation at all,
        # as on a page that draws no frame (our #1178's run 40375648529).
        assert node_id in state["heldNodeIds"] or state["heldObservations"] == 0, (
            f"ResizeObserver callbacks were held, but none for the narrowed node, "
            f"so React Flow is not measuring it and this test proves nothing: {state}"
        )
    finally:
        page.evaluate("() => window.__curioTestRelease && window.__curioTestRelease()")

    # The frame that ends the stall has run its callbacks: the view the scene set
    # lands. Polled on a timer, as the release itself needs no frame.
    try:
        page.wait_for_function(
            _FRAMED_JS, arg=[node_id, CENTRE_SLACK_PX], polling=100, timeout=15000,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"once the frame that ends the stall ran its callbacks, the scene had not "
            f"framed the narrowed node whole, centred on the canvas: "
            f"{page.evaluate(_FRAMING_JS, node_id)}"
        ) from None
