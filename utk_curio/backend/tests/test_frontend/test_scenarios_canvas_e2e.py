"""Playwright E2E: scenarios on the canvas (#662).

A loader feeds a branch: a Python node that scales a column, and an Autark map
of the result. This drives the whole path in a browser:

1. Select the branch (Shift and drag) and choose View, Duplicate as
   scenario. The copy reads the same loader, so the loader is the two
   scenarios' fixed context, and each copy names its original.
2. Collapse the copy: one box, its nodes hidden. Drag the box.
3. Run All with it collapsed: the shared loader runs once, and both branches
   run, the hidden one included.
4. Double-click the box: it expands in place and its map is drawn.
5. Collapse it again, save and reopen: the scenarios, the collapsed state, the
   box's place and the saved outputs are back. Expanded, the box's map draws
   from its restored input by itself, with nothing run.
6. Collapse it once more: Run scenario runs the copy's lever and reuses the
   restored loader, and the map, run inside the hidden box, is drawn once the
   box is expanded.

It runs the Autark node, which needs WebGPU: without an adapter it skips,
unless ``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job), where it fails.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scenarios_canvas_e2e.py -v
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from .utils import (
    SandboxRuns,
    api_json,
    assert_autark_map_drawn,
    frame_nodes,
    node_locator,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_dataflow,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
    wait_for_run_guard_released,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER = "scn-load"
SCALE = "scn-scale"
MAP = "scn-map"

# A 10 x 10 grid of cells over Chicago, each with its own value, so the map
# draws many colours (``assert_autark_map_drawn`` wants more than 8).
LOADER_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import box\n"
    "\n"
    "cells, pop = [], []\n"
    "for i in range(10):\n"
    "    for j in range(10):\n"
    "        x, y = -87.70 + 0.006 * i, 41.86 + 0.006 * j\n"
    "        cells.append(box(x, y, x + 0.005, y + 0.005))\n"
    "        pop.append(i * 10 + j)\n"
    'return gpd.GeoDataFrame({"pop": pop}, geometry=cells, crs="EPSG:4326")\n'
)
SCALE_CODE = 'gdf = input_0.copy()\ngdf["pop"] = gdf["pop"] * 2\nreturn gdf\n'
MAP_CONTENT = json.dumps({"map": {"layerRefs": [{
    "dataRef": "input_0",
    "getFnv": "pop",
    "getFnvType": "quantitative",
    "colorMapInterpolator": "interpolateViridis",
}]}}, indent=2)


def _spec() -> dict:
    node = lambda node_id, node_type, x, content: {  # noqa: E731
        "id": node_id, "type": node_type, "x": x, "y": 0, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }
    return {
        "dataflow": {
            "name": "Scenarios",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Scenarios",
            "nodes": [
                node(LOADER, "curio.builtin/data-loading", 0, LOADER_CODE),
                node(SCALE, "curio.builtin/computation-analysis", 645, SCALE_CODE),
                node(MAP, "curio.builtin/autk-grammar", 1290, MAP_CONTENT),
            ],
            "edges": [
                {"id": "e-load-scale", "source": LOADER, "target": SCALE,
                 "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-scale-map", "source": SCALE, "target": MAP,
                 "sourceHandle": "out", "targetHandle": "in"},
            ],
        }
    }


_STORE_NODES_JS = """() => window.__curio_reactFlow.getNodes().map((n) => ({
    id: n.id,
    selected: !!n.selected,
    nodeType: n.data && n.data.nodeType,
    copiedFrom: (n.data && n.data.copiedFrom) || null,
}))"""

_STORE_EDGES_JS = """() => window.__curio_reactFlow.getEdges().map((e) => ({
    source: e.source, target: e.target, targetHandle: e.targetHandle,
}))"""


def _require_webgpu(page) -> None:
    has_adapter = bool(page.evaluate(
        "async () => !!(navigator.gpu && await navigator.gpu.requestAdapter())"
    ))
    if not has_adapter:
        if os.environ.get("CURIO_REQUIRE_HARDWARE_WEBGPU") == "1":
            pytest.fail("CURIO_REQUIRE_HARDWARE_WEBGPU=1 but this browser has no WebGPU adapter")
        pytest.skip("running an Autark node needs a WebGPU adapter; this browser has none")


_ON_PANE_JS = """([x, y]) => {
    const hit = document.elementFromPoint(x, y);
    return !!hit && !!hit.closest('.react-flow__pane') && !hit.closest('.react-flow__node');
}"""


def _shift_drag_around(page, node_ids: list[str]) -> None:
    """Select *node_ids* the way a person does: Shift, and a box dragged
    around them on the empty canvas. From the bottom right, where nothing sits
    over the canvas; React Flow ends a selection whose pointer leaves it."""
    frame_nodes(page, node_ids)
    boxes = [node_locator(page, node_id).bounding_box() for node_id in node_ids]
    left = min(b["x"] for b in boxes) - 12
    top = min(b["y"] for b in boxes) - 12
    right = max(b["x"] + b["width"] for b in boxes) + 12
    bottom = max(b["y"] + b["height"] for b in boxes) + 12
    for point in ((right, bottom), (left, top)):
        assert page.evaluate(_ON_PANE_JS, list(point)), f"{point} is not on the empty canvas"
    page.mouse.move(right, bottom)
    page.keyboard.down("Shift")
    page.mouse.down()
    page.mouse.move(left, top, steps=20)
    page.mouse.up()
    page.keyboard.up("Shift")


def _scenario_menu(page, item: str) -> None:
    """The scenario commands sit in the View menu."""
    page.get_by_role("button", name="View menu").click()
    page.get_by_role("button", name=item, exact=True).click()


def _saved_spec(current_server: str, session: dict) -> dict:
    project_id = session["project"]["id"]
    return api_json(f"{current_server}/api/projects/{project_id}", session["token"])["spec"]


def _box(page, scenario_id: str):
    return page.get_by_test_id(f"scenario-box-{scenario_id}")


def _frame_box(page, scenario_id: str, members: list[str]):
    """Bring a collapsed scenario's box into view. It is not a React Flow node,
    so it cannot be scrolled to: frame its hidden members, which the fit places
    where they stand, at the box's corner."""
    frame_nodes(page, members)
    box = _box(page, scenario_id)
    box.wait_for(state="visible", timeout=10000)
    return box


def test_a_branch_duplicated_as_a_scenario_collapses_runs_and_expands(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = _spec()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scenarios Canvas",
        username="scenarios_canvas_e2e",
        project_name="Scenarios",
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    _require_webgpu(page)

    # 1. Select the branch and duplicate it as a scenario.
    _shift_drag_around(page, [SCALE, MAP])
    selected = sorted(n["id"] for n in page.evaluate(_STORE_NODES_JS) if n["selected"])
    assert selected == [MAP, SCALE], f"the Shift-drag selected {selected}, not the branch"
    _scenario_menu(page, "Duplicate as scenario")
    page.get_by_test_id("scenarios-panel").wait_for(state="visible", timeout=10000)

    copies = {n["copiedFrom"][-1]: n["id"] for n in page.evaluate(_STORE_NODES_JS) if n["copiedFrom"]}
    assert sorted(copies) == [MAP, SCALE], f"the copies name {sorted(copies)} as their originals"
    scale_copy, map_copy = copies[SCALE], copies[MAP]
    wiring = page.evaluate(_STORE_EDGES_JS)
    # The copy reads the same loader, and the copied edge between its nodes.
    assert {"source": LOADER, "target": scale_copy, "targetHandle": "in"} in wiring, wiring
    assert {"source": scale_copy, "target": map_copy, "targetHandle": "in"} in wiring, wiring

    save_dataflow(page)
    saved = _saved_spec(current_server, session)["dataflow"]
    scenarios = saved.get("scenarios") or []
    assert [sorted(s["nodes"]) for s in scenarios] == [sorted([SCALE, MAP]), sorted([scale_copy, map_copy])], scenarios
    original_id, copy_id = scenarios[0]["id"], scenarios[1]["id"]
    by_id = {n["id"]: n for n in saved["nodes"]}
    assert by_id[scale_copy]["metadata"].get("copiedFrom") == [SCALE], by_id[scale_copy]
    assert by_id[scale_copy]["content"] == SCALE_CODE

    # The panel lists the shared loader as each one's fixed context.
    for scenario_id in (original_id, copy_id):
        card = page.get_by_test_id(f"scenario-card-{scenario_id}")
        context = card.locator('[data-scenario-part="context"]').inner_text()
        assert "Data Loading" in context, f"scenario {scenario_id} lists {context!r} as its fixed context"

    # 2. Collapse the copy: one box, its nodes hidden but still there.
    page.get_by_test_id(f"scenario-card-{copy_id}").get_by_role("button", name="Collapse").click()
    box = _frame_box(page, copy_id, [scale_copy, map_copy])
    for node_id in (scale_copy, map_copy):
        member = node_locator(page, node_id)
        member.wait_for(state="attached", timeout=10000)
        assert not member.is_visible(), f"{node_id} still shows inside a collapsed scenario"
    assert node_locator(page, SCALE).is_visible()
    # Its fixed context and its outcome are listed on it.
    assert box.locator(f'[data-scenario-outcome="{map_copy}"]').count() == 1

    # Dragging the box moves it.
    before = box.bounding_box()
    page.mouse.move(before["x"] + 40, before["y"] + 15)
    page.mouse.down()
    page.mouse.move(before["x"] + 160, before["y"] + 15, steps=10)
    page.mouse.up()
    after = box.bounding_box()
    assert after["x"] - before["x"] > 100, f"the box did not follow the drag: {before} -> {after}"

    # 3. Run All with the copy collapsed: the shared loader runs once.
    sent = SandboxRuns(page, session["token"], session["project"]["id"])
    run_all_and_wait(page, timeout_ms=240000)
    executed = sent.stop()
    assert sorted(executed) == sorted([LOADER, SCALE, scale_copy]), (
        f"Run All sent {executed}: the shared loader must run once, and both branches once"
    )
    for node_id in (MAP, map_copy):
        status = wait_for_node_settled(page, node_id, node_type="autk-grammar", timeout_ms=120000)
        detail = read_node_error_text(node_locator(page, node_id)) if status == "error" else ""
        assert status == "done", f"{node_id} did not draw: {detail}"
    page.wait_for_function(
        """([box, node]) => {
            const row = document.querySelector(`[data-scenario-box="${box}"] [data-scenario-outcome="${node}"]`);
            return !!row && row.textContent.includes("Done");
        }""",
        arg=[copy_id, map_copy],
        timeout=15000,
    )

    # 4. Double-click the box: it expands in place, and the map is drawn.
    box = _frame_box(page, copy_id, [scale_copy, map_copy])
    box.dblclick()
    node_locator(page, map_copy).wait_for(state="visible", timeout=10000)
    assert _box(page, copy_id).count() == 0
    frame_nodes(page, [map_copy])
    assert_autark_map_drawn(page, map_copy, timeout=60000, attach_as="expanded after a collapsed run")

    # 5. Collapse it again, save, and reopen: everything is back.
    page.get_by_test_id(f"scenario-card-{copy_id}").get_by_role("button", name="Collapse").click()
    _box(page, copy_id).wait_for(state="visible", timeout=10000)
    save_dataflow(page)
    saved = _saved_spec(current_server, session)["dataflow"]
    copy = next(s for s in saved["scenarios"] if s["id"] == copy_id)
    assert copy.get("collapsed") is True, copy
    assert copy.get("box"), f"the moved box's place was not saved: {copy}"

    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{session['project']['id']}")
    node_locator(page, SCALE).wait_for(state="visible", timeout=45000)
    _box(page, copy_id).wait_for(state="visible", timeout=30000)
    for node_id in (scale_copy, map_copy):
        member = node_locator(page, node_id)
        member.wait_for(state="attached", timeout=30000)
        assert not member.is_visible(), f"{node_id} shows after a reopen, though its scenario was saved collapsed"
    _scenario_menu(page, "Show scenarios")
    for scenario_id in (original_id, copy_id):
        page.get_by_test_id(f"scenario-card-{scenario_id}").wait_for(state="visible", timeout=10000)
    # The outputs the scenario saved are back: its context and the node that
    # feeds its map read as having run.
    for node_id in (LOADER, scale_copy):
        status = node_locator(page, node_id).locator("[data-curio-node-status]").first.get_attribute(
            "data-curio-node-status", timeout=30000
        )
        assert status == "done", f"{node_id} reads {status!r} after a reopen: its saved output was not restored"

    # Expanded, the map draws from its restored input by itself: nobody runs
    # anything, and nothing reaches the sandbox.
    sent = SandboxRuns(page, session["token"], session["project"]["id"])
    box = _frame_box(page, copy_id, [scale_copy, map_copy])
    box.dblclick()
    node_locator(page, map_copy).wait_for(state="visible", timeout=10000)
    frame_nodes(page, [map_copy])
    assert_autark_map_drawn(page, map_copy, timeout=90000, attach_as="reopened and expanded, nothing run")
    status = wait_for_node_settled(page, map_copy, node_type="autk-grammar", timeout_ms=60000)
    detail = read_node_error_text(node_locator(page, map_copy)) if status == "error" else ""
    assert status == "done", f"{map_copy} ended {status} after the reopen: {detail}"
    executed = sent.stop()
    assert executed == [], f"the reopened map was drawn after {executed} ran, not from its restored input"

    # 6. Collapsed once more, Run scenario runs its levers, the restored loader
    # is reused, and the map runs inside the hidden box, its canvas made there.
    page.get_by_test_id(f"scenario-card-{copy_id}").get_by_role("button", name="Collapse").click()
    _box(page, copy_id).wait_for(state="visible", timeout=10000)
    sent = SandboxRuns(page, session["token"], session["project"]["id"])
    page.get_by_test_id(f"scenario-card-{copy_id}").get_by_role("button", name="Run scenario").click()
    status = wait_for_node_settled(page, map_copy, node_type="autk-grammar", timeout_ms=180000)
    wait_for_run_guard_released(page, timeout_ms=60000)
    executed = sent.stop()
    detail = read_node_error_text(node_locator(page, map_copy)) if status == "error" else ""
    assert status == "done", f"{map_copy} did not draw inside the collapsed scenario: {detail}"
    assert executed == [scale_copy], (
        f"Run scenario sent {executed}: only its lever should run, and its restored context be reused"
    )

    # Expanded, the map made inside the hidden box is drawn.
    box = _frame_box(page, copy_id, [scale_copy, map_copy])
    box.dblclick()
    node_locator(page, map_copy).wait_for(state="visible", timeout=10000)
    frame_nodes(page, [map_copy])
    assert_autark_map_drawn(page, map_copy, timeout=60000, attach_as="mounted hidden, then expanded")
