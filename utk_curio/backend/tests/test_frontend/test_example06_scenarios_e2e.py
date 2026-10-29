"""Playwright E2E: example 06 as a scenario study (#662).

Example 06 runs example 07's per-road sunlight shader in three scenarios over
one fixed context, the Back Bay loader and its data pool: "Baseline", every
building at its own height, "Twice as tall", a copy of it with every building
doubled, and "Two towers removed", where a Map Editor node removes two
towers, 200 Clarendon and Raffles, by their ``building_id`` before copies of
Baseline's nodes, and feeds a map of the buildings it is linked to. The
factor is a ``height_factor`` widget on each shadow step, read as an Autark
uniform. Each scenario ends in a Roads node that takes the roads layer out of
the five its shadow step hands on. Outside them, Scout's Bars (``curio.scout@1``)
charts the three Roads nodes' mean road sunlight, and a Python node, Sunlight
change, takes each road's sunlight change in Twice as tall from Baseline's map
and Twice as tall's, the roads matched by their shapes, which an Autark map
after it draws.

The first test drives the example as it ships:

1. Its three scenarios are listed in the Scenario Catalog drawer's In project
   tab, each with the shared pool as the fixed context its details list. Each
   shadow step's ``height_factor`` tag sits in its Widgets tab, with its value,
   and as a chip in its spec.
2. All collapsed, Run All: the loader loads once for all, on the server, the
   scenarios run hidden, and each box shows its outcomes done, Two towers
   removed's map of its buildings among them. The Map Editor node reads the
   loader's layers through the pool and hands them on without every part of
   both towers. Each shadow step's batched shader reads every building part it
   is handed: autk-grammar says it left none out (#757). A double-click expands
   one scenario in place, and its map is drawn.
3. The chart: Twice as tall has the lowest mean sunlight and Two towers removed
   the highest, in the rows the Bars chart reads, and the chart draws every
   scenario's colour.
4. The difference: each road's sunlight change, one row per road Baseline's
   Roads node hands on, below zero where the taller shadows reach it and zero
   elsewhere, in its ``sunlight`` and in its nested ``compute`` values, within
   -360 to 360 minutes, in a layer with no layer name or type: exactly what
   the rule writes from the two Roads nodes' layers, Twice as tall's minus
   Baseline's, the same roads in the same order with the same columns, types,
   values, shapes and coordinate system. The Autark map after the Sunlight
   change node draws it, under the title "Sunlight change (minutes)", its
   legend labelled -360, 0 and 360: a scale centered on no change.
5. A save and a reopen: the scenarios, their colours, the collapsed ones, the
   widgets and their values, the Map Editor node's code, which holds its edits,
   and the saved outputs come back.

The second test drags both scenarios from the Scenario Catalog into an empty
project, once the seeded example has run: they arrive with their results, read
one context, and each expands in place; a Vega-Lite chart reading ``inputs``,
wired to the two dropped Roads nodes, names each one's rows by its dropped box.

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

from .test_map_edits_e2e import _edits_of
from .test_multi_input_e2e import _wait_for_circles
from .test_scenario_drop_e2e import (
    _copies,
    _drag_scenario_onto_canvas,
    _open_scenario_catalog,
    _saved_spec,
    _status,
    _toast,
)
from .test_scenarios_canvas_e2e import _box, _frame_box
from .test_widget_tags_e2e import _open_tab, _panel
from .utils import (
    REPO_ROOT,
    _COLOR_PIXELS_JS,
    _OUTPUT_ARTIFACT_JS,
    _assert_legend_reads,
    _assert_legend_title,
    api_json,
    assert_autark_map_drawn,
    assert_vega_canvas_rendered,
    close_scenario_details,
    close_scenario_drawer,
    connect_nodes,
    dismiss_toasts,
    drag_builtin_to_canvas,
    frame_nodes,
    in_project_card,
    load_artifact_as_dict,
    node_locator,
    open_in_project_tab,
    open_scenario_details,
    play_node,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_all_and_wait,
    save_dataflow,
    scenario_card_button,
    scenario_part,
    set_node_code,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = Path(REPO_ROOT) / "docs" / "examples" / "06-back-bay-road-sunlight.json"
EXAMPLE_NAME = "Back Bay road sunlight when buildings change"
AUTARK = "curio.builtin/autk-grammar"
COMPARE = "curio.builtin/compare-scenarios"
BARS = "curio.scout/bars"
PYTHON = "curio.builtin/computation-analysis"
VEGA = "curio.builtin/vis-vega"
#: The chart the second test wires to the two dropped Roads nodes: mean
#: sunlight per scenario, its rows its inputs stacked under their boxes, in
#: the dataset its chip names.
DROPPED_CHART_SPEC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "data": {"name": "[!! inputs !!]"},
    "mark": "bar",
    "encoding": {
        "x": {"field": "scenario_name", "type": "nominal"},
        "y": {"field": "sunlight", "type": "quantitative", "aggregate": "mean"},
    },
}, indent=2)

DATA = "whatif-data"
B_COMPUTE, B_MAP, B_ROADS = "whatif-baseline-compute", "whatif-baseline-map", "whatif-baseline-roads"
T_COMPUTE, T_MAP, T_ROADS = "whatif-modified-compute", "whatif-modified-map", "whatif-modified-roads"
E_EDIT, E_COMPUTE, E_MAP, E_ROADS = (
    "whatif-towers-edit", "whatif-towers-compute", "whatif-towers-map", "whatif-towers-roads",
)
#: The map of the buildings Two towers removed's Map Editor node hands on,
#: which it is linked to: an outcome of the scenario.
E_BUILDINGS = "whatif-towers-buildings"
#: Scout's Bars chart of mean sunlight and the Python node that takes the
#: sunlight change, which keep the ids of the Compare nodes they replaced.
CHART, DIFFERENCE = "whatif-compare-chart", "whatif-compare-difference"
#: The Autark map after the Sunlight change node, which draws each road's change.
DIFFERENCE_MAP = "whatif-difference-map"
#: Its color range in minutes, symmetric about no change, which takes the
#: diverging scheme's middle: its legend reads the ends and the middle, and
#: every road's change lies within it.
CHANGE_RANGE = (-360, 360)
#: The coordinate system Autark draws in, as a layer names it in its GeoJSON
#: (``sandbox/util/input_layers._crs_named_by``).
AUTARK_CRS = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3395"}}
BASELINE, TWICE, TOWERS = "s-baseline", "s-twice", "s-towers"
NAMES = {BASELINE: "Baseline", TWICE: "Twice as tall", TOWERS: "Two towers removed"}
COLORS = {BASELINE: "#3567c7", TWICE: "#e86a3c", TOWERS: "#2f8f4a"}
MEMBERS = {
    BASELINE: [B_COMPUTE, B_MAP, B_ROADS],
    TWICE: [T_COMPUTE, T_MAP, T_ROADS],
    TOWERS: [E_EDIT, E_BUILDINGS, E_COMPUTE, E_MAP, E_ROADS],
}
#: The outcomes each box lists that the test checks done: its Roads node, which
#: the chart reads, and Two towers removed's map of its buildings.
OUTCOMES = {BASELINE: [B_ROADS], TWICE: [T_ROADS], TOWERS: [E_BUILDINGS, E_ROADS]}
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


def _ran_on_the_server(backend: str, token: str, project_id: str) -> list[str]:
    """The nodes the dataflow's last run executed on the server: its steps
    that ran there and kept an output. A node a tab ran and reported keeps none."""
    runs = api_json(f"{backend}/api/projects/{project_id}/runs?limit=1", token)["runs"]
    assert runs, "Run All started no run on the server"
    run = api_json(f"{backend}/api/runs/{runs[0]['id']}", token)
    return [step["nodeId"] for step in run["steps"] if step["role"] == "run" and step["outputPath"]]


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


def _stored(page, node_id: str) -> dict:
    """*node_id*'s saved output, a layer, as the sandbox stores it."""
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, f"{node_id} shows no saved output"
    stored = load_artifact_as_dict(artifact)
    assert stored["dataType"] == "geodataframe", f"{node_id} gave {stored['dataType']}"
    return stored


def _rows(page, node_id: str) -> list[dict]:
    """The rows of *node_id*'s saved output, a layer, as the sandbox stores them."""
    return [feature["properties"] for feature in _stored(page, node_id)["data"]["features"]]


def _layer_of(stored: dict):
    """A stored layer, as the sandbox hands it to the page, rebuilt as the
    frame it was: its columns in the order and of the types its schema names,
    its outlines, and its coordinate system."""
    import geopandas as gpd

    data = stored["data"]
    geometry = data.get("geometry_name") or "geometry"
    name = ((data.get("crs") or {}).get("properties") or {}).get("name", "")
    frame = gpd.GeoDataFrame.from_features(data["features"], crs=f"EPSG:{name.rsplit(':', 1)[-1]}" if name else None)
    if geometry != "geometry":
        frame = frame.rename_geometry(geometry)
    frame = frame[list(stored["schema"])]
    for column, dtype in stored["schema"].items():
        if column != geometry and str(frame[column].dtype) != dtype:
            frame[column] = frame[column].astype(dtype)
    return frame


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

# Per scenario name, the sum and the count of *field* in the rows a chart's
# last view reads as its ``inputs`` dataset (useVega.ts names it so).
_INPUTS_SUMS_JS = """([id, field]) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    if (!view) return null;
    let rows;
    try {
        rows = view.data("inputs");
    } catch (error) {
        return null;
    }
    const sums = {};
    for (const row of rows) {
        const value = row[field];
        if (typeof value !== "number") continue;
        const entry = sums[row.scenario_name] || (sums[row.scenario_name] = [0, 0]);
        entry[0] += value;
        entry[1] += 1;
    }
    return sums;
}"""


# The runs of the rows a chart's last view reads as ``inputs``, in their
# order: ``[scenario, scenario_name, how many rows]`` for each run of one box.
_INPUTS_LABELS_JS = """(id) => {
    const view = (window.__curioVegaViews || {})["vega" + id];
    if (!view) return null;
    let rows;
    try {
        rows = view.data("inputs");
    } catch (error) {
        return null;
    }
    const runs = [];
    for (const row of rows) {
        const last = runs[runs.length - 1];
        if (last && last[0] === row.scenario && last[1] === row.scenario_name) last[2] += 1;
        else runs.push([row.scenario, row.scenario_name, 1]);
    }
    return runs;
}"""


def _inputs_labels(page, node_id: str, count: int) -> list:
    """The *count* runs of one box in the rows the chart reads, once its view holds them."""
    runs = None
    deadline = time.time() + 30
    while time.time() < deadline:
        runs = page.evaluate(_INPUTS_LABELS_JS, node_id)
        if runs and len(runs) == count:
            return runs
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart {node_id} reads the runs {runs}, not {count}")


def _chart_means(page, node_id: str, field: str) -> dict:
    """Each scenario's mean *field* over the rows the chart reads, by name."""
    sums = None
    deadline = time.time() + 30
    while time.time() < deadline:
        sums = page.evaluate(_INPUTS_SUMS_JS, [node_id, field])
        if sums and set(sums) == set(NAMES.values()):
            return {name: total / count for name, (total, count) in sums.items()}
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart {node_id} reads the rows {sums}, not every scenario's {field}")


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
    """The chart drew, and its canvas holds every scenario's colour."""
    assert_vega_canvas_rendered(page, node_id, timeout=30000)
    colors = [COLORS[BASELINE], COLORS[TWICE], COLORS[TOWERS]]
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_COLOR_PIXELS_JS, [node_id, colors])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart does not draw every scenario's colour {colors}: pixels {counts}")


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
    """The same, in the layers Map Editor hands on, as an Autark node does."""
    for item in wrapper["data"]:
        if item.get("layerName") == BUILDINGS:
            return _ids_of(item["data"])
    raise AssertionError(f"the handed-on layers hold no {BUILDINGS}: {[i.get('layerName') for i in wrapper['data']]}")


def _assert_towers_removed(page) -> None:
    """The Map Editor node read the loader's layers, through the pool, and
    handed them on without every part of both towers: every id it names is a
    building of the input, so none is unknown."""
    source = page.evaluate(_INPUT_ARTIFACT_JS, E_EDIT)
    assert source, "the pool did not name the artifact it read, for the Map Editor node to read"
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
    """The In project tab lists the three scenarios, and each one's details
    hold its name and colour and list the data pool as the fixed context it
    reads. The drawer is closed again after."""
    open_in_project_tab(page)
    for scenario_id, name in NAMES.items():
        card = in_project_card(page, scenario_id)
        card.wait_for(state="visible", timeout=15000)
        assert name in card.inner_text(), f"the {scenario_id} card reads {card.inner_text()!r}"
        details = open_scenario_details(page, scenario_id)
        assert details.get_by_label("Scenario name").input_value() == name
        assert details.get_by_label(f"Color of {name}").input_value().lower() == COLORS[scenario_id]
        context = scenario_part(details, "Shared context")
        assert "Data Pool" in context, f"{name} lists {context!r} as its fixed context"
        close_scenario_details(page)
    close_scenario_drawer(page)


def test_example_06_compares_its_three_scenarios_in_the_canvas(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(_KEEP_VEGA_VIEWS_INIT)
    spec = _example()
    assert not [n["id"] for n in spec["dataflow"]["nodes"] if n["type"] == COMPARE], "example 06 still holds a Compare node"
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
    require_webgpu(page)

    # 1. Three scenarios over the shared pool, and each shadow step's tag.
    _assert_cards(page)
    for scenario_id in NAMES:
        assert _frame_color(page, scenario_id) == _rgb(COLORS[scenario_id])
    _assert_tag_and_chip(page, B_COMPUTE, "1")
    _assert_tag_and_chip(page, T_COMPUTE, "2")
    _assert_tag_and_chip(page, E_COMPUTE, "1")

    # 2. All collapsed, Run All: the loader loads once, and every scenario runs.
    open_in_project_tab(page)
    for scenario_id in NAMES:
        scenario_card_button(page, scenario_id, "Collapse").click()
        _box(page, scenario_id).wait_for(state="attached", timeout=10000)
        for node_id in MEMBERS[scenario_id]:
            assert not node_locator(page, node_id).is_visible(), f"{node_id} shows inside a collapsed scenario"
    close_scenario_drawer(page)
    python, loads, stop = _record_runs(page, DATA)
    left_out, stop_left_out = _record_batched_left_out(page)
    run_all_and_wait(page, timeout_ms=RUN_MS)
    for node_id, node_type in (
        (B_MAP, AUTARK), (T_MAP, AUTARK), (E_EDIT, EDIT_TYPE), (E_BUILDINGS, AUTARK), (E_MAP, AUTARK),
        (B_ROADS, PYTHON), (T_ROADS, PYTHON), (E_ROADS, PYTHON), (CHART, BARS), (DIFFERENCE, PYTHON),
        (DIFFERENCE_MAP, AUTARK),
    ):
        _settled_done(page, node_id, node_type)
    stop()
    stop_left_out()
    # The run on the server loads what the three scenarios share, once, and
    # runs each Python node it reaches; the page runs the rest.
    on_server = _ran_on_the_server(current_server, token, project_id)
    assert loads == [] and on_server.count(DATA) == 1, (
        f"the loader the three scenarios share loaded {on_server.count(DATA)} time(s) on the server "
        f"and {len(loads)} in the page, not once on the server"
    )
    ran = sorted(python + [node_id for node_id in on_server if node_id != DATA])
    assert ran == sorted([E_EDIT, B_ROADS, T_ROADS, E_ROADS, DIFFERENCE]), (
        f"Run All ran {python} in the page and {on_server} on the server: each Python node once, "
        "in and below the hidden scenarios"
    )
    _assert_towers_removed(page)
    # Every building part reaches each shadow step's shader: Back Bay's 2102,
    # and the 2095 Two towers removed hands on (#757).
    assert not left_out, (
        "a shadow step's shader did not read every building part it was handed: " + "; ".join(left_out)
    )
    for scenario_id in NAMES:
        _frame_box(page, scenario_id, MEMBERS[scenario_id])
        assert _box_color(page, scenario_id) == _rgb(COLORS[scenario_id])
        # Its outcomes: the Roads node, which the chart reads, and Two
        # towers removed's map of the buildings its Map Editor node hands on.
        for outcome in OUTCOMES[scenario_id]:
            page.wait_for_function(
                """([box, node]) => {
                    const row = document.querySelector(`[data-scenario-box="${box}"] [data-scenario-row="${node}"]`);
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
    # the most, in the rows the Bars chart reads.
    frame_nodes(page, [CHART])
    _assert_chart_drew(page, CHART)
    means = _chart_means(page, CHART, "sunlight")
    assert means["Twice as tall"] < means["Baseline"] < means["Two towers removed"], (
        f"mean road sunlight per scenario: {means}"
    )

    # 4. The difference: each road's change, below zero where shadows grew, on
    # a scale centered on no change, one row per road Baseline's Roads node
    # hands on.
    baseline_roads = _rows(page, B_ROADS)
    frame_nodes(page, [DIFFERENCE, DIFFERENCE_MAP])
    assert_autark_map_drawn(page, DIFFERENCE_MAP, timeout=60000, attach_as="the sunlight change per road")
    _assert_legend_title(page, DIFFERENCE_MAP, "Sunlight change (minutes)")
    low, high = CHANGE_RANGE
    _assert_legend_reads(page, DIFFERENCE_MAP, (low, (low + high) / 2, high))
    # The Sunlight change node writes a layer with no layer name or type.
    written = _stored(page, DIFFERENCE)
    assert "metadata" not in written["data"], written["data"].get("metadata")
    # It writes exactly what the rule writes from the two Roads nodes' layers,
    # Twice as tall's minutes minus Baseline's, road by road: the same roads,
    # in the same order, with the same columns, types, values and shapes
    # (roads_change, which the fixture of Compare's own output holds to it,
    # the order of its columns too: the sandbox's /get writes its JSON with the
    # keys sorted, so a page cannot see that order). The node reads its roads
    # from the two maps, which name the coordinate system Autark draws in; the
    # Roads nodes read the same roads from the shadow steps, whose layers name
    # none. So the node's coordinate system is held to Autark's, as the unit
    # test holds it, and the rest of its layer to the rule's.
    from utk_curio.backend.tests._support.scenario_changes import first_difference, roads_change
    from utk_curio.sandbox.util.parsers import parseOutput

    expected = parseOutput(roads_change(_layer_of(_stored(page, B_ROADS)), _layer_of(_stored(page, T_ROADS))))
    assert written["data"].get("crs") == AUTARK_CRS, written["data"].get("crs")
    assert expected["data"].get("crs") in (None, AUTARK_CRS), expected["data"].get("crs")

    def _without_crs(envelope: dict) -> dict:
        data = {k: v for k, v in envelope["data"].items() if k != "crs"}
        return {"dataType": envelope["dataType"], "schema": envelope["schema"], "data": data}

    difference = first_difference(_without_crs(written), _without_crs(expected))
    assert difference is None, f"the Sunlight change node does not write Twice as tall's roads minus Baseline's: {difference}"
    rows = _rows(page, DIFFERENCE)
    assert len(rows) == len(baseline_roads), f"{len(rows)} rows for {len(baseline_roads)} roads"
    assert {row["change"] for row in rows} <= {"changed", "unchanged"}, (
        "both scenarios have the same roads, matched by their shapes, so none is added or removed"
    )
    for row in rows:
        assert row["sunlight"] <= 0, f"a road gained sunlight from taller buildings: {row}"
        assert (row["change"] == "changed") == (row["sunlight"] < 0), row
        assert row["compute"]["sunlight"] == row["sunlight"], (
            f"the nested compute value is not the difference too: {row}"
        )
        assert low <= row["sunlight"] <= high, f"a road's change is outside the map's color range {CHANGE_RANGE}: {row}"
    assert any(row["sunlight"] < 0 for row in rows), "no road lost sunlight to the taller buildings"

    # 5. Saved and reopened: everything comes back.
    save_dataflow(page)
    saved = _saved_spec(current_server, token, project_id)["dataflow"]
    by_id = {node["id"]: node for node in saved["nodes"]}
    shipped = {node["id"]: node for node in spec["dataflow"]["nodes"]}
    for node_id in (CHART, DIFFERENCE, B_ROADS, T_ROADS, E_ROADS):
        assert by_id[node_id]["content"] == shipped[node_id]["content"], f"{node_id} rewrote its code"
    saved_values = {w["name"]: w.get("value", w["default"]) for w in by_id[CHART]["metadata"]["widgets"]}
    assert saved_values == {"y": "sunlight", "combine": "mean", "y_title": "mean of sunlight"}, saved_values
    assert by_id[E_EDIT]["content"] == shipped[E_EDIT]["content"], f"{E_EDIT} rewrote its code"
    # Its edits are in its code, the node's only state: the two towers removed
    # by building_id, on the buildings layer.
    edits, keywords = _edits_of(by_id[E_EDIT]["content"])
    assert edits == [{"op": "remove", "ids": sorted(TOWER_PARTS)}], edits
    assert (keywords.get("key"), keywords.get("layer")) == ("building_id", BUILDINGS), keywords
    assert "editFeatures" not in by_id[E_EDIT]["metadata"], by_id[E_EDIT]["metadata"]
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
    assert {DATA, B_COMPUTE, T_COMPUTE, E_COMPUTE} <= recorded, (
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
    for node_id in (DATA, B_COMPUTE, T_COMPUTE, E_COMPUTE):
        assert _status(page, node_id) == "done", f"{node_id} reads {_status(page, node_id)!r}: its saved output was not restored"
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
    its scenarios are dragged in from the Scenario Catalog: they show their
    saved results with no run, read one context, and expand in place. A
    Vega-Lite chart reading ``inputs``, wired to the two dropped Roads nodes,
    names each input's rows by the dropped box its node is in."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(_KEEP_VEGA_VIEWS_INIT)
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
    require_webgpu(page)
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
    for original in (B_COMPUTE, T_COMPUTE):
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

    # Each dropped scenario expands in place on a double-click.
    for name in ("Baseline", "Twice as tall"):
        scenario = dropped[name]
        box = _frame_box(page, scenario["id"], scenario["nodes"])
        box.dblclick()
        node_locator(page, scenario["nodes"][-1]).wait_for(state="visible", timeout=10000)

    # A Vega-Lite chart reading inputs, over the two dropped Roads nodes:
    # each input's rows carry the dropped box their node is in, its id and its
    # name, in circle order.
    from utk_curio.backend.tests.test_example06_sunlight_change import ROAD_COUNT

    chart = drag_builtin_to_canvas(page, "#tile-vis-vega", at=(900.0, 260.0))
    set_node_code(page, chart, DROPPED_CHART_SPEC)
    _wait_for_circles(page, chart, ["in"])
    # The drops' toasts sit bottom right, where a dropped node's handle can be.
    frame_nodes(page, [copies[B_ROADS], chart])
    dismiss_toasts(page)
    connect_nodes(page, copies[B_ROADS], chart)
    _wait_for_circles(page, chart, ["in", "in_1"])
    frame_nodes(page, [copies[T_ROADS], chart])
    dismiss_toasts(page)
    connect_nodes(page, copies[T_ROADS], chart, target_handle="in_1")
    play_node(page, chart)
    _settled_done(page, chart, VEGA)
    labels = _inputs_labels(page, chart, 2)
    assert labels == [
        [dropped["Baseline"]["id"], "Baseline", ROAD_COUNT],
        [dropped["Twice as tall"]["id"], "Twice as tall", ROAD_COUNT],
    ], f"the chart names its inputs' rows {labels}, not by the dropped boxes"
