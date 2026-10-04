"""Playwright E2E: an Autark map redraws like a Vega chart, and a selection does not.

A map that has new data reaching it redraws on its own, as a Vega-Lite chart
does: here, when the node feeding it runs again. A Data Pool selection re-emits
the same rows with new ``interacted`` flags; that only highlights, so the map is
not rebuilt.

The signal is the map's canvas: a run replaces it, a highlight keeps it.

Both tests run an Autark map, which needs WebGPU: they skip without an adapter
unless ``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job).

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_redraw_e2e.py -v
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from .utils import (
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    run_node_and_wait,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER_ID = "redraw-loader"
POOL_ID = "redraw-pool"
MAP_ID = "redraw-map"
BAR_ID = "redraw-bar"
MAP_ON_INPUT = json.dumps({"map": {"layerRefs": [{"dataRef": "input_0"}]}}, indent=2)

LOADER_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import Point\n"
    "\n"
    "return gpd.GeoDataFrame(\n"
    '    {"label": ["a", "b", "c"], "value": [1, 3, 2]},\n'
    "    geometry=[Point(-87.63, 41.88), Point(-87.62, 41.89), Point(-87.61, 41.87)],\n"
    '    crs="EPSG:4326",\n'
    ")\n"
)
BAR_SPEC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "params": [{"name": "highlight", "select": {"type": "point", "on": "pointerover"}}],
    "mark": {"type": "bar"},
    "encoding": {
        "x": {"field": "label", "type": "ordinal"},
        "y": {"field": "value", "type": "quantitative"},
        "color": {"condition": {"test": "datum.interacted === '1'", "value": "red"}, "value": "blue"},
    },
})


def _node(node_id: str, node_type: str, x: int, y: int, content: str) -> dict:
    return {
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _edge(source: str, target: str) -> dict:
    return {"id": f"reactflow__edge-{source}out-{target}in", "source": source, "target": target}


def _spec(nodes: list, edges: list) -> dict:
    return {"dataflow": {
        "name": "Autark redraw", "task": "", "timestamp": 1789193389280,
        "provenance_id": "Autark redraw", "nodes": nodes, "edges": edges,
    }}


def _open(page, app_frontend, current_server, *, username: str, spec: dict) -> None:
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark Redraw",
        username=username,
        project_name="Autark redraw",
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    has_adapter = bool(page.evaluate("async () => !!(navigator.gpu && await navigator.gpu.requestAdapter())"))
    if not has_adapter:
        if os.environ.get("CURIO_REQUIRE_HARDWARE_WEBGPU") == "1":
            pytest.fail("CURIO_REQUIRE_HARDWARE_WEBGPU=1 but this browser has no WebGPU adapter")
        pytest.skip("drawing an Autark map needs a WebGPU adapter; this browser has none")


# The map's canvas now, kept on window so a later check can ask whether it is
# still the one on the page (a run replaces it; a highlight does not).
_KEEP_CANVAS_JS = """(id) => {
    const canvas = document.getElementById('autk-grammar-map-' + id);
    window.__curioKeptMapCanvas = canvas;
    return !!canvas;
}"""
_CANVAS_REPLACED_JS = """(id) => {
    const kept = window.__curioKeptMapCanvas;
    const now = document.getElementById('autk-grammar-map-' + id);
    return !!kept && !kept.isConnected && !!now;
}"""
_CANVAS_KEPT_JS = """() => { const kept = window.__curioKeptMapCanvas; return !!kept && kept.isConnected; }"""


def test_an_autark_map_redraws_when_the_node_feeding_it_runs_again(
    app_frontend: "FrontendPage", current_server: str, page,
):
    spec = _spec(
        [_node(LOADER_ID, "curio.builtin/data-loading", 0, 0, LOADER_CODE),
         _node(MAP_ID, "curio.builtin/autk-grammar", 645, 0, MAP_ON_INPUT)],
        [_edge(LOADER_ID, MAP_ID)],
    )
    _open(page, app_frontend, current_server, username="autark_redraw_rerun", spec=spec)

    run_all_and_wait(page, timeout_ms=180000)
    assert page.evaluate(_KEEP_CANVAS_JS, MAP_ID), "the map never drew"

    # Run the loader alone: new data reaches the map, and it redraws itself.
    run_node_and_wait(page, LOADER_ID, node_type="DATA_LOADING", timeout_ms=120000)
    page.wait_for_function(_CANVAS_REPLACED_JS, arg=MAP_ID, timeout=60000)


def test_a_pool_selection_highlights_an_autark_map_without_redrawing_it(
    app_frontend: "FrontendPage", current_server: str, page,
):
    spec = _spec(
        [_node(LOADER_ID, "curio.builtin/data-loading", 0, 0, LOADER_CODE),
         _node(POOL_ID, "curio.builtin/data-pool", 600, 0, ""),
         _node(MAP_ID, "curio.builtin/autk-grammar", 1200, -300, MAP_ON_INPUT),
         _node(BAR_ID, "curio.builtin/vis-vega", 1200, 300, BAR_SPEC)],
        [_edge(LOADER_ID, POOL_ID), _edge(POOL_ID, MAP_ID), _edge(POOL_ID, BAR_ID),
         {"type": "Interaction", "id": f"reactflow__edge-{BAR_ID}in/out-{POOL_ID}in/out",
          "source": BAR_ID, "target": POOL_ID}],
    )
    _open(page, app_frontend, current_server, username="autark_redraw_selection", spec=spec)

    run_all_and_wait(page, timeout_ms=180000)
    page.locator(f"#vega{BAR_ID} canvas").first.wait_for(state="attached", timeout=60000)
    page.wait_for_timeout(1500)
    assert page.evaluate(_KEEP_CANVAS_JS, MAP_ID), "the map never drew"

    box = page.locator(f"#vega{BAR_ID} canvas").first.bounding_box()
    assert box, "the bar chart has no canvas box"
    for fraction in (0.8, 0.5, 0.3):
        page.mouse.move(box["x"] + box["width"] * fraction, box["y"] + box["height"] * 0.8)
        page.wait_for_timeout(700)
    # Long enough for a redraw, if one were coming, to replace the canvas.
    page.wait_for_timeout(3000)
    assert page.evaluate(_CANVAS_KEPT_JS), "a selection redrew the Autark map instead of highlighting it"
