"""Playwright E2E: the Autark node reads its input the way the Vega-Lite node does.

A fresh Autark node opens empty; wired to a loader it says the loader has not
run, and when the loader runs it fills with a starter document chosen from the
input (``utils/autkDefaultSpec.ts``). An input it cannot draw is refused with the
reason, in the node body and in its error, instead of an empty map under a green
Done. A DataFrame with a geometry column is drawn. A node with several inputs
draws a layer from each (#662), and a layer chip on an input of one frame with
no layer name draws that frame, whatever the chip names.

The first test needs no WebGPU. The others run the Autark node, which does: they
skip without an adapter unless ``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job),
except the several-inputs and layer chip tests, which fail without one.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_input_e2e.py -v
"""

from __future__ import annotations

import json
import os
import time
from io import BytesIO
from typing import TYPE_CHECKING

import allure
import pytest

from .utils import (
    _AUTK_MAP_PIXELS_JS,
    assert_autark_map_drawn,
    changed_pixels,
    node_locator,
    play_node,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    run_node_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER_ID = "autk-input-loader"
AUTK_ID = "autk-input-map"
MAP_ON_INPUT = json.dumps({"map": {"layerRefs": [{"dataRef": "input_0"}]}}, indent=2)

GDF_LOADER = (
    "import geopandas as gpd\n"
    "from shapely.geometry import Point\n"
    "\n"
    "return gpd.GeoDataFrame(\n"
    '    {"pop": [1, 2, 3]},\n'
    "    geometry=[Point(-87.63, 41.88), Point(-87.62, 41.89), Point(-87.61, 41.87)],\n"
    '    crs="EPSG:4326",\n'
    ")\n"
)
DF_WITHOUT_GEOMETRY = (
    "import pandas as pd\n"
    "\n"
    'return pd.DataFrame({"zone": ["n", "s"], "pop": [1, 2]})\n'
)
DF_WITH_GEOMETRY = (
    "import geopandas as gpd\n"
    "import pandas as pd\n"
    "from shapely.geometry import Point\n"
    "\n"
    "gdf = gpd.GeoDataFrame(\n"
    '    {"pop": [1, 2]},\n'
    "    geometry=[Point(-87.63, 41.88), Point(-87.62, 41.89)],\n"
    '    crs="EPSG:4326",\n'
    ")\n"
    "return pd.DataFrame(gdf)\n"
)

# Three footprints as a table holds them, every row with every column: one with
# a height, one with only building:levels (its height null), one with neither.
# 2 km squares, so they fill much of the view autk-map opens on (its camera
# starts 10 km above the data).
_FOOTPRINTS = (
    "import geopandas as gpd\n"
    "from shapely.geometry import box\n"
    "\n"
    "gdf = gpd.GeoDataFrame(\n"
    '    {"building": ["yes", "yes", "yes"],\n'
    '     "height": [30.0, None, None],\n'
    '     "building:levels": [None, 8.0, None]},\n'
    "    geometry=[box(-87.700, 41.870, -87.676, 41.888),\n"
    "              box(-87.670, 41.870, -87.646, 41.888),\n"
    "              box(-87.640, 41.870, -87.616, 41.888)],\n"
    '    crs="EPSG:4326",\n'
    ")\n"
)
# The line a Discovery OpenStreetMap Buildings download's loader ends with.
TYPED_BUILDINGS = _FOOTPRINTS + 'gdf.metadata = {"layerType": "buildings"}\nreturn gdf\n'
UNTYPED_BUILDINGS = _FOOTPRINTS + "return gdf\n"

# A 10 x 10 grid of cells, each with its own value, so the map draws many
# colours (``assert_autark_map_drawn`` wants more than 8).
GRID_LOADER = (
    "import geopandas as gpd\n"
    "from shapely.geometry import box\n"
    "\n"
    "cells, pop = [], []\n"
    "for i in range(10):\n"
    "    for j in range(10):\n"
    "        x, y = -87.70 + 0.006 * i, 41.86 + 0.006 * j\n"
    "        cells.append(box(x, y, x + 0.005, y + 0.005))\n"
    "        pop.append(i * 10 + j)\n"
    'return gpd.GeoDataFrame({"pop": pop}, geometry=cells, crs="EPSG:4326")\n'
)

_GRAMMAR_EDITOR_JS = """(nodeId) => {
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const ed = editors.find((e) => {
        const model = e.getModel();
        const path = model && model.uri && model.uri.path;
        return !!path && path.includes(`grammar-${nodeId}`);
    });
    return ed ? ed.getValue() : null;
}"""


def _pairs_spec(pairs: list[tuple[str, str, str, str]]) -> dict:
    """One Data Loading node feeding one Autark node per row of *pairs*:
    ``(loader_id, loader_code, autark_id, autark_content)``."""
    node = lambda node_id, node_type, x, y, content: {  # noqa: E731
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }
    nodes, edges = [], []
    for row, (loader_id, loader_code, autark_id, autark_content) in enumerate(pairs):
        nodes += [
            node(loader_id, "curio.builtin/data-loading", 0, 520 * row, loader_code),
            node(autark_id, "curio.builtin/autk-grammar", 645, 520 * row, autark_content),
        ]
        edges.append({
            "id": f"reactflow__edge-{loader_id}out-{autark_id}in",
            "source": loader_id,
            "target": autark_id,
        })
    return {
        "dataflow": {
            "name": "Autark input",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Autark input",
            "nodes": nodes,
            "edges": edges,
        }
    }


def _spec(loader_code: str, autark_content: str) -> dict:
    return _pairs_spec([(LOADER_ID, loader_code, AUTK_ID, autark_content)])


def _open(page, app_frontend, current_server, *, username: str, spec: dict) -> None:
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark Input",
        username=username,
        project_name="Autark input",
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)


def _require_webgpu(page) -> None:
    has_adapter = bool(page.evaluate(
        "async () => !!(navigator.gpu && await navigator.gpu.requestAdapter())"
    ))
    if not has_adapter:
        if os.environ.get("CURIO_REQUIRE_HARDWARE_WEBGPU") == "1":
            pytest.fail("CURIO_REQUIRE_HARDWARE_WEBGPU=1 but this browser has no WebGPU adapter")
        pytest.skip("running an Autark node needs a WebGPU adapter; this browser has none")


def _empty_reason(page, node_id: str) -> str | None:
    return node_locator(page, node_id).locator("[data-curio-node-empty]").first.get_attribute(
        "data-curio-node-empty", timeout=15000,
    )


def _open_output(page, node_id: str) -> None:
    # A finished run already shows the Output pane, and the node's outcome
    # banner can sit over the tab, so click only when it is not the active one.
    tab = node_locator(page, node_id).locator('.nav-link[data-rr-ui-event-key="output"]').first
    tab.wait_for(state="visible", timeout=15000)
    if "active" not in (tab.get_attribute("class") or ""):
        tab.dispatch_event("click")


def test_a_fresh_autark_node_fills_from_its_input(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _open(page, app_frontend, current_server, username="autark_input_starter", spec=_spec(GDF_LOADER, ""))

    # An edge alone carries no schema: nothing is written, and the body says
    # what a Vega-Lite chart says in the same place.
    before = page.evaluate(_GRAMMAR_EDITOR_JS, AUTK_ID)
    assert before is None or before.strip() in ("", "{}"), f"filled before its input ran: {before!r}"
    _open_output(page, AUTK_ID)
    assert _empty_reason(page, AUTK_ID) == "upstream-not-run"

    run_node_and_wait(page, LOADER_ID, node_type="DATA_LOADING", timeout_ms=120000)
    page.wait_for_function(
        "(nodeId) => { const v = (" + _GRAMMAR_EDITOR_JS + ")(nodeId); return !!v && v.includes('layerRefs'); }",
        arg=AUTK_ID,
        timeout=60000,
    )
    starter = json.loads(page.evaluate(_GRAMMAR_EDITOR_JS, AUTK_ID))
    assert starter == {
        "map": {"layerRefs": [{
            "dataRef": "input_0",
            "getFnv": "pop",
            "getFnvType": "quantitative",
            "colorMapInterpolator": "interpolateViridis",
        }]},
    }, starter


def test_a_dataframe_without_geometry_is_refused_with_the_reason(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _open(page, app_frontend, current_server, username="autark_input_refused",
          spec=_spec(DF_WITHOUT_GEOMETRY, MAP_ON_INPUT))
    _require_webgpu(page)

    run_node_and_wait(page, LOADER_ID, node_type="DATA_LOADING", timeout_ms=120000)
    play_node(page, AUTK_ID)
    status = wait_for_node_settled(page, AUTK_ID, node_type="autk-grammar", timeout_ms=120000)
    assert status == "error", "an input with no geometry must not end in Done"

    error = read_node_error_text(node_locator(page, AUTK_ID)) or ""
    assert "input_0 has no geometry column" in error, error
    assert "not at fault" in error, error
    _open_output(page, AUTK_ID)
    assert _empty_reason(page, AUTK_ID) == "geometry-unresolved"


def test_a_dataframe_with_a_geometry_column_is_drawn(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _open(page, app_frontend, current_server, username="autark_input_dataframe",
          spec=_spec(DF_WITH_GEOMETRY, MAP_ON_INPUT))
    _require_webgpu(page)

    run_all_and_wait(page, timeout_ms=180000)
    status = wait_for_node_settled(page, AUTK_ID, node_type="autk-grammar", timeout_ms=120000)
    detail = read_node_error_text(node_locator(page, AUTK_ID)) if status == "error" else ""
    assert status == "done", f"the map did not draw: {detail}"


def _map_image(page, node_id: str):
    import base64

    from PIL import Image

    url = page.evaluate(_AUTK_MAP_PIXELS_JS, node_id)
    if not url:
        return None
    return Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")


def _footprints_drawn(page, node_id: str, *, timeout: float = 30000):
    """The map canvas once the footprints show: more than 5% of it unlike its
    corner, which is background. (Three flat boxes hold too few colours for
    ``assert_autark_map_drawn``, which is made for whole maps.)"""
    deadline = time.monotonic() + timeout / 1000
    image, drawn = None, 0.0
    while True:
        image = _map_image(page, node_id)
        if image is not None:
            background = image.getpixel((0, 0))
            unlike = sum(1 for pixel in image.getdata()
                         if max(abs(a - b) for a, b in zip(pixel, background)) > 6)
            drawn = unlike / (image.width * image.height)
        if drawn > 0.05 or time.monotonic() >= deadline:
            break
        page.wait_for_timeout(500)
    assert image is not None, f"Autark node {node_id} has no map canvas"
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    allure.attach(buffer.getvalue(), name=f"{node_id}: canvas pixels", attachment_type=allure.attachment_type.PNG)
    assert drawn > 0.05, f"Autark node {node_id}: only {drawn:.1%} of its map canvas shows anything"
    return image


def test_a_frame_that_names_its_layer_buildings_draws_every_building(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """A Discovery OpenStreetMap Buildings download's loader names the frame's
    layer (``gdf.metadata``), and the map draws it as buildings, not as the
    polygons it draws the same rows as without it. Every building stands: the
    one with only building:levels, whose height the table holds as null, and
    the one with no height at all."""
    typed_map, untyped_map = "autk-buildings-typed", "autk-buildings-untyped"
    culled: list[str] = []
    page.on("console", lambda message: culled.append(message.text)
            if "no valid height metadata" in message.text or "Invalid Building Layer" in message.text
            else None)
    _open(page, app_frontend, current_server, username="autark_input_buildings", spec=_pairs_spec([
        ("loader-buildings-typed", TYPED_BUILDINGS, typed_map, MAP_ON_INPUT),
        ("loader-buildings-untyped", UNTYPED_BUILDINGS, untyped_map, MAP_ON_INPUT),
    ]))
    _require_webgpu(page)

    run_all_and_wait(page, timeout_ms=180000)
    drawn = {}
    for node_id in (typed_map, untyped_map):
        status = wait_for_node_settled(page, node_id, node_type="autk-grammar", timeout_ms=120000)
        detail = read_node_error_text(node_locator(page, node_id)) if status == "error" else ""
        assert status == "done", f"{node_id} did not draw: {detail}"
        drawn[node_id] = _footprints_drawn(page, node_id)

    # autk-map says so when it drops a building for want of a height.
    assert culled == [], culled
    # The same rows, the same camera: only the layer they are drawn as differs
    # (autk-map's buildings colour and shading against its polygons colour).
    typed, untyped = drawn[typed_map], drawn[untyped_map]
    share = changed_pixels(untyped, typed, threshold=6) / (typed.width * typed.height)
    assert share > 0.01, (
        f"the map drew the frame named buildings as it drew the plain one: {share:.2%} of its pixels differ"
    )


def test_a_map_draws_a_layer_from_each_of_its_inputs(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """#662: an Autark node takes several edges, and its document reads each
    input as the table ``input_<k>``, written as the chip ``[!! input k !!]``.
    One loader's footprints feed two maps; a second loader, the same footprints
    named buildings, feeds the second map's second circle. That map draws both
    layers, so it differs from the map of the first input alone, which has the
    same footprints and the same camera."""
    alone, both = "autk-inputs-alone", "autk-inputs-both"
    plain, buildings = "loader-inputs-plain", "loader-inputs-buildings"
    node = lambda node_id, node_type, x, y, content: {  # noqa: E731
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }
    edge = lambda source, target, handle: {  # noqa: E731
        "id": f"reactflow__edge-{source}out-{target}{handle}",
        "source": source, "target": target, "targetHandle": handle,
    }
    spec = {"dataflow": {
        "name": "Autark inputs", "task": "", "timestamp": 1789193389280, "provenance_id": "Autark inputs",
        "nodes": [
            node(plain, "curio.builtin/data-loading", 0, 0, UNTYPED_BUILDINGS),
            node(buildings, "curio.builtin/data-loading", 0, 520, TYPED_BUILDINGS),
            node(alone, "curio.builtin/autk-grammar", 645, 0,
                 '{"map": {"layerRefs": [{"dataRef": [!! input 0 !!]}]}}'),
            node(both, "curio.builtin/autk-grammar", 645, 520,
                 '{"map": {"layerRefs": [{"dataRef": [!! input 0 !!]}, {"dataRef": [!! input 1 !!]}]}}'),
        ],
        "edges": [edge(plain, alone, "in"), edge(plain, both, "in"), edge(buildings, both, "in_1")],
    }}
    _open(page, app_frontend, current_server, username="autark_inputs_two", spec=spec)
    assert page.evaluate("async () => !!(navigator.gpu && await navigator.gpu.requestAdapter())"), (
        "drawing an Autark map needs a WebGPU adapter, which CI's GPU job has"
    )

    run_all_and_wait(page, timeout_ms=180000)
    drawn = {}
    for node_id in (alone, both):
        status = wait_for_node_settled(page, node_id, node_type="autk-grammar", timeout_ms=120000)
        detail = read_node_error_text(node_locator(page, node_id)) if status == "error" else ""
        assert status == "done", f"{node_id} did not draw: {detail}"
        drawn[node_id] = _footprints_drawn(page, node_id)

    share = changed_pixels(drawn[alone], drawn[both], threshold=6) / (drawn[both].width * drawn[both].height)
    assert share > 0.01, (
        f"the map of two inputs drew what the map of the first input draws: {share:.2%} of its pixels differ"
    )


def test_a_layer_chip_draws_the_one_frame_its_input_carries(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """#662: a layer chip in an Autark document works as it does in code. An
    input that carries one frame with no layer name, here the GeoDataFrame a
    Python node returns, is that layer whatever the chip names, so
    ``[!! input 0:anything !!]`` names the table the frame is read by and the
    map draws the grid."""
    chip_map = json.dumps({"map": {"layerRefs": [{
        "dataRef": "[!! input 0:anything !!]",
        "getFnv": "pop",
        "getFnvType": "quantitative",
        "colorMapInterpolator": "interpolateViridis",
    }]}}, indent=2)
    _open(page, app_frontend, current_server, username="autark_input_layer_chip",
          spec=_spec(GRID_LOADER, chip_map))
    assert page.evaluate("async () => !!(navigator.gpu && await navigator.gpu.requestAdapter())"), (
        "drawing an Autark map needs a WebGPU adapter, which CI's GPU job has"
    )

    run_all_and_wait(page, timeout_ms=180000)
    status = wait_for_node_settled(page, AUTK_ID, node_type="autk-grammar", timeout_ms=120000)
    detail = read_node_error_text(node_locator(page, AUTK_ID)) if status == "error" else ""
    assert status == "done", f"the map did not draw its input through the layer chip: {detail}"
    assert_autark_map_drawn(page, AUTK_ID, timeout=60000, attach_as="a GeoDataFrame through a layer chip")
