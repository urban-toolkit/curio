"""Playwright E2E: every Autark map draws in its notebook cell.

A notebook cell is as tall as its content, but a map has no height of its own:
the cell gives an Autark map or plot a definite 400px to draw in. A map that
came out blank at that height (a canvas sized 0, or never resized) would still
leave a cell on the page, so this runs the gallery's five-map example in the
notebook view and reads each map's canvas. One of the five is fed a frame with
no geometry on purpose (``EXPECTED_EMPTY`` in ``test_workflows.py``): its cell
must say why it drew nothing.

Kept apart from ``test_notebook_view_e2e.py``: an Autark node needs WebGPU, so
this module runs on the GPU runner, and that one stays on the desktop runner
where its screenshots were made. Without a WebGPU adapter it skips, unless
``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job), where it fails.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_notebook_view_maps_e2e.py -v
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .test_scenarios_canvas_e2e import _require_webgpu
from .test_workflows import EXPECTED_EMPTY
from .utils import (
    REPO_ROOT,
    assert_autark_map_drawn,
    dismiss_toasts,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = Path(REPO_ROOT) / "docs" / "examples" / "17-autark-geodataframe-maps.json"
BAR = "header[data-curio-menu-bar]"
AUTARK = "curio.builtin/autk-grammar"
#: The height a cell gives an Autark map or plot.
MAP_HEIGHT = 400

RUN_MS = 420000


def _maps(spec: dict) -> list[str]:
    """The example's Autark nodes that draw a map."""
    return [
        node["id"] for node in spec["dataflow"]["nodes"]
        if node["type"].split("@")[0] == AUTARK and "map" in json.loads(node["content"])
    ]


def test_every_autark_map_draws_in_its_cell(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    refused = EXPECTED_EMPTY[EXAMPLE.name]
    maps = [m for m in _maps(spec) if m not in refused]
    blank = [m for m in _maps(spec) if m in refused]
    assert len(maps) == 4 and len(blank) == 1, f"example 17 should have four maps that draw and one refused: {maps}, {blank}"
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Notebook Maps",
        username="notebook_maps_e2e",
        project_name="Notebook view maps e2e",
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    dismiss_toasts(page)
    _require_webgpu(page)

    radio = page.locator(BAR).get_by_role("radio", name="Notebook view", exact=True)
    radio.click()
    expect(radio).to_have_attribute("aria-checked", "true")
    page.wait_for_function(
        "(count) => { const ns = window.__curio_reactFlow.getNodes();"
        " return ns.length === count && new Set(ns.map((n) => n.position.x)).size === 1; }",
        arg=len(spec["dataflow"]["nodes"]),
        timeout=20000,
    )

    # The notebook view has no rail: its page has a Run all button of its own.
    expect(page.locator("#notebook-run-all").get_by_role("button", name="Run all nodes")).to_be_visible()
    run_all_and_wait(page, timeout_ms=RUN_MS)

    for map_id in maps:
        node_locator(page, map_id).scroll_into_view_if_needed()
        # The map's canvas fills the 400px the cell gives it.
        try:
            page.wait_for_function(
                "([id, h]) => { const c = document.getElementById('autk-grammar-map-' + id);"
                " return !!c && Math.abs(c.offsetHeight - h) <= 2 && c.offsetWidth > 0; }",
                arg=[map_id, MAP_HEIGHT],
                timeout=30000,
            )
        except PlaywrightTimeoutError:
            size = page.evaluate(
                "(id) => { const c = document.getElementById('autk-grammar-map-' + id);"
                " return c ? [c.offsetWidth, c.offsetHeight] : null; }",
                map_id,
            )
            raise AssertionError(f"map {map_id}'s canvas is {size}, not {MAP_HEIGHT}px tall in its cell") from None
        assert_autark_map_drawn(page, map_id, timeout=60000, attach_as=f"map {map_id} in its notebook cell")

    # The map fed no geometry says so in its cell, in view.
    for map_id in blank:
        cell = node_locator(page, map_id)
        cell.scroll_into_view_if_needed()
        empty = cell.locator(f'[data-curio-node-empty="{refused[map_id]}"]')
        expect(empty).to_be_visible(timeout=30000)
        assert (empty.bounding_box() or {}).get("height", 0) > 0, f"map {map_id}'s empty state has no height"
