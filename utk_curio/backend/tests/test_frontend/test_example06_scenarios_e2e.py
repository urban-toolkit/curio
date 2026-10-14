"""Playwright E2E: example 06 as a scenario study (#662).

Example 06 runs example 07's per-road sunlight shader in three scenarios over
one fixed context, the Back Bay loader and its data pool: "Baseline", every
building at its own height, "Twice as tall", a copy of it with every building
doubled, and "Two towers removed", where an Edit Features node removes two
towers, 200 Clarendon and Raffles, by their ``building_id`` before copies of
Baseline's nodes. The
factor is a ``height_factor`` widget on each shadow step, read as an Autark
uniform. In each scenario a Python node takes the roads out of the layers its
map hands on. A Vega-Lite node comparing the scenarios charts their mean road
sunlight, and a Python node takes each road's sunlight change in Twice as tall,
the roads matched by their shapes, which an Autark map draws.

The first test drives the example as it ships:

1. Its three scenarios are listed over the shared pool. Each shadow step's
   ``height_factor`` tag sits in its Widgets tab, with its value, and as a chip
   in its spec.
2. All collapsed, Run All: the loader loads once for all, the scenarios run
   hidden, and each box shows its outcome done. The Edit Features node reads the
   loader's layers through the pool and hands them on without every part of
   both towers. Each shadow step's batched shader reads every building part it
   is handed: autk-grammar says it left none out (#757). A double-click expands
   one scenario in place, and its map is drawn.
3. The chart: Twice as tall has the lowest mean sunlight and Two towers removed
   the highest, and it draws every scenario's colour.
4. The difference: each road's sunlight change, below zero where the taller
   shadows reach it and zero elsewhere, mapped.
5. A save and a reopen: the scenarios, their colours, the collapsed ones, the
   widgets and their values, the edit list, and the saved outputs come back.

The second test drags both scenarios from the Scenario Catalog into an empty
project, once the seeded example has run, and compares them there: they arrive
with their results and read one context, and a Vega-Lite node with its Compare
scenarios switch on labels its two inputs by them.

They run Autark nodes, which need WebGPU: without an adapter they skip, unless
``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job), where they fail.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_example06_scenarios_e2e.py -v --with-examples
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .test_multi_input_e2e import _wait_for_circles
from .test_scenario_drop_e2e import (
    _copies,
    _drag_scenario_onto_canvas,
    _open_scenario_catalog,
    _saved_spec,
    _status,
    _toast,
)
from .test_scenarios_canvas_e2e import _box, _frame_box, _require_webgpu, _scenario_menu
from .test_widget_tags_e2e import _open_tab, _panel
from .utils import (
    OUTPUT_ARTIFACT_JS,
    REPO_ROOT,
    api_json,
    assert_autark_map_drawn,
    assert_scenario_colors_drawn,
    assert_vega_canvas_rendered,
    connect_nodes,
    dismiss_toasts,
    drag_to_canvas,
    frame_nodes,
    load_artifact_as_dict,
    node_locator,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_dataflow,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = Path(REPO_ROOT) / "docs" / "examples" / "06-autark-what-if-shadow-study.json"
EXAMPLE_NAME = "Autark what-if shadow study"
AUTARK = "curio.builtin/autk-grammar"
PYTHON = "curio.builtin/computation-analysis"
VEGA = "curio.builtin/vis-vega"

DATA = "whatif-data"
B_COMPUTE, B_MAP, B_ROADS = "whatif-baseline-compute", "whatif-baseline-map", "whatif-baseline-roads"
T_COMPUTE, T_MAP, T_ROADS = "whatif-modified-compute", "whatif-modified-map", "whatif-modified-roads"
E_EDIT, E_COMPUTE, E_MAP, E_ROADS = "whatif-towers-edit", "whatif-towers-compute", "whatif-towers-map", "whatif-towers-roads"
CHART, DIFFERENCE, CHANGE_MAP = "whatif-sunlight-chart", "whatif-sunlight-change", "whatif-sunlight-change-map"
BASELINE, TWICE, TOWERS = "s-baseline", "s-twice", "s-towers"
NAMES = {BASELINE: "Baseline", TWICE: "Twice as tall", TOWERS: "Two towers removed"}
COLORS = {BASELINE: "#3567c7", TWICE: "#e86a3c", TOWERS: "#2f8f4a"}
MEMBERS = {
    BASELINE: [B_COMPUTE, B_MAP, B_ROADS],
    TWICE: [T_COMPUTE, T_MAP, T_ROADS],
    TOWERS: [E_EDIT, E_COMPUTE, E_MAP, E_ROADS],
}
ROADS_OF = {BASELINE: B_ROADS, TWICE: T_ROADS, TOWERS: E_ROADS}
ROADS = "table_osm_roads"
BUILDINGS = "table_osm_buildings"
EDIT_TYPE = "curio.builtin/edit-features"
#: The two towers Two towers removed takes out, by building_id, and how many
#: parts each has in Back Bay's PBF: 200 Clarendon and Raffles. autk-db names a
#: building by the smallest OpenStreetMap id among its parts.
TOWER_PARTS = {29623484: 4, 29628154: 3}

RUN_MS = 420000
SETTLE_MS = 180000


def _example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _rgb(hex_color: str) -> str:
    return "rgb({}, {}, {})".format(*(int(hex_color[i:i + 2], 16) for i in (1, 3, 5)))


def _record_runs(page, data_node: str):
    """What the page sends to run from now on: each Python node's run, by node
    id, and each data load *data_node* sends, as whether it came back with an
    output. A run on the server sends its browser part from the page too."""
    python: list[str] = []
    loads: list[bool] = []

    def _request(request) -> None:
        if request.method != "POST" or not request.url.endswith("/processPythonCode"):
            return
        try:
            python.append(str(json.loads(request.post_data or "{}").get("nodeId")))
        except ValueError:
            python.append("?")

    def _response(response) -> None:
        if response.request.method != "POST" or not response.url.endswith("/processJavaScriptCode"):
            return
        try:
            body = json.loads(response.request.post_data or "{}")
        except ValueError:
            return
        if body.get("nodeId") != data_node or "loadOsm" not in str(body.get("code") or ""):
            return
        try:
            output = (response.json() or {}).get("output") or {}
        except Exception:  # noqa: BLE001 - a load that failed has no output
            output = {}
        loads.append(bool(isinstance(output, dict) and output.get("path")))

    page.on("request", _request)
    page.on("response", _response)

    def stop() -> None:
        page.remove_listener("request", _request)
        page.remove_listener("response", _response)

    return python, loads, stop


#: How autk-grammar's console messages about a batched compute begin. It logs
#: one only when it leaves features out: those past its cap, or those missing a
#: ``required`` path.
_BATCHED_COMPUTE = "[autk-grammar] batched compute"


def _record_batched_left_out(page):
    """Every console message from now on in which autk-grammar says a batched
    compute left features out, and a function that stops the recording."""
    seen: list[str] = []

    def _console(message) -> None:
        if _BATCHED_COMPUTE in message.text:
            seen.append(message.text)

    page.on("console", _console)
    return seen, lambda: page.remove_listener("console", _console)


def _settled_done(page, node_id: str, node_type: str) -> None:
    status = wait_for_node_settled(page, node_id, node_type=node_type, timeout_ms=SETTLE_MS)
    assert status == "done", f"{node_id} ended {status!r}: {read_node_error_text(node_locator(page, node_id))}"


def _rows(page, node_id: str) -> list[dict]:
    """The rows of *node_id*'s saved output, a layer, as the sandbox stores them."""
    artifact = page.evaluate(OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, f"{node_id} shows no saved output"
    stored = load_artifact_as_dict(artifact)
    assert stored["dataType"] == "geodataframe", f"{node_id} gave {stored['dataType']}"
    return [feature["properties"] for feature in stored["data"]["features"]]


_REVEAL_REFERENCE_JS = """([nodeId, text]) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    const editorEl = nodeEl && nodeEl.querySelector(".monaco-editor");
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const editor = editors.find((e) => editorEl && editorEl.contains(e.getDomNode()));
    if (!editor) return null;
    const line = editor.getValue().split("\\n").findIndex((l) => l.includes(text));
    if (line < 0) return null;
    editor.revealLineInCenter(line + 1);
    return line + 1;
}"""

_CHIP_TEXT_JS = """(nodeId) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    const chips = nodeEl ? [...nodeEl.querySelectorAll(".monaco-editor .curio-widget-ref")] : [];
    return chips.map((chip) => chip.textContent).join("");
}"""


def _assert_tag_and_chip(page, node_id: str, value: str) -> None:
    """The node's ``height_factor`` tag is in its Widgets tab with *value*, and
    its spec draws the reference to it as a chip."""
    frame_nodes(page, [node_id])
    _open_tab(page, node_id, "widgets")
    row = _panel(page, node_id).locator('[data-widget-row="height_factor"]')
    row.wait_for(state="visible", timeout=15000)
    shown = row.locator("output").inner_text().strip()
    assert shown == value, f"{node_id}'s height_factor shows {shown!r}, not {value!r}"
    _open_tab(page, node_id, "grammar")
    deadline = time.time() + 20
    chips = ""
    while time.time() < deadline:
        line = page.evaluate(_REVEAL_REFERENCE_JS, [node_id, "[!! height_factor !!]"])
        chips = page.evaluate(_CHIP_TEXT_JS, node_id)
        if line and "height_factor" in chips:
            break
        page.wait_for_timeout(250)
    assert "height_factor" in chips, f"{node_id}'s spec draws no height_factor chip (chips: {chips!r})"


def _assert_chart_drew(page, node_id: str) -> None:
    """The chart drew, every scenario in its colour."""
    assert_vega_canvas_rendered(page, node_id, timeout=30000)
    assert_scenario_colors_drawn(page, node_id, [COLORS[BASELINE], COLORS[TWICE], COLORS[TOWERS]])


_INPUT_ARTIFACT_JS = """(id) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    const input = node && node.data && node.data.input;
    return input && typeof input.filename === "string" ? input.filename : null;
}"""


def _ids_of(fc: dict) -> list:
    return [feature["properties"].get("building_id") for feature in fc["features"]]


def _loaded_buildings(read: dict) -> dict:
    """The building parts an Autark data node loaded: its ``[{name, type,
    geojson}]`` records, as ``/get`` sends a list."""
    for item in read["data"]:
        if item["data"].get("name") == BUILDINGS:
            return item["data"]["geojson"]
    raise AssertionError(f"the loaded layers hold no {BUILDINGS}: {[i['data'].get('name') for i in read['data']]}")


def _assert_parts_pack_a_box(fc: dict) -> None:
    """Every building part the data node hands on is a Polygon, and its outer
    ring spans a box: the shadow step packs each part's
    ``geometry.coordinates.0`` (``iterate: "batched"``), and a part handed on
    as autk-db keeps a building, one GeometryCollection, would pack a box of
    zero area."""
    flat = []
    for feature in fc["features"]:
        geometry = feature.get("geometry") or {}
        ring = (geometry.get("coordinates") or [None])[0] if geometry.get("type") == "Polygon" else None
        xs = [point[0] for point in ring or []]
        ys = [point[1] for point in ring or []]
        if len(xs) < 4 or max(xs) <= min(xs) or max(ys) <= min(ys):
            flat.append((feature["properties"].get("building_id"), geometry.get("type")))
    assert not flat, f"{len(flat)} of {len(fc['features'])} building parts pack no box, e.g. {flat[:5]}"


def _handed_building_ids(wrapper: dict) -> list:
    """The same, in the layers Edit Features hands on, as an Autark node does."""
    for item in wrapper["data"]:
        if item.get("layerName") == BUILDINGS:
            return _ids_of(item["data"])
    raise AssertionError(f"the handed-on layers hold no {BUILDINGS}: {[i.get('layerName') for i in wrapper['data']]}")


def _assert_towers_removed(page) -> None:
    """The Edit Features node read the loader's layers, through the pool, and
    handed them on without every part of both towers: every id it names is a
    building of the input, so none is unknown."""
    source = page.evaluate(_INPUT_ARTIFACT_JS, E_EDIT)
    assert source, "the pool did not name the artifact it read, for the Edit Features node to read"
    loaded = _loaded_buildings(load_artifact_as_dict(source))
    _assert_parts_pack_a_box(loaded)
    before = _ids_of(loaded)
    for tower, parts in TOWER_PARTS.items():
        assert before.count(tower) == parts, f"the loaded buildings hold {before.count(tower)} parts of {tower}, not {parts}"
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, E_EDIT)
    assert artifact, f"{E_EDIT} shows no saved output"
    stored = load_artifact_as_dict(artifact)
    handed = stored["data"]
    assert handed["dataType"] == "outputs", handed.get("dataType")
    names = [item["layerName"] for item in handed["data"]]
    assert sorted(names) == sorted(["table_osm_surface", "table_osm_parks", "table_osm_water", ROADS, BUILDINGS]), names
    after = _handed_building_ids(handed)
    assert not set(TOWER_PARTS) & set(after), f"a tower is still in the buildings: {sorted(set(TOWER_PARTS) & set(after))}"
    assert len(after) == len(before) - sum(TOWER_PARTS.values()), (len(before), len(after))


def _zoom_out(page, zoom: float = 0.2) -> None:
    """Zoom the canvas out and keep it there. A load fits the view once its
    nodes are measured (up to 4 s after the registry is ready), which can land
    after a first set, so the zoom is set until it holds for 4 s."""
    read = "() => window.__curio_reactFlow.getViewport().zoom"
    now = None
    deadline = time.time() + 30
    while time.time() < deadline:
        page.evaluate(f"() => window.__curio_reactFlow.setViewport({{ x: 0, y: 0, zoom: {zoom} }})")
        page.wait_for_timeout(1500)
        now = page.evaluate(read)
        if abs(now - zoom) < 1e-6:
            page.wait_for_timeout(2500)
            now = page.evaluate(read)
            if abs(now - zoom) < 1e-6:
                return
    raise AssertionError(f"the canvas would not stay at zoom {zoom}: it is at {now}")


def _box_color(page, scenario_id: str) -> str:
    return page.evaluate(
        "(id) => { const el = document.querySelector(`[data-scenario-box=\"${id}\"]`);"
        " return el ? getComputedStyle(el).borderTopColor : null; }",
        scenario_id,
    )


def _frame_color(page, scenario_id: str) -> str:
    return page.evaluate(
        "(id) => { const el = document.querySelector(`[data-scenario-frame=\"${id}\"]`);"
        " return el ? getComputedStyle(el).borderTopColor : null; }",
        scenario_id,
    )


def _assert_cards(page) -> None:
    """The Scenarios panel lists the three scenarios, by name and colour, each
    with the data pool as the fixed context it reads."""
    for scenario_id, name in NAMES.items():
        card = page.get_by_test_id(f"scenario-card-{scenario_id}")
        card.wait_for(state="visible", timeout=15000)
        assert card.get_by_label("Scenario name").input_value() == name
        assert card.get_by_label(f"Color of {name}").input_value().lower() == COLORS[scenario_id]
        context = card.locator('[data-scenario-part="context"]').inner_text()
        assert "Data Pool" in context, f"{name} lists {context!r} as its fixed context"


def test_example_06_compares_its_three_scenarios_in_the_canvas(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = _example()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Example 06 Scenarios",
        username="example06_scenarios_e2e",
        project_name=EXAMPLE_NAME,
        project_spec=spec,
    )
    require_owner_view(page)
    token, project_id = session["token"], session["project"]["id"]
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    _require_webgpu(page)

    # 1. Three scenarios over the shared pool, and each shadow step's tag.
    _scenario_menu(page, "Show scenarios")
    _assert_cards(page)
    for scenario_id in NAMES:
        assert _frame_color(page, scenario_id) == _rgb(COLORS[scenario_id])
    _assert_tag_and_chip(page, B_COMPUTE, "1")
    _assert_tag_and_chip(page, T_COMPUTE, "2")
    _assert_tag_and_chip(page, E_COMPUTE, "1")

    # 2. All collapsed, Run All: the loader loads once, and every scenario runs.
    for scenario_id in NAMES:
        page.get_by_test_id(f"scenario-card-{scenario_id}").get_by_role("button", name="Collapse").click()
        _box(page, scenario_id).wait_for(state="attached", timeout=10000)
        for node_id in MEMBERS[scenario_id]:
            assert not node_locator(page, node_id).is_visible(), f"{node_id} shows inside a collapsed scenario"
    python, loads, stop = _record_runs(page, DATA)
    left_out, stop_left_out = _record_batched_left_out(page)
    run_all_and_wait(page, timeout_ms=RUN_MS)
    for node_id, node_type in (
        (B_MAP, AUTARK), (T_MAP, AUTARK), (E_EDIT, EDIT_TYPE), (E_MAP, AUTARK),
        (B_ROADS, PYTHON), (T_ROADS, PYTHON), (E_ROADS, PYTHON),
        (CHART, VEGA), (DIFFERENCE, PYTHON), (CHANGE_MAP, AUTARK),
    ):
        _settled_done(page, node_id, node_type)
    stop()
    stop_left_out()
    assert loads.count(True) == 1, f"the loader the three scenarios share loaded {loads}, not once"
    assert sorted(python) == sorted([B_ROADS, T_ROADS, E_ROADS, DIFFERENCE, E_EDIT]), (
        f"Run All ran {python}: each Python node once, in and below the hidden scenarios"
    )
    _assert_towers_removed(page)
    # Every building part reaches each shadow step's shader: Back Bay's 2108,
    # and the 2101 Two towers removed hands on (#757).
    assert not left_out, (
        "a shadow step's shader did not read every building part it was handed: " + "; ".join(left_out)
    )
    for scenario_id in NAMES:
        _frame_box(page, scenario_id, MEMBERS[scenario_id])
        assert _box_color(page, scenario_id) == _rgb(COLORS[scenario_id])
        # Its outcome: its roads, which the comparisons read.
        for outcome in MEMBERS[scenario_id][-1:]:
            page.wait_for_function(
                """([box, node]) => {
                    const row = document.querySelector(`[data-scenario-box="${box}"] [data-scenario-outcome="${node}"]`);
                    return !!row && row.textContent.includes("Done");
                }""",
                arg=[scenario_id, outcome],
                timeout=15000,
            )

    # A double-click expands Baseline in place, and its map is drawn.
    box = _frame_box(page, BASELINE, MEMBERS[BASELINE])
    box.dblclick()
    node_locator(page, B_MAP).wait_for(state="visible", timeout=10000)
    assert _box(page, BASELINE).count() == 0
    frame_nodes(page, [B_MAP])
    assert_autark_map_drawn(page, B_MAP, timeout=60000, attach_as="Baseline's map, expanded after a collapsed run")

    # 3. The chart: Twice as tall has the least sunlight and Two towers removed
    # the most.
    roads = {scenario_id: _rows(page, ROADS_OF[scenario_id]) for scenario_id in NAMES}
    means = {NAMES[sid]: sum(row["sunlight"] for row in rows) / len(rows) for sid, rows in roads.items() if rows}
    assert len(means) == 3, f"a scenario's roads are empty: {sorted(means)}"
    assert means["Twice as tall"] < means["Baseline"] < means["Two towers removed"], (
        f"mean road sunlight per scenario: {means}"
    )
    frame_nodes(page, [CHART])
    _assert_chart_drew(page, CHART)

    # 4. The difference: each road's change, below zero where shadows grew.
    rows = _rows(page, DIFFERENCE)
    assert len(rows) == len(roads[BASELINE]), f"{len(rows)} rows for {len(roads[BASELINE])} roads"
    for row in rows:
        assert row["sunlight_change"] <= 0, f"a road gained sunlight from taller buildings: {row}"
        assert row["sunlight_change"] == row["sunlight"] - row["sunlight_before"], row
    assert any(row["sunlight_change"] < 0 for row in rows), "no road lost sunlight to the taller buildings"
    frame_nodes(page, [CHANGE_MAP])
    assert_autark_map_drawn(page, CHANGE_MAP, timeout=60000, attach_as="the sunlight change per road")

    # 5. Saved and reopened: everything comes back.
    save_dataflow(page)
    saved = _saved_spec(current_server, token, project_id)["dataflow"]
    by_id = {node["id"]: node for node in saved["nodes"]}
    shipped = {node["id"]: node for node in spec["dataflow"]["nodes"]}
    for node_id in (CHART, DIFFERENCE):
        assert by_id[node_id]["content"] == shipped[node_id]["content"], f"{node_id} rewrote its content"
    assert json.loads(by_id[CHART]["content"])["data"] == {"name": "inputs"}
    assert by_id[E_EDIT]["content"] == shipped[E_EDIT]["content"], f"{E_EDIT} rewrote its code"
    assert by_id[E_EDIT]["metadata"]["editFeatures"] == shipped[E_EDIT]["metadata"]["editFeatures"]
    scenarios = {scenario["id"]: scenario for scenario in saved["scenarios"]}
    assert [(s["name"], s["color"]) for s in saved["scenarios"]] == [
        (NAMES[s], COLORS[s]) for s in (BASELINE, TWICE, TOWERS)
    ], saved["scenarios"]
    assert scenarios[TWICE].get("collapsed") is True and not scenarios[BASELINE].get("collapsed")
    assert scenarios[TOWERS].get("collapsed") is True
    widgets = {node_id: by_id[node_id]["metadata"]["widgets"][0] for node_id in (B_COMPUTE, T_COMPUTE, E_COMPUTE)}
    assert widgets[B_COMPUTE].get("value", widgets[B_COMPUTE]["default"]) == 1, widgets
    assert widgets[T_COMPUTE]["value"] == 2, widgets
    assert widgets[E_COMPUTE].get("value", widgets[E_COMPUTE]["default"]) == 1, widgets
    recorded = {output["node_id"] for output in api_json(f"{current_server}/api/projects/{project_id}", token)["outputs"]}
    assert {DATA, B_ROADS, T_ROADS, E_ROADS} <= recorded, (
        f"the save recorded the outputs of {sorted(recorded)}, not every scenario context and outcome"
    )

    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    node_locator(page, B_COMPUTE).wait_for(state="visible", timeout=45000)
    for scenario_id in (TWICE, TOWERS):
        _box(page, scenario_id).wait_for(state="visible", timeout=30000)
        for node_id in MEMBERS[scenario_id]:
            node_locator(page, node_id).wait_for(state="attached", timeout=30000)
            assert not node_locator(page, node_id).is_visible(), f"{node_id} shows, though its scenario was saved collapsed"
        assert _box_color(page, scenario_id) == _rgb(COLORS[scenario_id])
    assert _frame_color(page, BASELINE) == _rgb(COLORS[BASELINE])
    for node_id in (DATA, B_ROADS, T_ROADS, E_ROADS):
        assert _status(page, node_id) == "done", f"{node_id} reads {_status(page, node_id)!r}: its saved output was not restored"
    _scenario_menu(page, "Show scenarios")
    _assert_cards(page)
    _assert_tag_and_chip(page, B_COMPUTE, "1")
    box = _frame_box(page, TWICE, MEMBERS[TWICE])
    box.dblclick()
    node_locator(page, T_COMPUTE).wait_for(state="visible", timeout=10000)
    _assert_tag_and_chip(page, T_COMPUTE, "2")


@pytest.mark.examples
def test_both_scenarios_dragged_into_an_empty_project_read_one_context(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The seeded example runs and is saved; then, in an empty project, both of
    its scenarios are dragged in from the Scenario Catalog and compared."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    empty = {"dataflow": {
        "name": "Shadow comparison", "task": "", "timestamp": 1789193389280,
        "provenance_id": "Shadow comparison", "nodes": [], "edges": [],
    }}
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Example 06 Drop",
        username="example06_drop_e2e",
        project_name="Shadow comparison",
        project_spec=empty,
    )
    require_owner_view(page)
    token, target = session["token"], session["project"]["id"]
    # The first listing seeds the account's copies of the shipped dataflows.
    listed = api_json(f"{current_server}/api/projects", token, timeout=120)
    seeded = [p for p in listed if p.get("name") == EXAMPLE_NAME]
    assert seeded, f"the account has no seeded {EXAMPLE_NAME!r}: {sorted(p.get('name') for p in listed)}"
    source = seeded[0]["id"]

    # The seeded example runs and is saved: its context and outcomes are saved.
    page.goto(f"{app_frontend.base_url}/dataflow/{source}")
    for node_id in (DATA, B_MAP, T_MAP):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    _require_webgpu(page)
    run_all_and_wait(page, timeout_ms=RUN_MS)
    for node_id, node_type in ((B_MAP, AUTARK), (T_MAP, AUTARK)):
        _settled_done(page, node_id, node_type)
    save_dataflow(page)

    # Both scenarios dragged into the empty project: nothing runs. Zoomed out
    # first, so the two land far enough apart to be expanded side by side.
    page.goto(f"{app_frontend.base_url}/dataflow/{target}")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=45000)
    page.locator(".react-flow__pane").wait_for(state="visible", timeout=45000)
    drawer = page.locator('[data-curio-scenario-catalog-drawer="true"]')
    python, _loads, stop = _record_runs(page, DATA)
    for scenario_id, name, at in ((BASELINE, "Baseline", (200.0, 80.0)), (TWICE, "Twice as tall", (200.0, 420.0))):
        _zoom_out(page)
        if not drawer.is_visible():
            _open_scenario_catalog(page)
        _drag_scenario_onto_canvas(page, source, scenario_id, at=at)
        _toast(page, f'Added "{name}" from {EXAMPLE_NAME}.')
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, '[data-curio-scenario-catalog-drawer="true"]')
    # The pool passes on the loader's layers, so the Data Loading node that
    # stands for it is a copy of the loader's saved output.
    copies = _copies(page)
    for original in (DATA, *MEMBERS[BASELINE], *MEMBERS[TWICE]):
        assert original in copies, f"no copy of {original} arrived: {copies}"
    for original in (B_ROADS, T_ROADS):
        assert _status(page, copies[original]) == "done", (
            f"{copies[original]} (from {original}) does not show the result its source saved"
        )
    stop()
    assert python == [], f"the drops ran {python}: dropped scenarios show their saved results without a run"

    save_dataflow(page)
    saved = _saved_spec(current_server, token, target)["dataflow"]
    dropped = {scenario["name"]: scenario for scenario in saved["scenarios"]}
    assert sorted(dropped) == ["Baseline", "Twice as tall"], saved["scenarios"]
    for name, scenario in dropped.items():
        assert scenario["collapsed"] is True, scenario
        assert scenario["source"]["project"] == source, scenario
    # One Data Loading node stands for the pool, fixed data both scenarios read.
    loader = copies[DATA]
    by_id = {node["id"]: node for node in saved["nodes"]}
    assert by_id[loader]["type"].startswith("curio.builtin/data-loading"), by_id[loader]["type"]
    readers = sorted(edge["target"] for edge in saved["edges"] if edge["source"] == loader)
    assert readers == sorted([copies[B_COMPUTE], copies[T_COMPUTE]]), (
        f"the shared context feeds {readers}, not both shadow steps"
    )

    # A Vega-Lite node comparing both dropped scenarios' roads.
    chart = drag_to_canvas(page, page.locator("#tile-vis-vega"), at=(900.0, 260.0))
    for name in ("Baseline", "Twice as tall"):
        scenario = dropped[name]
        box = _frame_box(page, scenario["id"], scenario["nodes"])
        box.dblclick()
        node_locator(page, scenario["nodes"][-1]).wait_for(state="visible", timeout=10000)
    _wait_for_circles(page, chart, ["in"])
    # The drops' toasts sit bottom right, where a dropped node's handle can be.
    frame_nodes(page, [copies[B_ROADS], chart])
    dismiss_toasts(page)
    connect_nodes(page, copies[B_ROADS], chart)
    _wait_for_circles(page, chart, ["in", "in_1"])
    frame_nodes(page, [copies[T_ROADS], chart])
    dismiss_toasts(page)
    connect_nodes(page, copies[T_ROADS], chart, target_handle="in_1")

    # Its circles read the scenarios' roads in order: a spec over the stacked
    # inputs (the dataset inputs) names each from its circle (__input__).
    wired = page.evaluate(
        """(id) => Object.fromEntries(window.__curio_reactFlow.getEdges()
            .filter((e) => e.target === id).map((e) => [e.targetHandle, e.source]))""",
        chart,
    )
    assert wired == {"in": copies[B_ROADS], "in_1": copies[T_ROADS]}, f"the chart's circles read {wired}"
