"""Playwright E2E: rasters as large as SCOUT's flood grid, on an Autark map and in Difference.

An Autark map loads a raster at its own size up to 4096 by 4096 cells, and so
does a Compare Scenarios node's Difference, which loads both rasters as such a
map does. SCOUT's whole flood grid is 2592 by 2064 cells.

1. Two scenarios each hold one Python node that writes a 2592 by 2064 raster
   of 10 m cells in UTM zone 16N: "Baseline" a ramp that is below 0 west of
   its middle column and above 0 east of it, with 4 by 4 nodata cells in its
   north-west corner, and "Twice as tall" the same ramp times 2. An Autark map
   draws the second, and a Compare Scenarios node in Difference subtracts the
   first from the second: the ramp itself, below 0 in the west. Then
   **Change** asks for each difference's size: the node writes
   ``absolute=True`` into its code, runs again, and maps the ramp's size, the
   west's cells as positive as the east's, under "band_1 absolute change".
2. Rasters of 4097 by 4096 cells are refused, in a map and in Difference,
   with the cap's own figures.
3. The page keeps answering while an Autark map draws the Baseline's raster:
   a 20 ms timer runs while the map draws it 3 times, and no gap between its
   ticks reaches 5.9 s.

The map's and the difference's close-ups are the frames, the difference before
and after **Change**, and the map's refusal.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_large_rasters_e2e.py -v
"""

from __future__ import annotations

import base64
import json
import time
from typing import TYPE_CHECKING

import numpy as np

from .test_compare_difference_e2e import (
    BASE,
    BASELINE,
    COMPARE,
    COMPARE_TYPE,
    DIFFERENCE_LINES,
    PYTHON_TYPE,
    TALL,
    TWICE,
    _OUTPUT_ARTIFACT_JS,
    _assert_difference_mapped,
    _enter,
    _factor,
    _run_outcomes_then_wire_them,
    _wait_for_code,
)
from .utils import (
    api_json,
    assert_autark_map_drawn,
    frame_nodes,
    load_artifact_as_dict,
    node_locator,
    play_node,
    read_node_error_text,
    run_all_and_wait,
    save_dataflow,
    save_node_closeup,
    wait_for_node_done,
    wait_for_node_run_to_end,
    wait_for_node_settled,
    watch_node_run,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

MAP = "lgr-map"
MAP_TYPE = "curio.builtin/autk-grammar"
MAP_SPEC = {"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}

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

#: What an Autark map and a Difference say of a raster past the cap.
CAP_WORDS = (
    "is 4097 by 4096 cells, more than an Autark map loads at its own size "
    "(16777216 cells, 8192 on a side). Crop it in the node that makes it, "
    "for example with a rasterio window read, and run that node again."
)

ABSOLUTE_LINES = (*DIFFERENCE_LINES, "], absolute=True)")

#: The longest the page may stop answering while an Autark map draws SCOUT's
#: whole flood grid. On test-gpu, Chrome stops for 6.8 to 8.3 s with autk-map
#: 4.1.1, which builds a color scale for every cell, and for 4.3 to 5.0 s with
#: autk-map from urban-toolkit/autark#118, which builds one for the raster.
STALL_LIMIT_MS = 5900
#: How many times the map draws the raster while the timer runs.
DRAWS = 3

# A 20 ms timer, from the click that draws the map to 3 s after its run ends.
# The longest gap between its ticks is the longest the page stopped answering.
_START_TIMER_JS = """() => {
    const timer = { ticks: [performance.now()] };
    timer.id = setInterval(() => timer.ticks.push(performance.now()), 20);
    window.__curioStallTimer = timer;
}"""

_LONGEST_STALL_JS = """() => {
    const timer = window.__curioStallTimer;
    clearInterval(timer.id);
    const ticks = [...timer.ticks, performance.now()];
    let longest = 0;
    for (let i = 1; i < ticks.length; i++) longest = Math.max(longest, ticks[i] - ticks[i - 1]);
    return Math.round(longest);
}"""

_NOT_RUNNING_JS = """(nodeId) => {
    const el = document.querySelector(`.react-flow__node[data-id="${nodeId}"] [data-curio-node-status]`);
    return !el || el.getAttribute('data-curio-node-status') !== 'running';
}"""


def _ramp() -> np.ndarray:
    """The Baseline's ramp, rows north to south, NaN where it is nodata."""
    rows, cols = np.mgrid[0:HEIGHT, 0:WIDTH]
    ramp = ((cols - WIDTH // 2) * 0.01 + rows * 0.001).astype("float32").astype("float64")
    ramp[:4, :4] = np.nan
    return ramp


def _spec(code: str, name: str) -> dict:
    """Both outcomes, the Compare Scenarios node and an Autark map of the
    comparison. Nothing is pinned to the dashboard: a difference this large is
    over a dashboard page's 25 MB."""
    def node(node_id, node_type, x, y, content, title=None, metadata=None):
        saved = {
            "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "",
            "metadata": {"keywords": [], **(metadata or {})},
        }
        if title:
            saved["title"] = title
        return saved

    return {
        "dataflow": {
            "name": name,
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": name,
            "nodes": [
                node(BASE, PYTHON_TYPE, 0, 0, code, "Outcome", _factor(1)),
                node(TALL, PYTHON_TYPE, 0, 520, code, "Outcome", {**_factor(2), "copiedFrom": [BASE]}),
                node(COMPARE, COMPARE_TYPE, 760, 0, ""),
                node(MAP, MAP_TYPE, 760, 560, json.dumps(MAP_SPEC, indent=2)),
            ],
            "edges": [{
                "id": f"reactflow__edge-{TALL}out-{MAP}in",
                "source": TALL, "target": MAP, "sourceHandle": "out", "targetHandle": "in",
            }],
            "scenarios": [
                {"id": "s-base", "name": "Baseline", "color": "#2a9d8f", "nodes": [BASE]},
                {"id": "s-tall", "name": "Twice as tall", "color": "#e76f51", "nodes": [TALL]},
            ],
        }
    }


# Where the difference map stands and the output it draws
# (components/compare/CompareMap.tsx).
_MAP_OF_JS = """(id) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const map = node && node.querySelector("[data-compare-map-state]");
    return map ? [map.getAttribute("data-compare-map-state"), map.getAttribute("data-compare-map-path")] : null;
}"""


def _difference_cells(page, attach_as: str, legend: str) -> np.ndarray:
    """The node's output once its map has drawn it, with its legend titled
    *legend*: the difference's band, rows north to south."""
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, COMPARE)
    assert artifact, "Compare Scenarios shows no saved output"
    # The map has drawn this output, not the one before it.
    deadline = time.time() + 180
    state = None
    while time.time() < deadline:
        state = page.evaluate(_MAP_OF_JS, COMPARE)
        if state and state[1] == artifact and state[0] in ("drawn", "problem"):
            break
        page.wait_for_timeout(250)
    assert state and state[1] == artifact, f"the difference map shows {state!r}, not output {artifact}"
    _assert_difference_mapped(page, COMPARE, attach_as, legend=legend)

    stored = load_artifact_as_dict(artifact)
    envelope = stored.get("data") if stored.get("dataType") == "dict" else stored
    assert envelope["dataType"] == "raster", stored.get("dataType")
    assert envelope["data"]["grid"] == {
        "crs": "EPSG:32616", "width": WIDTH, "height": HEIGHT,
        "originX": 447000, "originY": 4637000, "resX": 10, "resY": -10,
    }, envelope["data"]["grid"]
    raw = base64.b64decode(envelope["data"]["features"][0]["properties"]["band_1"]["float32le"])
    # The envelope's rows run from south to north (utils/raster/rasterWire.ts).
    return np.frombuffer(raw, dtype="<f4").reshape(HEIGHT, WIDTH)[::-1].astype("float64")


def test_a_raster_of_scouts_whole_flood_grid_draws_on_a_map_and_in_an_absolute_difference(
    app_frontend: "FrontendPage", current_server: str, page,
):
    test_name = "test_a_raster_of_scouts_whole_flood_grid_draws_on_a_map_and_in_an_absolute_difference"
    spec = _spec(RAMP_CODE, "Large Rasters")
    session = _enter(page, app_frontend, current_server, spec, "large_rasters_e2e")
    project_id = session["project"]["id"]

    # Both outcomes run, then go into the circles: two rasters, so Difference.
    _run_outcomes_then_wire_them(page)
    _wait_for_code(page, COMPARE, DIFFERENCE_LINES)

    # Run All: the map draws the comparison at its own size, and the node
    # subtracts the two through Autark and maps the difference.
    run_all_and_wait(page, timeout_ms=600000)
    status = wait_for_node_settled(page, MAP, node_type=MAP_TYPE, timeout_ms=240000)
    assert status == "done", f"the map did not draw the raster: {read_node_error_text(node_locator(page, MAP))}"
    frame_nodes(page, [MAP])
    assert_autark_map_drawn(page, MAP, timeout=120000, attach_as="a 2592 by 2064 raster on an Autark map")
    save_node_closeup(page, "large-raster-map", MAP, test_name=test_name, sweep_toasts=True)

    status = wait_for_node_settled(page, COMPARE, node_type=COMPARE_TYPE, timeout_ms=240000)
    assert status == "done", f"Compare Scenarios did not subtract its inputs: {read_node_error_text(node_locator(page, COMPARE))}"
    frame_nodes(page, [COMPARE])
    ramp = _ramp()
    signed = _difference_cells(page, "the difference of two 2592 by 2064 rasters", "band_1 change")
    # Twice the ramp less the ramp is the ramp: the south-west corner fell by
    # 10.897, the north-east one rose by 12.95, and nodata stays nodata.
    assert np.array_equal(signed, ramp, equal_nan=True)
    assert round(float(signed[HEIGHT - 1, 0]), 3) == -10.897
    assert round(float(signed[0, WIDTH - 1]), 3) == 12.95
    assert int(np.isnan(signed).sum()) == 16
    save_node_closeup(page, "large-raster-difference", COMPARE, test_name=test_name, sweep_toasts=True)

    # Change: each difference's size. The code says so, and the node runs again.
    compare = node_locator(page, COMPARE)
    change = compare.locator('select[aria-label="Change"]')
    assert change.input_value() == "signed"
    change.select_option("absolute")
    content = _wait_for_code(page, COMPARE, ABSOLUTE_LINES)
    watch_node_run(page, COMPARE)
    play_node(page, COMPARE)
    status = wait_for_node_run_to_end(page, COMPARE, node_type=COMPARE_TYPE, timeout_ms=240000)
    assert status == "done", f"Compare Scenarios did not run again: {read_node_error_text(node_locator(page, COMPARE))}"
    frame_nodes(page, [COMPARE])
    absolute = _difference_cells(page, "the absolute difference of two 2592 by 2064 rasters", "band_1 absolute change")
    assert np.array_equal(absolute, np.abs(ramp), equal_nan=True)
    assert round(float(absolute[HEIGHT - 1, 0]), 3) == 10.897
    assert int(np.isnan(absolute).sum()) == 16
    save_node_closeup(page, "large-raster-absolute-difference", COMPARE, test_name=test_name, sweep_toasts=True)

    # The choice is saved with the code it wrote.
    save_dataflow(page)
    project = api_json(f"{current_server}/api/projects/{project_id}", session["token"])
    saved = {n["id"]: n for n in project["spec"]["dataflow"]["nodes"]}
    assert saved[COMPARE]["metadata"]["compareScenarios"] == {
        "inputs": [BASELINE, TWICE],
        "difference": {"absolute": True},
    }, saved[COMPARE]["metadata"]
    assert saved[COMPARE]["content"] == content


def test_a_raster_over_4096_by_4096_cells_is_refused_in_a_map_and_in_the_difference(
    app_frontend: "FrontendPage", current_server: str, page,
):
    spec = _spec(OVERSIZE_CODE, "Oversize Rasters")
    _enter(page, app_frontend, current_server, spec, "oversize_rasters_e2e")
    _run_outcomes_then_wire_them(page)
    _wait_for_code(page, COMPARE, DIFFERENCE_LINES)
    run_all_and_wait(page, timeout_ms=300000)

    # The map draws nothing and says why, in the cap's own figures.
    map_node = node_locator(page, MAP)
    frame_nodes(page, [MAP])
    tab = map_node.locator('.nav-link[data-rr-ui-event-key="output"]').first
    tab.wait_for(state="visible", timeout=15000)
    if "active" not in (tab.get_attribute("class") or ""):
        tab.dispatch_event("click")
    refused = map_node.locator('[data-curio-node-empty="input-type-rejected"]').first
    refused.wait_for(state="visible", timeout=120000)
    assert f"input_0 {CAP_WORDS}" in refused.inner_text(), refused.inner_text()

    # The Difference refuses it too, before a byte of it is written.
    status = wait_for_node_settled(page, COMPARE, node_type=COMPARE_TYPE, timeout_ms=120000)
    assert status == "error", f"Compare Scenarios subtracted rasters past the cap: {status}"
    problem = node_locator(page, COMPARE).locator("[data-compare-run-error]").first
    problem.wait_for(state="visible", timeout=15000)
    assert f"input_0 (Baseline) {CAP_WORDS}" in problem.inner_text(), problem.inner_text()

    save_node_closeup(
        page, "large-raster-refused", MAP,
        test_name="test_a_raster_over_4096_by_4096_cells_is_refused_in_a_map_and_in_the_difference",
        sweep_toasts=True,
    )


def test_the_page_keeps_answering_while_an_autark_map_draws_scouts_whole_flood_grid(
    app_frontend: "FrontendPage", current_server: str, page, record_property,
):
    raster = "lgr-raster"
    spec = {"dataflow": {
        "name": "Large Raster Stall",
        "task": "",
        "nodes": [
            {
                "id": raster, "type": PYTHON_TYPE, "x": 0, "y": 0,
                "content": RAMP_CODE.replace("[!! factor !!]", "1"),
                "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
            },
            {
                "id": MAP, "type": MAP_TYPE, "x": 760, "y": 0,
                "content": json.dumps(MAP_SPEC, indent=2),
                "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
            },
        ],
        "edges": [{
            "id": f"reactflow__edge-{raster}out-{MAP}in",
            "source": raster, "target": MAP, "sourceHandle": "out", "targetHandle": "in",
        }],
    }}
    _enter(page, app_frontend, current_server, spec, "large_raster_stall_e2e")

    play_node(page, raster)
    wait_for_node_done(page, raster, node_type=PYTHON_TYPE, timeout_ms=300000)
    # The map draws the raster when it arrives; that draw ends before the timer starts.
    page.wait_for_function(_NOT_RUNNING_JS, arg=MAP, timeout=300000, polling=250)
    page.wait_for_timeout(3000)

    stalls = []
    for _ in range(DRAWS):
        page.evaluate(_START_TIMER_JS)
        watch_node_run(page, MAP)
        play_node(page, MAP)
        status = wait_for_node_run_to_end(page, MAP, node_type=MAP_TYPE, timeout_ms=300000)
        page.wait_for_timeout(3000)
        stalls.append(page.evaluate(_LONGEST_STALL_JS))
        # A stall measured while a map failed to draw would mean nothing.
        assert status == "done", f"the map did not draw the raster: {read_node_error_text(node_locator(page, MAP))}"
        assert_autark_map_drawn(page, MAP, timeout=120000)

    record_property("longest stall of each draw (ms)", json.dumps(stalls))
    assert max(stalls) < STALL_LIMIT_MS, (
        f"the page stopped answering for {max(stalls)} ms while an Autark map drew a {WIDTH} by {HEIGHT} raster; "
        f"the longest stall of each of the {DRAWS} draws was {stalls} ms, and the limit is {STALL_LIMIT_MS} ms"
    )
