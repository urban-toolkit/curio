"""SCOUT's weather routing example, mapped through Autark and charted (#662, step 20).

The shipped test dataflow ``WeatherRouting.json`` is SCOUT's weather routing
example: a Data Loading node that loads downtown Chicago's roads from the Data
Catalog (``data.osm.chicago-downtown-roads``, OpenStreetMap), and the
``scout.routing@1`` package's Weather
Routing node set as SCOUT's example sets it (Default weights, K 1, midnight on
6 July 2025), which reads the roads through its layer chip
``[!! input_0:table_osm_roads !!]``. It finds SCOUT's two routes, the fastest
(SCOUT's C) and the one its weather weights favor (D). Two scenarios,
"Fastest route" and "Weather-aware route" (its copy), each keep one of them: a
node with the route as a band, and one with its metrics. An Autark map draws
both scenarios' routes in their colors, SCOUT's, with a darker outline; four
Compare Scenarios nodes chart the two routes' duration, distance, rain exposure
and wind exposure, one bar per scenario, as SCOUT's example compares them. Run
All drives the whole path:

1. Weather Routing routes over the roads the Data Loading node loads.
2. The map draws.
3. Each chart draws both scenarios in their colors from the stacked table,
   whose metrics are the ones the package's own test pins for the same roads
   (``EXAMPLE`` in ``test_packages/test_scout_routing.py``).
4. What differs lists two levers, each scenario's two nodes, each with the one
   code line that names the route it keeps; nothing is warned.

The five close-ups are the frames.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_routing_e2e.py -v
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from utk_curio.backend.tests.test_packages.test_scout_routing import EXAMPLE, EXAMPLE_CHARTS, EXAMPLE_SCENARIOS

from .test_compare_scenarios_e2e import _CHART_STATE_JS, _COLOR_PIXELS_JS, _OUTPUT_ARTIFACT_JS
from .utils import (
    REPO_ROOT,
    api_json,
    assert_autark_map_drawn,
    assert_vega_canvas_rendered,
    frame_nodes,
    load_artifact_as_dict,
    node_locator,
    park_pointer,
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

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "WeatherRouting.json"
PACKAGE_DIR = "scout.routing@1"
ROUTING_TYPE = "scout.routing/weather-routing"
AUTARK_TYPE = "curio.builtin/autk-grammar"
LOADING_TYPE = "curio.builtin/data-loading"
COMPARE_TYPE = "curio.builtin/compare-scenarios"
#: The two scenarios' colors, SCOUT's: the fastest route, the weather-aware one.
ROUTE_COLORS = [color for _name, color, _route in EXAMPLE_SCENARIOS.values()]
TEST_NAME = "test_scouts_routing_example_is_mapped_and_charted"
#: The stacked table's metric columns, and where each sits in an ``EXAMPLE`` row.
COLUMNS = {"distance": 3, "duration": 4, "rain_exposure": 5, "wind_exposure": 6}
#: The opacity of each of a node's header tools, which show under the pointer,
#: while focus is inside the node, or while it is selected.
_TOOLS_OPACITY_JS = """(id) => {
    const card = document.getElementById(`${id}resizable`);
    return card ? [...card.querySelectorAll('.curio-node-tools')].map((el) => Number(getComputedStyle(el).opacity)) : null;
}"""


def _release_nodes(page, node_id: str) -> None:
    """Click the empty pane where the pointer parks, so no node keeps the
    pointer, focus or the selection, and wait for *node_id*'s header tools to
    hide."""
    park_pointer(page)
    page.mouse.down()
    page.mouse.up()
    opacities = None
    deadline = time.time() + 5
    while time.time() < deadline:
        opacities = page.evaluate(_TOOLS_OPACITY_JS, node_id)
        if opacities is not None and all(opacity == 0 for opacity in opacities):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"{node_id}'s header tools still show before its close-up: opacities {opacities}")


def _assert_chart_drew(page, node_id: str) -> None:
    """The bars compiled with no problem, and the canvas holds both scenarios'
    colors."""
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
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_COLOR_PIXELS_JS, [node_id, ROUTE_COLORS])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart does not draw both routes' colors {ROUTE_COLORS}: pixels {counts}")


def _assert_stacked_table(page, node_id: str) -> None:
    """The node's saved table: each scenario's route, with the metrics the
    package's test pins for these roads."""
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, "Compare Scenarios shows no saved table"
    stacked = load_artifact_as_dict(artifact)
    assert stacked["dataType"] == "dataframe", stacked["dataType"]
    table = stacked["data"]
    expected = [(sid, row) for sid, (_n, _c, route) in EXAMPLE_SCENARIOS.items() for row in EXAMPLE if row[0] == route]
    assert table["scenario"] == [sid for sid, _row in expected]
    assert table["scenario_name"] == [EXAMPLE_SCENARIOS[sid][0] for sid, _row in expected]
    assert table["route"] == [row[0] for _sid, row in expected]
    for column, at in COLUMNS.items():
        tolerance = 1e-6 if column in ("distance", "duration") else 1e-3
        assert table[column] == pytest.approx([row[at] for _sid, row in expected], abs=tolerance), column


def test_scouts_routing_example_is_mapped_and_charted(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Weather Routing",
        username="scout_weather_routing",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    assert PACKAGE_DIR in store, (
        f"{PACKAGE_DIR} is not in the account's store {store}: start the stack --with-examples"
    )
    nodes = spec["dataflow"]["nodes"]
    edges = spec["dataflow"]["edges"]
    for node in nodes:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    (routing,) = [n["id"] for n in nodes if n["type"] == ROUTING_TYPE]
    (loader_id,) = [n["id"] for n in nodes if n["type"] == LOADING_TYPE]
    # The routing node reads the loaded roads through its layer chip.
    assert [e["source"] for e in edges if e["target"] == routing] == [loader_id]
    (map_id,) = [n["id"] for n in nodes if n["type"] == AUTARK_TYPE and "map" in json.loads(n["content"])]
    charts = {n["metadata"]["compareScenarios"]["chart"]["y"]: n["id"] for n in nodes if n["type"] == COMPARE_TYPE}
    assert list(charts) == EXAMPLE_CHARTS

    # 1. Run All: SCOUT's two routes over the catalog's roads.
    run_all_and_wait(page, timeout_ms=300000)
    status = wait_for_node_settled(page, loader_id, node_type=LOADING_TYPE, timeout_ms=120000)
    assert status == "done", f"the roads did not load: {read_node_error_text(node_locator(page, loader_id))}"
    status = wait_for_node_settled(page, routing, node_type=ROUTING_TYPE, timeout_ms=120000)
    assert status == "done", f"Weather Routing did not run: {read_node_error_text(node_locator(page, routing))}"
    for node_id in charts.values():
        status = wait_for_node_settled(page, node_id, node_type=COMPARE_TYPE, timeout_ms=120000)
        assert status == "done", f"Compare Scenarios did not compare: {read_node_error_text(node_locator(page, node_id))}"

    # 2. The routes map.
    frame_nodes(page, [map_id])
    assert_autark_map_drawn(page, map_id, timeout=60000)

    # 3. The four charts, from the metrics the package's test pins.
    for column in EXAMPLE_CHARTS:
        frame_nodes(page, [charts[column]])
        _assert_chart_drew(page, charts[column])
        _assert_stacked_table(page, charts[column])

    # 4. What differs: the route each scenario keeps, and nothing else.
    frame_nodes(page, [charts["duration"]])
    compare = node_locator(page, charts["duration"])
    compare.get_by_role("tab", name="What differs", exact=True).click()
    compare.locator("[data-compare-lever]").first.wait_for(state="visible", timeout=10000)
    assert compare.locator("[data-compare-lever]").count() == 2
    assert compare.locator("[data-compare-widget]").count() == 0
    assert sorted(compare.locator("[data-compare-code-added]").all_inner_texts()) == [
        '+ return metrics[metrics["route"] == "weighted-route"]',
        '+ route = routes[routes["weight_type"] == "weighted-route"]']
    assert compare.locator("[data-compare-code-removed]").count() == 2
    assert compare.locator("[data-compare-warning]").count() == 0
    compare.get_by_role("tab", name="Chart", exact=True).click()

    frame_nodes(page, [map_id])
    assert_autark_map_drawn(page, map_id, timeout=30000)
    _release_nodes(page, map_id)
    save_node_closeup(page, "scout-routing-routes-map", map_id, test_name=TEST_NAME, sweep_toasts=True)
    for column in EXAMPLE_CHARTS:
        frame_nodes(page, [charts[column]])
        _assert_chart_drew(page, charts[column])
        _release_nodes(page, charts[column])
        save_node_closeup(
            page, f"scout-routing-{column.replace('_', '-')}", charts[column],
            test_name=TEST_NAME, sweep_toasts=True,
        )
