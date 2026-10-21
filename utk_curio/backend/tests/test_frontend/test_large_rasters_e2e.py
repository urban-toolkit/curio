"""Playwright E2E: rasters as large as SCOUT's flood grid, on an Autark map and in a Raster Calculator's difference.

An Autark map loads a raster at its own size up to 4096 by 4096 cells. SCOUT's
whole flood grid is 2592 by 2064 cells, and Scout's Raster Calculator
(``curio.scout@1``) subtracts two such rasters as the flood dataflow takes its
Depth change.

1. Two scenarios each hold one Python node that writes a 2592 by 2064 raster
   of 10 m cells in UTM zone 16N: "Baseline" a ramp that is below 0 west of
   its middle column and above 0 east of it, with 4 by 4 nodata cells in its
   north-west corner, and "Twice as tall" the same ramp times 2. An Autark map
   draws the second, and a Raster Calculator subtracts the first from the
   second: the ramp itself, below 0 in the west, which a second Autark map,
   after the node, draws on a scale centered on 0. Then the node's code asks
   for each difference's size, ``absolute=True``, the node runs again, and
   the map after it draws the ramp's size, the west's cells as positive as
   the east's.
2. Rasters of 4097 by 4096 cells are refused by a map, with the cap's own
   figures, and so is their difference, which the Raster Calculator computes,
   by the map after it.

The Compare Scenarios node that took this difference before went in step 6.4
of the plan answering komar41's review.

The close-ups of the two maps are the frames, the difference's before and
after ``absolute=True``, and the first map's refusal.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_large_rasters_e2e.py -v
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np

from .utils import (
    _OUTPUT_ARTIFACT_JS,
    _assert_legend_title,
    api_json,
    assert_autark_map_drawn,
    frame_nodes,
    load_raster_cells,
    node_locator,
    play_node,
    read_node_code,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_dataflow,
    save_node_closeup,
    set_node_code,
    stub_login_and_enter_workflow,
    wait_for_node_run_to_end,
    wait_for_node_settled,
    watch_node_run,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

PYTHON_TYPE = "curio.builtin/computation-analysis"
MAP_TYPE = "curio.builtin/autk-grammar"
CALCULATOR_TYPE = "curio.scout/raster-calculator"
#: The package the Raster Calculator is a node of, which the dataflow declares.
SCOUT_PACKAGE = "curio.scout@1"
BASE = "cdf-base"
TALL = "cdf-tall"
CALCULATOR = "lgr-calculator"
MAP = "lgr-map"
DIFFERENCE_MAP = "lgr-difference-map"
MAP_SPEC = {"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}
#: The map after the Raster Calculator: its difference on a diverging scale
#: centered on 0, under its own title.
DIFFERENCE_MAP_SPEC = {"map": {"layerRefs": [{
    "dataRef": "input_0",
    "getFnv": "band_1",
    "colorMapInterpolator": "interpolateRdBu",
    "colorMapCenter": 0,
    "title": "Ramp change",
}]}}

#: The Raster Calculator's code, as the flood dataflow takes its Depth change:
#: Twice as tall's ramp, on input_1, minus Baseline's, on input_0, cell by cell.
CALCULATOR_HEAD = (
    "# Twice as tall's ramp, on input_1, minus Baseline's, on input_0, cell by cell.\n"
    "from scout_rasters.raster_algebra import raster_calculate\n"
    "\n"
)
SIGNED_CODE = CALCULATOR_HEAD + (
    'return raster_calculate("subtract", [input_1, input_0], output_file=curio_output_file)\n'
)
#: Each difference's size, the flood dataflow's own line.
ABSOLUTE_CODE = CALCULATOR_HEAD + (
    'return raster_calculate("subtract", [input_1, input_0], absolute=True, output_file=curio_output_file)\n'
)

#: SCOUT's flood grid, width by height.
WIDTH, HEIGHT = 2592, 2064
NODATA = -9999.0

#: The ramp times the node's factor, written to a file of the node's own,
#: which it returns as a rasterio dataset.
RAMP_CODE = (
    "import numpy as np\n"
    "import rasterio\n"
    "from rasterio.transform import from_origin\n"
    f"width, height = {WIDTH}, {HEIGHT}\n"
    "rows, cols = np.mgrid[0:height, 0:width]\n"
    "band = ((cols - width // 2) * 0.01 + rows * 0.001) * [!! factor !!]\n"
    f"band[:4, :4] = {NODATA}\n"
    "path = curio_output_file('large-raster-[!! factor !!].tif')\n"
    "with rasterio.open(path, 'w', driver='GTiff', width=width, height=height, count=1,\n"
    f"                   dtype='float32', crs='EPSG:32616', nodata={NODATA}, compress='DEFLATE',\n"
    "                   transform=from_origin(447000.0, 4637000.0, 10.0, 10.0)) as target:\n"
    "    target.write(band.astype('float32'), 1)\n"
    "return rasterio.open(path)\n"
)

#: One cell more than 4096 on a side: uint8, so it is cheap to write.
OVERSIZE_CODE = (
    "import numpy as np\n"
    "import rasterio\n"
    "from rasterio.transform import from_origin\n"
    "path = curio_output_file('oversize-raster-[!! factor !!].tif')\n"
    "with rasterio.open(path, 'w', driver='GTiff', width=4097, height=4096, count=1,\n"
    "                   dtype='uint8', crs='EPSG:32616', nodata=255, compress='DEFLATE',\n"
    "                   transform=from_origin(447000.0, 4637000.0, 10.0, 10.0)) as target:\n"
    "    target.write(np.full((4096, 4097), [!! factor !!], dtype='uint8'), 1)\n"
    "return rasterio.open(path)\n"
)

#: What an Autark map says of a raster past the cap.
CAP_WORDS = (
    "is 4097 by 4096 cells, more than an Autark map loads at its own size "
    "(16777216 cells, 8192 on a side). Crop it in the node that makes it, "
    "for example with a rasterio window read, and run that node again."
)


def _ramp() -> np.ndarray:
    """The Baseline's ramp, rows north to south, NaN where it is nodata."""
    rows, cols = np.mgrid[0:HEIGHT, 0:WIDTH]
    ramp = ((cols - WIDTH // 2) * 0.01 + rows * 0.001).astype("float32").astype("float64")
    ramp[:4, :4] = np.nan
    return ramp


def _factor(value: int) -> dict:
    return {"widgets": [{"name": "factor", "type": "number", "default": 1, "value": value}]}


def _spec(code: str, name: str) -> dict:
    """Both outcomes, the Raster Calculator after them, an Autark map of the
    comparison and an Autark map of the difference, after the calculator. The
    dataflow names Scout's package, the calculator's. Nothing is pinned to the
    dashboard: a difference this large is over a dashboard page's 25 MB."""
    def node(node_id, node_type, x, y, content, title=None, metadata=None):
        saved = {
            "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "",
            "metadata": {"keywords": [], **(metadata or {})},
        }
        if title:
            saved["title"] = title
        return saved

    def edge(source, target, handle="in"):
        return {
            "id": f"reactflow__edge-{source}out-{target}{handle}",
            "source": source, "target": target, "sourceHandle": "out", "targetHandle": handle,
        }

    return {
        "dataflow": {
            "name": name,
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": name,
            "nodes": [
                node(BASE, PYTHON_TYPE, 0, 0, code, "Outcome", _factor(1)),
                node(TALL, PYTHON_TYPE, 0, 520, code, "Outcome", {**_factor(2), "copiedFrom": [BASE]}),
                node(CALCULATOR, CALCULATOR_TYPE, 760, 0, SIGNED_CODE, metadata={"packageTemplateLabel": "Ramp change"}),
                node(MAP, MAP_TYPE, 760, 560, json.dumps(MAP_SPEC, indent=2)),
                node(DIFFERENCE_MAP, MAP_TYPE, 1440, 0, json.dumps(DIFFERENCE_MAP_SPEC, indent=2)),
            ],
            "edges": [
                edge(TALL, MAP), edge(BASE, CALCULATOR), edge(TALL, CALCULATOR, "in_1"),
                edge(CALCULATOR, DIFFERENCE_MAP),
            ],
            "scenarios": [
                {"id": "s-base", "name": "Baseline", "color": "#2a9d8f", "nodes": [BASE]},
                {"id": "s-tall", "name": "Twice as tall", "color": "#e76f51", "nodes": [TALL]},
            ],
            "packages": [SCOUT_PACKAGE],
        }
    }


def _enter(page, app_frontend, current_server, spec: dict, username: str) -> dict:
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    name = spec["dataflow"]["name"]
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name=name,
        username=username,
        project_name=name,
        project_spec=spec,
    )
    require_owner_view(page)
    # The Raster Calculator is Scout's node: the account has the package
    # because the stack starts --with-examples, and the dataflow declares it.
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    assert SCOUT_PACKAGE in store, f"{SCOUT_PACKAGE} is not in the account's store {store}: start the stack --with-examples"
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    return session


def _difference_cells(page, attach_as: str) -> np.ndarray:
    """The Raster Calculator's output once the map after it has drawn it,
    under the map's own title: the difference's band, rows north to south."""
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, CALCULATOR)
    assert artifact, "the Raster Calculator shows no saved output"
    frame_nodes(page, [CALCULATOR, DIFFERENCE_MAP])
    assert_autark_map_drawn(page, DIFFERENCE_MAP, timeout=60000, attach_as=attach_as)
    _assert_legend_title(page, DIFFERENCE_MAP, DIFFERENCE_MAP_SPEC["map"]["layerRefs"][0]["title"])

    grid, bands = load_raster_cells(artifact)
    assert grid == {
        "crs": "EPSG:32616", "width": WIDTH, "height": HEIGHT,
        "originX": 447000, "originY": 4637000, "resX": 10, "resY": -10,
    }, grid
    (cells,) = bands
    return cells.astype("float64")


def _refusal(page, node_id: str) -> str:
    """What an Autark map that refuses its input says on its output tab."""
    map_node = node_locator(page, node_id)
    frame_nodes(page, [node_id])
    tab = map_node.locator('.nav-link[data-rr-ui-event-key="output"]').first
    tab.wait_for(state="visible", timeout=15000)
    if "active" not in (tab.get_attribute("class") or ""):
        tab.dispatch_event("click")
    refused = map_node.locator('[data-curio-node-empty="input-type-rejected"]').first
    refused.wait_for(state="visible", timeout=120000)
    return refused.inner_text()


def test_a_raster_of_scouts_whole_flood_grid_draws_on_a_map_and_in_an_absolute_difference(
    app_frontend: "FrontendPage", current_server: str, page,
):
    test_name = "test_a_raster_of_scouts_whole_flood_grid_draws_on_a_map_and_in_an_absolute_difference"
    spec = _spec(RAMP_CODE, "Large Rasters")
    session = _enter(page, app_frontend, current_server, spec, "large_rasters_e2e")
    project_id = session["project"]["id"]

    # Run All: the map draws the comparison at its own size, the Raster
    # Calculator subtracts the two, and the map after it draws the difference.
    run_all_and_wait(page, timeout_ms=600000)
    status = wait_for_node_settled(page, MAP, node_type=MAP_TYPE, timeout_ms=240000)
    assert status == "done", f"the map did not draw the raster: {read_node_error_text(node_locator(page, MAP))}"
    frame_nodes(page, [MAP])
    assert_autark_map_drawn(page, MAP, timeout=120000, attach_as="a 2592 by 2064 raster on an Autark map")
    save_node_closeup(page, "large-raster-map", MAP, test_name=test_name, sweep_toasts=True)

    status = wait_for_node_settled(page, CALCULATOR, node_type=CALCULATOR_TYPE, timeout_ms=240000)
    assert status == "done", (
        f"the Raster Calculator did not subtract its inputs: {read_node_error_text(node_locator(page, CALCULATOR))}"
    )
    status = wait_for_node_settled(page, DIFFERENCE_MAP, node_type=MAP_TYPE, timeout_ms=240000)
    assert status == "done", (
        f"the map after the Raster Calculator did not draw the difference: "
        f"{read_node_error_text(node_locator(page, DIFFERENCE_MAP))}"
    )
    ramp = _ramp()
    signed = _difference_cells(page, "the difference of two 2592 by 2064 rasters")
    # Twice the ramp less the ramp is the ramp: the south-west corner fell by
    # 10.897, the north-east one rose by 12.95, and nodata stays nodata.
    assert np.array_equal(signed, ramp, equal_nan=True)
    assert round(float(signed[HEIGHT - 1, 0]), 3) == -10.897
    assert round(float(signed[0, WIDTH - 1]), 3) == 12.95
    assert int(np.isnan(signed).sum()) == 16
    save_node_closeup(page, "large-raster-difference-map", DIFFERENCE_MAP, test_name=test_name, sweep_toasts=True)

    # Each difference's size: absolute=True in the node's code, the node runs
    # again, and its new output reaches the map after it, which draws it.
    assert read_node_code(page, CALCULATOR) == SIGNED_CODE
    set_node_code(page, CALCULATOR, ABSOLUTE_CODE)
    watch_node_run(page, CALCULATOR)
    watch_node_run(page, DIFFERENCE_MAP)
    play_node(page, CALCULATOR)
    status = wait_for_node_run_to_end(page, CALCULATOR, node_type=CALCULATOR_TYPE, timeout_ms=240000)
    assert status == "done", (
        f"the Raster Calculator did not run again: {read_node_error_text(node_locator(page, CALCULATOR))}"
    )
    status = wait_for_node_run_to_end(page, DIFFERENCE_MAP, node_type=MAP_TYPE, timeout_ms=240000)
    assert status == "done", (
        f"the map after the Raster Calculator did not draw the new difference: "
        f"{read_node_error_text(node_locator(page, DIFFERENCE_MAP))}"
    )
    absolute = _difference_cells(page, "the absolute difference of two 2592 by 2064 rasters")
    assert np.array_equal(absolute, np.abs(ramp), equal_nan=True)
    assert round(float(absolute[HEIGHT - 1, 0]), 3) == 10.897
    assert int(np.isnan(absolute).sum()) == 16
    save_node_closeup(
        page, "large-raster-absolute-difference-map", DIFFERENCE_MAP, test_name=test_name, sweep_toasts=True,
    )

    # The code it ran is saved with the dataflow.
    save_dataflow(page)
    project = api_json(f"{current_server}/api/projects/{project_id}", session["token"])
    saved = {n["id"]: n for n in project["spec"]["dataflow"]["nodes"]}
    assert saved[CALCULATOR]["content"] == ABSOLUTE_CODE, saved[CALCULATOR]["content"]


def test_a_raster_over_4096_by_4096_cells_and_its_difference_are_refused_by_their_maps(
    app_frontend: "FrontendPage", current_server: str, page,
):
    spec = _spec(OVERSIZE_CODE, "Oversize Rasters")
    _enter(page, app_frontend, current_server, spec, "oversize_rasters_e2e")
    run_all_and_wait(page, timeout_ms=300000)

    # The map draws nothing and says why, in the cap's own figures.
    refused = _refusal(page, MAP)
    assert f"input_0 {CAP_WORDS}" in refused, refused

    # The Raster Calculator has no cap of its own and subtracts them, and the
    # map after it refuses their difference in the same words.
    status = wait_for_node_settled(page, CALCULATOR, node_type=CALCULATOR_TYPE, timeout_ms=120000)
    assert status == "done", (
        f"the Raster Calculator did not subtract the rasters: {read_node_error_text(node_locator(page, CALCULATOR))}"
    )
    refused = _refusal(page, DIFFERENCE_MAP)
    assert f"input_0 {CAP_WORDS}" in refused, refused

    save_node_closeup(
        page, "large-raster-refused", MAP,
        test_name="test_a_raster_over_4096_by_4096_cells_and_its_difference_are_refused_by_their_maps",
        sweep_toasts=True,
    )
