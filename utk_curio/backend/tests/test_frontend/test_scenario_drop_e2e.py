"""Playwright E2E: dragging a scenario into another project (#662).

A source project holds a loader feeding a branch: a Python node that scales a
column, and an Autark map of the result. The branch is the scenario "Twice as
tall", so the loader is its fixed context. Then, in a second project:

1. Drag the scenario from the Scenario Catalog drawer onto the canvas. It
   arrives collapsed, where it was dropped; its context arrives as a Data
   Loading node reading a copy of the loader's saved output; its lever and
   that loader show the source's results, with nothing run.
2. Run scenario runs the lever and reuses the copied context. Expanded, the
   map is drawn.
3. The source runs again with other data: its own saved output changes, the
   copy in the second project does not.
4. The copied loader is replaced by a node of the second project, wired to the
   lever. Run scenario runs that node, and the lever reads its output.

A second test drops a scenario whose lever needs ``curio.weather`` into a
project without it: the package is added. One whose package is in no catalog
is refused, naming it, and adds nothing.

The first runs an Autark node, which needs WebGPU: without an adapter it
skips, unless ``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job), where it
fails.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scenario_drop_e2e.py -v
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

from .utils import (
    api_json,
    assert_autark_map_drawn,
    frame_nodes,
    node_locator,
    play_node,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_dataflow,
    set_node_code,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
    wait_for_run_guard_released,
)
from .utils.canvas_authoring import CANVAS_DROP_TARGET, _DRAG_TO_CANVAS_JS, connect_nodes

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER = "src-load"
SCALE = "src-scale"
MAP = "src-map"
OWN = "own-grid"
SCENARIO = "tall"


def _grid_code(scale: int) -> str:
    """A 10 x 10 grid of cells over Chicago, each with its own value, so the
    map draws many colours (``assert_autark_map_drawn`` wants more than 8)."""
    return (
        "import geopandas as gpd\n"
        "from shapely.geometry import box\n"
        "\n"
        "cells, pop = [], []\n"
        "for i in range(10):\n"
        "    for j in range(10):\n"
        "        x, y = -87.70 + 0.006 * i, 41.86 + 0.006 * j\n"
        "        cells.append(box(x, y, x + 0.005, y + 0.005))\n"
        f"        pop.append((i * 10 + j) * {scale})\n"
        'return gpd.GeoDataFrame({"pop": pop}, geometry=cells, crs="EPSG:4326")\n'
    )


SCALE_CODE = 'gdf = arg.copy()\ngdf["pop"] = gdf["pop"] * 2\nreturn gdf\n'
MAP_CONTENT = json.dumps({"map": {"layerRefs": [{
    "dataRef": "input_0",
    "getFnv": "pop",
    "getFnvType": "quantitative",
    "colorMapInterpolator": "interpolateViridis",
}]}}, indent=2)


def _node(node_id, node_type, x, content, y=0):
    return {
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _dataflow(name, nodes, edges=(), scenarios=(), packages=None) -> dict:
    dataflow = {
        "name": name, "task": "", "timestamp": 1789193389280, "provenance_id": name,
        "nodes": list(nodes), "edges": list(edges),
    }
    if scenarios:
        dataflow["scenarios"] = list(scenarios)
    if packages is not None:
        dataflow["packages"] = packages
    return {"dataflow": dataflow}


def _source_spec() -> dict:
    return _dataflow(
        "Shadows",
        [
            _node(LOADER, "curio.builtin/data-loading", 0, _grid_code(1)),
            _node(SCALE, "curio.builtin/computation-analysis", 645, SCALE_CODE),
            _node(MAP, "curio.builtin/autk-grammar", 1290, MAP_CONTENT),
        ],
        [
            {"id": "e-load-scale", "source": LOADER, "target": SCALE, "sourceHandle": "out", "targetHandle": "in"},
            {"id": "e-scale-map", "source": SCALE, "target": MAP, "sourceHandle": "out", "targetHandle": "in"},
        ],
        [{"id": SCENARIO, "name": "Twice as tall", "color": "#e86a3c", "nodes": [SCALE, MAP]}],
    )


def _create_project(server: str, token: str, name: str, spec: dict) -> str:
    created = api_json(f"{server}/api/projects", token, method="POST",
                       payload={"name": name, "spec": spec, "outputs": []})
    return created["id"]


def _require_webgpu(page) -> None:
    has_adapter = bool(page.evaluate(
        "async () => !!(navigator.gpu && await navigator.gpu.requestAdapter())"
    ))
    if not has_adapter:
        if os.environ.get("CURIO_REQUIRE_HARDWARE_WEBGPU") == "1":
            pytest.fail("CURIO_REQUIRE_HARDWARE_WEBGPU=1 but this browser has no WebGPU adapter")
        pytest.skip("running an Autark node needs a WebGPU adapter; this browser has none")


_STORE_NODES_JS = """() => window.__curio_reactFlow.getNodes().map((n) => ({
    id: n.id,
    copiedFrom: (n.data && n.data.copiedFrom) || [],
}))"""


def _copies(page) -> dict[str, str]:
    """``{original id: its copy's id}`` on this canvas."""
    return {n["copiedFrom"][-1]: n["id"] for n in page.evaluate(_STORE_NODES_JS) if n["copiedFrom"]}


def _status(page, node_id: str) -> str | None:
    return node_locator(page, node_id).locator("[data-curio-node-status]").first.get_attribute(
        "data-curio-node-status", timeout=30000,
    )


def _record_python_runs(page):
    """The Python runs that leave the page from now on, as ``(nodeId, input
    path)``, and each run's output path by node. Returns both and a stop."""
    sent: list[tuple[str, str | None]] = []
    outputs: dict[str, str] = {}

    def _request(request) -> None:
        if request.method != "POST" or not request.url.endswith("/processPythonCode"):
            return
        try:
            body = json.loads(request.post_data or "{}")
        except ValueError:
            body = {}
        given = body.get("input") if isinstance(body.get("input"), dict) else {}
        sent.append((str(body.get("nodeId")), given.get("path")))

    def _response(response) -> None:
        if response.request.method != "POST" or not response.url.endswith("/processPythonCode"):
            return
        try:
            body = json.loads(response.request.post_data or "{}")
            output = (response.json() or {}).get("output") or {}
        except Exception:  # noqa: BLE001 - a failed run is reported by its node
            return
        if isinstance(output, dict) and output.get("path"):
            outputs[str(body.get("nodeId"))] = output["path"]

    page.on("request", _request)
    page.on("response", _response)

    def stop() -> None:
        page.remove_listener("request", _request)
        page.remove_listener("response", _response)

    return sent, outputs, stop


def _open_scenario_catalog(page):
    page.get_by_role("button", name="Scenario Catalog").click()
    drawer = page.locator('[data-curio-scenario-catalog-drawer="true"]')
    drawer.wait_for(state="visible", timeout=15000)
    return drawer


def _drag_scenario_onto_canvas(page, project_id: str, scenario_id: str, at=(700.0, 120.0)) -> None:
    """Drag the scenario's card from the open drawer onto the canvas, as
    ``drag_to_canvas`` drags a dataset: dragstart on the card, then dragover
    and drop on the canvas, then dragend."""
    card = page.locator(f'[data-curio-scenario-catalog-drawer="true"] [data-scenario-key="{project_id}/{scenario_id}"]')
    card.wait_for(state="visible", timeout=20000)
    pane = page.locator(CANVAS_DROP_TARGET)
    box = pane.bounding_box()
    assert box, f"{CANVAS_DROP_TARGET} has no layout box"
    result = page.evaluate(_DRAG_TO_CANVAS_JS, {
        "source": card.element_handle(),
        "targetSelector": CANVAS_DROP_TARGET,
        "clientX": box["x"] + at[0],
        "clientY": box["y"] + at[1],
    })
    assert result == "ok", f"drag to canvas failed: {result}"


_UNDER_THE_DRAWER_JS = """([x, y]) => {
    const hit = document.elementFromPoint(x, y);
    return !!hit && !!hit.closest('[data-curio-scenario-catalog-drawer="true"]');
}"""


def _drag_card_with_the_mouse(page, project_id: str, scenario_id: str, at=(300.0, 200.0)) -> None:
    """Drag the scenario's card with the mouse, as a person does. The open
    drawer's scrim lies over the canvas, so the drop lands on the canvas only
    if the drawer lets the drag through while it lasts."""
    drawer = page.locator('[data-curio-scenario-catalog-drawer="true"]')
    card = drawer.locator(f'[data-scenario-key="{project_id}/{scenario_id}"]')
    card.wait_for(state="visible", timeout=20000)
    card_box = card.bounding_box()
    pane_box = page.locator(CANVAS_DROP_TARGET).bounding_box()
    assert card_box and pane_box, "the card or the canvas has no layout box"
    target = (pane_box["x"] + at[0], pane_box["y"] + at[1])
    assert page.evaluate(_UNDER_THE_DRAWER_JS, list(target)), f"{target} is not under the drawer's scrim"

    start = (card_box["x"] + 40, card_box["y"] + 20)
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(start[0] - 40, start[1] + 10, steps=6)
    page.locator('[data-curio-scenario-catalog-drawer="true"][data-dragging="true"]').wait_for(
        state="attached", timeout=5000,
    )
    page.mouse.move(*target, steps=12)
    page.mouse.up()


def _toast(page, text: str, timeout: float = 30000):
    toast = page.locator('[aria-label="Notifications"]').get_by_text(text, exact=False)
    toast.first.wait_for(state="visible", timeout=timeout)
    return toast.first.inner_text()


def _scenario_menu(page, item: str) -> None:
    """The scenario commands sit in the View menu."""
    page.get_by_role("button", name="View menu").click()
    page.get_by_role("button", name=item, exact=True).click()


def _box(page, scenario_id: str):
    return page.get_by_test_id(f"scenario-box-{scenario_id}")


def _saved_spec(server: str, token: str, project_id: str) -> dict:
    return api_json(f"{server}/api/projects/{project_id}", token)["spec"]


def _preview(server: str, token: str, dataset_id: str) -> dict:
    return api_json(f"{server}/api/datasets/{dataset_id}/preview?rowLimit=100", token)


def _rows(preview: dict):
    """What a preview says the dataset holds, without when it was made."""
    return {key: value for key, value in preview.items() if key not in ("updatedAt", "createdAt")}


def _expand(page, scenario_id: str, members: list[str]) -> None:
    frame_nodes(page, members)
    box = _box(page, scenario_id)
    box.wait_for(state="visible", timeout=10000)
    box.dblclick()
    node_locator(page, members[-1]).wait_for(state="visible", timeout=10000)


def test_a_scenario_dragged_into_another_project_brings_its_results_and_its_own_context(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scenario Drop",
        username="scenario_drop_e2e",
        project_name="Shadows",
        project_spec=_source_spec(),
    )
    require_owner_view(page)
    token = session["token"]
    source = session["project"]["id"]
    for node_id in (LOADER, SCALE, MAP):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    _require_webgpu(page)

    # The source runs and saves: its context and what its outcome shows are saved.
    run_all_and_wait(page, timeout_ms=240000)
    status = wait_for_node_settled(page, MAP, node_type="autk-grammar", timeout_ms=120000)
    assert status == "done", read_node_error_text(node_locator(page, MAP))
    save_dataflow(page)
    details = api_json(f"{current_server}/api/scenarios/{source}/{SCENARIO}", token)
    assert [r["nodeId"] for r in details["context"][0]["results"]] == [LOADER], details["context"]
    assert [r["nodeId"] for r in details["outcomes"][0]["results"]] == [SCALE], details["outcomes"]

    # Another project, with a grid of its own.
    target = _create_project(current_server, token, "Elsewhere", _dataflow(
        "Elsewhere", [_node(OWN, "curio.builtin/data-loading", 0, _grid_code(7), y=600)],
    ))
    page.goto(f"{app_frontend.base_url}/dataflow/{target}")
    node_locator(page, OWN).wait_for(state="visible", timeout=45000)

    # 1. Drag the scenario in: nothing runs, and its results are there.
    sent, _outputs, stop = _record_python_runs(page)
    _open_scenario_catalog(page)
    _drag_scenario_onto_canvas(page, source, SCENARIO)
    _toast(page, 'Added "Twice as tall" from Shadows.')
    page.keyboard.press("Escape")
    copies = _copies(page)
    assert sorted(copies) == sorted([LOADER, SCALE, MAP]), copies
    loader, scale, map_copy = copies[LOADER], copies[SCALE], copies[MAP]
    assert len({loader, scale, map_copy, LOADER, SCALE, MAP}) == 6, "a copy kept its original's id"
    for node_id in (loader, scale):
        assert _status(page, node_id) == "done", f"{node_id} does not show the result its source saved"
    stop()
    assert sent == [], f"the drop ran {sent}: a dropped scenario shows its saved results without a run"

    save_dataflow(page)
    saved = _saved_spec(current_server, token, target)["dataflow"]
    [dropped] = saved["scenarios"]
    assert dropped["source"] == {"project": source, "scenario": SCENARIO}, dropped
    assert dropped["collapsed"] is True and dropped.get("box"), dropped
    assert sorted(dropped["nodes"]) == sorted([scale, map_copy]), dropped
    by_id = {n["id"]: n for n in saved["nodes"]}
    assert by_id[loader]["type"].startswith("curio.builtin/data-loading"), by_id[loader]
    copy_id = computed_dataset_id(loader, target)
    assert copy_id in by_id[loader]["content"], by_id[loader]["content"]
    assert by_id[scale]["metadata"]["copiedFrom"] == [SCALE]
    assert {(e["source"], e["target"]) for e in saved["edges"]} == {(loader, scale), (scale, map_copy)}
    for node_id in (scale, map_copy):
        member = node_locator(page, node_id)
        member.wait_for(state="attached", timeout=10000)
        assert not member.is_visible(), f"{node_id} shows, though the scenario arrived collapsed"

    # 2. Run scenario: the lever runs, the copied context is reused.
    sent, _outputs, stop = _record_python_runs(page)
    _scenario_menu(page, "Show scenarios")
    page.get_by_test_id(f"scenario-card-{dropped['id']}").get_by_role("button", name="Run scenario").click()
    status = wait_for_node_settled(page, map_copy, node_type="autk-grammar", timeout_ms=180000)
    wait_for_run_guard_released(page, timeout_ms=60000)
    stop()
    assert status == "done", read_node_error_text(node_locator(page, map_copy))
    assert [node for node, _ in sent] == [scale], f"Run scenario sent {sent}: only its lever should run"
    _expand(page, dropped["id"], [scale, map_copy])
    frame_nodes(page, [map_copy])
    assert_autark_map_drawn(page, map_copy, timeout=60000, attach_as="dropped, run and expanded")
    save_dataflow(page)

    # 3. The source runs again with other data; the copy stays as it was.
    copy_before = _rows(_preview(current_server, token, copy_id))
    source_before = _rows(_preview(current_server, token, computed_dataset_id(LOADER, source)))
    page.goto(f"{app_frontend.base_url}/dataflow/{source}")
    node_locator(page, LOADER).wait_for(state="visible", timeout=45000)
    set_node_code(page, LOADER, _grid_code(100))
    play_node(page, LOADER)
    assert wait_for_node_settled(page, LOADER, timeout_ms=120000) == "done"
    save_dataflow(page)
    assert _rows(_preview(current_server, token, computed_dataset_id(LOADER, source))) != source_before, (
        "the source's saved output did not change, so this proves nothing"
    )
    assert _rows(_preview(current_server, token, copy_id)) == copy_before, (
        "a run of the source changed the copy the other project reads"
    )

    # 4. The other project's own grid replaces the copied context. The
    #    scenario was saved expanded, so its lever is there to wire.
    page.goto(f"{app_frontend.base_url}/dataflow/{target}")
    node_locator(page, OWN).wait_for(state="visible", timeout=45000)
    node_locator(page, scale).wait_for(state="visible", timeout=30000)
    frame_nodes(page, [loader])
    node_locator(page, loader).click(position={"x": 300, "y": 8})
    page.keyboard.press("Delete")
    node_locator(page, loader).wait_for(state="detached", timeout=10000)
    frame_nodes(page, [OWN, scale])
    connect_nodes(page, OWN, scale)
    sent, outputs, stop = _record_python_runs(page)
    _scenario_menu(page, "Show scenarios")
    page.get_by_test_id(f"scenario-card-{dropped['id']}").get_by_role("button", name="Run scenario").click()
    status = wait_for_node_settled(page, map_copy, node_type="autk-grammar", timeout_ms=180000)
    wait_for_run_guard_released(page, timeout_ms=60000)
    stop()
    assert status == "done", read_node_error_text(node_locator(page, map_copy))
    assert [node for node, _ in sent] == [OWN, scale], f"Run scenario sent {sent}"
    assert OWN in outputs, f"no output recorded for {OWN}: {outputs}"
    assert dict(sent)[scale] == outputs[OWN], (
        f"the lever read {dict(sent)[scale]!r}, not the re-wired node's output {outputs[OWN]!r}"
    )


def test_a_dropped_scenario_brings_the_packages_its_levers_need(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scenario Packages",
        username="scenario_packages_e2e",
        project_name="Plain",
        project_spec=_dataflow(
            "Plain", [_node("plain", "curio.builtin/computation-analysis", 0, "return 1")],
            packages=["curio.builtin@1"],
        ),
    )
    require_owner_view(page)
    token = session["token"]
    target = session["project"]["id"]
    node_locator(page, "plain").wait_for(state="visible", timeout=45000)
    # Adding a package the account does not hold would run pip for minutes;
    # the stack is started --with-examples, which seeds curio.weather (example 09).
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", token)["packages"]]
    assert "curio.weather@1" in store, f"curio.weather@1 is not in the account's store {store}: start the stack --with-examples"
    # The source projects are never opened here, so nothing installs for them.
    source = _create_project(current_server, token, "Weather study", _dataflow(
        "Weather study",
        [_node("weather", "curio.weather/weather-load@1", 0, "return 1")],
        scenarios=[{"id": "era5", "name": "ERA5", "color": "#2f8f4a", "nodes": ["weather"]}],
    ))
    ghost = _create_project(current_server, token, "Ghosts", _dataflow(
        "Ghosts",
        [_node("ghost", "acme.missing/thing@1", 0, "return 1")],
        scenarios=[{"id": "boo", "name": "Haunted", "color": "#7a4bd1", "nodes": ["ghost"]}],
    ))
    lockfile = lambda: api_json(f"{current_server}/api/packages/projects/{target}", token)["packages"]  # noqa: E731
    assert "curio.weather@1" not in lockfile()
    before = {n["id"] for n in page.evaluate(_STORE_NODES_JS)}

    # A package in no catalog: refused, naming it, and nothing is added.
    _open_scenario_catalog(page)
    _drag_scenario_onto_canvas(page, ghost, "boo")
    assert "acme.missing@1" in _toast(page, "acme.missing@1")
    assert {n["id"] for n in page.evaluate(_STORE_NODES_JS)} == before

    # A package the account holds: added to the project, and its node is
    # known. Dragged with the mouse, across the drawer's scrim.
    _drag_card_with_the_mouse(page, source, "era5")
    _toast(page, "Added curio.weather@1 to this project.")
    copy = _copies(page)["weather"]
    node_locator(page, copy).wait_for(state="attached", timeout=15000)
    assert node_locator(page, copy).get_by_test_id("unresolved-node").count() == 0, (
        "the dropped weather node came up as an unknown kind: its package did not arrive first"
    )
    assert "curio.weather@1" in lockfile()

    # The dataflow saves on top of the package the drop added. The drawer
    # closes first: its scrim lies over the File menu.
    page.keyboard.press("Escape")
    page.locator('[data-curio-scenario-catalog-drawer="true"][aria-hidden="true"]').wait_for(
        state="attached", timeout=10000,
    )
    save_dataflow(page)
    saved = _saved_spec(current_server, token, target)["dataflow"]
    [dropped] = saved["scenarios"]
    assert dropped["source"] == {"project": source, "scenario": "era5"}, dropped
    assert dropped["nodes"] == [copy], dropped
    assert "curio.weather@1" in lockfile()
