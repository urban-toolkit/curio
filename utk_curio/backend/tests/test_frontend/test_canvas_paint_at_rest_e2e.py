"""Playwright E2E: the canvas is painted at the zoom it shows (#533).

``components/MainCanvas.css`` gave the canvas viewport ``will-change:
transform`` all the time. Chrome keeps such a layer painted at the zoom it was
rasterized at, so after a fit the nodes could stay a scaled bitmap of an
earlier zoom: soft text and edges until something repainted them. Re-mints
showed it at random (example 09's close-up came out 2.62% off its baseline in
run 36791096981). The viewport now takes the hint only while a pan or zoom
gesture moves it (``useViewportMotionHint``).

Two kinds of check, all on one load:

* the viewport's computed ``will-change``: ``auto`` after the load's fit, after
  a programmatic fit, and once a wheel zoom or a drag has settled; ``transform``
  while the gesture moves it, which keeps panning on a layer;
* a repaint forced after the viewport moved changes nothing: the node is
  captured, then captured again with the layer dropped (inline ``will-change:
  auto``, ``canvas_painted_at_shown_zoom``). A canvas that still shows an
  earlier zoom's raster comes out different the second time.

Every check runs and the failures are reported together, so one run shows each
of them.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_canvas_paint_at_rest_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    CLOSEUP_PIXEL_THRESHOLD,
    VIEWPORT_SETTLE_WAIT_MS,
    _wait_for_reactflow_ready,
    canvas_painted_at_shown_zoom,
    capture_node,
    changed_pixels,
    dismiss_toasts,
    frame_nodes,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    viewport_hints,
    viewport_will_change,
    watch_viewport_hint,
)
from .walkthroughs import load_example_spec

if TYPE_CHECKING:
    from .utils import FrontendPage

#: No map or chart that keeps drawing: its nodes are code and Vega charts.
EXAMPLE = "01-vega-lite-chained-transforms.json"

#: The node captured: a code node whose editor is mostly text, the part that
#: went soft.
PROBE = "a0c5d21f-ce16-4318-95fe-598451859de1"

#: Share of the probe's pixels, over ``CLOSEUP_PIXEL_THRESHOLD``, that a forced
#: repaint may change. A canvas painted at the zoom it shows repaints the same
#: pixels.
PAINT_PROBE_MAX_RATIO = 0.001

_TWO_FRAMES_JS = """() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"""

# Centres the probe at *zoom* without a gesture, as setViewport does for a fit.
_ZOOM_ON_NODE_JS = """({ id, zoom }) => {
    const rf = window.__curio_reactFlow;
    const node = rf.getNode(id);
    const pane = document.querySelector('.react-flow').getBoundingClientRect();
    const at = node.positionAbsolute || node.position;
    rf.setViewport({
        x: pane.width / 2 - (at.x + node.width / 2) * zoom,
        y: pane.height / 2 - (at.y + node.height / 2) * zoom,
        zoom,
    });
}"""


def _painted(page, settle_ms: int = 300) -> None:
    page.evaluate(_TWO_FRAMES_JS)
    page.wait_for_timeout(settle_ms)


def _repaint_changes(page) -> float:
    """Share of the probe's pixels that a forced repaint changes."""
    _painted(page)
    shown = capture_node(page, PROBE)
    with canvas_painted_at_shown_zoom(page):
        _painted(page)
        repainted = capture_node(page, PROBE)
    return changed_pixels(shown, repainted, CLOSEUP_PIXEL_THRESHOLD) / (shown.width * shown.height)


def _empty_pane_point(page) -> tuple[float, float]:
    """A point on the pane just left of the probe, in the gap before its neighbour."""
    box = page.locator(f'.react-flow__node[data-id="{PROBE}"]').bounding_box()
    assert box, "the probe node has no box"
    return box["x"] - 40, box["y"] + box["height"] / 2


def test_the_canvas_is_painted_at_the_zoom_it_shows(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Canvas Paint User",
        username="canvas_paint",
        project_name="Canvas Paint",
        project_spec=load_example_spec(EXAMPLE),
    )
    require_owner_view(page)
    page.wait_for_selector(f'.react-flow__node[data-id="{PROBE}"]', timeout=45000)
    dismiss_toasts(page)
    problems: list[str] = []

    # The load's own fit (and the second one it makes 75 ms later).
    _painted(page, 1000)
    if (value := viewport_will_change(page)) != "auto":
        problems.append(f"after the load's fit the viewport's will-change is {value!r}, not 'auto'")

    _wait_for_reactflow_ready(page)
    _painted(page)
    if (value := viewport_will_change(page)) != "auto":
        problems.append(f"after a programmatic fit the viewport's will-change is {value!r}, not 'auto'")

    # A fit to a node from another zoom, both ways, as a dataflow's load and
    # the tests' own fits do.
    for start in (2.0, 0.3):
        page.evaluate(_ZOOM_ON_NODE_JS, {"id": PROBE, "zoom": start})
        _painted(page, 500)
        frame_nodes(page, [PROBE])
        ratio = _repaint_changes(page)
        if ratio > PAINT_PROBE_MAX_RATIO:
            problems.append(
                f"fitted from zoom {start}: a forced repaint changed {ratio:.2%} of the "
                f"probe (allowed {PAINT_PROBE_MAX_RATIO:.2%}), so it showed an earlier raster"
            )

    # A wheel zoom in and back out, about a point of the pane beside the probe.
    frame_nodes(page, [PROBE])
    _painted(page)
    x, y = _empty_pane_point(page)
    page.mouse.move(x, y)
    watch_viewport_hint(page)
    for delta in (-240, -240, 240, 240):
        page.mouse.wheel(0, delta)
        page.wait_for_timeout(60)
    during = viewport_hints(page)
    page.wait_for_timeout(VIEWPORT_SETTLE_WAIT_MS)
    if "transform" not in during:
        problems.append(f"the viewport took no will-change hint during the wheel zoom (saw {during!r})")
    if (value := viewport_will_change(page)) != "auto":
        problems.append(f"once the wheel zoom settled the viewport's will-change is {value!r}, not 'auto'")
    ratio = _repaint_changes(page)
    if ratio > PAINT_PROBE_MAX_RATIO:
        problems.append(
            f"after a wheel zoom: a forced repaint changed {ratio:.2%} of the probe "
            f"(allowed {PAINT_PROBE_MAX_RATIO:.2%}), so it showed an earlier raster"
        )

    # A drag on the empty pane pans it.
    watch_viewport_hint(page)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 80, y + 40, steps=8)
    during = viewport_hints(page)
    page.mouse.up()
    page.wait_for_timeout(VIEWPORT_SETTLE_WAIT_MS)
    if "transform" not in during:
        problems.append(f"the viewport took no will-change hint during the drag (saw {during!r})")
    if (value := viewport_will_change(page)) != "auto":
        problems.append(f"once the drag settled the viewport's will-change is {value!r}, not 'auto'")

    assert not problems, "the canvas is not painted at the zoom it shows (#533):\n- " + "\n- ".join(problems)
