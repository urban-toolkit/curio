"""Playwright E2E: the scenario comparison charts test dataflow runs with no
network, and each of its nine charts draws its scenarios (re-made from
komar41's ScenarioCharts in #914; each chart on its scenarios' own nodes since
the plan answering komar41's review, step 6.2).

``docs/examples/dataflows/scenario-comparison-charts.json`` loads nine example
tables from the Data Catalog. In each row a Data Transformation node per
scenario keeps that scenario's rows, and a chart of the Scout package
(``curio.scout@1``) takes each of those nodes on an input of its own: a
Vega-Lite chart whose spec names no scenario and no color. The account's
store holds that package, which the dataflow declares.

The test adds Scout's Dots with a range over the four street plans of the
daily trips, and beside each chart a Compare Scenarios node over the same
inputs, on which steps 2 and 4 read what they read on the dataflow's Compare
nodes until those went (step 6.4 removes them with the node). Every request
that would leave the stack is refused, and Run All drives the whole dataflow:

1. Every node runs to Done.
2. Each Compare node's output is its scenarios' rows, under their ids and
   names, in the order of its circles.
3. Each chart draws. A chart draws its marks in its scenarios' colors, or in
   its own where its scenarios color only its axis labels (the stacked bars
   by stage, the matrix of weights), and the table its text in the shades of
   them that read on white. Dots with a range draws a grey rule per mode and
   each plan's dots in its color.
4. What differs on the four street plans lists one lever, its Case widget,
   set to each plan, and no code line; nothing is warned.
5. A chart draws its scenarios in their boxes' colors: one scenario of each
   chart but the table recolored, each chart draws the new color and not the
   old one, with no run, its axis labels included where they are what its
   scenarios color. Dots with a range follows the plan recolored for the
   grouped bars.
6. No request left the stack.

Each of the nine charts' close-up is a frame, taken before the recolor.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scenario_comparison_charts_e2e.py -v
"""
from __future__ import annotations

import copy
import csv
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from .test_compare_scenarios_e2e import _COLOR_PIXELS_JS, _OUTPUT_ARTIFACT_JS
from .utils import (
    REPO_ROOT,
    api_json,
    assert_vega_canvas_rendered,
    close_scenario_details,
    close_scenario_drawer,
    frame_nodes,
    load_artifact_as_dict,
    node_locator,
    open_in_project_tab,
    open_scenario_details,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    sandbox_base_url,
    save_node_closeup,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "scenario-comparison-charts.json"
SCOUT = Path(REPO_ROOT) / "packages" / "curio.scout@1"
TEST_NAME = "test_the_nine_charts_draw_their_scenarios_with_no_network"
LOAD = "curio.builtin/data-loading"
KEEP = "curio.builtin/data-transformation"
COMPARE = "curio.builtin/compare-scenarios"
#: The two charts whose scenarios color only their axis labels.
STAGES = "data.curio.example-building-carbon"
WEIGHTS = "data.curio.example-bike-route-factors"
#: The table, which writes its scenarios' rows in their colors' readable shades.
ROOFS = "data.curio.example-green-roofs"
#: The street plans, which Dots with a range reads and What differs is read on.
PLANS = "data.curio.example-trips-by-mode"
#: The Dots with a range node the test adds over the street plans.
DOTS = "plans-dots"
#: What the Compare node the test adds beside each chart charts itself: what
#: the dataflow's Compare node of that table charted.
COMPARE_CHARTS = {
    "data.curio.example-trips-by-mode": {"preset": "grouped-bar", "x": "mode", "y": "daily_trips", "aggregate": "none"},
}
#: Dots with a range's rules.
RULE_GREY = "#9ca3af"
#: For each chart but the table, by its table: the scenario recolored in step
#: 5 and its new color. Each new color is far from every color its chart
#: draws, and reads at 3:1 on white, so a text mark draws it as it is. The two
#: storm charts share their scenarios: the 100-year storm is recolored once,
#: and both follow.
RECOLORS = {
    "data.curio.example-pedestrians-by-hour": ("Weekend", "#7b3294"),
    "data.curio.example-flood-damage-curves": ("Floodproofed", "#c51b7d"),
    "data.curio.example-street-flooding": ("100-year storm", "#d95f02"),
    "data.curio.example-peak-depths": ("100-year storm", "#d95f02"),
    "data.curio.example-trips-by-mode": ("Bus lanes", "#01665e"),
    "data.curio.example-building-carbon": ("Timber frame", "#1b7837"),
    "data.curio.example-park-shade": ("Tree canopy", "#e7298a"),
    "data.curio.example-bike-route-factors": ("Route C", "#9e6bd6"),
}


def _refuse_the_network(page, *urls) -> list:
    """Refuse every request to a host other than the stack's, and record it."""
    hosts = {urlsplit(url).hostname for url in urls} | {"localhost", "127.0.0.1"}
    refused: list = []

    def handle(route, request):
        if urlsplit(request.url).hostname in hosts:
            route.continue_()
        else:
            refused.append(request.url)
            route.abort()

    page.route("**/*", handle)
    return refused


def _labels(flow: dict, node_id: str) -> list:
    """The boxes of *node_id*'s inputs, in the order of its circles, as
    ``{"scenario", "name", "color"}``."""
    box_of = {member: box for box in flow["scenarios"] for member in box["nodes"]}
    wired = sorted(
        (0 if e.get("targetHandle") in (None, "in") else int(e["targetHandle"].split("_")[1]), e["source"])
        for e in flow["edges"] if e["target"] == node_id
    )
    return [
        {"scenario": box_of[source]["id"], "name": box_of[source]["name"], "color": box_of[source]["color"]}
        for _circle, source in wired
    ]


def _rows(flow: dict) -> list:
    """``(dataset id, chart node)`` per table, top to bottom: the dataflow's
    own charts, not the nodes the test adds."""
    by_id = {node["id"]: node for node in flow["nodes"]}
    found = []
    for loader in (node for node in flow["nodes"] if node["type"] == LOAD):
        [dataset_id] = re.findall(r'curio_load_data\("([^"]+)"\)', loader["content"])
        keep = next(e["target"] for e in flow["edges"] if e["source"] == loader["id"])
        [chart] = [
            e["target"] for e in flow["edges"]
            if e["source"] == keep and by_id[e["target"]]["type"].startswith("curio.scout/") and e["target"] != DOTS
        ]
        found.append((dataset_id, by_id[chart]))
    return sorted(found, key=lambda row: row[1]["y"])


def _compare_id(dataset_id: str) -> str:
    """The id of the Compare node the test adds beside *dataset_id*'s chart."""
    return f"compare-{_slug(dataset_id)}"


def _table(dataset_id: str) -> list:
    """The example table's rows."""
    folder = Path(REPO_ROOT) / "datasets" / f"{dataset_id}@1"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    with open(folder / manifest["dataFile"], newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _cases(dataset_id: str) -> Counter:
    """How many rows of each case the example table holds."""
    return Counter(row["case"] for row in _table(dataset_id))


def _mark_colors(dataset_id: str, spec: dict, labels: list) -> list:
    """The colors the chart's marks are drawn in: its scenarios', but for the
    two charts whose scenarios color only their axis labels."""
    if dataset_id == STAGES:
        # The part palette's first colors, one per life-cycle stage the table
        # holds: its parts.
        stages = {row["stage"] for row in _table(dataset_id)}
        return spec["layer"][0]["encoding"]["color"]["scale"]["range"][:len(stages)]
    if dataset_id == WEIGHTS:
        # For and Against.
        return spec["encoding"]["stroke"]["scale"]["range"]
    return [label["color"] for label in labels]


def _readable_shade(color: str) -> str:
    """The color a table writes a scenario's text in: *color* when it reads at
    3:1 on white, else its lightest shade toward black that does
    (``tableTextColor`` in ``utils/compare/comparePresets.ts``)."""

    def contrast(channels):
        linear = [c / 255 / 12.92 if c / 255 <= 0.04045 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in channels]
        return 1.05 / (0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2] + 0.05)

    channels = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    for left in range(100, 0, -1):
        shade = [round(c * left / 100) for c in channels]
        if contrast(shade) >= 3:
            return color if left == 100 else "#" + "".join(f"{c:02x}" for c in shade)
    return "#000000"


# Whether the scenario's box on the canvas, the border of its frame, is drawn in
# the color ``#rrggbb``.
_BOX_COLOR_IS_JS = """([id, hex]) => {
    const frame = document.querySelector(`[data-scenario-frame="${id}"]`);
    if (!frame) return false;
    const rgb = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
    return getComputedStyle(frame).borderTopColor === `rgb(${rgb.join(", ")})`;
}"""

# How many opaque pixels of the chart's canvas are each color, within *within*
# of each channel: text antialiased on white reaches its color only where a
# glyph covers a whole pixel, so text is counted a little more loosely.
_TEXT_PIXELS_JS = """([id, colors, within]) => {
    const canvas = document.querySelector(`#vega${id} canvas`);
    if (!canvas || !canvas.width || !canvas.height) return null;
    const { data } = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
    const targets = colors.map((hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)));
    const counts = targets.map(() => 0);
    for (let p = 0; p < data.length; p += 4) {
        if (data[p + 3] < 200) continue;
        targets.forEach((t, k) => {
            if (Math.abs(data[p] - t[0]) <= within && Math.abs(data[p + 1] - t[1]) <= within
                && Math.abs(data[p + 2] - t[2]) <= within) counts[k] += 1;
        });
    }
    return counts;
}"""


def _assert_colors_drawn(page, node_id: str, colors: list, what: str) -> None:
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_COLOR_PIXELS_JS, [node_id, colors])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"{what} does not draw its colors {colors}: pixels {counts}")


def _assert_text_drawn(page, node_id: str, colors: list, what: str) -> None:
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_TEXT_PIXELS_JS, [node_id, colors, 24])
        if counts and all(count >= 10 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"{what} does not write its text in {colors}: pixels {counts}")


def _slug(dataset_id: str) -> str:
    return dataset_id.rsplit(".", 1)[-1].removeprefix("example-")


def _stack_code(labels: list) -> str:
    """The code a Compare Scenarios node writes for its inputs, labelled by
    *labels* in circle order (``utils/compare/compareCode.ts``)."""
    entries = "".join(
        f"    ({json.dumps(label['scenario'])}, {json.dumps(label['name'])}, [!! input_{circle} !!]),\n"
        for circle, label in enumerate(labels)
    )
    return (
        "# Compare Scenarios writes this code from its inputs: each input, under the\n"
        "# id and the name of its scenario. It is written again when they change.\n"
        f"return curio_stack_scenarios([\n{entries}])\n"
    )


def _with_compare_nodes_and_dots(spec: dict) -> dict:
    """*spec* with a Compare Scenarios node beside each chart, over the chart's
    inputs on the same circles, and Dots with a range over the four street
    plans, below the last row. Each Compare node holds the labels and the code
    it writes for its inputs, so a load writes nothing again."""
    spec = copy.deepcopy(spec)
    flow = spec["dataflow"]
    rows = _rows(flow)
    added_edges = []
    for dataset_id, chart in rows:
        labels = _labels(flow, chart["id"])
        flow["nodes"].append({
            "id": _compare_id(dataset_id), "type": COMPARE,
            "x": chart["x"] + chart.get("width", 525) + 200, "y": chart["y"],
            "title": f"Compare: {chart['title']}",
            "content": _stack_code(labels),
            "out": "DEFAULT", "in": "DEFAULT", "goal": "",
            "metadata": {"keywords": [], "compareScenarios": {
                "inputs": labels,
                "chart": COMPARE_CHARTS.get(dataset_id, {"preset": "table"}),
                "mode": "chart",
            }},
        })
        added_edges += [
            {**edge, "id": f"{edge['id']}-{_compare_id(dataset_id)}", "target": _compare_id(dataset_id)}
            for edge in flow["edges"] if edge["target"] == chart["id"]
        ]
    [(_dataset, plans)] = [row for row in rows if row[0] == PLANS]
    manifest = json.loads((SCOUT / "manifest.json").read_text(encoding="utf-8"))
    [dots] = [t for t in manifest["templates"] if t["id"] == "dots-with-a-range"]
    values = {"category": "mode", "value": "daily_trips", "x_title": "Daily trips", "y_title": "Mode"}
    bottom = max(node["y"] + node.get("height", 420) for node in flow["nodes"])
    flow["nodes"].append({
        "id": DOTS, "type": "curio.scout/dots-with-a-range", "x": plans["x"], "y": bottom + 160,
        "title": "Dots with a range: daily trips by mode",
        "content": (SCOUT / dots["source"]).read_text(encoding="utf-8"),
        "out": "DEFAULT", "in": "DEFAULT", "goal": "",
        "metadata": {"keywords": [], "widgets": [dict(w, value=values[w["name"]]) for w in dots["widgets"]]},
        "width": 680, "height": 440,
    })
    added_edges += [
        {**edge, "id": f"{edge['id']}-{DOTS}", "target": DOTS}
        for edge in flow["edges"] if edge["target"] == plans["id"]
    ]
    flow["edges"] += added_edges
    return spec


def test_the_nine_charts_draw_their_scenarios_with_no_network(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = _with_compare_nodes_and_dots(json.loads(DATAFLOW.read_text(encoding="utf-8")))
    flow = spec["dataflow"]
    rows = _rows(flow)
    assert len(rows) == 9, [row[0] for row in rows]
    plan_labels = _labels(flow, DOTS)
    assert [label["name"] for label in plan_labels] == ["Today", "Bus lanes", "Bike network", "Car-free center"]
    for dataset_id, chart in rows:
        assert _labels(flow, _compare_id(dataset_id)) == _labels(flow, chart["id"]), dataset_id
    refused = _refuse_the_network(page, app_frontend.base_url, current_server, sandbox_base_url())
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scenario Charts",
        username="scenario_comparison_charts",
        project_name=flow["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    # The account's store holds every package the dataflow declares: the one
    # its charts are nodes of.
    assert flow["packages"], "the dataflow declares no package for its charts"
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    missing = [package for package in flow["packages"] if package not in store]
    assert not missing, f"{missing} are not in the account's store {store}: start the stack --with-examples"
    for node in flow["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)

    # 1. Run All runs every node.
    run_all_and_wait(page, timeout_ms=600000)
    for node in flow["nodes"]:
        status = wait_for_node_settled(page, node["id"], node_type=node["type"], timeout_ms=240000)
        assert status == "done", (
            f"{node.get('title')} ({node['type']}) ended {status}: {read_node_error_text(node_locator(page, node['id']))}"
        )

    # 2. Each Compare node stacks its scenarios' rows in its circles' order.
    for dataset_id, _chart in rows:
        compare_id = _compare_id(dataset_id)
        labels = _labels(flow, compare_id)
        artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, compare_id)
        assert artifact, f"{compare_id} shows no saved table"
        stored = load_artifact_as_dict(artifact)
        assert stored["dataType"] == "dataframe", stored["dataType"]
        table = stored["data"]
        assert "case" not in table, sorted(table)
        assert list(dict.fromkeys(zip(table["scenario"], table["scenario_name"]))) == [
            (label["scenario"], label["name"]) for label in labels
        ], compare_id
        assert Counter(table["scenario_name"]) == _cases(dataset_id), compare_id

    # 3. Each chart draws, and its close-up is the frame.
    for dataset_id, chart in rows:
        labels = _labels(flow, chart["id"])
        frame_nodes(page, [chart["id"]])
        assert_vega_canvas_rendered(page, chart["id"], timeout=30000)
        if dataset_id == ROOFS:
            shades = [_readable_shade(label["color"]) for label in labels]
            _assert_text_drawn(page, chart["id"], shades, chart["title"])
        else:
            colors = _mark_colors(dataset_id, json.loads(chart["content"]), labels)
            _assert_colors_drawn(page, chart["id"], colors, chart["title"])
        save_node_closeup(page, f"scenario-charts-{_slug(dataset_id)}", chart["id"], test_name=TEST_NAME, sweep_toasts=True)
    # Dots with a range: a grey rule per mode, and each plan's dots in its color.
    frame_nodes(page, [DOTS])
    assert_vega_canvas_rendered(page, DOTS, timeout=30000)
    _assert_colors_drawn(page, DOTS, [RULE_GREY, *[label["color"] for label in plan_labels]], "Dots with a range")

    # 4. What differs on the street plans: the Case widget, set to each plan.
    frame_nodes(page, [_compare_id(PLANS)])
    compare = node_locator(page, _compare_id(PLANS))
    compare.get_by_role("tab", name="What differs", exact=True).click()
    compare.locator('[data-compare-widget="case"]').wait_for(state="visible", timeout=10000)
    assert compare.locator("[data-compare-lever]").count() == 1
    for label in plan_labels:
        shown = compare.locator(f'[data-compare-value="{label["scenario"]}"]').inner_text()
        assert shown.endswith(f"{label['name']}: {label['name']}"), shown
    assert compare.locator("[data-compare-code-added]").count() == 0
    assert compare.locator("[data-compare-code-removed]").count() == 0
    assert compare.locator("[data-compare-warning]").count() == 0
    compare.get_by_role("tab", name="Chart", exact=True).click()

    # 5. One scenario of each chart recolored: each chart draws the new color,
    # whatever its spec writes, and draws it with no run. The stacked bars and
    # the matrix draw it in their axis labels, which read the scale their
    # scenarios fill.
    recolored = [(dataset_id, chart) for dataset_id, chart in rows if dataset_id != ROOFS]
    assert sorted(dataset_id for dataset_id, _chart in recolored) == sorted(RECOLORS)
    boxes = {}
    for dataset_id, chart in recolored:
        name, color = RECOLORS[dataset_id]
        [label] = [label for label in _labels(flow, chart["id"]) if label["name"] == name]
        assert boxes.setdefault(label["scenario"], (label, color)) == (label, color), name
    open_in_project_tab(page)
    for label, color in boxes.values():
        open_scenario_details(page, label["scenario"]).get_by_label(f"Color of {label['name']}").fill(color)
        page.wait_for_function(_BOX_COLOR_IS_JS, arg=[label["scenario"], color], timeout=10000)
        close_scenario_details(page)
    close_scenario_drawer(page)
    followers = [*recolored, (PLANS, {"id": DOTS, "title": "Dots with a range"})]
    for dataset_id, chart in followers:
        labels = _labels(flow, chart["id"])
        name, color = RECOLORS[dataset_id]
        [old] = [label["color"] for label in labels if label["name"] == name]
        what = f"{chart['title']}, {name} recolored"
        frame_nodes(page, [chart["id"]])
        if dataset_id in (STAGES, WEIGHTS):
            _assert_colors_drawn(page, chart["id"], [color], what)
        else:
            _assert_colors_drawn(
                page, chart["id"], [color if label["name"] == name else label["color"] for label in labels], what,
            )
        stale = page.evaluate(_COLOR_PIXELS_JS, [chart["id"], [old]])
        assert stale == [0], f"{what} still draws {name} in its old color {old}: pixels {stale}"

    # 6. Nothing left the stack.
    assert refused == [], f"the dataflow reached the network: {refused}"
