"""SCOUT's high-rise shadow case on the canvas, compared as two scenarios (#662, step 19).

The shipped test dataflow ``chicago-loop-shadow-towers.json``: SCOUT's Chicago Loop buildings
(the Data Catalog dataset ``data.scout.loop-buildings``) and a season Parameter
node are the fixed context. In "Existing", Rasterize Buildings
(``curio.scout@1``) draws them into one zoom-16 height raster,
Accumulated Shadow, the node of the model package ``model.scout.deep-umbra@1``,
runs SCOUT's Deep Umbra model on it, in the season both scenarios share, an
Autark map draws the shadow, and a Raster Calculator (``curio.scout@1`` too)
takes the shadow's statistics over the ground, the heights as its mask.
"Towers removed" first reads the buildings through a Map Editor node, its
lever, whose code removes the 15 buildings SCOUT's second scenario removes,
matched on building_id, and which feeds a map of the remaining buildings it
is linked to. Outside the scenarios, Scout's Bars charts
each scenario's mean accumulated shadow, and a third Raster Calculator takes
its change, Towers removed's shadow minus Existing's, which an Autark map after
it draws on a scale centered on no change.

Run All in the browser runs the whole dataflow:

1. The rows the chart reads hold one row per scenario with SCOUT's mean
   accumulated shadow for each (128.64 and 106.73 minutes in SCOUT's metrics
   files, in summer) within 0.1 minutes, each row its scenario's statistics
   value for value, and the chart draws in both scenarios' colors.
2. The change is a raster on the shadow mosaics' grid, 512 by 512 cells in
   EPSG:3395, in minutes: towers removed minus existing, cell for cell, from
   the two shadows Deep Umbra saved, which takes shadow away on the whole.
   The Autark map after the Raster Calculator draws it, under the title
   "Shadow change (minutes)".
3. Each scenario's map draws its shadow, under the title "Accumulated shadow
   (minutes)", its legend labelled 0 to 720, the color range both maps share,
   and Towers removed's map of its buildings, linked to the lever, draws them
   under the title its layer gives. The close-ups of the four maps are the
   frames.

A second test edits the lever, as a user does, and presses Commit edits:
the scenario runs again with the edit, and its numbers move (see its
docstring).

The packages are in every account's store and their libraries are installed
because the stack starts with ``--with-examples`` and this dataflow declares the
packages.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_shadow_e2e.py -v
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest
from playwright.sync_api import expect

from .test_map_edits_e2e import (
    OUTLINES,
    _assert_linked,
    _back_to_layers,
    _commit,
    _edits_of,
    _open,
    _overlay,
    _rule,
    _wait_for_edits,
    _wait_for_lit,
    _wait_for_selection,
)
from .test_scenario_drop_e2e import _saved_spec
from .test_widget_tags_e2e import _open_tab
from .utils import (
    INTERACTION_VIEWPORT,
    REPO_ROOT,
    _COLOR_PIXELS_JS,
    _OUTPUT_ARTIFACT_JS,
    _assert_legend_reads,
    _assert_legend_title,
    api_json,
    assert_autark_map_drawn,
    assert_vega_canvas_rendered,
    assert_vega_charts_fit,
    frame_nodes,
    load_artifact_as_dict,
    load_raster_cells,
    node_locator,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_all_and_wait,
    save_dataflow,
    save_node_closeup,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "chicago-loop-shadow-towers.json"
TEST_NAME = "test_two_building_sets_are_shadowed_charted_and_mapped"
SHADOW_TYPE = "model.scout.deep-umbra/accumulated-shadow"
CALCULATOR_TYPE = "curio.scout/raster-calculator"
BARS_TYPE = "curio.scout/bars"
COMPARE_TYPE = "curio.builtin/compare-scenarios"
MAP_TYPE = "curio.builtin/autk-grammar"
PACKAGES = ("curio.scout@1", "model.scout.deep-umbra@1")
#: SCOUT's A_shadows_metric.csv and B_shadows_metric.csv.
SCOUT_MEANS = {"existing": 128.63593, "towers-removed": 106.73111}
#: The columns of each row the Bars chart reads, past the ones the stacking
#: keeps for itself (``__input__``): its scenario's box, then the scenario's
#: statistics, a table of one row.
ROW_COLUMNS = ["count", "max", "mean", "median", "min", "scenario", "scenario_name"]
#: The color range both scenarios' shadow maps share, in minutes
#: (``colorMapRange``): both legends read its ends.
SHADOW_RANGE = (0, 720)

LEVER_TEST_NAME = "test_an_edit_in_the_towers_lever_reaches_the_shadow_with_commit_edits"
#: The Map Editor node (#958; its type id is still the Edit Features node's).
LEVER_TYPE = "curio.builtin/edit-features"
LOADER_TYPE = "curio.builtin/data-loading"
#: The buildings Towers removed's lever removes as shipped, by building_id:
#: the 15 SCOUT's second scenario leaves out.
SCOUT_TOWERS = [8, 10, 12, 13, 14, 18, 19, 31, 34, 51, 66, 77, 82, 106, 122]
#: The edit the test makes in the lever: the buildings still taller than 200 m,
#: picked by a rule and removed too.
TALLER = "height > 200"


def _shadow_maps(dataflow: dict) -> dict:
    """Each scenario's map of its shadow, by the scenario's id: the Autark map
    in its box that its Accumulated Shadow node feeds."""
    types = {node["id"]: node["type"] for node in dataflow["nodes"]}
    into = {edge["target"]: edge["source"] for edge in dataflow["edges"] if edge.get("targetHandle") == "in"}
    found = {}
    for scenario in dataflow["scenarios"]:
        members = [node_id for node_id in scenario["nodes"]
                   if types.get(node_id) == MAP_TYPE and types.get(into.get(node_id)) == SHADOW_TYPE]
        assert len(members) == 1, f"scenario {scenario['name']!r} holds {len(members)} maps of its shadow, not one"
        found[scenario["id"]] = members[0]
    return found


def _parts(dataflow: dict) -> dict:
    """The dataflow's chart and change, by what they are: ``chart``, Scout's
    Bars, and ``change``, the Raster Calculator that is no statistics."""
    nodes = dataflow["nodes"]
    assert not [n["id"] for n in nodes if n["type"] == COMPARE_TYPE], "the dataflow still holds a Compare node"
    (chart,) = [n["id"] for n in nodes if n["type"] == BARS_TYPE]
    (change,) = [n["id"] for n in nodes if n["type"] == CALCULATOR_TYPE
                 and "\nreturn raster_statistics(" not in n["content"]]
    return {"chart": chart, "change": change}


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


def _chart_rows(page, chart: str, count: int) -> list[dict]:
    """The *count* rows the Bars chart reads, once its view holds them."""
    rows = None
    deadline = time.time() + 30
    while time.time() < deadline:
        rows = page.evaluate(_INPUTS_ROWS_JS, chart)
        if rows and len(rows) == count:
            return rows
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart {chart} reads the rows {rows}, not {count}")


def _assert_chart_drew(page, node_id: str, colors: list[str]) -> None:
    """The Bars chart drew, and its canvas holds both scenarios' colors."""
    assert_vega_canvas_rendered(page, node_id, timeout=30000)
    _assert_colors_drawn(page, node_id, colors)


def _assert_colors_drawn(page, node_id: str, colors: list[str]) -> None:
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_COLOR_PIXELS_JS, [node_id, colors])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart does not draw both scenarios' colors {colors}: pixels {counts}")


def _saved_output(page, node_id: str) -> dict:
    return load_artifact_as_dict(_saved_artifact(page, node_id))


def _saved_artifact(page, node_id: str) -> str:
    """The artifact *node_id*'s output is saved to."""
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, f"{node_id} shows no saved output"
    return artifact


def _chart_means(page, chart: str) -> dict:
    """Each scenario's mean accumulated shadow, from the rows the Bars chart reads."""
    return {row["scenario"]: row["mean"] for row in _chart_rows(page, chart, 2)}


def _heights(page, node_id: str) -> dict:
    """``{building_id: height}`` of the buildings *node_id* handed on, a layer."""
    stored = _saved_output(page, node_id)
    assert stored["dataType"] == "geodataframe", f"{node_id} handed on {stored['dataType']}"
    return {feature["properties"]["building_id"]: feature["properties"]["height"]
            for feature in stored["data"]["features"]}


def test_two_building_sets_are_shadowed_charted_and_mapped(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    record_property,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(_KEEP_VEGA_VIEWS_INIT)
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    shadows = [n for n, node in nodes.items() if node["type"] == SHADOW_TYPE]
    statistics = [n for n, node in nodes.items() if node["type"] == CALCULATOR_TYPE
                  and "\nreturn raster_statistics(" in node["content"]]
    assert len(shadows) == len(statistics) == 2, (shadows, statistics)
    parts = _parts(dataflow)
    chart, change = parts["chart"], parts["change"]
    colors = [scenario["color"] for scenario in dataflow["scenarios"]]
    maps = _shadow_maps(dataflow)
    into = {edge["target"]: edge["source"] for edge in dataflow["edges"] if edge["targetHandle"] == "in"}
    for scenario, map_id in maps.items():
        assert nodes[into[map_id]]["type"] == SHADOW_TYPE, f"the {scenario} map does not draw its shadow"
    # Towers removed's lever feeds a map of the remaining buildings, in its box,
    # linked to it: every other map is a shadow's or the change's.
    (lever,) = [n for n, node in nodes.items() if node["type"] == LEVER_TYPE]
    buildings_map = _lever_map(dataflow, lever)
    scenario_of = {node_id: box["id"] for box in dataflow["scenarios"] for node_id in box["nodes"]}
    assert scenario_of.get(buildings_map) == "towers-removed", "the lever's map is not in its scenario's box"
    after = [n for n, node in nodes.items() if node["type"] == MAP_TYPE and into.get(n) == change]
    assert len(after) == 1, f"the change feeds the Autark maps {after}, not one"
    (difference_map,) = after

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scout Shadows",
        username="scout_shadows_e2e",
        project_name=dataflow["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    missing = [package for package in PACKAGES if package not in store]
    assert not missing, f"{missing} are not in the account's store {store}: start the stack --with-examples"
    for node_id in nodes:
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)

    run_all_and_wait(page, timeout_ms=600000)
    for node_id in [*shadows, *statistics, *maps.values(), buildings_map, chart, change, difference_map]:
        status = wait_for_node_settled(page, node_id, node_type=nodes[node_id]["type"], timeout_ms=180000)
        assert status == "done", (
            f"{nodes[node_id]['type']} {node_id} ended {status}: {read_node_error_text(node_locator(page, node_id))}"
        )

    # 1. One row per scenario, SCOUT's means, bars in both scenarios' colors:
    # in the rows the Bars chart reads.
    rows = _chart_rows(page, chart, 2)
    assert [row["__input__"] for row in rows] == [0, 1], rows
    assert [sorted(name for name in row if not name.startswith("_")) for row in rows] == [ROW_COLUMNS] * 2, rows
    read = {name: [row.get(name) for row in rows] for name in ("scenario", "scenario_name", "mean", "count")}
    where = "the rows the Bars chart reads"
    assert read["scenario"] == ["existing", "towers-removed"], (where, read["scenario"])
    assert read["scenario_name"] == ["Existing", "Towers removed"], (where, read["scenario_name"])
    # The ground: the cells with no building, most of SCOUT's four tiles.
    assert all(100000 < count < 512 * 512 for count in read["count"]), (where, read["count"])
    means = dict(zip(read["scenario"], read["mean"]))
    record_property(f"mean accumulated shadow (minutes) in {where}", json.dumps({"ours": means, "scout": SCOUT_MEANS}))
    # The proof's tolerance (test_scout_shadow.py): Deep Umbra's output moves
    # with onnxruntime's thread count above 16.
    assert all(abs(means[key] - SCOUT_MEANS[key]) <= 0.1 for key in SCOUT_MEANS), (
        f"mean accumulated shadow in {where}, ours {means}, SCOUT's {SCOUT_MEANS}"
    )
    # Each row is its scenario's statistics, the table of one row its Raster
    # Calculator saved, value for value.
    scenario_of = {node_id: scenario["id"] for scenario in dataflow["scenarios"] for node_id in scenario["nodes"]}
    for row in rows:
        (node_id,) = [n for n in statistics if scenario_of.get(n) == row["scenario"]]
        table = _saved_output(page, node_id)["data"]
        assert sorted(table) == ["count", "max", "mean", "median", "min"], (node_id, sorted(table))
        for name in ("mean", "median", "min", "max"):
            (value,) = table[name]
            assert row[name] == pytest.approx(value, rel=1e-12), (row["scenario"], name, row[name], value)
        assert [row["count"]] == table["count"], (row["scenario"], row["count"], table["count"])
    frame_nodes(page, [chart])
    _assert_chart_drew(page, chart, colors)
    # The chart shows whole in its node, its axes and legend included (#1097).
    assert_vega_charts_fit(page, DATAFLOW.name, [chart], every=False)

    # 2. Towers removed minus existing, on the mosaics' grid, mapped: the
    # Raster Calculator's raster, and the Autark map after it draws it.
    grid, bands = load_raster_cells(_saved_artifact(page, change))
    assert (grid["crs"], grid["width"], grid["height"]) == ("EPSG:3395", 512, 512), grid
    (cells,) = bands
    assert not np.isnan(cells).any(), "the change has nodata where both mosaics have shadow"
    mean_change = float(cells.mean())
    record_property("change (minutes)", json.dumps({
        "min": float(cells.min()), "max": float(cells.max()), "mean": mean_change,
    }))
    assert cells.min() < -100 and mean_change < 0, (cells.min(), cells.max(), mean_change)
    assert -720 <= cells.min() and cells.max() <= 720, (cells.min(), cells.max())
    # Cell for cell, Towers removed's shadow minus Existing's, the two rasters
    # Deep Umbra saved, on the change's grid: input_1 minus input_0. The Raster
    # Calculator subtracts in float32, so the two may part by a unit in the
    # last place.
    feeds = {edge["targetHandle"]: edge["source"] for edge in dataflow["edges"] if edge["target"] == change}
    assert sorted(feeds) == ["in", "in_1"] and {nodes[n]["type"] for n in feeds.values()} == {SHADOW_TYPE}, feeds
    shadow_grids, shadow_cells = [], []
    for handle in ("in", "in_1"):
        shadow_grid, (shadow,) = load_raster_cells(_saved_artifact(page, feeds[handle]))
        shadow_grids.append(shadow_grid)
        shadow_cells.append(shadow)
    for shadow_grid in shadow_grids:
        assert (shadow_grid["crs"], shadow_grid["width"], shadow_grid["height"]) == (
            grid["crs"], grid["width"], grid["height"]), (shadow_grid, grid)
        assert [shadow_grid[k] for k in ("originX", "originY", "resX", "resY")] == pytest.approx(
            [grid[k] for k in ("originX", "originY", "resX", "resY")], rel=1e-12), (shadow_grid, grid)
    existing, removed = shadow_cells
    took = (removed.astype("float64") - existing.astype("float64")).astype("float32")
    assert np.array_equal(np.isnan(cells), np.isnan(took))
    assert np.allclose(cells, took, rtol=0, atol=1e-3, equal_nan=True), (
        "the Raster Calculator's change differs from Towers removed's shadow minus Existing's by up to "
        f"{float(np.nanmax(np.abs(cells - took)))}"
    )
    frame_nodes(page, [change, difference_map])
    assert_autark_map_drawn(page, difference_map, timeout=60000,
                            attach_as="the change in accumulated shadow when the towers are removed")
    _assert_legend_title(page, difference_map, "Shadow change (minutes)")
    save_node_closeup(page, "scout-shadow-change-map", difference_map, test_name=TEST_NAME, sweep_toasts=True)

    # 3. Each scenario's map draws its shadow, under the grammar's title, on the
    # color range both maps share, so a color is the same minutes on both.
    for scenario, map_id in maps.items():
        frame_nodes(page, [map_id])
        assert_autark_map_drawn(page, map_id, timeout=60000, attach_as=f"the {scenario} shadow map")
        _assert_legend_title(page, map_id, "Accumulated shadow (minutes)")
        _assert_legend_reads(page, map_id, SHADOW_RANGE)
        save_node_closeup(page, f"scout-shadow-map-{scenario}", map_id, test_name=TEST_NAME, sweep_toasts=True)
    # Towers removed's map of its buildings, linked to the lever, under the
    # title its layer gives.
    frame_nodes(page, [lever, buildings_map])
    _assert_linked(page, lever, buildings_map, nodes[buildings_map]["title"])
    assert_autark_map_drawn(page, buildings_map, timeout=60000, attach_as="the towers removed buildings map")
    (layer,) = json.loads(nodes[buildings_map]["content"])["map"]["layerRefs"]
    _assert_legend_title(page, buildings_map, layer["title"])
    save_node_closeup(page, "scout-shadow-buildings-map-towers-removed", buildings_map, test_name=TEST_NAME,
                      sweep_toasts=True)


def _lever_map(dataflow: dict, lever: str) -> str:
    """The Autark map the lever edits on: the one it feeds on a data edge and
    is linked to by an interaction edge."""
    types = {node["id"]: node["type"] for node in dataflow["nodes"]}
    fed = {edge["target"] for edge in dataflow["edges"] if edge["source"] == lever and edge.get("type") != "Interaction"}
    linked = {
        edge["target"] if edge["source"] == lever else edge["source"]
        for edge in dataflow["edges"] if edge.get("type") == "Interaction" and lever in (edge["source"], edge["target"])
    }
    maps = sorted(node_id for node_id in fed & linked if types.get(node_id) == MAP_TYPE)
    assert len(maps) == 1, f"the lever {lever} feeds and is linked to the maps {maps}, not one"
    return maps[0]


def _below(dataflow: dict, node_id: str) -> list[str]:
    """The nodes below *node_id* by data edges: the ones Commit edits runs with it."""
    successors: dict = {}
    for edge in dataflow["edges"]:
        if edge.get("sourceHandle") == "in/out" and edge.get("targetHandle") == "in/out":
            continue
        successors.setdefault(edge["source"], []).append(edge["target"])
    reached, queue = set(), [node_id]
    while queue:
        for nxt in successors.get(queue.pop(), []):
            if nxt not in reached and nxt != node_id:
                reached.add(nxt)
                queue.append(nxt)
    return sorted(reached)


def test_an_edit_in_the_towers_lever_reaches_the_shadow_with_commit_edits(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    record_property,
):
    """Towers removed's Map Editor node is the scenario's lever: its code holds
    SCOUT's 15 removed buildings, one removal by building_id under a label, and
    it feeds a map of the remaining buildings, linked to it. An edit made
    there, then Commit edits, runs the scenario again with it:

    1. Run All gives SCOUT's two means, as the test above checks, each the
       mean its scenario's statistics took.
    2. The lever edits on its buildings map, which drew, lists its layer by
       building_id, and lists SCOUT's removal under its label.
    3. A rule picks the buildings still taller than 200 m, which light up on
       the map, and Remove makes it a second entry: the lever's code holds it,
       and the lever and the nodes below it lack it until Commit edits.
    4. Commit edits runs them. The lever hands on the buildings without
       SCOUT's 15 and without those; Towers removed's mean moves away from the
       one SCOUT's case gave, and the Bars chart shows the mean its statistics
       took; Existing, which did not run, keeps its mean. The lever's and its
       map's close-ups are the frames.
    5. The code is saved with the dataflow, SCOUT's entry under its label.
    """
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(_KEEP_VEGA_VIEWS_INIT)
    page.set_viewport_size(INTERACTION_VIEWPORT)
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    scenario_of = {node_id: scenario["id"] for scenario in dataflow["scenarios"] for node_id in scenario["nodes"]}
    levers = [n for n, node in nodes.items() if node["type"] == LEVER_TYPE]
    assert [scenario_of.get(n) for n in levers] == ["towers-removed"], (
        f"Towers removed reads the buildings through no Map Editor node: the Map Editor nodes are {levers}, "
        f"in the scenarios {[scenario_of.get(n) for n in levers]}"
    )
    (lever,) = levers
    # The lever's edits are in its code, its only state.
    shipped, keywords = _edits_of(nodes[lever]["content"])
    assert keywords.get("key") == "building_id", keywords
    assert [(edit["op"], edit["ids"]) for edit in shipped] == [("remove", SCOUT_TOWERS)], shipped
    assert "editFeatures" not in nodes[lever]["metadata"], nodes[lever]["metadata"]
    (label,) = [edit["label"] for edit in shipped]
    buildings_map = _lever_map(dataflow, lever)
    assert scenario_of.get(buildings_map) == "towers-removed", "the lever's map is not in its scenario's box"
    (loader,) = [n for n, node in nodes.items() if node["type"] == LOADER_TYPE]
    statistics = {scenario_of[n]: n for n, node in nodes.items() if node["type"] == CALCULATOR_TYPE
                  and "\nreturn raster_statistics(" in node["content"]}
    assert sorted(statistics) == ["existing", "towers-removed"], statistics
    chart = _parts(dataflow)["chart"]
    shadow_map = _shadow_maps(dataflow)["towers-removed"]

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scout Shadows Lever",
        username="scout_shadows_lever_e2e",
        project_name=dataflow["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    token, project_id = session["token"], session["project"]["id"]
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", token)["packages"]]
    missing = [package for package in PACKAGES if package not in store]
    assert not missing, f"{missing} are not in the account's store {store}: start the stack --with-examples"
    for node_id in nodes:
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)
    require_webgpu(page)

    # 1. Run All: SCOUT's two means, in the rows the Bars chart reads.
    run_all_and_wait(page, timeout_ms=600000)
    for node_id in [loader, lever, buildings_map, *statistics.values(), chart]:
        status = wait_for_node_settled(page, node_id, node_type=nodes[node_id]["type"], timeout_ms=180000)
        assert status == "done", (
            f"{nodes[node_id]['type']} {node_id} ended {status}: {read_node_error_text(node_locator(page, node_id))}"
        )
    before = _chart_means(page, chart)
    assert all(abs(before[key] - SCOUT_MEANS[key]) <= 0.1 for key in SCOUT_MEANS), (
        f"mean accumulated shadow, ours {before}, SCOUT's {SCOUT_MEANS}"
    )
    # Each mean the chart reads is its scenario's statistics' mean.
    for scenario, node_id in statistics.items():
        (mean,) = _saved_output(page, node_id)["data"]["mean"]
        assert before[scenario] == pytest.approx(mean, rel=1e-12), (scenario, before[scenario], mean)

    # 2. The lever, on its buildings map: its layer by building_id, and SCOUT's entry.
    edit = node_locator(page, lever)
    frame_nodes(page, [lever, buildings_map])
    _open_tab(page, lever, "output")
    _assert_linked(page, lever, buildings_map, nodes[buildings_map]["title"])
    assert_autark_map_drawn(page, buildings_map, timeout=60000, attach_as="the towers lever's buildings map")
    layer = edit.get_by_test_id("interaction-layer-input_0")
    expect(layer).to_contain_text("Buildings")
    expect(layer).not_to_contain_text("no id column")
    assert edit.locator("[data-curio-node-empty]").count() == 0, edit.locator("[data-curio-node-empty]").all_inner_texts()
    scouts = f"{label}: Remove building_id {', '.join(str(i) for i in SCOUT_TOWERS)}"
    expect(edit.locator('[data-edit-list="1"] [data-edit-op="remove"]')).to_contain_text(scouts, timeout=10000)

    # 3. The buildings still taller than 200 m, picked by a rule, lit up on
    # the map, and removed.
    heights = _heights(page, loader)
    assert sorted(heights) == list(range(123)), f"the buildings' ids are not 0 to 122: {sorted(heights)[:10]}"
    taller = sorted(i for i, height in heights.items() if i not in SCOUT_TOWERS and height > 200)
    assert taller, "no building is taller than 200 m once SCOUT's 15 are gone"
    _open(page, lever, "remove")
    edit.get_by_test_id("interaction-remove-by-rule").click()
    _rule(page, lever, ">", "200")
    left = len(heights) - len(SCOUT_TOWERS)
    expect(edit.get_by_test_id("interaction-matching")).to_have_text(
        f"Matches {len(taller)} {'area' if len(taller) == 1 else 'areas'} of {left}", timeout=10000,
    )
    _wait_for_selection(page, buildings_map, lever, set(taller), f"the rule {TALLER}")
    _wait_for_lit(page, buildings_map, taller, f"the rule {TALLER}")
    expect(_overlay(page, buildings_map).locator(OUTLINES)).to_have_count(0)
    remove = edit.get_by_test_id("interaction-remove-picked")
    expect(remove).to_have_text(f"Remove {len(taller)} {'area' if len(taller) == 1 else 'areas'}")
    remove.click()
    code, _keywords = _wait_for_edits(page, lever, [*shipped, {"op": "remove", "where": TALLER}], f"the Remove where {TALLER}")
    edit.locator('[data-edit-list="2"]').wait_for(state="attached", timeout=10000)
    expect(edit.locator('[data-edit-op="remove"]').nth(1)).to_contain_text(f"Remove where {TALLER}", timeout=10000)
    expect(edit.get_by_test_id("interaction-counts")).to_have_text(
        f"{len(SCOUT_TOWERS) + len(taller)} removed, 0 changed", timeout=10000,
    )

    # 4. Commit edits runs the lever and every node below it: each one that
    # saves an output saves it to a new file, and its maps draw again. The
    # Bars chart saves none: it draws what it reads, which the rows below check.
    _commit(page, lever, [lever, statistics["towers-removed"]], [buildings_map, shadow_map],
            below=len(_below(dataflow, lever)))
    handed = _heights(page, lever)
    assert sorted(handed) == sorted(set(heights) - set(SCOUT_TOWERS) - set(taller)), (
        f"the lever handed on {sorted(handed)}, not the buildings without SCOUT's 15 and {taller}"
    )
    (mean,) = _saved_output(page, statistics["towers-removed"])["data"]["mean"]
    after = None
    deadline = time.time() + 30
    while time.time() < deadline:
        after = _chart_means(page, chart)
        if abs(after["towers-removed"] - mean) < 1e-6:
            break
        page.wait_for_timeout(250)
    record_property("mean accumulated shadow (minutes)", json.dumps({"before": before, "after": after}))
    assert abs(after["towers-removed"] - mean) < 1e-6 and abs(after["existing"] - before["existing"]) < 1e-6, (
        f"the Bars chart reads the means {after}; Towers removed's statistics took {mean}"
    )
    assert abs(after["towers-removed"] - before["towers-removed"]) > 0.1, (
        f"removing {taller} too left Towers removed's mean at {after['towers-removed']}, "
        f"where it was {before['towers-removed']}"
    )
    assert abs(after["existing"] - before["existing"]) < 1e-6, (
        f"Existing's mean moved from {before['existing']} to {after['existing']}, though none of its nodes ran"
    )
    _back_to_layers(page, lever)
    assert_autark_map_drawn(page, buildings_map, timeout=60000, attach_as="the towers lever's buildings map after the edit")
    save_node_closeup(page, "scout-shadow-towers-lever", lever, test_name=LEVER_TEST_NAME, sweep_toasts=True)
    save_node_closeup(page, "scout-shadow-towers-lever-map", buildings_map, test_name=LEVER_TEST_NAME, sweep_toasts=True)

    # 5. The code is saved with the dataflow.
    save_dataflow(page)
    saved = {node["id"]: node for node in _saved_spec(current_server, token, project_id)["dataflow"]["nodes"]}
    assert saved[lever]["content"] == code
    edits, keywords = _edits_of(saved[lever]["content"])
    assert keywords.get("key") == "building_id", keywords
    assert edits == [*shipped, {"op": "remove", "where": TALLER}], edits
    assert "editFeatures" not in saved[lever]["metadata"], saved[lever]["metadata"]
