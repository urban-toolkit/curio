"""Playwright E2E: the provenance graph keeps its edges when you zoom in.

Reported symptom: open Provenance, zoom in, and the edges between the version
cards disappear while the cards themselves stay put.

The report was a COMPOSITOR failure (#504). With this graph's viewport on its
own GPU layer (``will-change: transform``, which ``components/MainCanvas.css``
gave every React Flow viewport then), Chrome stopped painting the 2px edges at
some zoom levels while the cards stayed. ``TrillProvenanceWindow.module.css``
sets ``will-change: auto`` on this graph's viewport (pinned in
``src/tests/styles/provenanceEdgesLayer.test.ts``), and MainCanvas.css now
gives the hint only to a canvas the user is moving (#533).

``getBoundingClientRect`` reports correct boxes whether or not the edges are
painted, so the assertions below cannot see that failure; the screenshots this
test saves can. The assertions guard another way the edges can vanish:
``ProvenanceEdge`` returns ``null`` the moment a node measurement is missing
(``if (!src?.width || !src?.height || ...) return null``), so anything that
disturbs node measurement silently removes every edge.

Every count is taken inside the modal: the dataflow canvas behind it has edges
of its own.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_provenance_zoom_edges_e2e.py -v
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from .utils import (
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
)
from .walkthroughs import load_example_spec
from .walkthroughs.steps import PROVENANCE_EDGE_PATH, await_provenance_graph

if TYPE_CHECKING:
    from .utils import FrontendPage

#: Any example with a few nodes; the provenance chain comes from the saves the
#: harness makes, not from the spec's own shape.
EXAMPLE = "01-vega-lite-chained-transforms.json"

EDGE_PATH = PROVENANCE_EDGE_PATH

#: How many times slower than the runner Chromium runs while the window opens.
#: A wait that sleeps a fixed time passes on a fast runner and fails here; a
#: wait for the drawn graph passes on both.
CPU_THROTTLE = 4


@contextmanager
def _throttled_cpu(page, rate: int):
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": rate})
    try:
        yield
    finally:
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
        cdp.detach()


def _open_provenance(page):
    page.get_by_test_id("provenance-btn").click(force=True)
    dialog = page.get_by_role("dialog").filter(has_text="Provenance for")
    dialog.wait_for(state="visible", timeout=20000)
    await_provenance_graph(page)
    return dialog


def _edge_geometry(page) -> list[dict]:
    """Every provenance edge path, with the box the browser actually gives it."""
    return page.evaluate(
        """(sel) => Array.from(document.querySelectorAll(sel)).map((p) => {
            const r = p.getBoundingClientRect();
            const cs = getComputedStyle(p);
            return {
              d: (p.getAttribute('d') || '').slice(0, 24),
              w: Math.round(r.width), h: Math.round(r.height),
              display: cs.display, visibility: cs.visibility, opacity: cs.opacity,
            };
        })""",
        EDGE_PATH,
    )


def test_provenance_edges_survive_zooming_in(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Prov User",
        username="prov_zoom",
        project_name="Provenance Zoom",
        project_spec=load_example_spec(EXAMPLE),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)

    with _throttled_cpu(page, CPU_THROTTLE):
        dialog = _open_provenance(page)
        before = _edge_geometry(page)
        cards = dialog.locator(".react-flow__node").count()
    if len(before) == 0:
        # Only one version means no edges at all, and the test would pass
        # vacuously at every zoom level.
        raise AssertionError(
            "the provenance graph has no edges to begin with, so this test "
            "cannot tell a zoom bug from an empty chain - the harness needs to "
            "save the dataflow more than once first"
        )
    # Every version but the first has one parent edge, so a fully drawn graph
    # shows one edge per card after the first. Zooming is judged against that.
    assert len(before) == cards - 1, (
        f"before zooming, the provenance graph shows {len(before)} edges for "
        f"{cards} versions; a fully drawn graph has {cards - 1}"
    )

    save_workflow_test_screenshot(
        page, "provenance-edges-before-zoom",
        test_name="test_provenance_edges_survive_zooming_in",
        fit_reactflow=False,
    )

    # Both ways a user zooms. The control steps discretely through `zoomIn()`;
    # the wheel drives d3-zoom continuously and is the only one that produces
    # fractional intermediate scales - so a rendering problem that depends on
    # the scale value can hide from one and not the other.
    graph = dialog.locator(".react-flow__pane").first
    box = graph.bounding_box()
    assert box, "the provenance graph has no layout box"
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    for _ in range(14):
        page.mouse.wheel(0, -240)
        page.wait_for_timeout(120)
    page.wait_for_timeout(500)

    mid = _edge_geometry(page)
    save_workflow_test_screenshot(
        page, "provenance-edges-wheel-zoom",
        test_name="test_provenance_edges_survive_zooming_in",
        fit_reactflow=False,
    )
    assert len(mid) == len(before), (
        f"wheel-zooming dropped provenance edges: {len(before)} -> {len(mid)}"
    )

    # Then the control, for the discrete `zoomIn()` path - skipping any click
    # once React Flow has disabled it at maxZoom, which the wheel pass above
    # has usually already reached.
    zoom_in = dialog.get_by_role("button", name="zoom in")
    zoom_in.wait_for(state="visible", timeout=10000)
    for _ in range(6):
        if not zoom_in.is_enabled():
            break
        zoom_in.click()
        page.wait_for_timeout(200)
    page.wait_for_timeout(500)

    after = _edge_geometry(page)

    save_workflow_test_screenshot(
        page, "provenance-edges-after-zoom",
        test_name="test_provenance_edges_survive_zooming_in",
        fit_reactflow=False,
    )

    assert len(after) == len(before), (
        f"zooming in dropped provenance edges from the DOM: {len(before)} paths "
        f"before, {len(after)} after. Before={before} After={after}"
    )

    # Present in the DOM is not enough - a path with a zero box, display:none or
    # visibility:hidden is invisible to the user, which is the reported symptom.
    invisible = [
        e for e in after
        if e["display"] == "none"
        or e["visibility"] == "hidden"
        or float(e["opacity"] or 1) == 0
        or (e["w"] == 0 and e["h"] == 0)
    ]
    assert not invisible, (
        f"after zooming in, {len(invisible)} of {len(after)} provenance edges "
        f"render as nothing: {invisible}"
    )
