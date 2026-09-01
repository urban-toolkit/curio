"""Playwright E2E: the provenance graph keeps its edges when you zoom in.

Reported symptom: open Provenance, zoom in, and the edges between the version
cards disappear while the cards themselves stay put.

The suspected cause is a GLOBAL rule. ``components/MainCanvas.css`` is imported
once for the whole app and styles ``.react-flow__viewport`` unscoped, so it
applies to *every* React Flow in the app - including the one nested inside the
Provenance modal:

    .react-flow__viewport { will-change: transform; }

``will-change: transform`` promotes the viewport to its own compositor layer.
React Flow paints edges as a single ``<svg class="react-flow__edges">`` inside
that layer while each node is its own DOM subtree, so when the promoted layer
grows past what the compositor will rasterise, the SVG is the part that stops
being painted - which is exactly "the edges vanish, the cards remain".

This test does not assert the cause, only the behaviour: after zooming in, the
edge paths must still be present AND still have a non-zero rendered geometry.
``TrillProvenanceWindow``'s ``ProvenanceEdge`` returns ``null`` whenever a node
measurement is missing, so a regression there would show up here too, which is
the other reason to check geometry rather than mere presence.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_provenance_zoom_edges_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
)
from .walkthroughs import load_example_spec

if TYPE_CHECKING:
    from .utils import FrontendPage

#: Any example with a few nodes; the provenance chain comes from the saves the
#: harness makes, not from the spec's own shape.
EXAMPLE = "01-vega-lite-chained-transforms.json"

EDGE_PATH = ".react-flow__edges path.react-flow__edge-path"


def _open_provenance(page):
    page.get_by_role("button", name="Provenance ⏷", exact=True).click(force=True)
    page.get_by_role("button", name="Provenance", exact=True).click()
    dialog = page.get_by_role("dialog").filter(has_text="Provenance for")
    dialog.wait_for(state="visible", timeout=20000)
    page.wait_for_selector(".react-flow__node", timeout=20000)
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

    dialog = _open_provenance(page)
    page.wait_for_timeout(1200)

    before = _edge_geometry(page)
    if len(before) == 0:
        # Only one version means no edges at all, and the test would pass
        # vacuously at every zoom level.
        raise AssertionError(
            "the provenance graph has no edges to begin with, so this test "
            "cannot tell a zoom bug from an empty chain - the harness needs to "
            "save the dataflow more than once first"
        )

    save_workflow_test_screenshot(
        page, "provenance-edges-before-zoom",
        test_name="test_provenance_edges_survive_zooming_in",
        fit_reactflow=False,
    )

    # Zoom in the way a user does: the modal's own zoom-in control, repeatedly.
    zoom_in = dialog.get_by_role("button", name="zoom in")
    zoom_in.wait_for(state="visible", timeout=10000)
    for _ in range(5):
        zoom_in.click()
        page.wait_for_timeout(250)
    page.wait_for_timeout(600)

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
