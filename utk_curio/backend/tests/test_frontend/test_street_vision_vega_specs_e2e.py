"""Playwright E2E: the street-vision example's two Vega-Lite specs draw.

Example 10 cannot run end to end offline (its first two nodes need a Google
Maps key and the HuggingFace model), so its tail was never exercised, and both
of its Vega-Lite specs were wrong in ways no unit test could see (#276):

* the polygon map's only layer read a dataset called ``table``, which nothing
  ever fills (the node feeds its rows to the spec's root ``data``), so the layer
  was empty by construction;
* every field was written as ``properties.<name>``, but the node spreads each
  feature's properties into the row, so no such path resolves;
* Spatial Join emits plain GeoJSON with no ``geometry_name``, and the node only
  attached geometry when that name was declared, so a geoshape over it ended in
  "No geometry to draw".

This runs everything after the CV nodes for real: a stand-in for the inference
output (one tagged point inside each Chicago ZIP polygon), the real polygon
loader, the real Spatial Join node and route, and the two specs read from the
shipped example file, so the example's own text is what is under test.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_street_vision_vega_specs_e2e.py -v
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from .utils import (
    REPO_ROOT,
    assert_vega_canvas_rendered,
    node_locator,
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = os.path.join(REPO_ROOT, "docs", "examples", "10-street-vision-cv-analysis.json")
MAP_NODE = "8aaff248-9894-4ca8-b9a3-3b79216ce592"
BARS_NODE = "1aa27f1a-5ed7-4872-a413-ce6fd1eb2c6b"

POINTS_ID = "sv-points"
POLYGONS_ID = "sv-polygons"
JOIN_ID = "sv-join"
MAP_ID = "sv-map"
BARS_ID = "sv-bars"

# What HF CV Inference emits, minus the pictures: a point per panorama with the
# class it was dominated by (resultsToFeatureCollection.ts). One point inside
# each ZIP polygon keeps every neighborhood populated, so the bar chart has a
# row per ZIP and the map a dot in each.
POINTS_CODE = """import geopandas as gpd

polys = gpd.read_file(curio_dataset_path("data.urbanlab.chicago-boundary"))
pts = polys.representative_point()
classes = ["road", "sidewalk", "building", "vegetation", "sky", "car"]
gdf = gpd.GeoDataFrame(
    {
        "image_id": [f"img_{i}" for i in range(len(pts))],
        "latitude": pts.y.round(5).tolist(),
        "longitude": pts.x.round(5).tolist(),
        "dominant_class": [classes[i % len(classes)] for i in range(len(pts))],
        "dominant_pct": [40 + (i % 5) * 10 for i in range(len(pts))],
    },
    geometry=list(pts),
    crs=polys.crs,
)
return gdf
"""

# Example 10 renames `pri_neigh` to `name`; the ZIP file calls it `zip`.
POLYGONS_CODE = """import geopandas as gpd

gdf = gpd.read_file(curio_dataset_path("data.urbanlab.chicago-boundary"))
return gdf.rename(columns={"zip": "name"})
"""


def _shipped_spec(node_prefix: str) -> str:
    with open(EXAMPLE, encoding="utf-8") as fh:
        nodes = json.load(fh)["dataflow"]["nodes"]
    matches = [n for n in nodes if n["id"].startswith(node_prefix[:8])]
    assert len(matches) == 1, f"example 10 has {len(matches)} nodes starting {node_prefix[:8]}"
    return matches[0]["content"]


def _node(node_id: str, node_type: str, x: int, y: int, content: str) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "x": x,
        "y": y,
        "content": content,
        "in": "DEFAULT",
        "out": "DEFAULT",
        "goal": "",
        "metadata": {"keywords": []},
    }


def _edge(source: str, target: str, target_handle: str) -> dict:
    return {
        "id": f"reactflow__edge-{source}out-{target}{target_handle}",
        "source": source,
        "sourceHandle": "out",
        "target": target,
        "targetHandle": target_handle,
    }


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "Street-vision tail",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Street-vision tail",
            "nodes": [
                _node(POINTS_ID, "curio.builtin/data-loading", 0, 0, POINTS_CODE),
                _node(POLYGONS_ID, "curio.builtin/data-loading", 0, 430, POLYGONS_CODE),
                _node(JOIN_ID, "curio.builtin/spatial-join", 645, 215, ""),
                _node(MAP_ID, "curio.builtin/vis-vega", 1045, 0, _shipped_spec(MAP_NODE)),
                _node(BARS_ID, "curio.builtin/vis-vega", 1045, 430, _shipped_spec(BARS_NODE)),
            ],
            "edges": [
                _edge(POINTS_ID, JOIN_ID, "in_points"),
                _edge(POLYGONS_ID, JOIN_ID, "in_polygons"),
                _edge(JOIN_ID, MAP_ID, "in"),
                _edge(JOIN_ID, BARS_ID, "in"),
            ],
            "datasets": [
                {
                    "datasetId": "data.urbanlab.chicago-boundary",
                    "dirName": "data.urbanlab.chicago-boundary@1",
                    "origin": "imported",
                    "producerNodeId": None,
                    "consumerNodeIds": [],
                    "installedAt": "2026-09-12T00:00:00Z",
                }
            ],
        }
    }


def _distinct_canvas_colours(page, node_id: str, *, min_alpha: int = 200) -> int:
    """How many distinct opaque, non-white colours a Vega node's canvas holds.

    Sampled on a 4px grid, then rounded to 16 levels per channel so
    antialiasing does not inflate the count. A chart whose colour encoding
    resolved has one colour per category plus the axes; one whose field is
    missing has the palette's first colour and nothing else.
    """
    return page.evaluate(
        """(containerId) => {
            const el = document.getElementById(containerId);
            const canvas = el && el.querySelector('canvas');
            if (!canvas) return 0;
            const ctx = canvas.getContext('2d');
            const { data, width, height } = ctx.getImageData(0, 0, canvas.width, canvas.height);
            const seen = new Set();
            for (let y = 0; y < height; y += 4) {
                for (let x = 0; x < width; x += 4) {
                    const i = (y * width + x) * 4;
                    const r = data[i], g = data[i + 1], b = data[i + 2], a = data[i + 3];
                    if (a < %d) continue;
                    if (r > 235 && g > 235 && b > 235) continue;
                    seen.add(((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4));
                }
            }
            return seen.size;
        }""" % min_alpha,
        f"vega{node_id}",
    )


def test_the_street_vision_vega_specs_draw_from_a_spatial_join(
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
        name="Street Vision Tail",
        username="street_vision_tail",
        project_name="Street-vision tail",
        project_spec=_spec(),
    )
    require_owner_view(page)
    for node_id in (POINTS_ID, POLYGONS_ID, JOIN_ID, MAP_ID, BARS_ID):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)

    run_node_and_wait(page, POINTS_ID, node_type="DATA_LOADING", timeout_ms=120000)
    run_node_and_wait(page, POLYGONS_ID, node_type="DATA_LOADING", timeout_ms=120000)
    # Spatial Join fires on its own once both slots hold data.
    wait_for_node_done(page, JOIN_ID, node_type="SPATIAL_JOIN", timeout_ms=120000)

    # Every synthetic point sits inside its own ZIP polygon, so the join must
    # tag all of them. This also proves the tag column the specs read is the
    # one the backend writes (`joined`): the node counts tagged features by it.
    status = node_locator(page, JOIN_ID).locator("[data-curio-spatial-join-status]")
    status.wait_for(state="visible", timeout=30000)
    assert "Tagged 61 of 61 points" in status.inner_text(), status.inner_text()

    # The map: a geoshape layer over the joined points, coloured by the
    # per-polygon dominant class. Before the fixes it was blank three times
    # over (empty "table" dataset, unresolvable field paths, no geometry
    # attached). `assert_vega_canvas_rendered` only proves *something* was
    # drawn, and axes count, so the colour count is what says the encodings
    # resolved: a missing field paints every mark the palette's first colour.
    play_node(page, MAP_ID)
    assert_vega_canvas_rendered(page, MAP_ID)
    assert _distinct_canvas_colours(page, MAP_ID) >= 6, (
        "the map drew, but in too few colours for a dominant-class scale: the "
        "colour field did not resolve on the joined rows"
    )

    # The bars: images per polygon, coloured by dominant class. With the filter
    # on `joined` dropping every row this chart is just its axes.
    play_node(page, BARS_ID)
    assert_vega_canvas_rendered(page, BARS_ID)
    assert _distinct_canvas_colours(page, BARS_ID) >= 6, (
        "the bar chart drew only its axes: the rows carried no `joined` column"
    )
