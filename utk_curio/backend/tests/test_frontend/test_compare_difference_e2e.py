"""Playwright E2E: two scenarios' rasters compared in Difference, drawn by an Autark node after it (#662).

Two scenarios each hold one Python node that writes a raster from the small
committed GeoTIFF of #718 (``data/autark_raster_utm16n.tif``, 40 by 30 cells
of 100 m in UTM zone 16N, nine of them nodata): "Baseline" scales it by its
factor widget, 1, and "Twice as tall", its copy, by 2. A Compare Scenarios
node stands beside them, and after it an Autark map, pinned to the dashboard,
whose spec draws the node's output with the grammar's own options: a
diverging scale centered on 0, under a title. This drives the whole path in a
browser:

1. Both outcomes run, then go into the node's circles: they are two rasters,
   so the node picks Difference and writes its code for it.
2. Run All subtracts them in the sandbox's Node process, through Autark: the
   node's output is a raster envelope whose cells are comparison minus
   reference, the original raster itself, nodata kept. The node draws no map
   of it and says that an Autark node after it does; the Autark map draws it,
   its legend under the spec's title.
3. Compare as switches the node to Chart and back: its code follows, and the
   choice is saved.
4. The dashboard draws the pinned map from the saved difference, with no run.
5. A reopen draws it again from the saved difference, and writes nothing.

The close-ups of the node and of the map are the frames.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_compare_difference_e2e.py -v
"""

from __future__ import annotations

import base64
import json
import math
import struct
import time
from typing import TYPE_CHECKING

from .test_multi_input_e2e import _wait_for_circles
from .utils import (
    api_json,
    assert_autark_map_drawn,
    connect_nodes,
    frame_nodes,
    load_artifact_as_dict,
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
    stub_login_and_enter_workflow,
    wait_for_node_done,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

COMPARE_TYPE = "curio.builtin/compare-scenarios"
PYTHON_TYPE = "curio.builtin/computation-analysis"
MAP_TYPE = "curio.builtin/autk-grammar"
BASE = "cdf-base"
TALL = "cdf-tall"
COMPARE = "cdf-compare"
MAP = "cdf-map"
BASELINE = {"scenario": "s-base", "name": "Baseline", "color": "#2a9d8f"}
TWICE = {"scenario": "s-tall", "name": "Twice as tall", "color": "#e76f51"}

#: A layer of 36 small squares near the Loop, each with its osm_id and a
#: sunlight of id over the factor. With factor 2 the first square is gone and a
#: 37th is new, so the difference has a removed row and an added one.
LAYER_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import box\n"
    "factor = [!! factor !!]\n"
    "ids = list(range(1, 37)) if factor == 1 else list(range(2, 38))\n"
    "cells = [box(-87.64 + (i % 6) * 0.001, 41.88 + (i // 6) * 0.001,\n"
    "             -87.6392 + (i % 6) * 0.001, 41.8808 + (i // 6) * 0.001) for i in ids]\n"
    "return gpd.GeoDataFrame({'osm_id': ids, 'sunlight': [i / factor for i in ids]},\n"
    "                        geometry=cells, crs='EPSG:4326')\n"
)

#: The committed raster, scaled by the node's factor and written to a file of
#: the node's own, which it returns as a rasterio dataset.
RASTER_CODE = (
    "import rasterio\n"
    "with rasterio.open('utk_curio/backend/tests/test_frontend/data/autark_raster_utm16n.tif') as source:\n"
    "    profile = source.profile\n"
    "    band = source.read(1, masked=True) * [!! factor !!]\n"
    "path = curio_output_file('compare-difference-[!! factor !!].tif')\n"
    "with rasterio.open(path, 'w', **profile) as target:\n"
    "    target.write(band.filled(profile['nodata']).astype('float32'), 1)\n"
    "return rasterio.open(path)\n"
)

#: The Autark map after the node, for a raster's difference: input_1 minus
#: input_0 on a diverging scale centered on no change, under its own title.
RASTER_MAP_SPEC = {"map": {"layerRefs": [{
    "dataRef": "[!! input_0 !!]",
    "getFnv": "band_1",
    "colorMapInterpolator": "interpolateRdBu",
    "colorMapCenter": 0,
    "title": "Change when twice as tall",
}]}}

#: The Autark map after the node, for a layer's difference: each row colored
#: by its change, one color for added, removed, changed and unchanged.
LAYER_MAP_SPEC = {"map": {"layerRefs": [{
    "dataRef": "[!! input_0 !!]",
    "getFnv": "change",
    "getFnvType": "categorical",
    "colorMapInterpolator": "schemeTableau10",
    "colorMapDomain": ["added", "removed", "changed", "unchanged"],
    "title": "Change",
}]}}

# The lines the node writes in Difference and in Chart (utils/compare/compareCode.ts).
ENTRY_LINES = (
    '    ("s-base", "Baseline", [!! input_0 !!]),',
    '    ("s-tall", "Twice as tall", [!! input_1 !!]),',
)
DIFFERENCE_LINES = ("return curio_difference_scenarios([", *ENTRY_LINES)
STACK_LINES = ("return curio_stack_scenarios([", *ENTRY_LINES)


def _factor(value: int) -> dict:
    return {"widgets": [{"name": "factor", "type": "number", "default": 1, "value": value}]}


def _spec(code: str = RASTER_CODE, name: str = "Compare Difference", map_spec: dict = RASTER_MAP_SPEC) -> dict:
    def node(node_id, node_type, x, y, content, title=None, metadata=None, **fields):
        saved = {
            "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "",
            "metadata": {"keywords": [], **(metadata or {})}, **fields,
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
                node(COMPARE, COMPARE_TYPE, 760, 160, ""),
                node(MAP, MAP_TYPE, 1440, 160, json.dumps(map_spec, indent=2), "Difference map", dashboardPinned=True),
            ],
            "edges": [{
                "id": f"reactflow__edge-{COMPARE}out-{MAP}in",
                "source": COMPARE, "target": MAP, "sourceHandle": "out", "targetHandle": "in",
            }],
            "scenarios": [
                {"id": "s-base", "name": "Baseline", "color": "#2a9d8f", "nodes": [BASE]},
                {"id": "s-tall", "name": "Twice as tall", "color": "#e76f51", "nodes": [TALL]},
            ],
        }
    }


def _wait_for_code(page, node_id: str, lines, timeout_s: float = 15.0) -> str:
    deadline = time.time() + timeout_s
    code = ""
    while time.time() < deadline:
        code = read_node_code(page, node_id)
        if all(line in code for line in lines):
            return code
        page.wait_for_timeout(250)
    raise AssertionError(f"the Compare Scenarios node did not write {lines[0]!r} for its inputs:\n{code}")


_OUTPUT_ARTIFACT_JS = """(id) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    const content = node && node.data && node.data.output && node.data.output.content;
    const match = typeof content === "string" ? content.match(/Saved to file: (\\S+)/) : null;
    return match ? match[1] : null;
}"""

# What a Compare Scenarios node shows in Difference (components/compare/
# CompareDifference.tsx): its view, the kind of difference it holds, whether it
# says an Autark node after it draws the map, and how many maps it holds itself.
_COMPARE_DIFFERENCE_JS = """(id) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const body = node && node.querySelector("[data-compare-mode]");
    if (!body) return null;
    const difference = node.querySelector("[data-compare-difference]");
    return {
        mode: body.getAttribute("data-compare-mode"),
        kind: difference ? difference.getAttribute("data-compare-difference") : null,
        note: !!node.querySelector('[data-compare-difference-map="autark"]'),
        maps: node.querySelectorAll('canvas[id^="autk-grammar-map-"], [data-compare-map-state]').length,
    };
}"""


# The title of a node's map legend, which autk-map writes as the legend's
# first child (`#autkMapLegend`, one per map, so read inside the node).
_LEGEND_TITLE_JS = """(id) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const heading = node && node.querySelector("#autkMapLegend")?.firstElementChild;
    return heading ? heading.textContent : null;
}"""


def _assert_legend_title(page, node_id: str, title: str) -> None:
    """The node's map legend is titled *title*, the layerRef's title,
    not the table the layer is read as."""
    deadline = time.time() + 15
    shown = None
    while time.time() < deadline:
        shown = page.evaluate(_LEGEND_TITLE_JS, node_id)
        if shown == title:
            return
        page.wait_for_timeout(250)
    assert shown == title, f"the map's legend reads {shown!r}, not {title!r}"


def _assert_compare_draws_no_map(page, node_id: str) -> str:
    """The Compare Scenarios node is in Difference and holds a raster's or a
    layer's difference, and draws no map of it: its tab says that an Autark
    node after it draws the map, and the node holds no map canvas. Returns the
    difference's kind."""
    deadline = time.time() + 90
    state = None
    while time.time() < deadline:
        state = page.evaluate(_COMPARE_DIFFERENCE_JS, node_id)
        if state and state["kind"] in ("raster", "layer") and state["note"]:
            break
        page.wait_for_timeout(250)
    assert state and state["mode"] == "difference" and state["kind"] in ("raster", "layer") and state["note"], (
        f"Compare Scenarios {node_id} does not leave its difference's map to an Autark node: {state!r}"
    )
    assert state["maps"] == 0, f"Compare Scenarios {node_id} draws a map of its own: {state!r}"
    return state["kind"]


def _assert_difference_mapped(page, compare_id: str, map_id: str, attach_as: str, legend: str = "") -> None:
    """The Compare Scenarios node draws no map of its difference, and the
    Autark node after it holds a drawn map, its legend titled *legend* when
    given."""
    _assert_compare_draws_no_map(page, compare_id)
    assert_autark_map_drawn(page, map_id, timeout=60000, attach_as=attach_as)
    if legend:
        _assert_legend_title(page, map_id, legend)


def _band(envelope: dict) -> list[float]:
    """The envelope's one band, rows from south to north (utils/raster/rasterWire.ts)."""
    properties = envelope["data"]["features"][0]["properties"]
    raw = base64.b64decode(properties["band_1"]["float32le"])
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


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
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    return session


def _run_outcomes_then_wire_them(page) -> None:
    """Both scenarios' outcomes run, then go into the node's circles in order,
    so the node knows what they are as they arrive."""
    for outcome in (BASE, TALL):
        play_node(page, outcome)
        wait_for_node_done(page, outcome, node_type=PYTHON_TYPE)
    _wait_for_circles(page, COMPARE, ["in"])
    frame_nodes(page, [BASE, COMPARE])
    connect_nodes(page, BASE, COMPARE)
    _wait_for_circles(page, COMPARE, ["in", "in_1"])
    frame_nodes(page, [TALL, COMPARE])
    connect_nodes(page, TALL, COMPARE, target_handle="in_1")


def _run_and_read_output(page, attach_as: str, legend: str) -> dict:
    """Run All; the node subtracts its inputs, and the Autark map after it
    draws the difference, its legend titled *legend*. Returns the node's
    output as the sandbox stores it."""
    run_all_and_wait(page, timeout_ms=240000)
    status = wait_for_node_settled(page, COMPARE, node_type=COMPARE_TYPE, timeout_ms=120000)
    assert status == "done", f"Compare Scenarios did not subtract its inputs: {read_node_error_text(node_locator(page, COMPARE))}"
    status = wait_for_node_settled(page, MAP, node_type=MAP_TYPE, timeout_ms=120000)
    assert status == "done", f"the Autark map did not draw the difference: {read_node_error_text(node_locator(page, MAP))}"
    frame_nodes(page, [COMPARE, MAP])
    _assert_difference_mapped(page, COMPARE, MAP, attach_as, legend=legend)
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, COMPARE)
    assert artifact, "Compare Scenarios shows no saved output"
    return load_artifact_as_dict(artifact)


def test_two_rasters_are_compared_in_difference_and_mapped(
    app_frontend: "FrontendPage", current_server: str, page,
):
    spec = _spec()
    session = _enter(page, app_frontend, current_server, spec, "compare_difference_e2e")
    project_id = session["project"]["id"]
    legend = RASTER_MAP_SPEC["map"]["layerRefs"][0]["title"]

    # 1. Both outcomes run, then go into the circles: two rasters, so Difference.
    _run_outcomes_then_wire_them(page)
    _wait_for_code(page, COMPARE, DIFFERENCE_LINES)

    # 2. Run All subtracts them through Autark; the Autark map after the node
    # draws the difference, and the node draws none.
    stored = _run_and_read_output(page, "the difference of two rasters", legend)
    compare = node_locator(page, COMPARE)
    envelope = stored.get("data") if stored.get("dataType") == "dict" else stored
    assert envelope["dataType"] == "raster", stored.get("dataType")
    assert envelope["data"]["grid"] == {
        "crs": "EPSG:32616", "width": 40, "height": 30,
        "originX": 447000, "originY": 4637000, "resX": 100, "resY": -100,
    }, envelope["data"]["grid"]
    cells = _band(envelope)
    assert len(cells) == 1200
    # Twice the raster minus the raster is the raster, sign and all: its south
    # row starts 14.5, 14.75, 15, 15.25; its north row, three nodata cells and
    # then 0.75, 1, 1.25. Nodata on either side is nodata in the difference.
    assert [round(v, 4) for v in cells[0:4]] == [14.5, 14.75, 15.0, 15.25], cells[0:4]
    assert all(math.isnan(v) for v in cells[1160:1163]), cells[1160:1163]
    assert [round(v, 4) for v in cells[1163:1166]] == [0.75, 1.0, 1.25], cells[1163:1166]
    assert sum(1 for v in cells if math.isnan(v)) == 9
    # The node offers no colors: the map's spec chooses them.
    assert compare.locator('select[aria-label="Color by"]').count() == 0

    # 3. Compare as: Chart, then Difference again. The code follows the view.
    switch = compare.locator('select[aria-label="Compare as"]')
    switch.select_option("chart")
    _wait_for_code(page, COMPARE, STACK_LINES)
    compare.locator('select[aria-label="Compare as"]').select_option("difference")
    content = _wait_for_code(page, COMPARE, DIFFERENCE_LINES)
    save_dataflow(page)
    project = api_json(f"{current_server}/api/projects/{project_id}", session["token"])
    saved = {n["id"]: n for n in project["spec"]["dataflow"]["nodes"]}
    assert saved[COMPARE]["metadata"]["compareScenarios"] == {
        "inputs": [BASELINE, TWICE],
        "mode": "difference",
    }, saved[COMPARE]["metadata"]
    assert saved[COMPARE]["content"] == content
    assert saved[MAP]["dashboardPinned"] is True and "dashboardPinned" not in saved[COMPARE]
    recorded = {output["node_id"] for output in project["outputs"]}
    assert COMPARE in recorded, f"the save recorded the outputs of {sorted(recorded)}, not the difference the pinned map draws"

    # 4. The dashboard draws the pinned map from the saved difference, no run.
    page.goto(f"{app_frontend.base_url}/dashboard/{project_id}")
    page.get_by_test_id("open-dataflow-link").wait_for(state="visible", timeout=45000)
    node_locator(page, MAP).wait_for(state="visible", timeout=45000)
    assert_autark_map_drawn(page, MAP, timeout=60000, attach_as="the difference on the dashboard")
    _assert_legend_title(page, MAP, legend)

    # 5. Reopened, the map draws the saved difference with no run, the node
    # draws none, and nothing is written.
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    compare = node_locator(page, COMPARE)
    compare.wait_for(state="visible", timeout=45000)
    assert _wait_for_code(page, COMPARE, DIFFERENCE_LINES) == content
    frame_nodes(page, [COMPARE, MAP])
    compare.locator('.nav-link[data-rr-ui-event-key="output"]').click()
    _assert_difference_mapped(page, COMPARE, MAP, "the difference after a reopen", legend=legend)
    assert compare.locator('select[aria-label="Compare as"]').input_value() == "difference"
    assert page.locator("[data-curio-save-state]").first.get_attribute("data-curio-save-state") == "saved"

    save_node_closeup(
        page, "compare-difference", COMPARE,
        test_name="test_two_rasters_are_compared_in_difference_and_mapped",
        sweep_toasts=True,
    )
    save_node_closeup(
        page, "compare-difference-map", MAP,
        test_name="test_two_rasters_are_compared_in_difference_and_mapped",
        sweep_toasts=True,
    )


def test_two_layers_are_joined_on_their_osm_id_and_mapped(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """Two layers that have run: Difference again, a Python join on osm_id, and
    the difference layer drawn by the Autark map after the node, each row in
    the color of its change."""
    spec = _spec(LAYER_CODE, "Compare Difference Layers", LAYER_MAP_SPEC)
    _enter(page, app_frontend, current_server, spec, "compare_difference_layers_e2e")

    _run_outcomes_then_wire_them(page)
    _wait_for_code(page, COMPARE, DIFFERENCE_LINES)
    stored = _run_and_read_output(page, "the difference of two layers by its change", "Change")
    assert stored["dataType"] == "geodataframe", stored["dataType"]
    rows = [feature["properties"] for feature in stored["data"]["features"]]
    # The reference's squares in its order, the first gone, then the new one.
    assert [row["osm_id"] for row in rows] == list(range(1, 38))
    assert [row["change"] for row in rows] == ["removed", *["changed"] * 35, "added"]
    # Half the sunlight minus the sunlight, and nothing where a side has none.
    assert rows[0]["sunlight"] is None and rows[-1]["sunlight"] is None, (rows[0], rows[-1])
    assert [row["sunlight"] for row in rows[1:4]] == [-1.0, -1.5, -2.0], rows[1:4]

    compare = node_locator(page, COMPARE)
    assert _assert_compare_draws_no_map(page, COMPARE) == "layer"
    assert compare.locator('select[aria-label="Color by"]').count() == 0
    assert compare.locator('select[aria-label="Key"]').count() == 1
