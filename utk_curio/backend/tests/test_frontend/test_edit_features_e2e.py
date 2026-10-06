"""Playwright E2E: the Edit Features node (#662).

Two scenarios count the buildings of one layer: "Every building", whose Edit
Features node has no edits, and "One removed", a copy of it. The layer holds
three building parts, two of them one building's, so they share its
``building_id``, as Autark's buildings do. In One removed's Edit Features node
a building is picked with a double-click on the node's map, the Autark node's
own map code, and removed:

1. The node's map is drawn, its id column is ``building_id``, and it says an
   edit applies to every part of a building.
2. A double-click on a building picks it: the node lists its id.
3. Remove makes an edit, written into the node's code.
4. Run, the node's output has lost the building with every part, so the count
   downstream drops.
5. A Compare Scenarios node over both counts lists the edit in its What differs
   tab, against no edits in Every building.
6. The edit list is saved with the dataflow.

It runs an Autark map, which needs WebGPU: without an adapter it skips, unless
``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job), where it fails.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_edit_features_e2e.py -v
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from .test_compare_scenarios_e2e import _OUTPUT_ARTIFACT_JS
from .test_scenario_drop_e2e import _saved_spec
from .test_scenarios_canvas_e2e import _require_webgpu
from .test_widget_tags_e2e import _open_tab
from .utils import (
    assert_in_view,
    dismiss_toasts,
    frame_nodes,
    load_artifact_as_dict,
    mark_point,
    node_locator,
    play_node,
    read_node_code,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_dataflow,
    save_node_closeup,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EDIT_TYPE = "curio.builtin/edit-features"
LOAD = "ef-load"
EDIT, EDIT_2 = "ef-edit", "ef-edit-2"
COUNT, COUNT_2 = "ef-count", "ef-count-2"
COMPARE = "ef-compare"
EVERY, LESS = "s-every", "s-less"

# Building 1 in two parts, side by side on the left; building 2, one part as
# wide as both, on the right. Near Back Bay, in degrees.
LOAD_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import box\n"
    "x, y, w, h = -71.0790, 42.3490, 0.0010, 0.0012\n"
    "return gpd.GeoDataFrame(\n"
    '    {"building_id": [1, 1, 2], "height": [20.0, 35.0, 50.0]},\n'
    "    geometry=[box(x, y, x + w, y + h), box(x + w, y, x + 2 * w, y + h), box(x + 2 * w, y, x + 4 * w, y + h)],\n"
    "    crs=4326,\n"
    ")\n"
)
PARTS = {1: 2, 2: 1}
COUNT_CODE = "return len(arg)\n"
EMPTY_LIST = (
    "# Edit Features writes this code from its edit list: each edit, in the\n"
    "# order it was made, on the features whose key is one of its ids. It is\n"
    "# written again when the list changes.\n"
    'return curio_edit_features(arg, [], key="building_id")\n'
)

#: Where a double-click is tried on the map, as fractions of its drawing.
PICK_SPOTS = ((0.25, 0.5), (0.75, 0.5), (0.4, 0.5), (0.6, 0.5), (0.5, 0.5), (0.15, 0.6), (0.85, 0.6))


def _spec() -> dict:
    def node(node_id, node_type, x, y, content, title, metadata=None):
        return {
            "id": node_id, "type": node_type, "x": x, "y": y, "content": content, "title": title,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "",
            "metadata": {"keywords": [], **(metadata or {})},
        }

    def edge(source, target, handle="in"):
        return {"id": f"e-{source}-{target}", "source": source, "target": target, "sourceHandle": "out", "targetHandle": handle}

    key_only = {"editFeatures": {"key": "building_id"}}
    return {
        "dataflow": {
            "name": "Edit Features",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Edit Features",
            "nodes": [
                node(LOAD, "curio.builtin/data-loading", 0, 300, LOAD_CODE, "Buildings"),
                node(EDIT, EDIT_TYPE, 700, 0, EMPTY_LIST, "Edit Features", key_only),
                node(COUNT, "curio.builtin/computation-analysis", 1400, 0, COUNT_CODE, "Count"),
                node(EDIT_2, EDIT_TYPE, 700, 600, EMPTY_LIST, "Edit Features", {**key_only, "copiedFrom": [EDIT]}),
                node(COUNT_2, "curio.builtin/computation-analysis", 1400, 600, COUNT_CODE, "Count", {"copiedFrom": [COUNT]}),
                node(COMPARE, "curio.builtin/compare-scenarios", 2100, 300, "", "Compare"),
            ],
            "edges": [
                edge(LOAD, EDIT), edge(EDIT, COUNT), edge(LOAD, EDIT_2), edge(EDIT_2, COUNT_2),
                edge(COUNT, COMPARE, "in"), edge(COUNT_2, COMPARE, "in_1"),
            ],
            "scenarios": [
                {"id": EVERY, "name": "Every building", "color": "#3567c7", "nodes": [EDIT, COUNT]},
                {"id": LESS, "name": "One removed", "color": "#2f8f4a", "nodes": [EDIT_2, COUNT_2]},
            ],
        }
    }


def _done(page, node_id: str, node_type: str = "") -> None:
    status = wait_for_node_settled(page, node_id, node_type=node_type, timeout_ms=180000)
    assert status == "done", f"{node_id} ended {status!r}: {read_node_error_text(node_locator(page, node_id))}"


def _count(page, node_id: str) -> int:
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, f"{node_id} shows no saved output"
    stored = load_artifact_as_dict(artifact)
    assert stored["dataType"] == "int", stored
    return stored["data"]


def _picked(page) -> str:
    return node_locator(page, EDIT_2).locator("[data-edit-picked]").get_attribute("data-edit-picked") or ""


_SHOWN_JS = """([selector, x, y]) => document.elementFromPoint(x, y) === document.querySelector(selector)"""


def _pick_a_building(page) -> int:
    """Double-click the map where it draws a building, until the node lists one.

    The buildings fill the layer's extent, which the map fits, so a spot along
    the map's middle lands on one: the marked pixel nearest the spot when the
    buildings are drawn in a saturated colour, else the spot itself."""
    canvas = f"#autk-grammar-map-{EDIT_2}"
    tried = []
    for at in PICK_SPOTS:
        frame_nodes(page, [EDIT_2])
        dismiss_toasts(page)
        point = mark_point(page, canvas, at)
        if not point:
            box = page.locator(canvas).bounding_box()
            assert box, "the Edit Features map has no layout box"
            point = {"x": box["x"] + at[0] * box["width"], "y": box["y"] + at[1] * box["height"]}
        x, y = assert_in_view(page, point["x"], point["y"], f"the building near {at} of the Edit Features map")
        if not page.evaluate(_SHOWN_JS, [canvas, x, y]):
            tried.append((at, "covered"))
            continue
        page.mouse.dblclick(x, y)
        deadline = time.time() + 10
        while time.time() < deadline:
            picked = _picked(page)
            if picked:
                ids = [int(token) for token in picked.split()]
                assert len(ids) == 1 and ids[0] in PARTS, f"a double-click on one building picked {picked!r}"
                return ids[0]
            page.wait_for_timeout(250)
        tried.append((at, (round(x), round(y))))
    raise AssertionError(f"no double-click on the Edit Features map picked a building: {tried}")


def test_a_building_picked_and_removed_drops_the_count_and_is_listed_as_what_differs(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Edit Features",
        username="edit_features_e2e",
        project_name="Edit Features",
        project_spec=_spec(),
    )
    require_owner_view(page)
    token, project_id = session["token"], session["project"]["id"]
    for node_id in (LOAD, EDIT, EDIT_2, COUNT, COUNT_2, COMPARE):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    _require_webgpu(page)

    run_all_and_wait(page, timeout_ms=300000)
    for node_id in (EDIT, EDIT_2):
        _done(page, node_id, EDIT_TYPE)
    for node_id in (COUNT, COUNT_2):
        _done(page, node_id)
    assert (_count(page, COUNT), _count(page, COUNT_2)) == (3, 3), "with no edits every part is counted"

    # 1. The map is drawn, by building_id, and says an edit takes every part.
    edit = node_locator(page, EDIT_2)
    frame_nodes(page, [EDIT_2])
    _open_tab(page, EDIT_2, "output")
    edit.locator('[data-edit-map-state]:not([data-edit-map-state="drawing"])').wait_for(state="attached", timeout=90000)
    state = edit.locator("[data-edit-map-state]").get_attribute("data-edit-map-state")
    assert state == "drawn", f"the Edit Features map ended {state!r}: {edit.locator('[data-edit-map-problem]').all_inner_texts()}"
    # Three flat boxes fill the map with a few colours, under the many a city
    # map holds (assert_autark_map_drawn's test): the pick below is what proves
    # the buildings are drawn, a double-click landing on one; the close-up is
    # compared with its baseline.
    assert edit.get_by_label("Id", exact=True).input_value() == "building_id"
    note = edit.locator("[data-edit-building-note]").inner_text()
    assert "applies to the whole building" in note, note
    assert edit.locator("[data-edit-refusal]").count() == 0
    save_node_closeup(
        page, "edit-features", EDIT_2,
        test_name="test_a_building_picked_and_removed_drops_the_count_and_is_listed_as_what_differs",
        sweep_toasts=True,
    )

    # 2. A double-click picks a building; 3. Remove makes it an edit.
    picked = _pick_a_building(page)
    edit.get_by_test_id("edit-features-remove").click()
    edit.locator('[data-edit-list="1"]').wait_for(state="attached", timeout=10000)
    shown = edit.locator('[data-edit-op="remove"]').inner_text()
    assert f"Remove building_id {picked}" in shown, shown
    assert _picked(page) == "", "the pick is spent once it is an edit"
    deadline = time.time() + 15
    code = ""
    while time.time() < deadline:
        code = read_node_code(page, EDIT_2)
        if f'{{"op": "remove", "ids": [{picked}]}},' in code:
            break
        page.wait_for_timeout(250)
    assert f'{{"op": "remove", "ids": [{picked}]}},' in code, f"the node did not write its edit into its code:\n{code}"
    assert '], key="building_id")' in code, code

    # 4. Run: the building is gone with every part, and the count drops.
    play_node(page, EDIT_2)
    _done(page, EDIT_2, EDIT_TYPE)
    play_node(page, COUNT_2)
    _done(page, COUNT_2)
    expected = 3 - PARTS[picked]
    assert _count(page, COUNT_2) == expected < 3, (
        f"removing building {picked} ({PARTS[picked]} parts) left {_count(page, COUNT_2)} of 3 parts"
    )
    assert _count(page, COUNT) == 3, "the other scenario's count changed"

    # 5. What differs lists the edit, against no edits in Every building.
    compare = node_locator(page, COMPARE)
    frame_nodes(page, [COMPARE])
    _open_tab(page, COMPARE, "output")
    compare.get_by_role("tab", name="What differs", exact=True).click()
    lever = compare.locator(f'[data-compare-lever="{EDIT}"]')
    lever.wait_for(state="visible", timeout=15000)
    edits = lever.locator(f'[data-compare-edits="{LESS}"]').inner_text()
    assert "One removed:" in edits and f"Remove building_id {picked}" in edits, edits
    assert "no edits" in lever.locator(f'[data-compare-edits="{EVERY}"]').inner_text()
    assert lever.locator("[data-compare-code]").count() == 0, "What differs lists the code lines the edit list wrote"
    levers = compare.locator("[data-compare-lever]").evaluate_all("els => els.map((el) => el.getAttribute('data-compare-lever'))")
    assert levers == [EDIT], f"What differs lists {levers}, not only the Edit Features node"

    # 6. The edit list is saved with the dataflow.
    save_dataflow(page)
    saved = {node["id"]: node for node in _saved_spec(current_server, token, project_id)["dataflow"]["nodes"]}
    assert saved[EDIT_2]["metadata"]["editFeatures"] == {
        "key": "building_id",
        "edits": [{"op": "remove", "ids": [picked]}],
    }, json.dumps(saved[EDIT_2]["metadata"])
    assert saved[EDIT_2]["content"] == code
    assert saved[EDIT]["metadata"]["editFeatures"] == {"key": "building_id"}
