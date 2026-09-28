"""Playwright E2E: a chart and an Autark map joined directly highlight each other.

Example 17 joins its bar chart and its first Autark map with an interaction
edge and no Data Pool between them. Both read the loader's rows, so a
selection names the same row at either end:

- hovering a bar highlights that ZIP on the map, and the map is not redrawn;
- a pick on the map marks that ZIP's row, and the chart colours its bar red.

The map's pixels are read in the page (``toDataURL``), not from a screenshot:
the map's own overlays (its menu button, its legend) sit over the canvas in a
screenshot, and a screenshot of a WebGPU canvas is not the same on every GPU.

The map needs WebGPU: the test skips without an adapter unless
``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job).

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_chart_map_link_e2e.py -v
"""

from __future__ import annotations

import base64
import io
import os
import uuid
from typing import TYPE_CHECKING

import pytest
from PIL import Image, ImageChops
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .utils import (
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)
from .walkthroughs import load_example_spec

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = "17-autark-geodataframe-maps.json"
LOADER_ID = "b4bf489f-0c68-5c14-9461-ba8bfa2bb5c0"
BARS_ID = "dfdcf935-96c9-5dcf-bb44-90376fbafad8"
MAP_ID = "eb39411d-d742-52c8-93aa-1424997ead25"

# The map's canvas now, kept on window so a later check can ask whether it is
# still the one in the page: a redraw replaces it, a highlight keeps it.
_KEEP_CANVAS_JS = """(id) => {
    const canvas = document.getElementById('autk-grammar-map-' + id);
    window.__curioKeptMapCanvas = canvas;
    return !!canvas;
}"""
_CANVAS_KEPT_JS = """() => { const kept = window.__curioKeptMapCanvas; return !!kept && kept.isConnected; }"""

# Pixels of the bar a marked row turns red (the spec's `datum.interacted` test).
_RED_PIXELS_JS = """(id) => {
    const c = document.querySelector('#vega' + id + ' canvas');
    if (!c || !c.width || !c.height) return -1;
    const px = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let red = 0;
    for (let i = 0; i < px.length; i += 4) {
        if (px[i] > 200 && px[i + 1] < 60 && px[i + 2] < 60 && px[i + 3] > 200) red += 1;
    }
    return red;
}"""


def _open_example(page, app_frontend, current_server) -> None:
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Chart Map Link",
        username=f"chart_map_{uuid.uuid4().hex[:8]}",
        project_name="Chart and map",
        project_spec=load_example_spec(EXAMPLE),
    )
    require_owner_view(page)
    for node_id in (LOADER_ID, BARS_ID, MAP_ID):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    has_adapter = bool(page.evaluate("async () => !!(navigator.gpu && await navigator.gpu.requestAdapter())"))
    if not has_adapter:
        if os.environ.get("CURIO_REQUIRE_HARDWARE_WEBGPU") == "1":
            pytest.fail("CURIO_REQUIRE_HARDWARE_WEBGPU=1 but this browser has no WebGPU adapter")
        pytest.skip("drawing an Autark map needs a WebGPU adapter; this browser has none")


# The map canvas as it last drew, read after two animation frames.
_MAP_PIXELS_JS = """async (id) => {
    const canvas = document.getElementById('autk-grammar-map-' + id);
    if (!canvas) return null;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return canvas.toDataURL('image/png');
}"""


def _map_pixels(page) -> Image.Image:
    url = page.evaluate(_MAP_PIXELS_JS, MAP_ID)
    assert url, "the map has no canvas"
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGBA")


def _colours(image: Image.Image) -> int:
    return len(set(image.getdata()))


def _changed_pixels(before: Image.Image, after: Image.Image) -> int:
    diff = ImageChops.difference(before, after).convert("L")
    return sum(1 for value in diff.getdata() if value > 40)


def test_a_direct_edge_links_the_chart_and_the_map_both_ways(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _open_example(page, app_frontend, current_server)

    # Running the loader is all it takes: new data reaches both nodes, and
    # each draws on its own.
    run_node_and_wait(page, LOADER_ID, node_type="data-loading")
    wait_for_node_done(page, BARS_ID, node_type="vis-vega", timeout_ms=120000)
    wait_for_node_done(page, MAP_ID, node_type="autk-grammar", timeout_ms=180000)
    page.locator(f"#vega{BARS_ID} canvas").first.wait_for(state="attached", timeout=60000)
    page.wait_for_timeout(1500)
    assert page.evaluate(_KEEP_CANVAS_JS, MAP_ID), "the map never drew"
    assert page.evaluate(_RED_PIXELS_JS, BARS_ID) == 0, "a bar is red before anything was selected"
    before = _map_pixels(page)
    assert _colours(before) > 8, (
        f"the map drew nothing: its {before.size[0]}x{before.size[1]} canvas holds "
        f"{_colours(before)} colour(s)"
    )

    # Chart to map: hover the bars.
    box = page.locator(f"#vega{BARS_ID} canvas").first.bounding_box()
    assert box, "the bar chart has no canvas box"
    for fraction in (0.2, 0.35, 0.5):
        page.mouse.move(box["x"] + box["width"] * fraction, box["y"] + box["height"] * 0.8)
        page.wait_for_timeout(700)
    page.wait_for_timeout(1500)
    changed = _changed_pixels(before, _map_pixels(page))
    assert changed > 100, f"hovering a bar left the map as it was ({changed} pixels changed)"
    assert page.evaluate(_CANVAS_KEPT_JS), "a selection redrew the map instead of highlighting it"

    # Map to chart: pick the ZIP under the middle of the map.
    canvas = page.locator(f"#autk-grammar-map-{MAP_ID}")
    size = canvas.bounding_box()
    assert size, "the map has no canvas box"
    canvas.dblclick(position={"x": size["width"] / 2, "y": size["height"] / 2})
    try:
        page.wait_for_function(f"() => ({_RED_PIXELS_JS})({BARS_ID!r}) > 0", timeout=15000)
    except PlaywrightTimeoutError:
        raise AssertionError("a pick on the map left every bar as it was") from None
