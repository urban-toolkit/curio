"""SCOUT's flood example on SCOUT's whole grid, in two scenarios from Curio's own nodes, each on an Autark map, compared on an absolute difference map and a chart (#662, step 18; #819).

The shipped test dataflow ``FloodScenarios.json``: Parameter nodes for the
period and the region's corners, at SCOUT's flood example's, which take every
cell of SCOUT's 2592 by 2064 cell grid; three Data Loading nodes reading the
region's window of SCOUT's rasters, which the Data Catalog holds whole; and two
scenarios, "No NbS" and "NbS" (its copy), each holding a Raster Calculator that
chooses the depth by nature-based solution (NbS) class, with its choice of NbS,
a Raster Statistics node and an Autark map of the depth. One Compare Scenarios
node, in Difference, maps the size of NbS minus No NbS through the Autark
node's map code (#723, #901); the other charts each scenario's median flood
depth (#720). Run All drives the whole path:

1. The loaders read SCOUT's rasters by id, for the region and the period
   (2020 - 2040) the Parameter nodes hold, and both calculators, statistics
   and maps run.
2. Each scenario's map draws its depth, its legend titled "Flood depth (m)".
3. The difference is a 2592 by 2064 cell raster in EPSG:4326 on SCOUT's grid,
   whose cells are the size of SCOUT's depths with NbS minus SCOUT's depths
   without, as autk-db reads both (float32): 267,494 cells changed, 842,515
   the same and 4,239,879 with no depth on one side or both, the counts
   SCOUT's rasters give. Its legend says it is the absolute change.
4. The chart draws both scenarios in their colors from the stacked table,
   whose medians and means are SCOUT's for its whole grid: a median flood depth
   of 7.164 m without NbS and 4.900 m with every NbS (``test_scout_flood.py``).
5. What differs lists one lever, the Raster Calculator, and in it one widget,
   the NbS choice; no code line differs, the statistics and the maps are the
   same, and nothing is warned.

The close-ups of the two maps, the difference and the chart are the frames.
Nothing is pinned to the dashboard: a difference of the whole grid is over a
dashboard page's 25 MB.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_flood_e2e.py -v
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest

from .test_compare_difference_e2e import _assert_difference_mapped, _assert_legend_title
from .test_compare_scenarios_e2e import _CHART_STATE_JS, _COLOR_PIXELS_JS, _OUTPUT_ARTIFACT_JS
from .utils import (
    REPO_ROOT,
    assert_autark_map_drawn,
    assert_vega_canvas_rendered,
    frame_nodes,
    load_artifact_as_dict,
    node_locator,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_node_closeup,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "FloodScenarios.json"
TEST_NAME = "test_two_flood_scenarios_are_mapped_and_charted"
CALCULATOR_TYPE = "curio.builtin/raster-calculator"
STATISTICS_TYPE = "curio.builtin/raster-statistics"
MAP_TYPE = "curio.builtin/autk-grammar"
COMPARE_TYPE = "curio.builtin/compare-scenarios"
COLORS = {"no-nbs": "#e76f51", "nbs": "#2a9d8f"}
CELL = 0.00010133941049058334
#: SCOUT's grid: its size, width by height, and its north-west corner.
WIDTH, HEIGHT = 2592, 2064
ORIGIN = (-90.6879323, 41.6242105)

#: SCOUT's median and mean flood depth for its whole grid in 2020 - 2040,
#: without NbS and with every NbS, and how many cells hold a depth
#: (``PINS`` in ``test_packages/test_scout_flood.py``).
MEDIANS = [7.163970947265625, 4.900075276692708]
MEANS = [6.346452299531106, 5.312285760833436]
COUNTS = [1160305, 1115187]


def _nodes_of(spec: dict, node_type: str) -> list[str]:
    return [node["id"] for node in spec["dataflow"]["nodes"] if node["type"] == node_type]


def _compare_nodes(spec: dict) -> dict:
    return {
        node["metadata"]["compareScenarios"]["mode"]: node["id"]
        for node in spec["dataflow"]["nodes"]
        if node["type"] == COMPARE_TYPE
    }


def _maps_by_scenario(spec: dict) -> dict:
    """Each scenario's Autark map, by the scenario's id."""
    maps = set(_nodes_of(spec, MAP_TYPE))
    found = {}
    for scenario in spec["dataflow"]["scenarios"]:
        (map_id,) = [node_id for node_id in scenario["nodes"] if node_id in maps]
        found[scenario["id"]] = map_id
    return found


def _assert_chart_drew(page, node_id: str) -> None:
    """The bar chart compiled with no problem, and its canvas holds both
    scenarios' colors."""
    deadline = time.time() + 60
    state = None
    while time.time() < deadline:
        state = page.evaluate(_CHART_STATE_JS, [node_id, "bar"])
        if state in ("drawn", "problem"):
            break
        page.wait_for_timeout(250)
    problem = node_locator(page, node_id).locator("[data-compare-chart-problem]").all_inner_texts()
    assert state == "drawn", f"the chart's compile ended {state!r}: {problem}"
    assert_vega_canvas_rendered(page, node_id, timeout=30000)
    colors = [COLORS["no-nbs"], COLORS["nbs"]]
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_COLOR_PIXELS_JS, [node_id, colors])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart does not draw both scenarios' colors {colors}: pixels {counts}")


def _band(envelope: dict) -> np.ndarray:
    """The envelope's one band (utils/raster/rasterWire.ts)."""
    raw = base64.b64decode(envelope["data"]["features"][0]["properties"]["band_1"]["float32le"])
    return np.frombuffer(raw, dtype="<f4")


def test_two_flood_scenarios_are_mapped_and_charted(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Flood Scenarios",
        username="scout_flood_scenarios",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    compares = _compare_nodes(spec)
    maps = _maps_by_scenario(spec)
    steps = [(node["id"], node["type"]) for node in spec["dataflow"]["nodes"]
             if node["type"] in (CALCULATOR_TYPE, STATISTICS_TYPE, MAP_TYPE)]
    assert len(steps) == 6, steps

    # 1. Run All: both scenarios read SCOUT's rasters for the shared region and period.
    run_all_and_wait(page, timeout_ms=600000)
    for node_id, node_type in steps:
        status = wait_for_node_settled(page, node_id, node_type=node_type, timeout_ms=240000)
        assert status == "done", f"{node_type} did not run: {read_node_error_text(node_locator(page, node_id))}"
    for node_id in compares.values():
        status = wait_for_node_settled(page, node_id, node_type=COMPARE_TYPE, timeout_ms=240000)
        assert status == "done", f"Compare Scenarios did not compare: {read_node_error_text(node_locator(page, node_id))}"

    # 2. Each scenario's map draws its depth, under the grammar's title.
    for scenario, map_id in maps.items():
        frame_nodes(page, [map_id])
        assert_autark_map_drawn(page, map_id, timeout=60000, attach_as=f"the {scenario} flood depth map")
        _assert_legend_title(page, map_id, "Flood depth (m)")
        save_node_closeup(page, f"scout-flood-depth-map-{scenario}", map_id, test_name=TEST_NAME, sweep_toasts=True)

    # 3. The difference, the size of NbS minus No NbS, on SCOUT's grid, mapped.
    frame_nodes(page, [compares["difference"]])
    _assert_difference_mapped(page, compares["difference"], "the size of NbS minus No NbS flood depth",
                              legend="band_1 absolute change")
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, compares["difference"])
    assert artifact, "Compare Scenarios shows no saved difference"
    stored = load_artifact_as_dict(artifact)
    envelope = stored.get("data") if stored.get("dataType") == "dict" else stored
    assert envelope["dataType"] == "raster", stored.get("dataType")
    grid = envelope["data"]["grid"]
    assert (grid["crs"], grid["width"], grid["height"]) == ("EPSG:4326", WIDTH, HEIGHT), grid
    assert (grid["originX"], grid["originY"]) == pytest.approx(ORIGIN, abs=1e-9), grid
    assert (grid["resX"], grid["resY"]) == pytest.approx((CELL, -CELL), rel=1e-9), grid
    cells = _band(envelope)
    assert cells.size == WIDTH * HEIGHT
    finite = cells[~np.isnan(cells)]
    counts = (
        int((finite < 0).sum()), int((finite > 0).sum()),
        int((finite == 0).sum()), int(cells.size - finite.size),
    )
    assert counts == (0, 267494, 842515, 4239879), counts
    assert float(finite.max()) == pytest.approx(10.645233154296875, abs=1e-5)

    # 4. The chart of the median flood depth, from SCOUT's numbers.
    frame_nodes(page, [compares["chart"]])
    _assert_chart_drew(page, compares["chart"])
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, compares["chart"])
    assert artifact, "Compare Scenarios shows no saved table"
    stacked = load_artifact_as_dict(artifact)
    assert stacked["dataType"] == "dataframe", stacked["dataType"]
    table = stacked["data"]
    # The stored table's columns come back by name, not in their order.
    assert sorted(table) == ["count", "max", "mean", "median", "min", "scenario", "scenario_name"], list(table)
    assert table["scenario"] == ["no-nbs", "nbs"] and table["scenario_name"] == ["No NbS", "NbS"]
    assert table["median"] == pytest.approx(MEDIANS, rel=1e-12)
    assert table["mean"] == pytest.approx(MEANS, rel=1e-12)
    assert table["count"] == COUNTS

    # 5. What differs: the NbS choice, and nothing else.
    compare = node_locator(page, compares["chart"])
    compare.get_by_role("tab", name="What differs", exact=True).click()
    widget = compare.locator('[data-compare-widget="use_NBS_classes"]')
    widget.wait_for(state="visible", timeout=10000)
    assert compare.locator("[data-compare-lever]").count() == 1
    assert compare.locator('[data-compare-value="no-nbs"]').inner_text().endswith("No NbS: []")
    assert '"Constructed wetlands"' in compare.locator('[data-compare-value="nbs"]').inner_text()
    assert compare.locator("[data-compare-code-added]").count() == 0
    assert compare.locator("[data-compare-code-removed]").count() == 0
    # The Raster Statistics pair and the map pair are the same in both scenarios.
    assert compare.locator("[data-compare-same]").get_attribute("data-compare-same") == "2"
    assert compare.locator("[data-compare-warning]").count() == 0
    compare.get_by_role("tab", name="Chart", exact=True).click()

    frame_nodes(page, [compares["difference"]])
    _assert_difference_mapped(page, compares["difference"], "the flood depth change before its close-up")
    save_node_closeup(page, "scout-flood-depth-change", compares["difference"], test_name=TEST_NAME, sweep_toasts=True)
    frame_nodes(page, [compares["chart"]])
    _assert_chart_drew(page, compares["chart"])
    save_node_closeup(page, "scout-flood-median-depth", compares["chart"], test_name=TEST_NAME, sweep_toasts=True)
