"""Example 06's Sunlight change node writes what Compare Scenarios wrote (the
plan answering komar41's review, step 6.3).

Until the plan's step 6.3, example 06 took each road's sunlight change with a
Compare Scenarios node in Difference over Baseline's map and Twice as tall's,
on their roads layer, the roads matched by their shapes, since they carry no
id. A Python node over the same two maps takes it now, and what it writes must
be what Compare wrote, column for column and value for value, so the Autark
map after it draws the same roads in the same colors and the numbers
``test_example06_scenarios_e2e.py`` pins stay.

Each test runs the node's shipped code as the sandbox runs a node with two
input circles, on what each scenario's map hands on: the layers the example's
own data node loads from Back Bay's extract (made as a run on the server makes
them: its document through the browser's compiler and the sandbox's autk-db,
the extract served from disk, no socket), handed on as a shadow step hands
them on, each road with its minutes of sunlight in a column and in the
``compute`` values the step writes its outputs under. The shader runs only on
a browser's GPU, so the minutes are made here: whole hours from none to
thirteen in Baseline, and up to three hours fewer on three roads of every four
in Twice as tall. The reference is the rule Compare's own function wrote by
(:func:`_compares_difference`), stated from the same inputs since step 6.4 of
that plan removed the node.

Imports are inside each test or helper, so a checkout without the sandbox's
pieces fails test by test.
"""
from __future__ import annotations

import copy
import json
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
EXAMPLE = REPO / "docs" / "examples" / "06-back-bay-road-sunlight.json"
LOADER = "whatif-data"
#: The Sunlight change node, which keeps the id of the Compare node it replaced.
CHANGE = "whatif-compare-difference"
PYTHON_TYPE = "curio.builtin/computation-analysis"
ROADS = "table_osm_roads"
#: The layers the data node loads, in its order, and the autk-db they come
#: from (``test_autk_server_data_load.py`` pins both).
LAYERS = ["table_osm_surface", "table_osm_parks", "table_osm_water", ROADS, "table_osm_buildings"]
AUTK_DB_VERSION = "4.1.1"
ROAD_COUNT = 736
#: The two inputs, by the scenario each comes from, as Compare's code named them.
SCENARIOS = [("s-baseline", "Baseline"), ("s-twice", "Twice as tall")]
#: The scale the map after the node draws the change on, in minutes.
CHANGE_RANGE = (-360, 360)


def _dataflow() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))["dataflow"]


@pytest.fixture(scope="module")
def back_bay_layers(tmp_path_factory):
    """The layers example 06's data node hands on, made as a run on the server
    makes them, as ``example_layers`` in ``test_scout_routing.py`` makes the
    routing example's: the node's document compiled by the browser's own
    compiler (``compile_data_spec``) and run in the sandbox with autk-db
    (``execute_js_code``), the extract served from disk by a ``fetch`` that
    refuses every other request, at an address nothing answers at. Made once
    for the module."""
    from utk_curio.cli import dependencies
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import _worker_init, execute_js_code
    from utk_curio.sandbox.tests.test_autk_server_data_load import _FETCH_FROM_DISK
    from utk_curio.sandbox.util.db import init_db, release_connection
    from utk_curio.sandbox.util.node_runtime import node_modules_dir
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    installed = json.loads(
        (node_modules_dir() / "@urban-toolkit" / "autk-db" / "package.json").read_text(encoding="utf-8")
    )["version"]
    assert installed == AUTK_DB_VERSION, f"Back Bay's roads are autk-db {AUTK_DB_VERSION}'s; the sandbox has {installed}"
    (loader,) = [n for n in _dataflow()["nodes"] if n["id"] == LOADER]
    (source,) = json.loads(loader["content"])["data"]
    extract = source["pbfFileUrl"]
    code = compile_data_spec(loader["content"])
    serve = _FETCH_FROM_DISK.replace("EXTRACT", json.dumps(extract)).replace("ROOT", json.dumps(str(REPO)))
    home = tmp_path_factory.mktemp("back-bay")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HOME", str(home))
        patch.setattr(Path, "home", lambda: home)
        patch.setenv("FLASK_BACKEND_HOST", "curio-backend.invalid")
        patch.setenv("FLASK_BACKEND_PORT", "1")
        patch.setenv("CURIO_LAUNCH_CWD", str(home))
        patch.setenv("CURIO_SHARED_DATA", str(home / "data"))
        release_connection()
        init_db()
        try:
            dependencies.seed_duckdb_extensions()
            _worker_init()
            result = execute_js_code(serve + code, "", "AUTK_GRAMMAR", "", launch_dir=str(REPO), session_id=None)
            assert result["output"]["path"], result["stderr"]
            assert result["output"]["dataType"] == "list", result["output"]
            assert f"[served] {extract}" in result["stdout"], result["stdout"]
            layers = load_from_duckdb(result["output"]["path"], session_id=None)
        finally:
            release_connection()
    assert [layer["name"] for layer in layers] == LAYERS
    (roads,) = [layer for layer in layers if layer["name"] == ROADS]
    assert len(roads["geojson"]["features"]) == ROAD_COUNT
    return layers


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A sandbox store of the test's own, as the sandbox suites make one."""
    from utk_curio.sandbox.util.db import init_db, release_connection

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    release_connection()
    init_db()
    yield tmp_path
    release_connection()


def _minutes(scenario: str, road: int) -> int:
    """The minutes of sunlight road *road* gets in *scenario*, in whole hours
    of 60 minutes as the shader adds them: none to thirteen hours in Baseline,
    and in Twice as tall up to three hours fewer on three roads of every
    four, never below none."""
    baseline = 60 * (road % 14)
    return baseline if scenario == "s-baseline" else max(0, baseline - 60 * (road % 4))


def _handed_on(layers: list, scenario: str, order: list | None = None) -> dict:
    """What *scenario*'s map hands on: the layers its shadow step handed it, in
    one ``outputs`` envelope, each under its ``layerName`` and ``layerType``
    (as ``test_input_layers.py`` writes a compute step's), each road with its
    sunlight in a column and in its ``compute`` values. With *order*, the
    roads come in that order, each keeping its own minutes."""
    data = []
    for layer in copy.deepcopy(layers):
        collection = layer["geojson"]
        if layer["name"] == ROADS:
            for road, feature in enumerate(collection["features"]):
                minutes = _minutes(scenario, road)
                feature["properties"]["compute"] = {"sunlight": minutes}
                feature["properties"]["sunlight"] = minutes
            if order is not None:
                collection["features"] = [collection["features"][road] for road in order]
        data.append({
            "dataType": "geodataframe", "data": collection,
            "layerName": layer["name"], "layerType": layer["type"],
        })
    return {"dataType": "outputs", "data": data}


def _stored(values: tuple) -> list:
    """Each of *values* saved as the store holds a map's output, and its id."""
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    return [save_to_duckdb(value, node_id=f"whatif-map-{k}") for k, value in enumerate(values)]


def _the_nodes_change(workspace, baseline: dict, twice: dict):
    """The shipped Sunlight change node's output on what Baseline's map and
    Twice as tall's hand on, the node run as the sandbox runs one with two
    circles, its code resolved as a run resolves it, the output as the store
    gives it back. The node is a Python node: Compare Scenarios is gone from
    the example."""
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    (shipped,) = [n for n in _dataflow()["nodes"] if n["id"] == CHANGE]
    assert shipped["type"] == PYTHON_TYPE, f"the Sunlight change is a {shipped['type']} node, not a Python node"
    spec = parse_workflow_dict({"dataflow": _dataflow()})
    (node,) = [n for n in spec.nodes if n.id == CHANGE]
    code = spec.node_code(node, "python")
    assert "[!!" not in code, f"a chip was left in the code:\n{code}"
    inputs = [{"path": art_id, "dataType": "outputs"} for art_id in _stored((baseline, twice))]
    _worker_init()
    result = execute_code(
        textwrap.indent(code, "    "), str(inputs), PYTHON_TYPE, "outputs",
        save_dataset=False, media_dir=str(workspace / "media"), input_slots=[0, 1],
    )
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "geodataframe", result["output"]
    return load_from_duckdb(result["output"]["path"])


def _compares_difference(baseline: dict, twice: dict):
    """What Compare Scenarios' Difference wrote for Baseline's roads and Twice
    as tall's, each road matched by its shape, as the store gives it back: the
    roads in Baseline's order, geometry first and ``change`` second, then the
    roads layer's other columns in their order. Each number column, and each
    number in a column of dicts (the ``compute`` values a shadow step writes),
    is Twice as tall's value minus Baseline's; ``change`` says ``changed``
    where any value differs; every other value, and the shape, is Twice as
    tall's (``roads_change``, which the fixture of Compare's own output holds
    to it). The two maps here hand on their roads in one order and with the
    same shapes, so each road's match is the road in its place."""
    from utk_curio.backend.tests._support.scenario_changes import roads_change
    from utk_curio.sandbox.util.input_layers import curio_layer
    from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

    before, after = (curio_layer(load_from_duckdb(art_id), ROADS) for art_id in _stored((baseline, twice)))
    return load_from_duckdb(save_to_duckdb(roads_change(before, after), node_id="expected-change"))


def test_the_change_is_what_compares_difference_wrote_on_back_bays_roads(workspace, back_bay_layers):
    """On Back Bay's roads the node writes what Compare's Difference wrote: the
    same columns in the same order, geometry first and ``change`` second, each
    of their types, every value and shape, and the coordinate system the layer
    names. Neither carries a layer name or type, so the map after the node
    draws its roads as it drew Compare's. Each number is Twice as tall's
    minutes minus Baseline's, not rounded, in ``sunlight`` and its ``compute``
    twin alike: below zero where a road lost sunlight, zero elsewhere, and
    within the map's scale."""
    from geopandas.testing import assert_geodataframe_equal

    baseline, twice = (_handed_on(back_bay_layers, scenario) for scenario, _name in SCENARIOS)
    ours = _the_nodes_change(workspace, baseline, twice)
    compares = _compares_difference(baseline, twice)
    assert list(ours.columns) == list(compares.columns)
    assert list(ours.columns)[:2] == ["geometry", "change"]
    assert ours.dtypes.astype(str).tolist() == compares.dtypes.astype(str).tolist()
    assert_geodataframe_equal(ours, compares)
    assert ours.crs.to_epsg() == 3395
    assert "metadata" not in ours.__dict__ and "metadata" not in compares.__dict__
    # The roads carry no id Compare would have joined on, so it matched them
    # by their shapes, as the node does: each road is on both sides.
    assert not {"osm_id", "building_id"} & set(compares.columns)
    assert len(ours) == ROAD_COUNT
    change = [_minutes("s-twice", road) - _minutes("s-baseline", road) for road in range(ROAD_COUNT)]
    assert ours["sunlight"].tolist() == change
    assert [cell["sunlight"] for cell in ours["compute"]] == change
    assert ours["change"].tolist() == ["changed" if minutes else "unchanged" for minutes in change]
    low, high = CHANGE_RANGE
    assert low <= min(change) < max(change) == 0 < high


def test_a_road_is_matched_by_its_shape_not_by_its_place(workspace, back_bay_layers):
    """Twice as tall's roads in another order, its shapes reversed and a shape
    that repeats keeping its roads' order, as two layers read from one source
    repeat it: each road is still matched to itself by its shape, as Compare
    matched it, so the change is what Compare wrote, which the order of the
    roads never moved, and what the roads in their own order give, road for
    road in Baseline's order."""
    from geopandas.testing import assert_geodataframe_equal

    baseline = _handed_on(back_bay_layers, "s-baseline")
    (roads,) = [layer for layer in back_bay_layers if layer["name"] == ROADS]
    shapes = [json.dumps(feature["geometry"], sort_keys=True) for feature in roads["geojson"]["features"]]
    first: dict = {}
    for road, shape in enumerate(shapes):
        first.setdefault(shape, road)
    order = sorted(range(len(shapes)), key=lambda road: (-first[shapes[road]], road))
    assert order != list(range(len(shapes)))
    reordered = _handed_on(back_bay_layers, "s-twice", order=order)
    ours = _the_nodes_change(workspace, baseline, reordered)
    twice = _handed_on(back_bay_layers, "s-twice")
    assert_geodataframe_equal(ours, _compares_difference(baseline, twice))
    in_place = _the_nodes_change(workspace, baseline, twice)
    assert_geodataframe_equal(ours, in_place)
