"""Playwright E2E for #445: only nodes that can save an output show the toggle.

Vega-Lite and Simple View nodes pass their input through and never save it, so
the save-output toggle beside their play button did nothing. A node that
computes a dataset keeps the toggle.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_save_output_toggle_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    drag_to_canvas,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

ANALYSIS_TILE = "#tile-computation-analysis"
VEGA_TILE = "#tile-vis-vega"
SIMPLE_TILE = "#tile-vis-simple"


def _toggle(page, node_id: str):
    return node_locator(page, node_id).locator(f"input#save-output-{node_id}")


def test_view_nodes_have_no_save_toggle_and_computing_nodes_keep_it(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Toggle User",
        username="toggle_user",
        project_name="Save toggle",
    )
    require_owner_view(page)

    analysis = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=(150, 150))
    vega = drag_to_canvas(page, page.locator(VEGA_TILE), at=(760, 150))
    simple = drag_to_canvas(page, page.locator(SIMPLE_TILE), at=(150, 600))

    # The computing node's toggle is the control for this check.
    expect(_toggle(page, analysis)).to_be_attached(timeout=15000)
    # The Vega-Lite node keeps its play button, so its footer has rendered
    # once that is there; the toggle beside it must not be.
    expect(
        node_locator(page, vega).locator("svg.fa-circle-play")
    ).to_be_visible(timeout=15000)
    expect(_toggle(page, vega)).to_have_count(0)
    expect(node_locator(page, simple)).to_be_visible(timeout=15000)
    expect(_toggle(page, simple)).to_have_count(0)
