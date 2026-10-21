"""The Map Edits node's step (its type is still ``curio.builtin/edit-features``),
``curio_map_edits``.

The node's code is one call of this step with the node's input, the column
that identifies a feature, the layer to edit, the ids to remove and the values
to change. The step applies them by that column, never by a feature's place,
reports ids no feature has, and hands on a new value: an Autark node's layers
as the envelope ``persistLayersToBackend`` stores, with every feature,
property and layer it did not edit as it came, or a table as a table.

``mapEditsCode.cases.json`` and ``mapEditsApply.cases.json`` are shared with
Jest (``src/tests/utils/mapEdits.test.ts``): Python reads the code the node
writes as the edits the node reads from it, and the step leaves the features
the node's map draws.

Every test imports the module itself, so a checkout without it fails test by
test rather than at collection.
"""
from __future__ import annotations

import ast
import copy
import json
import os
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

REPO_ROOT = Path(__file__).resolve().parents[3]
CASES_DIR = REPO_ROOT / "utk_curio/frontend/urban-workflows/src/utils/mapEdits"
#: The code the node writes and reads back (``utils/mapEdits/mapEdits.ts``).
CODE_CASES = CASES_DIR / "mapEditsCode.cases.json"
#: Edits applied to a layer's features, as the node's map draws them.
APPLY_CASES = CASES_DIR / "mapEditsApply.cases.json"
CRS = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3395"}}


def _edit(value, **kwargs):
    from utk_curio.sandbox.util.map_edits import map_edits

    return map_edits(value, **kwargs)


def _part(building_id, height, x, **extra):
    """One part of an Autark building: its own footprint, its building's id."""
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]]},
        "properties": {"building_id": building_id, "height": height, **extra},
    }


def _buildings():
    """Building 1 in two parts, building 2 in one, building 3 in one; a part
    with no height keeps the key absent, as Autark writes it."""
    features = [_part(1, 10.0, 0), _part(1, 12.0, 1), _part(2, 30.0, 2, name="Tower"), _part(3, 5.0, 3)]
    del features[3]["properties"]["height"]
    return {"type": "FeatureCollection", "features": features, "crs": CRS}


def _roads():
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 2], [4, 2]]}, "properties": {"highway": "primary"}}],
        "crs": CRS,
    }


def _records():
    """What an Autark data node's data section hands on: one record per layer."""
    return [
        {"name": "table_osm_roads", "type": "roads", "geojson": _roads()},
        {"name": "table_osm_buildings", "type": "buildings", "geojson": _buildings()},
    ]


def _wrapper():
    """What an Autark compute node hands on (``persistLayersToBackend``)."""
    return {
        "dataType": "outputs",
        "data": [
            {"dataType": "geodataframe", "data": _roads(), "layerName": "table_osm_roads", "layerType": "roads"},
            {"dataType": "geodataframe", "data": _buildings(), "layerName": "table_osm_buildings", "layerType": "buildings"},
        ],
    }


def _ids(fc):
    return [feature["properties"]["building_id"] for feature in fc["features"]]


def _kind(value) -> str:
    return "text" if isinstance(value, str) else "truth" if isinstance(value, bool) else "number"


def _same(a, b) -> bool:
    """Whether two ids are one, as the step compares them: 12 and 12.0 are, the
    text 12 and the number 12 are not."""
    return _kind(a) == _kind(b) and a == b


BUILDINGS = {"key": "building_id", "layer": "table_osm_buildings"}


class TestRemoveById:
    def test_a_building_is_removed_with_every_part_and_the_rest_is_handed_on_as_it_came(self):
        records = _records()
        out = _edit(records, remove=[1], **BUILDINGS)
        assert out["dataType"] == "outputs"
        roads, buildings = out["data"]
        assert (roads["layerName"], roads["layerType"]) == ("table_osm_roads", "roads")
        assert (buildings["layerName"], buildings["layerType"]) == ("table_osm_buildings", "buildings")
        assert _ids(buildings["data"]) == [2, 3]
        # Untouched: the other layer, the kept features, their properties and
        # the absent key, and the coordinate system Autark names.
        assert roads["data"] is records[0]["geojson"]
        kept = records[1]["geojson"]["features"]
        assert buildings["data"]["features"] == [kept[2], kept[3]]
        assert buildings["data"]["features"][0] is kept[2]
        assert "height" not in buildings["data"]["features"][1]["properties"]
        assert buildings["data"]["crs"] == CRS
        # The input is never changed.
        assert _ids(records[1]["geojson"]) == [1, 1, 2, 3]

    def test_an_autark_nodes_envelope_comes_back_as_the_same_envelope(self):
        wrapper = _wrapper()
        out = _edit(wrapper, remove=[1], **BUILDINGS)
        assert [item["layerName"] for item in out["data"]] == ["table_osm_roads", "table_osm_buildings"]
        assert out["data"][0] is wrapper["data"][0]
        assert _ids(out["data"][1]["data"]) == [2, 3]
        one = _edit(wrapper["data"][1], remove=[2], key="building_id")
        assert one["dataType"] == "geodataframe" and one["layerName"] == "table_osm_buildings"
        assert _ids(one["data"]) == [1, 1, 3]

    def test_ids_match_by_value_whatever_their_number_type_and_a_text_is_another_id(self):
        out = _edit(_records(), remove=[1.0, 3], **BUILDINGS)
        assert _ids(out["data"][1]["data"]) == [2]
        out = _edit(_records(), remove=["1"], **BUILDINGS)
        assert _ids(out["data"][1]["data"]) == [1, 1, 2, 3]

    def test_a_feature_is_never_matched_by_its_place(self):
        # Ids 0 and 1 are places too; only the features whose building_id is 1 go.
        out = _edit(_records(), remove=[0, 1], **BUILDINGS)
        assert _ids(out["data"][1]["data"]) == [2, 3]

    def test_no_edits_hand_the_input_on_as_it_came(self, capsys):
        records = _records()
        assert _edit(records) is records
        assert _edit(records, key="building_id", remove=[], change={}) is records
        assert _edit(records, change={1: {}}, **BUILDINGS) is records
        assert "no edits yet" in capsys.readouterr().out
        # Neither a key nor a layer is needed before there is an edit.
        frame = gpd.GeoDataFrame({"name": ["a"]}, geometry=[Point(0, 0)])
        assert _edit(frame, remove=None, change=None) is frame


class TestChangeById:
    def test_a_change_is_written_into_every_part_of_its_building(self):
        records = _records()
        out = _edit(records, change={1: {"height": 0}}, **BUILDINGS)
        features = out["data"][1]["data"]["features"]
        assert [f["properties"].get("height") for f in features] == [0, 0, 30.0, None]
        assert features[2] is records[1]["geojson"]["features"][2]
        # The input's own properties are left as they were.
        assert records[1]["geojson"]["features"][0]["properties"]["height"] == 10.0

    def test_none_is_written_and_a_new_property_is_made(self):
        out = _edit(_records(), change={2: {"name": None, "note": "kept"}}, **BUILDINGS)
        properties = out["data"][1]["data"]["features"][2]["properties"]
        assert properties == {"building_id": 2, "height": 30.0, "name": None, "note": "kept"}

    def test_a_removed_feature_takes_no_change(self):
        out = _edit(_records(), remove=[2], change={2: {"height": 1}}, **BUILDINGS)
        assert _ids(out["data"][1]["data"]) == [1, 1, 3]

    def test_a_text_id_and_a_number_id_are_edited_apart(self):
        fc = {"type": "FeatureCollection", "features": [_part(7, 1.0, 0), _part("7", 2.0, 1)]}
        out = _edit({"dataType": "geodataframe", "data": fc}, key="building_id", remove=[7], change={"7": {"name": "text"}})
        assert [f["properties"] for f in out["data"]["features"]] == [{"building_id": "7", "height": 2.0, "name": "text"}]


class TestUnknownIds:
    def test_an_id_no_feature_has_is_reported_and_the_run_goes_on(self, capsys):
        out = _edit(_records(), remove=[1, 999, "w7"], change={41: {"height": 1}}, **BUILDINGS)
        assert _ids(out["data"][1]["data"]) == [2, 3]
        printed = capsys.readouterr().out
        assert "Map Edits: layer table_osm_buildings has no feature with building_id 999, w7 to remove; the run goes on." in printed
        assert "Map Edits: layer table_osm_buildings has no feature with building_id 41 to change; the run goes on." in printed
        assert "features matched on building_id: 2 removed." in printed

    def test_an_id_both_removed_and_changed_is_not_reported(self, capsys):
        _edit(_records(), remove=[2], change={2: {"height": 1}}, **BUILDINGS)
        assert "has no feature" not in capsys.readouterr().out

    def test_a_table_reports_them_too(self, capsys):
        frame = gpd.GeoDataFrame({"osm_id": [10, 11]}, geometry=[Point(0, 0), Point(1, 1)], crs=3395)
        out = _edit(frame, key="osm_id", change={12: {"h": 1}})
        assert "the input has no feature with osm_id 12 to change; the run goes on." in capsys.readouterr().out
        assert out["osm_id"].tolist() == [10, 11]


class TestTables:
    """A table (a DataFrame or a GeoDataFrame) is edited by its rows' key and
    keeps its columns' types where the values allow it."""

    def _frame(self):
        frame = gpd.GeoDataFrame(
            {"osm_id": [10, 11, 12], "height": [100.0, 40.0, 70.0], "kind": ["tower", "house", "tower"]},
            geometry=[Point(0, 0), Point(1, 1), Point(2, 2)],
            crs=3395,
        )
        frame.__dict__["metadata"] = {"name": "table_osm_buildings", "layerType": "buildings"}
        return frame

    def test_a_table_is_edited_and_keeps_its_metadata_and_crs(self, capsys):
        frame = self._frame()
        table = _edit(frame, key="osm_id", remove=[11], change={12: {"kind": "park"}})
        assert isinstance(table, gpd.GeoDataFrame)
        assert table["osm_id"].tolist() == [10, 12]
        assert table["kind"].tolist() == ["tower", "park"]
        assert table.crs == frame.crs
        assert table.metadata == {"name": "table_osm_buildings", "layerType": "buildings"}
        # The input is never changed.
        assert frame["osm_id"].tolist() == [10, 11, 12]
        assert frame["kind"].tolist() == ["tower", "house", "tower"]
        assert "layer table_osm_buildings, features matched on osm_id: 1 removed, 1 changed." in capsys.readouterr().out

    def test_a_column_of_floats_stays_one(self):
        table = _edit(self._frame(), key="osm_id", change={10: {"height": 60}})
        assert table["height"].tolist() == [60.0, 40.0, 70.0]
        assert str(table["height"].dtype).startswith("float")

    def test_none_is_written_as_a_missing_value(self):
        table = _edit(self._frame(), key="osm_id", change={11: {"height": None}})
        assert table["height"].isna().tolist() == [False, True, False]
        assert str(table["height"].dtype).startswith("float")

    def test_a_new_column_is_made_and_a_value_of_another_type_is_written(self):
        table = _edit(self._frame(), key="osm_id", change={11: {"note": "x", "height": "tall"}})
        assert table["note"].isna().tolist() == [True, False, True]
        assert table["note"].tolist()[1] == "x"
        assert table["height"].tolist() == [100.0, "tall", 70.0]

    def test_numbers_match_by_value_and_texts_as_they_are(self, capsys):
        frame = pd.DataFrame({"id": [1, 2, 3], "v": ["a", "b", "c"]})
        table = _edit(frame, key="id", remove=[2.0], change={"3": {"v": "x"}, 1: {"v": "y"}})
        assert table["id"].tolist() == [1, 3]
        assert table["v"].tolist() == ["y", "c"]
        assert "the input has no feature with id 3 to change; the run goes on." in capsys.readouterr().out

    def test_the_geometry_cannot_be_written(self):
        frame = gpd.GeoDataFrame({"osm_id": [10]}, geometry=[Point(0, 0)], crs=3395)
        with pytest.raises(ValueError, match=r"Map Edits: geometry is the geometry of the input; a value cannot be set on it"):
            _edit(frame, key="osm_id", change={10: {"geometry": None}})
        # Nor in GeoJSON, where it would replace the geometry once the layer is a table.
        with pytest.raises(ValueError, match=r"geometry is the geometry of layer table_osm_buildings"):
            _edit(_records(), change={1: {"geometry": None}}, **BUILDINGS)


class TestRefusals:
    def test_several_layers_and_none_named_lists_them(self):
        with pytest.raises(ValueError, match=r"carries 2 layers \(table_osm_roads, table_osm_buildings\)\. Pick the one to edit in the node's Layer menu\."):
            _edit(_records(), remove=[1], key="building_id")

    def test_a_layer_the_input_does_not_have_names_the_ones_it_has(self):
        with pytest.raises(ValueError, match=r"has no layer table_osm_water\. Its layers are table_osm_roads, table_osm_buildings\."):
            _edit(_records(), remove=[1], key="building_id", layer="table_osm_water")

    def test_a_layer_without_the_key_is_refused(self):
        with pytest.raises(ValueError, match=r"layer table_osm_roads has no column building_id"):
            _edit(_records(), remove=[1], key="building_id", layer="table_osm_roads")
        frame = gpd.GeoDataFrame({"name": ["a"]}, geometry=[Point(0, 0)])
        with pytest.raises(ValueError, match=r"the input has no column osm_id\. Its columns are name, geometry\."):
            _edit(frame, remove=["a"], key="osm_id")

    @pytest.mark.parametrize("key", ["__row_index__", "_vgsid_", "interacted"])
    def test_a_rows_place_in_a_view_is_never_the_key(self, key):
        with pytest.raises(ValueError, match=rf"{key} is a row's place in a view"):
            _edit(_records(), remove=[0], key=key, layer="table_osm_buildings")

    def test_no_key_is_refused_once_there_are_edits(self):
        with pytest.raises(ValueError, match=r"Map Edits names no column that identifies a feature"):
            _edit(_records(), remove=[1], layer="table_osm_buildings")

    def test_the_key_cannot_be_written(self):
        with pytest.raises(ValueError, match=r"change writes building_id on 1, and building_id identifies the features"):
            _edit(_records(), change={1: {"building_id": 5}}, **BUILDINGS)

    def test_no_input_says_so(self):
        with pytest.raises(ValueError, match=r"Map Edits has no input"):
            _edit(None, remove=[1], **BUILDINGS)

    @pytest.mark.parametrize("value, kind", [({"a": 1}, "dict"), (5, "int")])
    def test_an_input_that_is_neither_layers_nor_a_table_is_refused(self, value, kind):
        with pytest.raises(ValueError, match=rf"Map Edits edits a layer or a table, and its input is a {kind}\."):
            _edit(value, remove=[1], key="osm_id")

    @pytest.mark.parametrize("edits, message", [
        ({"remove": 5}, r"remove lists the ids to take out, such as \[8, 10\], and it is a int"),
        ({"remove": "8"}, r"remove lists the ids to take out, such as \[8, 10\], and it is a str"),
        ({"remove": [True]}, r"remove holds True, which is not an id"),
        ({"remove": [None]}, r"remove holds None, which is not an id"),
        ({"remove": [float("nan")]}, r"remove holds nan, which is not an id"),
        ({"change": [1]}, r"change maps each id to the values it writes"),
        ({"change": {1: 5}}, r"change gives 1 5, which is not the values to write"),
        ({"change": {True: {"a": 1}}}, r"change names True, which is not an id"),
        ({"change": {1: {2: 3}}}, r"change writes 2 on 1, which is not a column's name"),
    ])
    def test_edits_that_are_not_ids_and_values_are_refused(self, edits, message):
        with pytest.raises(ValueError, match=message):
            _edit(_records(), **BUILDINGS, **edits)


class TestNamedTables:
    def test_tables_that_keep_their_layer_names_are_edited_and_handed_on_as_an_envelope(self):
        roads = gpd.GeoDataFrame({"highway": ["primary"]}, geometry=[Point(0, 2)], crs=3395)
        roads.__dict__["metadata"] = {"name": "table_osm_roads", "layerType": "roads"}
        buildings = gpd.GeoDataFrame({"building_id": [1, 1, 2]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(2, 0, 3, 1)], crs=3395)
        buildings.__dict__["metadata"] = {"name": "table_osm_buildings", "layerType": "buildings"}
        out = _edit([roads, buildings], remove=[1], **BUILDINGS)
        assert [(i["dataType"], i["layerName"], i["layerType"]) for i in out["data"]] == [
            ("geodataframe", "table_osm_roads", "roads"), ("geodataframe", "table_osm_buildings", "buildings"),
        ]
        assert _ids(out["data"][1]["data"]) == [2]
        assert out["data"][1]["data"]["crs"]["properties"]["name"] == "urn:ogc:def:crs:EPSG::3395"

    def test_tables_without_names_are_refused_when_there_are_several(self):
        a = gpd.GeoDataFrame({"building_id": [1]}, geometry=[Point(0, 0)])
        with pytest.raises(ValueError, match=r"not all of them have a name"):
            _edit([a, a.copy()], remove=[1], key="building_id")
        with pytest.raises(ValueError, match=r"has no layer table_osm_buildings\. Its layers are none with a name\."):
            _edit([a, a.copy()], remove=[1], key="building_id", layer="table_osm_buildings")


def _cases(path, part):
    """One part of a cases file; read at collection, so a checkout without it
    fails these tests rather than the whole module."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))[part]
    except FileNotFoundError:
        return [None]


def _case_id(case):
    return case["name"] if case else "missing"


def _keywords(code):
    """The keywords of the one ``curio_map_edits(input_0, ...)`` call *code*
    returns, as Python reads them."""
    (statement,) = ast.parse(code).body
    assert isinstance(statement, ast.Return), code
    call = statement.value
    assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "curio_map_edits", code
    assert [ast.unparse(arg) for arg in call.args] == ["input_0"], code
    return {keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords}


def _python_reads(keywords):
    """The edits a call's keywords hold; None leaves a keyword unset."""
    edits = {"remove": list(keywords.get("remove") or []), "change": list((keywords.get("change") or {}).items())}
    for name in ("key", "layer"):
        if keywords.get(name):
            edits[name] = keywords[name]
    return edits


def _node_reads(edits):
    """A case's edits, its changes as ``(id, values)`` in their order."""
    out = {"remove": edits["remove"], "change": [(change["id"], change["values"]) for change in edits["change"]]}
    for name in ("key", "layer"):
        if name in edits:
            out[name] = edits[name]
    return out


@pytest.mark.parametrize("case", _cases(CODE_CASES, "cases") + _cases(CODE_CASES, "read"), ids=_case_id)
def test_python_reads_the_code_as_the_edits_the_node_reads(case):
    """Each code the node writes (Jest checks it does) and each other code its
    reader takes holds, as Python reads it, the edits the node reads from it."""
    assert case is not None, "mapEditsCode.cases.json is missing"
    python, node = _python_reads(_keywords(case["code"])), _node_reads(case["edits"])
    assert python == node
    # == takes 1 for 1.0, as the step does, but also for True: the ids' kinds must agree too.
    assert [_kind(i) for i in python["remove"]] == [_kind(i) for i in node["remove"]]
    assert [_kind(i) for i, _values in python["change"]] == [_kind(i) for i, _values in node["change"]]


@pytest.mark.parametrize("case", _cases(CODE_CASES, "cases"), ids=_case_id)
def test_the_code_the_node_writes_runs_its_edits(case, capsys):
    """Each code the node writes runs as a Python node's code does, with the
    step in scope, on two parts for each id it names."""
    from utk_curio.sandbox.util.input_names import call_as_node
    from utk_curio.sandbox.util.map_edits import map_edits

    assert case is not None, "mapEditsCode.cases.json is missing"
    edits = case["edits"]
    key = edits.get("key", "building_id")
    named = [*edits["remove"], *(change["id"] for change in edits["change"])] or [1]
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [x, part]}, "properties": {key: feature_id, "height": 1.0}}
        for x, feature_id in enumerate(named) for part in range(2)
    ]}
    layer = edits.get("layer")
    value = (
        [{"name": "table_osm_roads", "type": "roads", "geojson": _roads()}, {"name": layer, "type": "buildings", "geojson": fc}]
        if layer else {"dataType": "geodataframe", "data": fc}
    )
    out = call_as_node(textwrap.indent(case["code"], "    "), {"curio_map_edits": map_edits}, value, [0])
    if out is value:
        features = fc["features"]
    elif out["dataType"] == "outputs":
        (envelope,) = [item for item in out["data"] if item.get("layerName") == layer]
        features = envelope["data"]["features"]
    else:
        features = out["data"]["features"]
    left = [feature["properties"][key] for feature in features]
    assert not [i for i in left if any(_same(i, gone) for gone in edits["remove"])]
    for change in edits["change"]:
        parts = [f["properties"] for f in features if _same(f["properties"][key], change["id"])]
        assert len(parts) == 2, change
        for properties in parts:
            assert {name: properties.get(name) for name in change["values"]} == change["values"]


@pytest.mark.parametrize("case", _cases(APPLY_CASES, "cases"), ids=_case_id)
def test_the_step_leaves_the_features_the_nodes_map_draws(case):
    """Each case Jest runs through ``applyMapEdits``, which the node's map draws
    from, leaves the same features here."""
    assert case is not None, "mapEditsApply.cases.json is missing"
    fc = {"type": "FeatureCollection", "features": case["features"]}
    before = copy.deepcopy(fc)
    out = _edit(
        {"dataType": "geodataframe", "data": fc},
        key=case["key"],
        remove=case["edits"]["remove"],
        change={change["id"]: change["values"] for change in case["edits"]["change"]},
    )
    assert out["data"]["features"] == case["expected"]
    assert fc == before


#: What a Map Edits node writes for building 1 removed and building 2 raised.
EXEC_CODE = (
    "return curio_map_edits(\n"
    "    input_0,\n"
    '    key="building_id",\n'
    '    layer="table_osm_buildings",\n'
    "    remove=[1],\n"
    '    change={2: {"height": 33}},\n'
    ")\n"
)


class ExecAppliesTheEditsTestCase(unittest.TestCase):
    """``/exec``, as a play or a run sends it: the input is an Autark node's
    stored output, read in process, and the output a new artifact."""

    def setUp(self):
        from utk_curio.sandbox.app import app
        from utk_curio.sandbox.util.db import init_db, release_connection

        self.client = app.test_client()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = mock.patch.dict(os.environ, {
            "CURIO_LAUNCH_CWD": self._tmp.name,
            "CURIO_SHARED_DATA": "./.curio/data/",
            "CURIO_ISOLATION": "off",
        })
        env.start()
        self.addCleanup(env.stop)
        (Path(self._tmp.name) / ".curio" / "data").mkdir(parents=True, exist_ok=True)
        release_connection()
        self.addCleanup(release_connection)
        init_db()

    def _run(self, value):
        from utk_curio.sandbox.util import parsers

        art_id = parsers.save_to_duckdb(value, node_id="map-edits-data", session_id="s1")
        response = self.client.post("/exec", json={
            "code": textwrap.indent(EXEC_CODE, "    "),
            "file_path": art_id,
            "nodeType": "curio.builtin/edit-features",
            "dataType": "dict",
            "session_id": "s1",
        })
        self.assertEqual(response.status_code, 200, response.data)
        body = response.get_json()
        self.assertTrue(body["output"]["path"], body)
        return body, parsers.load_from_duckdb(body["output"]["path"], session_id="s1")

    def _heights(self, fc):
        return {feature["properties"]["building_id"]: feature["properties"].get("height") for feature in fc["features"]}

    def test_an_autark_data_nodes_layers_are_edited_into_the_envelope_an_autark_node_stores(self):
        body, out = self._run(_records())
        self.assertEqual(body["output"]["dataType"], "dict")
        self.assertEqual([item["layerName"] for item in out["data"]], ["table_osm_roads", "table_osm_buildings"])
        self.assertEqual(_ids(out["data"][1]["data"]), [2, 3])
        self.assertEqual(self._heights(out["data"][1]["data"])[2], 33)

    def test_an_autark_compute_nodes_envelope_keeps_its_layer_names(self):
        # In process its layers reach the code as tables, named as Curio names
        # a frame; the step hands them on under those names.
        body, out = self._run(_wrapper())
        self.assertEqual(body["output"]["dataType"], "dict")
        self.assertEqual(
            [(item["layerName"], item["layerType"]) for item in out["data"]],
            [("table_osm_roads", "roads"), ("table_osm_buildings", "buildings")],
        )
        self.assertEqual(_ids(out["data"][1]["data"]), [2, 3])
        self.assertEqual(self._heights(out["data"][1]["data"])[2], 33)
        stdout = "\n".join(body.get("stdout") or [])
        self.assertIn("features matched on building_id: 2 removed, 1 changed.", stdout)


def test_an_autark_layer_reaching_python_keeps_its_name_and_type():
    from utk_curio.sandbox.app.worker import _resolve_outputs_elem

    envelope = {"dataType": "geodataframe", "data": _buildings(), "layerName": "table_osm_buildings", "layerType": "buildings"}
    frame = _resolve_outputs_elem(envelope)
    assert isinstance(frame, gpd.GeoDataFrame)
    assert frame.metadata == {"name": "table_osm_buildings", "layerType": "buildings"}
    # A frame that names itself keeps its own name.
    fc = _buildings()
    fc["metadata"] = {"name": "own"}
    named = _resolve_outputs_elem({"dataType": "geodataframe", "data": fc, "layerName": "table_osm_buildings"})
    assert named.metadata == {"name": "own"}
    # A table without a layer name is left as parseInput reads it.
    plain = _resolve_outputs_elem({"dataType": "geodataframe", "data": _buildings()})
    assert getattr(plain, "metadata", None) is None
