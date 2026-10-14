"""SCOUT's flood example in two scenarios, compared on an Autark map and a Vega-Lite table (#662).

The shipped test dataflow ``FloodScenarios.json``: Parameter nodes for the
period and SCOUT's corners (its whole flood grid), and two scenarios, "No NbS"
and "All NbS" (its copy), each holding a Flood Projection (``scout.flood@1``,
SCOUT's own ``simulate_flood_projection``) with its choice of nature-based
solutions (NbS), which returns the depth and SCOUT's own metrics, a node taking
the depth for an Autark map, and a node taking SCOUT's metrics. A Raster
Calculator takes the absolute change in depth, which an Autark map draws, and a
Vega-Lite node comparing the scenarios shows SCOUT's metrics in a table. Run All
drives the whole path:

1. Both Flood Projections read the Data Catalog's flood rasters for the region
   and the period (2020 - 2050) the Parameter nodes hold, and the nodes after
   them take the depth and SCOUT's metrics.
2. The difference is a 2592 by 2064 cell raster in EPSG:4326, on SCOUT's grid,
   whose cells are the size of SCOUT's depth with all NbS minus its depth
   without: 267,494 cells changed, 842,515 the same and 4,239,879 with no depth
   on one side or both. Its map draws it, its legend titled.
3. SCOUT's median flood depth of each scenario, the first number of SCOUT's
   metrics (``test_packages/test_scout_flood.py``), and the table draws both
   scenarios' colors.

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

from .utils import (
    OUTPUT_ARTIFACT_JS,
    REPO_ROOT,
    assert_autark_map_drawn,
    assert_scenario_colors_drawn,
    assert_vega_canvas_rendered,
    fetch_raster,
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
MAP_TYPE = "curio.builtin/autk-grammar"
VEGA_TYPE = "curio.builtin/vis-vega"
COLORS = {"no-nbs": "#e76f51", "all-nbs": "#2a9d8f"}
CELL = 0.00010133941049058334
#: SCOUT's grid's north-west corner, and its size.
ORIGIN = (-90.6879323, 41.6242105)
WIDTH, HEIGHT = 2592, 2064

#: SCOUT's median flood depth in 2020 - 2050, without NbS and with every NbS
#: (``PINS`` in ``test_packages/test_scout_flood.py``).
MEDIANS = [7.163970947265625, 4.900075276692708]

# The title of the node's map legend, which autk-map writes as the legend's
# first child (`#autkMapLegend`, one per map, so read inside the node).
_LEGEND_TITLE_JS = """(id) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const heading = node && node.querySelector("#autkMapLegend")?.firstElementChild;
    return heading ? heading.textContent : null;
}"""


def _one(spec: dict, node_type: str, **where) -> dict:
    nodes = [n for n in spec["dataflow"]["nodes"] if n["type"] == node_type
             and all(n.get(k) == v for k, v in where.items())]
    assert len(nodes) == 1, (node_type, where, [n["id"] for n in nodes])
    return nodes[0]


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
    # The absolute difference: a Python node calling curio_raster_calculate.
    calculator = _one(spec, PYTHON_TYPE, title="Flood depth change")["id"]
    change_map = _one(spec, MAP_TYPE, title="Flood depth change map")["id"]
    table = _one(spec, VEGA_TYPE)["id"]
    steps = [(node["id"], node["type"]) for node in spec["dataflow"]["nodes"]
             if node["type"] in (PROJECTION_TYPE, PYTHON_TYPE) and node["id"] != calculator]
    assert len(steps) == 6, steps

    # 1. Run All: both scenarios project SCOUT's flood for the shared region and period.
    run_all_and_wait(page, timeout_ms=300000)
    for node_id, node_type in [*steps, (calculator, PYTHON_TYPE)]:
        status = wait_for_node_settled(page, node_id, node_type=node_type, timeout_ms=120000)
        assert status == "done", f"{node_type} did not run: {read_node_error_text(node_locator(page, node_id))}"

    # 2. The absolute difference, on SCOUT's grid, mapped.
    artifact = page.evaluate(OUTPUT_ARTIFACT_JS, calculator)
    assert artifact, "the difference node shows no saved raster"
    values, profile = fetch_raster(artifact)
    assert (str(profile["crs"]), profile["width"], profile["height"]) == ("EPSG:4326", WIDTH, HEIGHT), profile
    transform = profile["transform"]
    assert (transform.c, transform.f) == pytest.approx(ORIGIN, abs=1e-9), transform
    assert (transform.a, transform.e) == pytest.approx((CELL, -CELL), rel=1e-9), transform
    cells = values[0].ravel().tolist()
    finite = [v for v in cells if not math.isnan(v)]
    assert min(finite) == 0.0
    counts = (sum(1 for v in finite if v > 0), sum(1 for v in finite if v == 0), len(cells) - len(finite))
    assert counts == (267494, 842515, 4239879), counts
    assert max(finite) == pytest.approx(10.645233154296875, abs=1e-5)
    status = wait_for_node_settled(page, change_map, node_type=MAP_TYPE, timeout_ms=120000)
    assert status == "done", f"the change map did not draw: {read_node_error_text(node_locator(page, change_map))}"
    frame_nodes(page, [change_map])
    assert_autark_map_drawn(page, change_map, timeout=60000, attach_as="the change in flood depth")
    page.wait_for_function(f"() => ({_LEGEND_TITLE_JS})({json.dumps(change_map)}) === 'Flood depth change (m)'",
                           timeout=15000)

    # 3. SCOUT's medians, and the table comparing the scenarios.
    medians = []
    for scenario in spec["dataflow"]["scenarios"]:
        metrics = _one(spec, PYTHON_TYPE, title=f"Metrics - {scenario['name']}")["id"]
        stored = load_artifact_as_dict(page.evaluate(OUTPUT_ARTIFACT_JS, metrics))
        assert stored["dataType"] == "dataframe", stored["dataType"]
        medians.extend(stored["data"]["median flood depth"])
    assert medians == pytest.approx(MEDIANS, rel=1e-12)
    status = wait_for_node_settled(page, table, node_type=VEGA_TYPE, timeout_ms=120000)
    assert status == "done", f"the table did not draw: {read_node_error_text(node_locator(page, table))}"
    frame_nodes(page, [table])
    assert_vega_canvas_rendered(page, table, timeout=30000)
    assert_scenario_colors_drawn(page, table, COLORS.values())

    save_node_closeup(
        page, "scout-flood-depth-change", change_map,
        test_name="test_two_flood_scenarios_are_mapped_and_charted",
        sweep_toasts=True,
    )
    save_node_closeup(
        page, "scout-flood-metrics", table,
        test_name="test_two_flood_scenarios_are_mapped_and_charted",
        sweep_toasts=True,
    )
