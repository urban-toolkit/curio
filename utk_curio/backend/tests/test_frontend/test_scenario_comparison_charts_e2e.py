"""Playwright E2E: the scenario comparison charts test dataflow runs with no
network, and each of its nine charts draws its scenarios (re-made from
komar41's ScenarioCharts in #914).

``docs/examples/dataflows/scenario-comparison-charts.json`` loads nine example
tables from the Data Catalog. In each row a Data Transformation node per
scenario keeps that scenario's rows, a Compare Scenarios node stacks them, and
the chart is the Compare node's own preset (grouped bars, a table) or a node
of the SCOUT Comparison package after it (``scout.comparison@1``), a Vega-Lite
chart whose spec names no scenario and no color. The account's store holds
that package, which the dataflow declares. Every request that would leave the
stack is refused, and Run All drives the whole dataflow:

1. Every node runs to Done.
2. Each Compare node's output is its scenarios' rows, under their ids and
   names, in the order of its circles.
3. Each chart draws. A SCOUT Comparison chart draws its marks in its
   scenarios' colors, or in its own where its scenarios color only its axis
   labels (the stacked bars by stage, the matrix of weights); a preset
   compiles with no problem.
4. What differs on the four street plans lists one lever, its Case widget,
   set to each plan, and no code line; nothing is warned.
5. A chart after a Compare node draws its scenarios in their boxes' colors:
   one scenario of each of the seven recolored, each chart draws the new
   color and not the old one, with no run, its axis labels included where
   they are what its scenarios color.
6. No request left the stack.

Each chart's close-up is a frame, taken before the recolor.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scenario_comparison_charts_e2e.py -v
"""
from __future__ import annotations

import csv
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from .test_compare_scenarios_e2e import _CHART_STATE_JS, _COLOR_PIXELS_JS, _OUTPUT_ARTIFACT_JS
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
TEST_NAME = "test_the_nine_charts_draw_their_scenarios_with_no_network"
COMPARE = "curio.builtin/compare-scenarios"
#: The two charts whose scenarios color only their axis labels.
STAGES = "data.curio.example-building-carbon"
WEIGHTS = "data.curio.example-bike-route-factors"
#: The Compare node What differs is read on: four street plans, one lever.
PLANS = "data.curio.example-trips-by-mode"
#: For each chart, by its table: the scenario recolored in step 5 and its new
#: color. Each new color is far from every color its chart draws, and reads at
#: 3:1 on white, so a text mark draws it as it is. The two storm charts share
#: their scenarios: the 100-year storm is recolored once, and both follow.
RECOLORS = {
    "data.curio.example-pedestrians-by-hour": ("Weekend", "#7b3294"),
    "data.curio.example-flood-damage-curves": ("Floodproofed", "#c51b7d"),
    "data.curio.example-street-flooding": ("100-year storm", "#d95f02"),
    "data.curio.example-peak-depths": ("100-year storm", "#d95f02"),
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


def _rows(flow: dict) -> list:
    """``(dataset id, Compare node, chart node or None)`` per table, top to bottom."""
    by_id = {node["id"]: node for node in flow["nodes"]}
    found = []
    for compare in (node for node in flow["nodes"] if node["type"] == COMPARE):
        keep = next(e["source"] for e in flow["edges"] if e["target"] == compare["id"])
        loader = next(e["source"] for e in flow["edges"] if e["target"] == keep)
        [dataset_id] = re.findall(r'curio_load_data\("([^"]+)"\)', by_id[loader]["content"])
        after = [e["target"] for e in flow["edges"] if e["source"] == compare["id"]]
        found.append((dataset_id, compare, by_id[after[0]] if after else None))
    return sorted(found, key=lambda row: row[1]["y"])


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


# Whether the scenario's box on the canvas, the border of its frame, is drawn in
# the color ``#rrggbb``.
_BOX_COLOR_IS_JS = """([id, hex]) => {
    const frame = document.querySelector(`[data-scenario-frame="${id}"]`);
    if (!frame) return false;
    const rgb = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
    return getComputedStyle(frame).borderTopColor === `rgb(${rgb.join(", ")})`;
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


def _assert_preset_drew(page, node_id: str, preset: str, what: str) -> None:
    deadline = time.time() + 60
    state = None
    while time.time() < deadline:
        state = page.evaluate(_CHART_STATE_JS, [node_id, preset])
        if state in ("drawn", "problem"):
            break
        page.wait_for_timeout(250)
    problem = node_locator(page, node_id).locator("[data-compare-chart-problem]").all_inner_texts()
    assert state == "drawn", f"{what}'s {preset} chart ended {state!r}: {problem}"
    assert_vega_canvas_rendered(page, node_id, timeout=30000)


def _slug(dataset_id: str) -> str:
    return dataset_id.rsplit(".", 1)[-1].removeprefix("example-")


def test_the_nine_charts_draw_their_scenarios_with_no_network(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    flow = spec["dataflow"]
    rows = _rows(flow)
    assert len(rows) == 9, [row[0] for row in rows]
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
    for dataset_id, compare, _chart in rows:
        labels = compare["metadata"]["compareScenarios"]["inputs"]
        artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, compare["id"])
        assert artifact, f"{compare['title']} shows no saved table"
        stored = load_artifact_as_dict(artifact)
        assert stored["dataType"] == "dataframe", stored["dataType"]
        table = stored["data"]
        assert "case" not in table, sorted(table)
        assert list(dict.fromkeys(zip(table["scenario"], table["scenario_name"]))) == [
            (label["scenario"], label["name"]) for label in labels
        ], compare["title"]
        assert Counter(table["scenario_name"]) == _cases(dataset_id), compare["title"]

    # 3. Each chart draws, and its close-up is the frame.
    for dataset_id, compare, chart in rows:
        labels = compare["metadata"]["compareScenarios"]["inputs"]
        if chart is None:
            preset = compare["metadata"]["compareScenarios"]["chart"]["preset"]
            frame_nodes(page, [compare["id"]])
            _assert_preset_drew(page, compare["id"], preset, compare["title"])
            if preset != "table":
                _assert_colors_drawn(page, compare["id"], [label["color"] for label in labels], compare["title"])
            shown = compare["id"]
        else:
            frame_nodes(page, [chart["id"]])
            assert_vega_canvas_rendered(page, chart["id"], timeout=30000)
            colors = _mark_colors(dataset_id, json.loads(chart["content"]), labels)
            _assert_colors_drawn(page, chart["id"], colors, chart["title"])
            shown = chart["id"]
        save_node_closeup(page, f"scenario-charts-{_slug(dataset_id)}", shown, test_name=TEST_NAME, sweep_toasts=True)

    # 4. What differs on the street plans: the Case widget, set to each plan.
    [(_dataset, plans, _none)] = [row for row in rows if row[0] == PLANS]
    labels = plans["metadata"]["compareScenarios"]["inputs"]
    frame_nodes(page, [plans["id"]])
    compare = node_locator(page, plans["id"])
    compare.get_by_role("tab", name="What differs", exact=True).click()
    compare.locator('[data-compare-widget="case"]').wait_for(state="visible", timeout=10000)
    assert compare.locator("[data-compare-lever]").count() == 1
    for label in labels:
        shown = compare.locator(f'[data-compare-value="{label["scenario"]}"]').inner_text()
        assert shown.endswith(f"{label['name']}: {label['name']}"), shown
    assert compare.locator("[data-compare-code-added]").count() == 0
    assert compare.locator("[data-compare-code-removed]").count() == 0
    assert compare.locator("[data-compare-warning]").count() == 0
    compare.get_by_role("tab", name="Chart", exact=True).click()

    # 5. One scenario of each chart recolored: each chart after its Compare
    # node draws the new color, whatever its spec writes, and draws it with no
    # run. The stacked bars and the matrix draw it in their axis labels, which
    # read the scale their scenarios fill.
    charted = [(dataset_id, compare, chart) for dataset_id, compare, chart in rows if chart is not None]
    assert sorted(dataset_id for dataset_id, _compare, _chart in charted) == sorted(RECOLORS)
    boxes = {}
    for dataset_id, compare, _chart in charted:
        name, color = RECOLORS[dataset_id]
        [label] = [label for label in compare["metadata"]["compareScenarios"]["inputs"] if label["name"] == name]
        assert boxes.setdefault(label["scenario"], (label, color)) == (label, color), name
    open_in_project_tab(page)
    for label, color in boxes.values():
        open_scenario_details(page, label["scenario"]).get_by_label(f"Color of {label['name']}").fill(color)
        page.wait_for_function(_BOX_COLOR_IS_JS, arg=[label["scenario"], color], timeout=10000)
        close_scenario_details(page)
    close_scenario_drawer(page)
    for dataset_id, compare, chart in charted:
        labels = compare["metadata"]["compareScenarios"]["inputs"]
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
