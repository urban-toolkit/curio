"""SCOUT's high-rise shadow case on the canvas, compared as two scenarios (#662, step 19).

The shipped test dataflow ``ScoutShadows.json``: SCOUT's Chicago Loop buildings
(the Data Catalog dataset ``data.scout.loop-buildings``) and a season Parameter
node are the fixed context. In "Existing", Rasterize Buildings
(``scout.raster-conversion@1``) draws them into one zoom-16 height raster,
Accumulated Shadow, the node of the model package ``model.scout.deep-umbra@1``,
runs SCOUT's Deep Umbra model on it, in the season both scenarios share, an
Autark map draws the shadow, and a Raster Calculator (``curio.builtin@1``)
takes the shadow's statistics over the ground, the heights as its mask.
"Towers removed" first reads the buildings through an Interaction node, its
lever, whose edit log removes the 15 buildings SCOUT's second scenario
removes, matched on building_id. Two Compare Scenarios nodes read the
scenarios' outcomes: one charts the mean accumulated shadow, the other takes
its change, which an Autark map after it draws on a scale centered on no
change.

Run All in the browser runs the whole dataflow:

1. The chart's stacked table holds one row per scenario with SCOUT's mean
   accumulated shadow for each (128.64 and 106.73 minutes in SCOUT's metrics
   files, in summer) within 0.1 minutes, and its bars draw in both scenarios'
   colors.
2. The difference is a raster on the shadow mosaics' grid, 512 by 512 cells in
   EPSG:3395, in minutes: towers removed minus existing, which takes shadow away
   on the whole. The node draws no map of it; the Autark map after it does,
   under the title "Shadow change (minutes)".
3. Each scenario's map draws its shadow, under the title "Accumulated shadow
   (minutes)", its legend labelled 0 to 720, the color range both maps share.
   The close-ups of the three maps are the frames.

A second test edits the lever, as a user does, and presses Update results:
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
import math
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .test_compare_difference_e2e import (
    _OUTPUT_ARTIFACT_JS,
    _assert_difference_mapped,
    _assert_legend_reads,
    _assert_legend_title,
    _band,
)
from .test_compare_scenarios_e2e import _CHART_STATE_JS, _COLOR_PIXELS_JS
from .test_edit_features_e2e import _apply_where
from .test_scenario_drop_e2e import _saved_spec
from .test_widget_tags_e2e import _open_tab
from .utils import (
    REPO_ROOT,
    api_json,
    assert_autark_map_drawn,
    assert_vega_canvas_rendered,
    frame_nodes,
    load_artifact_as_dict,
    node_locator,
    read_node_code,
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
    wait_for_run_guard_released,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "ScoutShadows.json"
TEST_NAME = "test_two_building_sets_are_shadowed_charted_and_mapped"
SHADOW_TYPE = "model.scout.deep-umbra/accumulated-shadow"
CALCULATOR_TYPE = "curio.builtin/raster-calculator"
COMPARE_TYPE = "curio.builtin/compare-scenarios"
MAP_TYPE = "curio.builtin/autk-grammar"
PACKAGES = ("model.scout.deep-umbra@1", "scout.raster-conversion@1")
#: SCOUT's A_shadows_metric.csv and B_shadows_metric.csv.
SCOUT_MEANS = {"existing": 128.63593, "towers-removed": 106.73111}
#: The color range both scenarios' shadow maps share, in minutes
#: (``colorMapRange``): both legends read its ends.
SHADOW_RANGE = (0, 720)

LEVER_TEST_NAME = "test_an_edit_in_the_towers_lever_reaches_the_shadow_with_update_results"
#: The Interaction node (#958; its type is still the Edit Features node's).
INTERACTION_TYPE = "curio.builtin/edit-features"
LOADER_TYPE = "curio.builtin/data-loading"
#: The buildings Towers removed's lever removes as shipped, by building_id:
#: the 15 SCOUT's second scenario leaves out.
SCOUT_TOWERS = [8, 10, 12, 13, 14, 18, 19, 31, 34, 51, 66, 77, 82, 106, 122]
#: The edit the test makes in the lever: the buildings still taller than 200 m,
#: picked by a condition and removed too.
TALLER = "height > 200"
#: How long Update results may take: the scenario's rasterizer and Deep Umbra
#: run again.
UPDATE_MS = 300000


def _maps_by_scenario(dataflow: dict) -> dict:
    """Each scenario's Autark map, by the scenario's id."""
    maps = {node["id"] for node in dataflow["nodes"] if node["type"] == MAP_TYPE}
    found = {}
    for scenario in dataflow["scenarios"]:
        members = [node_id for node_id in scenario["nodes"] if node_id in maps]
        assert len(members) == 1, f"scenario {scenario['name']!r} holds {len(members)} maps, not one of its shadow"
        found[scenario["id"]] = members[0]
    return found


def _assert_chart_drew(page, node_id: str, colors: list[str]) -> None:
    """The bar chart compiled with no problem, and its canvas holds both scenarios' colors."""
    deadline = time.time() + 60
    state = None
    while time.time() < deadline:
        state = page.evaluate(_CHART_STATE_JS, [node_id, "bar"])
        if state in ("drawn", "problem"):
            break
        page.wait_for_timeout(250)
    problem = node_locator(page, node_id).locator("[data-compare-chart-problem]").all_inner_texts()
    assert state == "drawn", f"the bar chart's compile ended {state!r}: {problem}"
    assert_vega_canvas_rendered(page, node_id, timeout=30000)
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_COLOR_PIXELS_JS, [node_id, colors])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart does not draw both scenarios' colors {colors}: pixels {counts}")


def _saved_output(page, node_id: str) -> dict:
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, f"{node_id} shows no saved output"
    return load_artifact_as_dict(artifact)


def _means(page, chart: str) -> dict:
    """Each scenario's mean accumulated shadow, from the chart's stacked table."""
    stacked = _saved_output(page, chart)
    assert stacked["dataType"] == "dataframe", stacked["dataType"]
    table = stacked["data"]
    return dict(zip(table["scenario"], table["mean"]))


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
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    shadows = [n for n, node in nodes.items() if node["type"] == SHADOW_TYPE]
    statistics = [n for n, node in nodes.items() if node["type"] == CALCULATOR_TYPE
                  and "\nreturn curio_raster_statistics(" in node["content"]]
    assert len(shadows) == len(statistics) == 2, (shadows, statistics)
    (chart,) = [n for n, node in nodes.items() if node["type"] == COMPARE_TYPE
                and node["metadata"]["compareScenarios"]["mode"] == "chart"]
    (difference,) = [n for n, node in nodes.items() if node["type"] == COMPARE_TYPE
                     and node["metadata"]["compareScenarios"]["mode"] == "difference"]
    colors = [scenario["color"] for scenario in dataflow["scenarios"]]
    maps = _maps_by_scenario(dataflow)
    into = {edge["target"]: edge["source"] for edge in dataflow["edges"] if edge["targetHandle"] == "in"}
    for scenario, map_id in maps.items():
        assert nodes[into[map_id]]["type"] == SHADOW_TYPE, f"the {scenario} map does not draw its shadow"
    after = [n for n, node in nodes.items() if node["type"] == MAP_TYPE and into.get(n) == difference]
    assert len(after) == 1, f"the difference feeds the Autark maps {after}, not one"
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
    for node_id in [*shadows, *statistics, *maps.values(), chart, difference, difference_map]:
        status = wait_for_node_settled(page, node_id, node_type=nodes[node_id]["type"], timeout_ms=180000)
        assert status == "done", (
            f"{nodes[node_id]['type']} {node_id} ended {status}: {read_node_error_text(node_locator(page, node_id))}"
        )

    # 1. One row per scenario, SCOUT's means, bars in both scenarios' colors.
    stacked = _saved_output(page, chart)
    assert stacked["dataType"] == "dataframe", stacked["dataType"]
    table = stacked["data"]
    # The read-back returns the columns by name, sorted, not in the table's order.
    assert sorted(table) == sorted(["scenario", "scenario_name", "mean", "median", "min", "max", "count"]), list(table)
    assert table["scenario"] == ["existing", "towers-removed"], table["scenario"]
    assert table["scenario_name"] == ["Existing", "Towers removed"], table["scenario_name"]
    # The ground: the cells with no building, most of SCOUT's four tiles.
    assert all(100000 < count < 512 * 512 for count in table["count"]), table["count"]
    means = dict(zip(table["scenario"], table["mean"]))
    record_property("mean accumulated shadow (minutes)", json.dumps({"ours": means, "scout": SCOUT_MEANS}))
    # The proof's tolerance (test_scout_shadow.py): Deep Umbra's output moves
    # with onnxruntime's thread count above 16.
    assert all(abs(means[key] - SCOUT_MEANS[key]) <= 0.1 for key in SCOUT_MEANS), (
        f"mean accumulated shadow, ours {means}, SCOUT's {SCOUT_MEANS}"
    )
    frame_nodes(page, [chart])
    _assert_chart_drew(page, chart, colors)

    # 2. Towers removed minus existing, on the mosaics' grid, mapped.
    stored = _saved_output(page, difference)
    envelope = stored.get("data") if stored.get("dataType") == "dict" else stored
    assert envelope["dataType"] == "raster", stored.get("dataType")
    grid = envelope["data"]["grid"]
    assert (grid["crs"], grid["width"], grid["height"]) == ("EPSG:3395", 512, 512), grid
    cells = _band(envelope)
    assert len(cells) == 512 * 512
    assert not any(math.isnan(v) for v in cells), "the difference has nodata where both mosaics have shadow"
    mean_change = sum(cells) / len(cells)
    record_property("difference (minutes)", json.dumps({"min": min(cells), "max": max(cells), "mean": mean_change}))
    assert min(cells) < -100 and mean_change < 0, (min(cells), max(cells), mean_change)
    assert -720 <= min(cells) and max(cells) <= 720, (min(cells), max(cells))
    frame_nodes(page, [difference, difference_map])
    _assert_difference_mapped(
        page, difference, difference_map, "the change in accumulated shadow when the towers are removed",
        legend="Shadow change (minutes)",
    )
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
    ``assert_autark_map_drawn`` asks of a city map, as the Interaction test's
    boxes do (``test_edit_features_e2e``): its state says it drew, and its
    close-up compares the drawing with its baseline."""
    edit = node_locator(page, lever)
    frame_nodes(page, [lever])
    _open_tab(page, lever, "output")
    edit.locator('[data-edit-map-state]:not([data-edit-map-state="drawing"])').wait_for(
        state="attached", timeout=90000,
    )
    state = edit.locator("[data-edit-map-state]").get_attribute("data-edit-map-state")
    problem = edit.locator("[data-edit-map-problem]").all_inner_texts()
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
    Compare Scenarios node's takes milliseconds), so the node need never show
    itself running, and ``watch_node_run`` would wait for a run that came and
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


def test_an_edit_in_the_towers_lever_reaches_the_shadow_with_update_results(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    record_property,
):
    """Towers removed's Interaction node is the scenario's lever: its log holds
    SCOUT's 15 removed buildings, one removal by building_id under a label. An
    edit made there, then Update results, runs the scenario again with it:

    1. Run All gives SCOUT's two means, as the test above checks.
    2. The lever draws the buildings on its map, matched on building_id, and
       lists SCOUT's removal under its label.
    3. A condition picks the buildings still taller than 200 m, and Remove
       makes it a second entry: the lever's code holds it, and the lever and
       the nodes below it are out of date.
    4. Update results runs them. The lever hands on the buildings without
       SCOUT's 15 and without those; Towers removed's mean moves away from the
       one SCOUT's case gave, and the chart shows the mean its statistics took;
       Existing, which did not run, keeps its mean. The lever's close-up is the
       frame.
    5. The log is saved with the dataflow, SCOUT's entry under its label.
    """
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    scenario_of = {node_id: scenario["id"] for scenario in dataflow["scenarios"] for node_id in scenario["nodes"]}
    levers = [n for n, node in nodes.items() if node["type"] == INTERACTION_TYPE]
    assert [scenario_of.get(n) for n in levers] == ["towers-removed"], (
        f"Towers removed reads the buildings through no Interaction node: the Interaction nodes are {levers}, "
        f"in the scenarios {[scenario_of.get(n) for n in levers]}"
    )
    (lever,) = levers
    shipped = nodes[lever]["metadata"]["editFeatures"]
    assert shipped["key"] == "building_id", shipped
    assert [(edit["op"], edit["ids"]) for edit in shipped["edits"]] == [("remove", SCOUT_TOWERS)], shipped
    (label,) = [edit["label"] for edit in shipped["edits"]]
    (loader,) = [n for n, node in nodes.items() if node["type"] == LOADER_TYPE]
    statistics = {scenario_of[n]: n for n, node in nodes.items() if node["type"] == CALCULATOR_TYPE
                  and "\nreturn curio_raster_statistics(" in node["content"]}
    assert sorted(statistics) == ["existing", "towers-removed"], statistics
    (chart,) = [n for n, node in nodes.items() if node["type"] == COMPARE_TYPE
                and node["metadata"]["compareScenarios"]["mode"] == "chart"]

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

    # 1. Run All: SCOUT's two means.
    run_all_and_wait(page, timeout_ms=600000)
    for node_id in [loader, lever, *statistics.values(), chart]:
        status = wait_for_node_settled(page, node_id, node_type=nodes[node_id]["type"], timeout_ms=180000)
        assert status == "done", (
            f"{nodes[node_id]['type']} {node_id} ended {status}: {read_node_error_text(node_locator(page, node_id))}"
        )
    before = _means(page, chart)
    assert all(abs(before[key] - SCOUT_MEANS[key]) <= 0.1 for key in SCOUT_MEANS), (
        f"mean accumulated shadow, ours {before}, SCOUT's {SCOUT_MEANS}"
    )

    # 2. The lever: the buildings on its map, by building_id, and SCOUT's entry.
    edit = node_locator(page, lever)
    _assert_lever_map_drawn(page, lever)
    assert edit.get_by_label("Id", exact=True).input_value() == "building_id"
    assert edit.locator("[data-edit-refusal]").count() == 0
    scouts = f"{label}: Remove building_id {', '.join(str(i) for i in SCOUT_TOWERS)}"
    expect(edit.locator('[data-edit-list="1"] [data-edit-op="remove"]')).to_contain_text(scouts, timeout=10000)

    # 3. The buildings still taller than 200 m, picked by a condition, removed.
    heights = _heights(page, loader)
    assert sorted(heights) == list(range(123)), f"the buildings' ids are not 0 to 122: {sorted(heights)[:10]}"
    taller = sorted(i for i, height in heights.items() if i not in SCOUT_TOWERS and height > 200)
    assert taller, "no building is taller than 200 m once SCOUT's 15 are gone"
    edit.get_by_test_id("interaction-where").fill(TALLER)
    matching = "1 feature" if len(taller) == 1 else f"{len(taller)} features"
    expect(edit.get_by_test_id("interaction-matching")).to_have_text(matching, timeout=10000)
    _apply_where(edit, TALLER, "remove")
    edit.locator('[data-edit-list="2"]').wait_for(state="attached", timeout=10000)
    expect(edit.locator('[data-edit-op="remove"]').nth(1)).to_contain_text(f"Remove where {TALLER}", timeout=10000)
    expect(edit.get_by_test_id("interaction-counts")).to_have_text(
        f"{len(SCOUT_TOWERS) + len(taller)} removed, 0 changed", timeout=10000,
    )
    entry = f'{{"op": "remove", "where": "{TALLER}"}},'
    deadline = time.time() + 15
    code = ""
    while time.time() < deadline:
        code = read_node_code(page, lever)
        if entry in code:
            break
        page.wait_for_timeout(250)
    assert entry in code, f"the lever did not write its new entry into its code:\n{code}"
    update = edit.get_by_test_id("interaction-update")
    expect(update).to_have_text(re.compile(r"^Update results \(\d+\)$"), timeout=10000)

    # 4. Update results runs the lever and every node below it: each one's
    # output is saved to a new file.
    ran = [lever, statistics["towers-removed"], chart]
    saved_to = {node_id: page.evaluate(_OUTPUT_ARTIFACT_JS, node_id) for node_id in ran}
    assert all(saved_to.values()), f"a node shows no saved output before Update results: {saved_to}"
    update.click()
    for node_id in ran:
        node_type = nodes[node_id]["type"]
        outcome = _wait_for_new_outcome(page, node_id, saved_to[node_id], node_type=node_type, timeout_ms=UPDATE_MS)
        status = wait_for_node_settled(page, node_id, node_type=node_type, timeout_ms=60000)
        assert (outcome, status) == ("success", "done"), (
            f"{node_type} {node_id} ran again and ended {outcome}, {status}: "
            f"{read_node_error_text(node_locator(page, node_id))}"
        )
    wait_for_run_guard_released(page, timeout_ms=UPDATE_MS)
    expect(update).to_have_text("Update results", timeout=30000)
    handed = _heights(page, lever)
    assert sorted(handed) == sorted(set(heights) - set(SCOUT_TOWERS) - set(taller)), (
        f"the lever handed on {sorted(handed)}, not the buildings without SCOUT's 15 and {taller}"
    )
    after = _means(page, chart)
    (mean,) = _saved_output(page, statistics["towers-removed"])["data"]["mean"]
    record_property("mean accumulated shadow (minutes)", json.dumps({"before": before, "after": after}))
    assert abs(after["towers-removed"] - mean) < 1e-6, (
        f"the chart shows Towers removed's mean as {after['towers-removed']}, its statistics took {mean}"
    )
    assert abs(after["towers-removed"] - before["towers-removed"]) > 0.1, (
        f"removing {taller} too left Towers removed's mean at {after['towers-removed']}, "
        f"where it was {before['towers-removed']}"
    )
    assert abs(after["existing"] - before["existing"]) < 1e-6, (
        f"Existing's mean moved from {before['existing']} to {after['existing']}, though none of its nodes ran"
    )
    _assert_lever_map_drawn(page, lever)
    save_node_closeup(page, "scout-shadow-towers-lever", lever, test_name=LEVER_TEST_NAME, sweep_toasts=True)

    # 5. The log is saved with the dataflow.
    save_dataflow(page)
    saved = {node["id"]: node for node in _saved_spec(current_server, token, project_id)["dataflow"]["nodes"]}
    log = saved[lever]["metadata"]["editFeatures"]
    assert log["key"] == "building_id", json.dumps(log)
    assert log["edits"] == [*shipped["edits"], {"op": "remove", "where": TALLER}], json.dumps(log)
    assert saved[lever]["content"] == code
