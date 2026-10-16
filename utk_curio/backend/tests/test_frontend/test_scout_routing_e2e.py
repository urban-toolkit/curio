"""SCOUT's weather routing example, mapped through Autark and charted in its scenarios' colors (#662; step 8 of #819's port).

The shipped test dataflow ``WeatherRouting.json`` is SCOUT's weather routing
example: an Autark node that loads the roads of SCOUT's box, in downtown
Chicago, from the committed OpenStreetMap extract, and the Weather Routing node
of the model package ``model.scout.weather-gnn@1``, set as SCOUT's example sets
it, which reads the roads layer through its layer chip
``[!! input_0:table_osm_roads !!]``. It finds SCOUT's two routes, the fastest
(SCOUT's C) and the one its weather weights favor (D). Two scenarios, "Fastest
route" and "Weather-aware route" (its copy), each keep one of them: a node with
the route and one with its metrics. An Autark map draws both routes over the
roads, each with a ``width``, in the color of its scenario's box, which Curio
gives the layer that names the scenario; four Compare Scenarios nodes chart the
two routes' duration, distance, rain exposure and wind exposure, one bar per
scenario, in the same colors. Run All drives the whole path:

1. Weather Routing routes over the roads the Autark node loads.
2. The map draws each route in its box's color.
3. Each chart fills each scenario's bar with its box's color, and its stacked
   table holds the metrics the package's own test pins for the same roads
   (``EXAMPLE`` in ``test_packages/test_scout_routing.py``).
4. What differs lists two levers, each scenario's two nodes, each with the one
   code line that names the route it keeps; nothing is warned.
5. The Fastest route's box takes another color in the scenario's details, from
   the Scenario Catalog drawer's In project tab, and Run All runs the flow
   again: the map draws that route in the new color and none in the old one,
   and every chart fills its bar with the new color; the other scenario keeps
   its own.

A route's color is read from the pixels of the map's canvas, which its close-up
shows. A bar's color is the fill Vega gives it, read from the chart's scene
graph: Vega draws the charts on a canvas, and its SVG renderer writes the same
fill.

The frames: the close-ups of the map and of each chart, then of the map and the
duration chart again once the box has its new color.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_routing_e2e.py -v
"""
from __future__ import annotations

import base64
import json
import time
from io import BytesIO
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
    close_scenario_details,
    close_scenario_drawer,
    frame_nodes,
    load_artifact_as_dict,
    node_locator,
    open_in_project_tab,
    open_scenario_details,
    park_pointer,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_all_and_wait,
    save_node_closeup,
    stub_login_and_enter_workflow,
    wait_for_node_run_to_end,
    wait_for_node_settled,
    watch_node_run,
)
from .utils.node_drawings import _AUTK_MAP_PIXELS_IN_FRAME_JS

if TYPE_CHECKING:
    from .utils import FrontendPage

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "WeatherRouting.json"
PACKAGE_DIR = "model.scout.weather-gnn@1"
ROUTING_TYPE = "model.scout.weather-gnn/weather-routing"
AUTARK_TYPE = "curio.builtin/autk-grammar"
COMPARE_TYPE = "curio.builtin/compare-scenarios"
TEST_NAME = "test_two_routing_scenarios_are_mapped_and_charted"
#: The stacked table's metric columns, and where each sits in an ``EXAMPLE`` row.
COLUMNS = {"distance": 3, "duration": 4, "rain_exposure": 5, "wind_exposure": 6}
#: The scenario whose box takes another color in step 5, and that color: far
#: from both scenarios' own blues and from the roads' grays.
RECOLORED = "fastest"
NEW_COLOR = "#d81b60"
#: A map pixel within this distance (RGB) of a color is drawn in it.
MAP_COLOR_DISTANCE = 40
#: Each route covers at least this many pixels of the map, and a color no
#: route has at most this many (a few antialiased edges).
ROUTE_PIXELS = 50
STRAY_PIXELS = 5
#: How long Run All may take: the roads load, Weather Routing runs, then the
#: maps and charts draw.
RUN_MS = 300000

#: The opacity of each of a node's header tools, which show under the pointer,
#: while focus is inside the node, or while it is selected.
_TOOLS_OPACITY_JS = """(id) => {
    const card = document.getElementById(`${id}resizable`);
    return card ? [...card.querySelectorAll('.curio-node-tools')].map((el) => Number(getComputedStyle(el).opacity)) : null;
}"""

# Before the page's own scripts: keep every Vega view by the element it draws
# in, whenever the charts' Vega module is set on the window (useVega.ts).
_KEEP_VEGA_VIEWS_INIT = """(() => {
    let vega;
    const keep = (module) => {
        if (!module || !module.View || module.View.prototype.__curioKeepsViews) return;
        const initialize = module.View.prototype.initialize;
        module.View.prototype.initialize = function (element, ...rest) {
            const id = typeof element === "string" ? element.replace(/^#/, "") : element && element.id;
            if (id) (window.__curioVegaViews = window.__curioVegaViews || {})[id] = this;
            return initialize.call(this, element, ...rest);
        };
        module.View.prototype.__curioKeepsViews = true;
    };
    Object.defineProperty(window, "__curio_vega", {
        configurable: true,
        get() { return vega; },
        set(module) { vega = module; keep(module); },
    });
})();"""

# Each bar of a chart's last view: its scenario and the fill Vega gives it.
_BAR_FILLS_JS = """(id) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    if (!view) return null;
    const bars = [];
    const visit = (node) => {
        if (!node) return;
        if (node.marktype === "rect" && node.role === "mark") {
            for (const item of node.items || []) {
                bars.push([item.datum ? item.datum.scenario_name : null, String(item.fill)]);
            }
            return;
        }
        for (const child of node.items || []) visit(child);
    };
    visit(view.scenegraph().root);
    return bars;
}"""

# The color of a scenario's box on the canvas: the border of its frame.
_BOX_COLOR_JS = """(id) => {
    const frame = document.querySelector(`[data-scenario-frame="${id}"]`);
    return frame ? getComputedStyle(frame).borderTopColor : null;
}"""


def _rgb(color: str) -> tuple[int, int, int]:
    """``#rrggbb`` or ``rgb(r, g, b)`` as a tuple."""
    if color.startswith("#"):
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(int(part) for part in color[color.index("(") + 1:color.index(")")].split(",")[:3])


def _hex(color: str) -> str:
    return "#{:02x}{:02x}{:02x}".format(*_rgb(color))


def _box_colors(page) -> dict[str, str]:
    """Each scenario's box color, as the canvas draws it."""
    colors = {}
    for scenario_id in EXAMPLE_SCENARIOS:
        drawn = page.evaluate(_BOX_COLOR_JS, scenario_id)
        assert drawn, f"the canvas draws no box for the scenario {scenario_id}"
        colors[scenario_id] = _hex(drawn)
    return colors


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


def _map_pixels(page, map_id: str, colors: list[str]) -> list[int]:
    """How many pixels of the map's canvas are each of *colors*."""
    from PIL import Image

    frame_nodes(page, [map_id])
    url = page.evaluate(_AUTK_MAP_PIXELS_IN_FRAME_JS, map_id)
    assert url, f"the map {map_id} has no canvas"
    image = Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
    targets = [_rgb(color) for color in colors]
    limit = MAP_COLOR_DISTANCE ** 2
    counts = [0] * len(targets)
    for pixel in image.getdata():
        for k, target in enumerate(targets):
            if sum((a - b) ** 2 for a, b in zip(pixel, target)) <= limit:
                counts[k] += 1
    return counts


def _assert_routes_drawn(page, map_id: str, drawn: dict[str, str], gone: list[str]) -> None:
    """The map draws each route of *drawn* (scenario to color) in its color, and
    nothing in a color of *gone*."""
    colors = list(drawn.values()) + gone
    counts = None
    deadline = time.time() + 30
    while time.time() < deadline:
        counts = _map_pixels(page, map_id, colors)
        if (all(count >= ROUTE_PIXELS for count in counts[:len(drawn)])
                and all(count <= STRAY_PIXELS for count in counts[len(drawn):])):
            return
        page.wait_for_timeout(500)
    found = dict(zip([f"{sid} {color}" for sid, color in drawn.items()] + [f"no longer {c}" for c in gone], counts))
    raise AssertionError(f"the map does not draw each route in its box's color: pixels {found}")


def _assert_chart_drew(page, node_id: str, colors: list[str]) -> None:
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
        counts = page.evaluate(_COLOR_PIXELS_JS, [node_id, colors])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart does not draw both routes' colors {colors}: pixels {counts}")


def _assert_bars_filled(page, node_id: str, colors: dict[str, str]) -> None:
    """The chart has one bar per scenario, filled with that scenario's box
    color (*colors*, scenario to color)."""
    expected = {EXAMPLE_SCENARIOS[sid][0]: color.lower() for sid, color in colors.items()}
    bars = None
    deadline = time.time() + 30
    while time.time() < deadline:
        bars = page.evaluate(_BAR_FILLS_JS, node_id)
        if bars and len(bars) == len(expected) and {name: fill.lower() for name, fill in bars} == expected:
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart {node_id}'s bars are {bars}, not each scenario in its box's color {expected}")


def _assert_stacked_table(page, node_id: str) -> None:
    """The node's saved table: each scenario's route, with the metrics the
    package's test pins for these roads."""
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, "Compare Scenarios shows no saved table"
    stacked = load_artifact_as_dict(artifact)
    assert stacked["dataType"] == "dataframe", stacked["dataType"]
    table = stacked["data"]
    expected = [(sid, row) for sid, (_n, _c, route) in EXAMPLE_SCENARIOS.items() for row in EXAMPLE if row[0] == route]
    assert table["scenario"] == [sid for sid, _row in expected], table["scenario"]
    assert table["scenario_name"] == [EXAMPLE_SCENARIOS[sid][0] for sid, _row in expected]
    assert table["route"] == [row[0] for _sid, row in expected]
    for column, at in COLUMNS.items():
        tolerance = 1e-6 if column in ("distance", "duration") else 1e-3
        assert table[column] == pytest.approx([row[at] for _sid, row in expected], abs=tolerance), (column, table[column])


def test_two_routing_scenarios_are_mapped_and_charted(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(_KEEP_VEGA_VIEWS_INIT)
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
    require_webgpu(page)
    routings = [n["id"] for n in nodes if n["type"] == ROUTING_TYPE]
    assert len(routings) == 1, f"WeatherRouting.json has {len(routings)} Weather Routing nodes, not one"
    (routing,) = routings
    (loader_id,) = [n["id"] for n in nodes if n["type"] == AUTARK_TYPE and "data" in json.loads(n["content"])]
    # The routing node reads the loader's roads layer through its layer chip.
    assert [e["source"] for e in edges if e["target"] == routing] == [loader_id]
    (map_id,) = [n["id"] for n in nodes if n["type"] == AUTARK_TYPE and "map" in json.loads(n["content"])]
    charts = {n["metadata"]["compareScenarios"]["chart"]["y"]: n["id"] for n in nodes if n["type"] == COMPARE_TYPE}
    assert list(charts) == EXAMPLE_CHARTS

    # 1. Run All: SCOUT's two routes over the roads the Autark node loads.
    run_all_and_wait(page, timeout_ms=RUN_MS)
    status = wait_for_node_settled(page, loader_id, node_type=AUTARK_TYPE, timeout_ms=120000)
    assert status == "done", f"the Autark node did not load the roads: {read_node_error_text(node_locator(page, loader_id))}"
    status = wait_for_node_settled(page, routing, node_type=ROUTING_TYPE, timeout_ms=120000)
    assert status == "done", f"Weather Routing did not run: {read_node_error_text(node_locator(page, routing))}"
    for node_id in charts.values():
        status = wait_for_node_settled(page, node_id, node_type=COMPARE_TYPE, timeout_ms=120000)
        assert status == "done", f"Compare Scenarios did not compare: {read_node_error_text(node_locator(page, node_id))}"

    # 2. The routes map: each route in its box's color.
    colors = _box_colors(page)
    assert colors == {sid: color.lower() for sid, (_name, color, _route) in EXAMPLE_SCENARIOS.items()}, colors
    frame_nodes(page, [map_id])
    assert_autark_map_drawn(page, map_id, timeout=60000)
    _assert_routes_drawn(page, map_id, colors, gone=[NEW_COLOR])

    # 3. The four charts: each bar in its box's color, from the metrics the
    # package's test pins.
    for column in EXAMPLE_CHARTS:
        frame_nodes(page, [charts[column]])
        _assert_chart_drew(page, charts[column], list(colors.values()))
        _assert_bars_filled(page, charts[column], colors)
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
        '+ return routes[routes["weight_type"] == "weighted-route"]']
    assert compare.locator("[data-compare-code-removed]").count() == 2
    assert compare.locator("[data-compare-warning]").count() == 0
    compare.get_by_role("tab", name="Chart", exact=True).click()

    frame_nodes(page, [map_id])
    assert_autark_map_drawn(page, map_id, timeout=30000)
    _release_nodes(page, map_id)
    save_node_closeup(page, "scout-routing-routes-map", map_id, test_name=TEST_NAME, sweep_toasts=True)
    for column in EXAMPLE_CHARTS:
        frame_nodes(page, [charts[column]])
        _assert_chart_drew(page, charts[column], list(colors.values()))
        _release_nodes(page, charts[column])
        save_node_closeup(
            page, f"scout-routing-{column.replace('_', '-')}", charts[column],
            test_name=TEST_NAME, sweep_toasts=True,
        )

    # 5. The Fastest route's box takes another color, and the flow runs again:
    # its route and its bars follow, and the other scenario keeps its color.
    name = EXAMPLE_SCENARIOS[RECOLORED][0]
    open_in_project_tab(page)
    open_scenario_details(page, RECOLORED).get_by_label(f"Color of {name}").fill(NEW_COLOR)
    page.wait_for_function(
        f"([id, color]) => {{ const read = {_BOX_COLOR_JS}; return read(id) === color; }}",
        arg=[RECOLORED, "rgb({}, {}, {})".format(*_rgb(NEW_COLOR))],
        timeout=10000,
    )
    # The details and the drawer lie over the canvas, where the routes are.
    close_scenario_details(page)
    close_scenario_drawer(page)
    recolored = {**colors, RECOLORED: NEW_COLOR}
    assert _box_colors(page) == recolored
    watch_node_run(page, map_id)
    run_all_and_wait(page, timeout_ms=RUN_MS)
    status = wait_for_node_run_to_end(page, map_id, node_type=AUTARK_TYPE, timeout_ms=120000)
    assert status == "done", f"the map did not draw again: {read_node_error_text(node_locator(page, map_id))}"
    frame_nodes(page, [map_id])
    assert_autark_map_drawn(page, map_id, timeout=60000)
    _assert_routes_drawn(page, map_id, recolored, gone=[colors[RECOLORED]])
    for column in EXAMPLE_CHARTS:
        frame_nodes(page, [charts[column]])
        _assert_chart_drew(page, charts[column], list(recolored.values()))
        _assert_bars_filled(page, charts[column], recolored)

    frame_nodes(page, [map_id])
    assert_autark_map_drawn(page, map_id, timeout=30000)
    _release_nodes(page, map_id)
    save_node_closeup(page, "scout-routing-routes-map-recolored", map_id, test_name=TEST_NAME, sweep_toasts=True)
    frame_nodes(page, [charts["duration"]])
    _assert_chart_drew(page, charts["duration"], list(recolored.values()))
    _release_nodes(page, charts["duration"])
    save_node_closeup(page, "scout-routing-duration-recolored", charts["duration"], test_name=TEST_NAME,
                      sweep_toasts=True)
