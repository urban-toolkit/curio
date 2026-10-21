"""SCOUT's high-rise shadow case on the canvas, compared as two scenarios (#662, step 19).

The shipped test dataflow ``chicago-loop-shadow-towers.json``: SCOUT's Chicago Loop buildings
(the Data Catalog dataset ``data.scout.loop-buildings``) and a season Parameter
node are the fixed context. In "Existing", Rasterize Buildings
(``curio.scout@1``) draws them into one zoom-16 height raster,
Accumulated Shadow, the node of the model package ``model.scout.deep-umbra@1``,
runs SCOUT's Deep Umbra model on it, in the season both scenarios share, an
Autark map draws the shadow, and a Raster Calculator (``curio.scout@1`` too)
takes the shadow's statistics over the ground, the heights as its mask.
"Towers removed" first reads the buildings through a Map Edits node, its
lever, whose code removes the 15 buildings SCOUT's second scenario removes,
matched on building_id. Outside the scenarios, Scout's Bars charts
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
   (minutes)", its legend labelled 0 to 720, the color range both maps share.
   The close-ups of the three maps are the frames.

A second test edits the lever, as a user does, putting one of the towers
back, and runs the scenario again with the edit: its numbers move (see its
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
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .test_map_edits_e2e import _listed, _panel, _wait_for_code, _wait_for_unsaved, _watch_save_state
from .test_scenario_drop_e2e import _saved_spec
from .test_widget_tags_e2e import _open_tab
from .utils import (
    REPO_ROOT,
    _COLOR_PIXELS_JS,
    _OUTPUT_ARTIFACT_JS,
    _assert_legend_reads,
    _assert_legend_title,
    api_json,
    assert_autark_map_drawn,
    assert_vega_canvas_rendered,
    frame_nodes,
    load_artifact_as_dict,
    load_raster_cells,
    node_locator,
    play_node,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_all_and_wait,
    save_dataflow,
    save_dataflow_and_settle_header,
    save_node_closeup,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
    wait_for_run_guard_released,
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

LEVER_TEST_NAME = "test_a_tower_put_back_in_the_towers_lever_reaches_the_shadow"
#: The Map Edits node (its type id is still the Edit Features node's).
MAP_EDITS_TYPE = "curio.builtin/edit-features"
LOADER_TYPE = "curio.builtin/data-loading"
#: The buildings Towers removed's lever removes as shipped, by building_id:
#: the 15 SCOUT's second scenario leaves out.
SCOUT_TOWERS = [8, 10, 12, 13, 14, 18, 19, 31, 34, 51, 66, 77, 82, 106, 122]
#: The edit the test makes in the lever: one of SCOUT's towers put back.
PUT_BACK = 8
#: How long the run after the edit may take: the scenario's rasterizer and
#: Deep Umbra run again.
UPDATE_MS = 300000


def _lever_code(removed: list[int]) -> str:
    """The lever's code as its map writes it (``mapEditsCode`` in
    ``utils/mapEdits/mapEdits.ts``) when it removes *removed*: the node's own
    comment lines, then the line that names SCOUT's buildings, which stays."""
    return (
        "# Map Edits writes this code from its map: the features it removes and the\n"
        "# values it changes, matched by building_id. Comment lines above the return stay.\n"
        "# SCOUT's 15 removed buildings.\n"
        "return curio_map_edits(\n"
        "    input_0,\n"
        '    key="building_id",\n'
        f"    remove=[{', '.join(str(i) for i in removed)}],\n"
        "    change={},\n"
        ")\n"
    )


def _maps_by_scenario(dataflow: dict) -> dict:
    """Each scenario's Autark map, by the scenario's id."""
    maps = {node["id"] for node in dataflow["nodes"] if node["type"] == MAP_TYPE}
    found = {}
    for scenario in dataflow["scenarios"]:
        members = [node_id for node_id in scenario["nodes"] if node_id in maps]
        assert len(members) == 1, f"scenario {scenario['name']!r} holds {len(members)} maps, not one of its shadow"
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
    maps = _maps_by_scenario(dataflow)
    into = {edge["target"]: edge["source"] for edge in dataflow["edges"] if edge["targetHandle"] == "in"}
    for scenario, map_id in maps.items():
        assert nodes[into[map_id]]["type"] == SHADOW_TYPE, f"the {scenario} map does not draw its shadow"
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
    for node_id in [*shadows, *statistics, *maps.values(), chart, change, difference_map]:
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


def _assert_lever_map_drawn(page, lever: str) -> None:
    """The lever's own map, the Autark map code drawing its input, drawn.

    The map draws the buildings flat in one colour, fewer colours than
    ``assert_autark_map_drawn`` asks of a city map, as the Map Edits test's
    boxes do (``test_map_edits_e2e``): its state says it drew, and its
    close-up compares the drawing with its baseline."""
    edit = node_locator(page, lever)
    frame_nodes(page, [lever])
    _open_tab(page, lever, "output")
    edit.locator('[data-map-edits-map-state]:not([data-map-edits-map-state="drawing"])').wait_for(
        state="attached", timeout=90000,
    )
    state = edit.locator("[data-map-edits-map-state]").get_attribute("data-map-edits-map-state")
    problem = edit.locator("[data-map-edits-map-problem]").all_inner_texts()
    assert state == "drawn", f"the towers lever's map ended {state!r}: {problem}"


# A node's new outcome: "error", or "success" once its output is saved to
# another file than *before*, the one it was saved to before the click.
_NEW_OUTCOME_JS = """([id, before]) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    const output = node && node.data && node.data.output;
    if (!output) return false;
    if (output.code === "error") return "error";
    if (output.code !== "success") return false;
    const match = String(output.content || "").match(/Saved to file: (\\S+)/);
    return match && match[1] !== before ? "success" : false;
}"""


def _wait_for_new_outcome(page, node_id: str, before: str, *, node_type: str, timeout_ms: int) -> str:
    """How *node_id*'s next run ended: ``"success"``, its output saved to a new
    file, or ``"error"``.

    A step of a run on the server can start and end between two renders (a
    quick node's takes milliseconds), so the node need never show itself
    running, and ``watch_node_run`` would wait for a run that came and
    went. The new file its output is saved to tells that it ran again. Polls on
    a timer, not on animation frames."""
    try:
        handle = page.wait_for_function(_NEW_OUTCOME_JS, arg=[node_id, before], timeout=timeout_ms, polling=500)
    except PlaywrightTimeoutError:
        box = node_locator(page, node_id)
        status = box.locator("[data-curio-node-status]").first.get_attribute("data-curio-node-status")
        raise AssertionError(
            f"{node_type} {node_id} did not run again within {timeout_ms} ms: its output is still saved to "
            f"{before}, status {status!r}: {read_node_error_text(box)}"
        ) from None
    return handle.json_value()


def test_a_tower_put_back_in_the_towers_lever_reaches_the_shadow(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    record_property,
):
    """Towers removed's Map Edits node is the scenario's lever: its code
    removes SCOUT's 15 buildings by building_id, under a comment line that
    names them. One of them put back there, then a run, runs the scenario
    again with it:

    1. Run All gives SCOUT's two means, as the test above checks, each the
       mean its scenario's statistics took.
    2. The lever draws the buildings on its map, matched on building_id, and
       its panel lists SCOUT's 15 under Removed.
    3. A click on building 8 there puts it back: the lever's code removes the
       other 14, its comment lines kept, the panel lists those, and the
       dataflow reads Unsaved.
    4. Playing Towers removed's statistics runs the lever, which is stale
       after the edit, and the nodes between them again. The lever hands on
       the buildings without the 14; Towers removed's mean rises, the tower's
       shadow on the ground again, and the Bars chart shows the mean its
       statistics took; Existing, which did not run, keeps its mean. The
       lever's close-up is the frame.
    5. The lever's code is saved with the dataflow, and nothing else holds
       its edits.
    """
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(_KEEP_VEGA_VIEWS_INIT)
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    scenario_of = {node_id: scenario["id"] for scenario in dataflow["scenarios"] for node_id in scenario["nodes"]}
    levers = [n for n, node in nodes.items() if node["type"] == MAP_EDITS_TYPE]
    assert [scenario_of.get(n) for n in levers] == ["towers-removed"], (
        f"Towers removed reads the buildings through no Map Edits node: the Map Edits nodes are {levers}, "
        f"in the scenarios {[scenario_of.get(n) for n in levers]}"
    )
    (lever,) = levers
    assert nodes[lever]["content"] == _lever_code(SCOUT_TOWERS), nodes[lever]["content"]
    assert "editFeatures" not in nodes[lever]["metadata"], nodes[lever]["metadata"]
    (loader,) = [n for n, node in nodes.items() if node["type"] == LOADER_TYPE]
    statistics = {scenario_of[n]: n for n, node in nodes.items() if node["type"] == CALCULATOR_TYPE
                  and "\nreturn raster_statistics(" in node["content"]}
    assert sorted(statistics) == ["existing", "towers-removed"], statistics
    chart = _parts(dataflow)["chart"]

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
    for node_id in [loader, lever, *statistics.values(), chart]:
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

    # 2. The lever: the buildings on its map, by building_id, and SCOUT's 15
    # under Removed.
    edit = node_locator(page, lever)
    _assert_lever_map_drawn(page, lever)
    assert edit.get_by_test_id("edit-features-key").input_value() == "building_id"
    assert edit.locator("[data-map-edits-refusal]").count() == 0
    assert _listed(page, lever, "put-back") == [str(i) for i in SCOUT_TOWERS]
    heights = _heights(page, loader)
    assert sorted(heights) == list(range(123)), f"the buildings' ids are not 0 to 122: {sorted(heights)[:10]}"

    # 3. Building 8 put back, with a click on its id.
    save_dataflow_and_settle_header(page)
    _watch_save_state(page)
    _panel(page, lever).locator(f'[data-map-edits-put-back="{PUT_BACK}"]').click()
    removed = [i for i in SCOUT_TOWERS if i != PUT_BACK]
    code = _lever_code(removed)
    _wait_for_code(page, lever, code, f"building {PUT_BACK} was put back")
    expect(_panel(page, lever).locator(f'[data-map-edits-put-back="{PUT_BACK}"]')).to_have_count(0)
    assert _listed(page, lever, "put-back") == [str(i) for i in removed]
    _wait_for_unsaved(page, f"building {PUT_BACK} was put back")

    # 4. Playing Towers removed's statistics runs the lever and every node
    # between them: each one's output is saved to a new file. The Bars chart
    # saves none: it draws what it reads, which the rows below check.
    ran = [lever, statistics["towers-removed"]]
    saved_to = {node_id: page.evaluate(_OUTPUT_ARTIFACT_JS, node_id) for node_id in ran}
    assert all(saved_to.values()), f"a node shows no saved output before the run: {saved_to}"
    play_node(page, statistics["towers-removed"])
    for node_id in ran:
        node_type = nodes[node_id]["type"]
        outcome = _wait_for_new_outcome(page, node_id, saved_to[node_id], node_type=node_type, timeout_ms=UPDATE_MS)
        status = wait_for_node_settled(page, node_id, node_type=node_type, timeout_ms=60000)
        assert (outcome, status) == ("success", "done"), (
            f"{node_type} {node_id} ran again and ended {outcome}, {status}: "
            f"{read_node_error_text(node_locator(page, node_id))}"
        )
    wait_for_run_guard_released(page, timeout_ms=UPDATE_MS)
    handed = _heights(page, lever)
    assert sorted(handed) == sorted(set(heights) - set(removed)), (
        f"the lever handed on {sorted(handed)}, not the buildings without {removed}"
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
    assert after["towers-removed"] > before["towers-removed"] + 0.1, (
        f"putting building {PUT_BACK} back left Towers removed's mean accumulated shadow at "
        f"{after['towers-removed']:.4f} minutes, where it was {before['towers-removed']:.4f}: "
        "the tower's shadow falls on the ground again"
    )
    assert abs(after["existing"] - before["existing"]) < 1e-6, (
        f"Existing's mean moved from {before['existing']} to {after['existing']}, though none of its nodes ran"
    )
    _assert_lever_map_drawn(page, lever)
    save_node_closeup(page, "scout-shadow-towers-lever", lever, test_name=LEVER_TEST_NAME, sweep_toasts=True)

    # 5. The lever's code is saved with the dataflow, and nothing else holds
    # its edits.
    save_dataflow(page)
    saved = {node["id"]: node for node in _saved_spec(current_server, token, project_id)["dataflow"]["nodes"]}
    assert saved[lever]["content"] == code, saved[lever]["content"]
    assert "editFeatures" not in saved[lever]["metadata"], saved[lever]["metadata"]
