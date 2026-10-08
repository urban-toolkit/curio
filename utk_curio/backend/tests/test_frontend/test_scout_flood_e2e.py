"""SCOUT's flood example in two scenarios, compared on an Autark map and a pie chart (#662).

The shipped test dataflow ``FloodScenarios.json``: Parameter nodes for the
period and SCOUT's corners (its whole flood grid), and two scenarios, "No NbS"
and "All NbS" (its copy), each holding a Flood Projection (``scout.flood@1``,
SCOUT's own ``simulate_flood_projection``) with its choice of nature-based
solutions (NbS), which returns the depth and SCOUT's own metrics, a node taking
the depth for an Autark map, and a node taking SCOUT's metrics. One Compare Scenarios node, in Difference, maps the absolute change in
depth through the Autark node's map code (#723); the other draws each
scenario's median flood depth, SCOUT's flood example's metric, on a pie chart
that plots each value as it is. Run All drives
the whole path:

1. Both Flood Projections read the Data Catalog's flood rasters for the region
   and the period (2020 - 2040) the Parameter nodes hold, and the nodes after
   them take the depth and SCOUT's metrics.
2. The difference is a 2592 by 2064 cell raster in EPSG:4326, on SCOUT's grid,
   whose cells are the size of SCOUT's depth with all NbS minus its depth
   without, as autk-db reads both (float32): 267,494 cells changed, 842,515 the
   same and 4,239,879 with no depth on one side or both.
3. The pie chart, its values not combined, draws SCOUT's median flood depth of each scenario, the first
   number of SCOUT's metrics CSV (``test_packages/test_scout_flood.py``).
4. What differs lists one lever, the Flood Projection, and in it one widget,
   the NbS choice; no code line differs, the maps and the nodes taking the
   depth and the metrics are the same, and nothing is warned.

The two close-ups are the frames.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_flood_e2e.py -v
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .test_compare_difference_e2e import _assert_difference_mapped, _band
from .test_compare_scenarios_e2e import _OUTPUT_ARTIFACT_JS, _assert_chart_drew
from .utils import (
    REPO_ROOT,
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
PROJECTION_TYPE = "scout.flood/flood-projection"
PYTHON_TYPE = "curio.builtin/computation-analysis"
COMPARE_TYPE = "curio.builtin/compare-scenarios"
COLORS = {"no-nbs": "#e76f51", "all-nbs": "#2a9d8f"}
CELL = 0.00010133941049058334
#: SCOUT's grid's north-west corner, and its size.
ORIGIN = (-90.6879323, 41.6242105)
WIDTH, HEIGHT = 2592, 2064

#: SCOUT's median flood depth in 2020 - 2040, without NbS and with every NbS
#: (``PINS`` in ``test_packages/test_scout_flood.py``).
MEDIANS = [7.163970947265625, 4.900075276692708]


def _compare_nodes(spec: dict) -> dict:
    return {
        node["metadata"]["compareScenarios"]["mode"]: node["id"]
        for node in spec["dataflow"]["nodes"]
        if node["type"] == COMPARE_TYPE
    }


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
             if node["type"] in (PROJECTION_TYPE, PYTHON_TYPE)]
    assert len(steps) == 6, steps

    # 1. Run All: both scenarios project SCOUT's flood for the shared region and period.
    run_all_and_wait(page, timeout_ms=300000)
    for node_id, node_type in steps:
        status = wait_for_node_settled(page, node_id, node_type=node_type, timeout_ms=120000)
        assert status == "done", f"{node_type} did not run: {read_node_error_text(node_locator(page, node_id))}"
    for node_id in compares.values():
        status = wait_for_node_settled(page, node_id, node_type=COMPARE_TYPE, timeout_ms=120000)
        assert status == "done", f"Compare Scenarios did not compare: {read_node_error_text(node_locator(page, node_id))}"

    # 2. The absolute difference, on SCOUT's grid, mapped.
    frame_nodes(page, [compares["difference"]])
    _assert_difference_mapped(page, compares["difference"], "the change in flood depth")
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
    assert len(cells) == WIDTH * HEIGHT
    finite = [v for v in cells if not math.isnan(v)]
    assert min(finite) == 0.0
    counts = (sum(1 for v in finite if v > 0), sum(1 for v in finite if v == 0), len(cells) - len(finite))
    assert counts == (267494, 842515, 4239879), counts
    assert max(finite) == pytest.approx(10.645233154296875, abs=1e-5)

    # 3. The pie chart of the median flood depth, SCOUT's numbers.
    frame_nodes(page, [compares["chart"]])
    _assert_chart_drew(page, compares["chart"], "pie")
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, compares["chart"])
    assert artifact, "Compare Scenarios shows no saved table"
    stacked = load_artifact_as_dict(artifact)
    assert stacked["dataType"] == "dataframe", stacked["dataType"]
    table = stacked["data"]
    # The stored table's columns come back by name, not in their order.
    assert sorted(table) == ["mean flood depth", "median flood depth", "scenario", "scenario_name"], list(table)
    assert table["scenario"] == ["no-nbs", "all-nbs"] and table["scenario_name"] == ["No NbS", "All NbS"]
    assert table["median flood depth"] == pytest.approx(MEDIANS, rel=1e-12)

    # 4. What differs: the NbS choice, and nothing else.
    compare = node_locator(page, compares["chart"])
    compare.get_by_role("tab", name="What differs", exact=True).click()
    widget = compare.locator('[data-compare-widget="use_NBS_classes"]')
    widget.wait_for(state="visible", timeout=10000)
    assert compare.locator("[data-compare-lever]").count() == 1
    assert compare.locator("[data-compare-widget]").count() == 1
    assert compare.locator('[data-compare-value="no-nbs"]').first.inner_text().endswith("No NbS: []")
    assert '"Constructed wetlands"' in compare.locator('[data-compare-value="all-nbs"]').first.inner_text()
    assert compare.locator("[data-compare-code-added]").count() == 0
    assert compare.locator("[data-compare-code-removed]").count() == 0
    # The maps and the nodes taking the depth and the metrics are the same in
    # both scenarios.
    assert compare.locator("[data-compare-same]").get_attribute("data-compare-same") == "3"
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
    _assert_chart_drew(page, compares["chart"], "pie")
    save_node_closeup(
        page, "scout-flood-median-depth", compares["chart"],
        test_name="test_two_flood_scenarios_are_mapped_and_charted",
        sweep_toasts=True,
    )
