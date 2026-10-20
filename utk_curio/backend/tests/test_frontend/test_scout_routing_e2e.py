"""SCOUT's weather routing example, mapped through Autark and charted in its scenarios' colors (#662; step 8 of #819's port).

The shipped test dataflow ``chicago-rain-wind-routing.json`` is SCOUT's weather routing
example: an Autark node that loads the roads of SCOUT's box, in downtown
Chicago, from the committed OpenStreetMap extract, and the Weather Routing node
of the model package ``model.scout.weather-gnn@1``, set as SCOUT's example sets
it, which reads the roads layer through its layer chip
``[!! input_0:table_osm_roads !!]``. It finds SCOUT's two routes, the fastest
(SCOUT's C) and the one its weather weights favor (D). Two scenarios, "Fastest
route" and "Weather-aware route" (its copy), each keep one of them: a node with
the route and one with its metrics. An Autark map outside both boxes draws both
routes over the roads, each with a ``width``, in the color of the box its input
comes from; four Bars nodes of Scout's (``curio.scout@1``) chart the two
routes' duration, distance, rain exposure and wind exposure, one bar per
scenario, in the same colors, each reading both scenarios' metrics stacked as
``inputs``.

The test adds a Compare Scenarios node beside the duration chart, over the
same two inputs, on which steps 3 and 4 read what they read on the dataflow's
Compare nodes until those went (step 6.4 of the plan answering komar41's
review removes it with the node). Run All drives the whole path:

1. Weather Routing routes over the roads the Autark node loads.
2. The map draws each route in its box's color.
3. Each chart fills each scenario's bar with its box's color, and the rows it
   reads hold the metrics the package's own test pins for the same roads
   (``EXAMPLE`` in ``test_packages/test_scout_routing.py``). The Compare node
   draws its bars, and its stacked table holds them too.
4. What differs, on the Compare node, lists two levers, each scenario's two
   nodes, each with the one code line that names the route it keeps; nothing
   is warned.
5. The Fastest route's box takes another color in the scenario's details, from
   the Scenario Catalog drawer's In project tab, and Run All runs the flow
   again: the map draws that route in the new color and none in the old one,
   and every chart fills its bar with the new color; the other scenario keeps
   its own.

A route's color is read from the pixels of the map's canvas, which its close-up
shows. A bar's color is the fill Vega gives it, read from the chart's scene
graph: Vega draws the charts on a canvas, and its SVG renderer writes the same
fill. The rows a chart reads are its view's ``inputs`` dataset.

The frames: the close-ups of the map and of each chart, then of the map and the
duration chart again once the box has its new color.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_routing_e2e.py -v
"""
from __future__ import annotations

import base64
import copy
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

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "chicago-rain-wind-routing.json"
PACKAGE_DIRS = ("curio.scout@1", "model.scout.weather-gnn@1")
ROUTING_TYPE = "model.scout.weather-gnn/weather-routing"
AUTARK_TYPE = "curio.builtin/autk-grammar"
BARS_TYPE = "curio.scout/bars"
COMPARE_TYPE = "curio.builtin/compare-scenarios"
#: The Compare Scenarios node the test adds beside the duration chart.
COMPARE_ID = "routing-compare-duration"
TEST_NAME = "test_two_routing_scenarios_are_mapped_and_charted"
#: The metric columns of the rows a chart reads, and where each sits in an
#: ``EXAMPLE`` row.
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

# The rows a chart's last view reads as its ``inputs`` dataset, as plain JSON.
_INPUTS_ROWS_JS = """(id) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    if (!view) return null;
    try {
        return JSON.parse(JSON.stringify(view.data("inputs")));
    } catch (error) {
        return null;
    }
}"""

# The color of a scenario's box on the canvas: the border of its frame.
_BOX_COLOR_JS = """(id) => {
    const frame = document.querySelector(`[data-scenario-frame="${id}"]`);
    return frame ? getComputedStyle(frame).borderTopColor : null;
}"""

#: The code the Compare node writes for its two inputs, the fastest route's
#: metrics and the weather-aware one's (``utils/compare/compareCode.ts``): the
#: dataflow's duration chart held it before it was Scout's Bars.
COMPARE_CODE = (
    "# Compare Scenarios writes this code from its inputs: each input, under the\n"
    "# id and the name of its scenario. It is written again when they change.\n"
    "return curio_stack_scenarios([\n"
    '    ("fastest", "Fastest route", [!! input_0 !!]),\n'
    '    ("weather-aware", "Weather-aware route", [!! input_1 !!]),\n'
    "])\n"
)


def _with_a_compare_node(spec: dict, chart_id: str) -> dict:
    """*spec* with a Compare Scenarios node beside the chart *chart_id*, over
    the chart's two inputs on the same circles, charting bars of duration as
    the dataflow's Compare node did. It holds the labels and the code it
    writes for its inputs, so a load writes nothing again."""
    spec = copy.deepcopy(spec)
    flow = spec["dataflow"]
    chart = next(node for node in flow["nodes"] if node["id"] == chart_id)
    labels = [{"scenario": s["id"], "name": s["name"], "color": s["color"]} for s in flow["scenarios"]]
    flow["nodes"].append({
        "id": COMPARE_ID, "type": COMPARE_TYPE,
        "x": chart["x"] + chart.get("width", 525) + 200, "y": chart["y"],
        "content": COMPARE_CODE,
        "out": "DEFAULT", "in": "DEFAULT", "goal": "Compare the two routes' duration, in minutes.",
        "metadata": {"keywords": [], "packageTemplateLabel": "Compare: duration", "compareScenarios": {
            "inputs": labels, "mode": "chart", "chart": {"preset": "bar", "y": "duration"},
        }},
    })
    flow["edges"] += [
        {**edge, "id": f"{edge['id']}-{COMPARE_ID}", "target": COMPARE_ID}
        for edge in flow["edges"] if edge["target"] == chart_id
    ]
    return spec


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


def _assert_colors_drawn(page, node_id: str, colors: list[str]) -> None:
    """The chart's canvas holds both scenarios' colors."""
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_COLOR_PIXELS_JS, [node_id, colors])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart {node_id} does not draw both routes' colors {colors}: pixels {counts}")


def _assert_chart_drew(page, node_id: str, colors: list[str]) -> None:
    """The Bars chart drew, and its canvas holds both scenarios' colors."""
    assert_vega_canvas_rendered(page, node_id, timeout=30000)
    _assert_colors_drawn(page, node_id, colors)


def _assert_compare_chart_drew(page, node_id: str, colors: list[str]) -> None:
    """The Compare node's bars compiled with no problem, and its canvas holds
    both scenarios' colors."""
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
    _assert_colors_drawn(page, node_id, colors)


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


def _expected_rows() -> list[tuple[str, tuple]]:
    """``(scenario id, EXAMPLE row)`` for each scenario's route, in box order."""
    return [(sid, row) for sid, (_n, _c, route) in EXAMPLE_SCENARIOS.items() for row in EXAMPLE if row[0] == route]


def _assert_metrics(table: dict, where: str) -> None:
    """*table*, columns of rows, holds each scenario's route with the metrics
    the package's test pins for these roads."""
    expected = _expected_rows()
    assert table["scenario"] == [sid for sid, _row in expected], (where, table["scenario"])
    assert table["scenario_name"] == [EXAMPLE_SCENARIOS[sid][0] for sid, _row in expected], where
    assert table["route"] == [row[0] for _sid, row in expected], where
    for column, at in COLUMNS.items():
        tolerance = 1e-6 if column in ("distance", "duration") else 1e-3
        assert table[column] == pytest.approx([row[at] for _sid, row in expected], abs=tolerance), (
            where, column, table[column],
        )


def _assert_chart_rows(page, node_id: str) -> None:
    """The rows the chart reads: one per scenario's metrics, in box order, each
    named from its box, with the metrics the package's test pins."""
    rows = None
    deadline = time.time() + 30
    while time.time() < deadline:
        rows = page.evaluate(_INPUTS_ROWS_JS, node_id)
        if rows and len(rows) == len(EXAMPLE_SCENARIOS):
            break
        page.wait_for_timeout(250)
    assert rows and len(rows) == len(EXAMPLE_SCENARIOS), f"the chart {node_id} reads the rows {rows}"
    assert [row["__input__"] for row in rows] == list(range(len(EXAMPLE_SCENARIOS))), rows
    columns = {name: [row.get(name) for row in rows] for name in ("scenario", "scenario_name", "route", *COLUMNS)}
    _assert_metrics(columns, f"the chart {node_id}'s rows")


def _assert_stacked_table(page, node_id: str) -> None:
    """The Compare node's saved table: each scenario's route, with the metrics
    the package's test pins for these roads."""
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, "Compare Scenarios shows no saved table"
    stacked = load_artifact_as_dict(artifact)
    assert stacked["dataType"] == "dataframe", stacked["dataType"]
    _assert_metrics(stacked["data"], "the Compare node's stacked table")


def test_two_routing_scenarios_are_mapped_and_charted(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(_KEEP_VEGA_VIEWS_INIT)
    shipped = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    nodes = shipped["dataflow"]["nodes"]
    edges = shipped["dataflow"]["edges"]
    routings = [n["id"] for n in nodes if n["type"] == ROUTING_TYPE]
    assert len(routings) == 1, f"chicago-rain-wind-routing.json has {len(routings)} Weather Routing nodes, not one"
    (routing,) = routings
    (loader_id,) = [n["id"] for n in nodes if n["type"] == AUTARK_TYPE and "data" in json.loads(n["content"])]
    # The routing node reads the loader's roads layer through its layer chip.
    assert [e["source"] for e in edges if e["target"] == routing] == [loader_id]
    (map_id,) = [n["id"] for n in nodes if n["type"] == AUTARK_TYPE and "map" in json.loads(n["content"])]
    assert not [n for n in nodes if n["type"] == COMPARE_TYPE], "the shipped dataflow still holds a Compare node"
    charts = {
        next(w.get("value", w["default"]) for w in n["metadata"]["widgets"] if w["name"] == "y"): n["id"]
        for n in nodes if n["type"] == BARS_TYPE
    }
    assert list(charts) == EXAMPLE_CHARTS
    spec = _with_a_compare_node(shipped, charts["duration"])
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
    missing = [package for package in PACKAGE_DIRS if package not in store]
    assert not missing, f"{missing} are not in the account's store {store}: start the stack --with-examples"
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    require_webgpu(page)

    # 1. Run All: SCOUT's two routes over the roads the Autark node loads.
    run_all_and_wait(page, timeout_ms=RUN_MS)
    status = wait_for_node_settled(page, loader_id, node_type=AUTARK_TYPE, timeout_ms=120000)
    assert status == "done", f"the Autark node did not load the roads: {read_node_error_text(node_locator(page, loader_id))}"
    status = wait_for_node_settled(page, routing, node_type=ROUTING_TYPE, timeout_ms=120000)
    assert status == "done", f"Weather Routing did not run: {read_node_error_text(node_locator(page, routing))}"
    for node_id in charts.values():
        status = wait_for_node_settled(page, node_id, node_type=BARS_TYPE, timeout_ms=120000)
        assert status == "done", f"the chart {node_id} did not draw: {read_node_error_text(node_locator(page, node_id))}"
    status = wait_for_node_settled(page, COMPARE_ID, node_type=COMPARE_TYPE, timeout_ms=120000)
    assert status == "done", f"Compare Scenarios did not compare: {read_node_error_text(node_locator(page, COMPARE_ID))}"

    # 2. The routes map: each route in its box's color.
    colors = _box_colors(page)
    assert colors == {sid: color.lower() for sid, (_name, color, _route) in EXAMPLE_SCENARIOS.items()}, colors
    frame_nodes(page, [map_id])
    assert_autark_map_drawn(page, map_id, timeout=60000)
    _assert_routes_drawn(page, map_id, colors, gone=[NEW_COLOR])

    # 3. The four charts: each bar in its box's color, from the metrics the
    # package's test pins; and the Compare node's bars and stacked table.
    for column in EXAMPLE_CHARTS:
        frame_nodes(page, [charts[column]])
        _assert_chart_drew(page, charts[column], list(colors.values()))
        _assert_bars_filled(page, charts[column], colors)
        _assert_chart_rows(page, charts[column])
    frame_nodes(page, [COMPARE_ID])
    _assert_compare_chart_drew(page, COMPARE_ID, list(colors.values()))
    _assert_bars_filled(page, COMPARE_ID, colors)
    _assert_stacked_table(page, COMPARE_ID)

    # 4. What differs: the route each scenario keeps, and nothing else.
    compare = node_locator(page, COMPARE_ID)
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
