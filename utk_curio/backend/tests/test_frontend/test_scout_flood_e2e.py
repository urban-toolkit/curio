"""SCOUT's flood example in two scenarios, from Curio's own nodes, compared on an Autark map and a chart (#662, step 18).

The shipped test dataflow ``FloodScenarios.json``: Parameter nodes for the
period and the region's corners, three Data Loading nodes reading the region's
window of the Data Catalog's crops of SCOUT's rasters, and two scenarios, "No
NbS" and "NbS" (its copy), each holding a Raster Calculator that chooses the
depth by nature-based solution (NbS) class, with its choice of NbS, and a Raster
Statistics node. One Compare Scenarios node, in Difference, maps NbS minus No
NbS through the Autark node's map code (#723); the other charts each scenario's
median flood depth (#720). Run All drives the whole path:

1. The loaders read the crops by id, for the region and the period (2020 - 2040)
   the Parameter nodes hold, and both calculators and statistics run.
2. The difference is a 256 by 256 cell raster in EPSG:4326, on SCOUT's cells,
   whose cells are SCOUT's depths with NbS minus SCOUT's depths without, as
   autk-db reads both (float32): 6,882 cells lower, 20 higher, 22,698 the same
   and 35,936 with no depth on either side, the counts SCOUT's rasters give for
   the region.
3. The chart draws both scenarios in their colors from the stacked table, whose
   medians and means are SCOUT's for the region (``test_scout_flood.py``).
4. What differs lists one lever, the Raster Calculator, and in it one widget,
   the NbS choice; no code line differs, the statistics are the same, and
   nothing is warned.

The two close-ups are the frames.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_flood_e2e.py -v
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .test_compare_difference_e2e import _assert_difference_mapped, _band
from .test_compare_scenarios_e2e import _CHART_STATE_JS, _COLOR_PIXELS_JS, _OUTPUT_ARTIFACT_JS
from .utils import (
    REPO_ROOT,
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
CALCULATOR_TYPE = "curio.builtin/raster-calculator"
STATISTICS_TYPE = "curio.builtin/raster-statistics"
COMPARE_TYPE = "curio.builtin/compare-scenarios"
COLORS = {"no-nbs": "#e76f51", "nbs": "#2a9d8f"}
CELL = 0.00010133941049058334
#: The region's north-west corner, on the edge of SCOUT's cells.
ORIGIN = (-90.48363204845099, 41.4669317349186)

#: SCOUT's median and mean flood depth for the region in 2020 - 2040, without
#: NbS and with every NbS (``PINS`` in ``test_packages/test_scout_flood.py``).
MEDIANS = [5.788970947265625, 3.7056172688802085]
MEANS = [5.822848300261312, 4.743663890809282]


def _compare_nodes(spec: dict) -> dict:
    return {
        node["metadata"]["compareScenarios"]["mode"]: node["id"]
        for node in spec["dataflow"]["nodes"]
        if node["type"] == COMPARE_TYPE
    }


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
    steps = [(node["id"], node["type"]) for node in spec["dataflow"]["nodes"]
             if node["type"] in (CALCULATOR_TYPE, STATISTICS_TYPE)]
    assert len(steps) == 4, steps

    # 1. Run All: both scenarios read SCOUT's crops for the shared region and period.
    run_all_and_wait(page, timeout_ms=300000)
    for node_id, node_type in steps:
        status = wait_for_node_settled(page, node_id, node_type=node_type, timeout_ms=120000)
        assert status == "done", f"{node_type} did not run: {read_node_error_text(node_locator(page, node_id))}"
    for node_id in compares.values():
        status = wait_for_node_settled(page, node_id, node_type=COMPARE_TYPE, timeout_ms=120000)
        assert status == "done", f"Compare Scenarios did not compare: {read_node_error_text(node_locator(page, node_id))}"

    # 2. The difference, NbS minus No NbS, on SCOUT's cells, mapped.
    frame_nodes(page, [compares["difference"]])
    _assert_difference_mapped(page, compares["difference"], "NbS minus No NbS flood depth")
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, compares["difference"])
    assert artifact, "Compare Scenarios shows no saved difference"
    stored = load_artifact_as_dict(artifact)
    envelope = stored.get("data") if stored.get("dataType") == "dict" else stored
    assert envelope["dataType"] == "raster", stored.get("dataType")
    grid = envelope["data"]["grid"]
    assert (grid["crs"], grid["width"], grid["height"]) == ("EPSG:4326", 256, 256), grid
    assert (grid["originX"], grid["originY"]) == pytest.approx(ORIGIN, abs=1e-9), grid
    assert (grid["resX"], grid["resY"]) == pytest.approx((CELL, -CELL), rel=1e-9), grid
    cells = _band(envelope)
    assert len(cells) == 256 * 256
    finite = [v for v in cells if not math.isnan(v)]
    counts = (
        sum(1 for v in finite if v < 0), sum(1 for v in finite if v > 0),
        sum(1 for v in finite if v == 0), len(cells) - len(finite),
    )
    assert counts == (6882, 20, 22698, 35936), counts
    assert min(finite) == pytest.approx(-10.64486026763916, abs=1e-5)

    # 3. The chart of the median flood depth, from SCOUT's numbers.
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
    assert table["count"] == [34041, 29625]

    # 4. What differs: the NbS choice, and nothing else.
    compare = node_locator(page, compares["chart"])
    compare.get_by_role("tab", name="What differs", exact=True).click()
    widget = compare.locator('[data-compare-widget="use_NBS_classes"]')
    widget.wait_for(state="visible", timeout=10000)
    assert compare.locator("[data-compare-lever]").count() == 1
    assert compare.locator('[data-compare-value="no-nbs"]').inner_text().endswith("No NbS: []")
    assert '"Constructed wetlands"' in compare.locator('[data-compare-value="nbs"]').inner_text()
    assert compare.locator("[data-compare-code-added]").count() == 0
    assert compare.locator("[data-compare-code-removed]").count() == 0
    # The Raster Statistics pair is the same in both scenarios.
    assert compare.locator("[data-compare-same]").get_attribute("data-compare-same") == "1"
    assert compare.locator("[data-compare-warning]").count() == 0
    compare.get_by_role("tab", name="Chart", exact=True).click()

    frame_nodes(page, [compares["difference"]])
    _assert_difference_mapped(page, compares["difference"], "the flood depth change before its close-up")
    save_node_closeup(
        page, "scout-flood-depth-change", compares["difference"],
        test_name="test_two_flood_scenarios_are_mapped_and_charted",
        sweep_toasts=True,
    )
    frame_nodes(page, [compares["chart"]])
    _assert_chart_drew(page, compares["chart"])
    save_node_closeup(
        page, "scout-flood-median-depth", compares["chart"],
        test_name="test_two_flood_scenarios_are_mapped_and_charted",
        sweep_toasts=True,
    )
