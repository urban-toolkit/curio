"""SCOUT's weather routing in two scenarios, mapped through Autark and charted (#662, step 20).

The shipped test dataflow ``WeatherRouting.json``: an Autark node that loads the
Chicago Loop's roads from the committed OpenStreetMap extract, a start-time
Parameter node, and two scenarios, "Avoid rain" and "Avoid wind" (its copy),
each holding the ``scout.routing@1`` package's Weather Routing node with its
weights, which reads the Autark node's roads layer through its layer chip
``[!! input 0:table_osm_roads !!]``, then a node that takes its routes and one
that takes their metrics. An
Autark map draws both scenarios' routes over the roads; four Compare Scenarios
nodes chart each route's duration, distance, rain exposure and wind exposure by
scenario (#720). Run All drives the whole path:

1. Both Weather Routing nodes route over the roads the Autark node loads, with
   the weather the WRF group gives at noon in Chicago, the time the Parameter
   node holds.
2. The map draws.
3. Each chart draws both scenarios in their colors from the stacked table,
   whose routes and metrics are the ones the package's own test pins for the
   same roads (``EXAMPLE`` in ``test_packages/test_scout_routing.py``).
4. What differs lists one lever, the Weather Routing node, and in it two
   widgets, the rain and wind weights; no code line differs, and nothing is
   warned.

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

from utk_curio.backend.tests.test_packages.test_scout_routing import EXAMPLE

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
COMPARE_TYPE = "curio.builtin/compare-scenarios"
SCENARIOS = {"avoid-rain": ("Avoid rain", "#2a9d8f"), "avoid-wind": ("Avoid wind", "#e76f51")}
TEST_NAME = "test_two_routing_scenarios_are_mapped_and_charted"
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
    hide: a close-up taken after a click inside a node (the What differs tabs)
    would show them."""
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
    """The grouped bars compiled with no problem, and the canvas holds both
    scenarios' colors."""
    deadline = time.time() + 60
    state = None
    while time.time() < deadline:
        state = page.evaluate(_CHART_STATE_JS, [node_id, "grouped-bar"])
        if state in ("drawn", "problem"):
            break
        page.wait_for_timeout(250)
    problem = node_locator(page, node_id).locator("[data-compare-chart-problem]").all_inner_texts()
    assert state == "drawn", f"the chart's compile ended {state!r}: {problem}"
    assert_vega_canvas_rendered(page, node_id, timeout=30000)
    colors = [color for _name, color in SCENARIOS.values()]
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_COLOR_PIXELS_JS, [node_id, colors])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart does not draw both scenarios' colors {colors}: pixels {counts}")


def _assert_stacked_table(page, node_id: str) -> None:
    """The node's saved table: each scenario's routes, in its order, with the
    metrics the package's test pins for these roads."""
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, "Compare Scenarios shows no saved table"
    stacked = load_artifact_as_dict(artifact)
    assert stacked["dataType"] == "dataframe", stacked["dataType"]
    table = stacked["data"]
    # The stored table's columns come back by name, not in their order.
    assert sorted(table) == sorted([
        "route", "route_index", "distance", "duration", "rain_exposure", "heat_exposure", "wind_exposure",
        "humidity_exposure", "scenario", "scenario_name"]), list(table)
    expected = [(scenario, row) for scenario in SCENARIOS for row in EXAMPLE[scenario]]
    assert table["scenario"] == [scenario for scenario, _row in expected]
    assert table["scenario_name"] == [SCENARIOS[scenario][0] for scenario, _row in expected]
    assert table["route"] == [row[0] for _scenario, row in expected]
    assert table["route_index"] == [row[1] for _scenario, row in expected]
    for column, at in COLUMNS.items():
        tolerance = 1e-6 if column in ("distance", "duration") else 1e-3
        assert table[column] == pytest.approx([row[at] for _scenario, row in expected], abs=tolerance), column


def test_two_routing_scenarios_are_mapped_and_charted(
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
    for node in nodes:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    routings = [n["id"] for n in nodes if n["type"] == ROUTING_TYPE]
    (loader_id,) = [n["id"] for n in nodes if n["type"] == AUTARK_TYPE and "data" in json.loads(n["content"])]
    # Both routing nodes read the loader's roads layer through their layer chip.
    assert {e["source"] for e in spec["dataflow"]["edges"] if e["target"] in routings} == {loader_id}
    (map_id,) = [n["id"] for n in nodes if n["type"] == AUTARK_TYPE and "map" in json.loads(n["content"])]
    compares = {n["metadata"]["compareScenarios"]["chart"]["y"]: n["id"] for n in nodes if n["type"] == COMPARE_TYPE}
    assert sorted(compares) == sorted(COLUMNS)

    # 1. Run All: both scenarios route over Autark's roads at the shared time.
    run_all_and_wait(page, timeout_ms=300000)
    status = wait_for_node_settled(page, loader_id, node_type=AUTARK_TYPE, timeout_ms=120000)
    assert status == "done", f"the Autark node did not load the roads: {read_node_error_text(node_locator(page, loader_id))}"
    for routing in routings:
        status = wait_for_node_settled(page, routing, node_type=ROUTING_TYPE, timeout_ms=120000)
        assert status == "done", f"Weather Routing did not run: {read_node_error_text(node_locator(page, routing))}"
    for node_id in compares.values():
        status = wait_for_node_settled(page, node_id, node_type=COMPARE_TYPE, timeout_ms=120000)
        assert status == "done", f"Compare Scenarios did not compare: {read_node_error_text(node_locator(page, node_id))}"

    # 2. The routes map.
    frame_nodes(page, [map_id])
    assert_autark_map_drawn(page, map_id, timeout=60000)

    # 3. The four charts, from the routes and metrics the package's test pins.
    for column in COLUMNS:
        frame_nodes(page, [compares[column]])
        _assert_chart_drew(page, compares[column])
        _assert_stacked_table(page, compares[column])

    # 4. What differs: the two weights, and nothing else.
    frame_nodes(page, [compares["duration"]])
    compare = node_locator(page, compares["duration"])
    compare.get_by_role("tab", name="What differs", exact=True).click()
    compare.locator('[data-compare-widget="rain"]').wait_for(state="visible", timeout=10000)
    assert compare.locator("[data-compare-lever]").count() == 1
    assert sorted(compare.locator("[data-compare-widget]").evaluate_all(
        "(els) => els.map((el) => el.getAttribute('data-compare-widget'))")) == ["rain", "wind"]
    rain = compare.locator('[data-compare-widget="rain"]')
    assert "0.85834" in rain.locator('[data-compare-value="avoid-rain"]').inner_text()
    assert "0.01657" in rain.locator('[data-compare-value="avoid-wind"]').inner_text()
    assert compare.locator("[data-compare-code-added]").count() == 0
    assert compare.locator("[data-compare-code-removed]").count() == 0
    assert compare.locator("[data-compare-same]").get_attribute("data-compare-same") == "2"
    assert compare.locator("[data-compare-warning]").count() == 0
    compare.get_by_role("tab", name="Chart", exact=True).click()

    frame_nodes(page, [map_id])
    assert_autark_map_drawn(page, map_id, timeout=30000)
    _release_nodes(page, map_id)
    save_node_closeup(page, "scout-routing-routes-map", map_id, test_name=TEST_NAME, sweep_toasts=True)
    for column in COLUMNS:
        frame_nodes(page, [compares[column]])
        _assert_chart_drew(page, compares[column])
        _release_nodes(page, compares[column])
        save_node_closeup(
            page, f"scout-routing-{column.replace('_', '-')}", compares[column],
            test_name=TEST_NAME, sweep_toasts=True,
        )
