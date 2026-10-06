"""The Edit Features node's step (#662), ``curio_edit_features``.

The node keeps a list of edits made on features picked on its map, and its
code hands the list to this step with the node's input, the column that
identifies a feature and the layer to edit. The step applies the edits by that
column, never by a feature's place, reports ids no feature has, and hands on
a new value: an Autark node's layers as the envelope ``persistLayersToBackend``
stores, with every feature, property and layer it did not edit as it came, or
a table as a table.

Every test imports the module itself, so a checkout without it fails test by
test rather than at collection.
"""
from __future__ import annotations

import json
import os
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

REPO_ROOT = Path(__file__).resolve().parents[3]
CASES = REPO_ROOT / "utk_curio/frontend/urban-workflows/src/utils/editFeatures/editFeaturesCode.cases.json"
CRS = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3395"}}


def _edit(value, edits, **kwargs):
    from utk_curio.sandbox.util.feature_edits import edit_features

    return edit_features(value, edits, **kwargs)


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


REMOVE_1 = [{"op": "remove", "ids": [1]}]
BUILDINGS = {"key": "building_id", "layer": "table_osm_buildings"}


class TestApplyById:
    def test_a_building_is_removed_with_every_part_and_the_rest_is_handed_on_as_it_came(self):
        records = _records()
        out = _edit(records, REMOVE_1, **BUILDINGS)
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
        out = _edit(wrapper, REMOVE_1, **BUILDINGS)
        assert [item["layerName"] for item in out["data"]] == ["table_osm_roads", "table_osm_buildings"]
        assert out["data"][0] is wrapper["data"][0]
        assert _ids(out["data"][1]["data"]) == [2, 3]
        one = _edit(wrapper["data"][1], [{"op": "remove", "ids": [2]}], key="building_id")
        assert one["dataType"] == "geodataframe" and one["layerName"] == "table_osm_buildings"
        assert _ids(one["data"]) == [1, 1, 3]

    def test_ids_match_by_value_whatever_their_number_type(self):
        out = _edit(_records(), [{"op": "remove", "ids": [1.0, 3]}], **BUILDINGS)
        assert _ids(out["data"][1]["data"]) == [2]

    def test_a_feature_is_never_matched_by_its_place(self):
        # Ids 0 and 1 are places too; only the feature whose building_id is 1 goes.
        out = _edit(_records(), [{"op": "remove", "ids": [0]}], **BUILDINGS)
        assert _ids(out["data"][1]["data"]) == [1, 1, 2, 3]

    def test_no_edits_hand_the_input_on_as_it_came(self, capsys):
        records = _records()
        assert _edit(records, []) is records
        assert "no edits yet" in capsys.readouterr().out


class TestUnknownIds:
    def test_an_id_no_feature_has_is_reported_and_the_run_goes_on(self, capsys):
        out = _edit(_records(), [{"op": "remove", "ids": [1, 999, "w7"]}], **BUILDINGS)
        assert _ids(out["data"][1]["data"]) == [2, 3]
        printed = capsys.readouterr().out
        assert "layer table_osm_buildings has no feature with building_id 999, w7; the remove skips them." in printed
        assert "features matched on building_id: 2 removed." in printed

    def test_a_table_reports_them_too(self, capsys):
        frame = gpd.GeoDataFrame({"osm_id": [10, 11]}, geometry=[Point(0, 0), Point(1, 1)], crs=3395)
        out = _edit(frame, [{"op": "set", "ids": [12], "column": "h", "value": 1}], key="osm_id")
        assert "the input has no feature with osm_id 12; the set skips it." in capsys.readouterr().out
        assert out["osm_id"].tolist() == [10, 11]


class TestSetValue:
    def test_a_column_is_set_on_the_matched_features_only(self):
        records = _records()
        out = _edit(records, [{"op": "set", "ids": [1], "column": "height", "value": 0}], **BUILDINGS)
        features = out["data"][1]["data"]["features"]
        assert [f["properties"].get("height") for f in features] == [0, 0, 30.0, None]
        assert features[2] is records[1]["geojson"]["features"][2]
        # The input's own properties are left as they were.
        assert records[1]["geojson"]["features"][0]["properties"]["height"] == 10.0

    def test_a_new_column_and_a_value_of_another_type_are_written(self):
        out = _edit(_records(), [{"op": "set", "ids": [3], "column": "note", "value": "kept"}], **BUILDINGS)
        assert [f["properties"].get("note") for f in out["data"][1]["data"]["features"]] == [None, None, None, "kept"]
        frame = gpd.GeoDataFrame({"osm_id": [10, 11], "h": [1.0, 2.0]}, geometry=[Point(0, 0), Point(1, 1)], crs=3395)
        table = _edit(frame, [
            {"op": "set", "ids": [11], "column": "h", "value": "tall"},
            {"op": "set", "ids": [10], "column": "note", "value": "x"},
        ], key="osm_id")
        assert table["h"].tolist() == [1.0, "tall"]
        assert table["note"].tolist() == ["x", None]
        assert table.crs == frame.crs

    def test_a_removed_feature_takes_no_value(self):
        out = _edit(_records(), [{"op": "remove", "ids": [2]}, {"op": "set", "ids": [2], "column": "height", "value": 1}], **BUILDINGS)
        assert _ids(out["data"][1]["data"]) == [1, 1, 3]

    def test_the_geometry_of_a_table_cannot_be_set(self):
        frame = gpd.GeoDataFrame({"osm_id": [10]}, geometry=[Point(0, 0)], crs=3395)
        with pytest.raises(ValueError, match=r"geometry is the geometry of the input; a value cannot be set on it"):
            _edit(frame, [{"op": "set", "ids": [10], "column": "geometry", "value": 1}], key="osm_id")


class TestRestore:
    def test_a_removed_and_changed_feature_comes_back_as_the_input_has_it(self, capsys):
        records = _records()
        out = _edit(records, [
            {"op": "set", "ids": [2], "column": "height", "value": 99},
            {"op": "remove", "ids": [1, 2]},
            {"op": "restore", "ids": [2]},
        ], **BUILDINGS)
        features = out["data"][1]["data"]["features"]
        assert _ids(out["data"][1]["data"]) == [2, 3]
        assert features[0] is records[1]["geojson"]["features"][2]
        assert "2 removed, 1 restored" in capsys.readouterr().out

    def test_a_table_restores_its_rows_and_values(self):
        frame = gpd.GeoDataFrame({"osm_id": [10, 11, 12], "h": [1.0, 2.0, 3.0]}, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)], crs=3395)
        out = _edit(frame, [
            {"op": "remove", "ids": [11]},
            {"op": "set", "ids": [12], "column": "h", "value": 0.0},
            {"op": "set", "ids": [12], "column": "note", "value": "x"},
            {"op": "restore", "ids": [11, 12]},
        ], key="osm_id")
        assert out["osm_id"].tolist() == [10, 11, 12]
        assert out["h"].tolist() == [1.0, 2.0, 3.0]
        assert out["note"].isna().all()

    def test_edits_apply_in_their_order(self):
        out = _edit(_records(), [{"op": "restore", "ids": [1]}, {"op": "remove", "ids": [1]}], **BUILDINGS)
        assert _ids(out["data"][1]["data"]) == [2, 3]


class TestRefusals:
    def test_several_layers_and_none_named_lists_them(self):
        with pytest.raises(ValueError, match=r"carries 2 layers \(table_osm_roads, table_osm_buildings\)\. Pick the one to edit in the node's Layer menu\."):
            _edit(_records(), REMOVE_1, key="building_id")

    def test_a_layer_the_input_does_not_have_names_the_ones_it_has(self):
        with pytest.raises(ValueError, match=r"has no layer table_osm_water\. Its layers are table_osm_roads, table_osm_buildings\."):
            _edit(_records(), REMOVE_1, key="building_id", layer="table_osm_water")

    def test_a_layer_without_the_key_is_refused(self):
        with pytest.raises(ValueError, match=r"layer table_osm_roads has no column building_id"):
            _edit(_records(), REMOVE_1, key="building_id", layer="table_osm_roads")
        frame = gpd.GeoDataFrame({"name": ["a"]}, geometry=[Point(0, 0)])
        with pytest.raises(ValueError, match=r"the input has no column osm_id\. Its columns are name, geometry\."):
            _edit(frame, [{"op": "remove", "ids": ["a"]}], key="osm_id")

    @pytest.mark.parametrize("key", ["__row_index__", "_vgsid_", "interacted"])
    def test_a_rows_place_in_a_view_is_never_the_key(self, key):
        with pytest.raises(ValueError, match=rf"{key} is a row's place in a view"):
            _edit(_records(), [{"op": "remove", "ids": [0]}], key=key, layer="table_osm_buildings")

    def test_no_key_is_refused_once_there_are_edits(self):
        with pytest.raises(ValueError, match=r"names no column that identifies a feature"):
            _edit(_records(), REMOVE_1, layer="table_osm_buildings")

    @pytest.mark.parametrize("edit", [{"op": "delete", "ids": [1]}, {"op": "remove", "ids": []}, {"op": "set", "ids": [1], "value": 2}, "remove 1"])
    def test_an_edit_the_node_does_not_make_is_refused(self, edit):
        with pytest.raises(ValueError, match=r"Edit Features: edit 0 "):
            _edit(_records(), [edit], **BUILDINGS)

    def test_no_input_says_so(self):
        with pytest.raises(ValueError, match=r"Edit Features has no input"):
            _edit(None, REMOVE_1, **BUILDINGS)


class TestNamedTables:
    def test_tables_that_keep_their_layer_names_are_edited_and_handed_on_as_an_envelope(self):
        roads = gpd.GeoDataFrame({"highway": ["primary"]}, geometry=[Point(0, 2)], crs=3395)
        roads.__dict__["metadata"] = {"name": "table_osm_roads", "layerType": "roads"}
        buildings = gpd.GeoDataFrame({"building_id": [1, 1, 2]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(2, 0, 3, 1)], crs=3395)
        buildings.__dict__["metadata"] = {"name": "table_osm_buildings", "layerType": "buildings"}
        out = _edit([roads, buildings], REMOVE_1, **BUILDINGS)
        assert [(i["dataType"], i["layerName"], i["layerType"]) for i in out["data"]] == [
            ("geodataframe", "table_osm_roads", "roads"), ("geodataframe", "table_osm_buildings", "buildings"),
        ]
        assert _ids(out["data"][1]["data"]) == [2]
        assert out["data"][1]["data"]["crs"]["properties"]["name"] == "urn:ogc:def:crs:EPSG::3395"

    def test_tables_without_names_are_refused_when_there_are_several(self):
        a = gpd.GeoDataFrame({"building_id": [1]}, geometry=[Point(0, 0)])
        with pytest.raises(ValueError, match=r"not all of them have a name"):
            _edit([a, a.copy()], REMOVE_1, key="building_id")
        with pytest.raises(ValueError, match=r"has no layer table_osm_buildings\. Its layers are none with a name\."):
            _edit([a, a.copy()], REMOVE_1, key="building_id", layer="table_osm_buildings")


def test_the_schema_names_the_edits_the_step_makes():
    from utk_curio.sandbox.util.feature_edits import OPS

    schema = json.loads((REPO_ROOT / "docs/schemas/trill.v1.json").read_text(encoding="utf-8"))
    edit = schema["$defs"]["nodeMetadata"]["properties"]["editFeatures"]["properties"]["edits"]["items"]
    assert tuple(edit["properties"]["op"]["enum"]) == OPS


def _code_cases():
    """The cases file's cases; read at collection, so a checkout without it
    fails this test rather than the whole module."""
    try:
        return json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    except FileNotFoundError:
        return [{"name": "editFeaturesCode.cases.json is missing", "code": None, "kept": None}]


@pytest.mark.parametrize("case", _code_cases(), ids=lambda c: c["name"])
def test_the_code_the_node_writes_runs_its_edits(case):
    """Each code ``editFeaturesCode.cases.json`` holds (Jest checks the node
    writes it) runs as a Python node's code does, with the helper in scope."""
    from utk_curio.sandbox.util.feature_edits import edit_features

    assert case["code"] is not None, case["name"]
    namespace = {"curio_edit_features": edit_features}
    exec(f"def userCode(arg):\n{textwrap.indent(case['code'], '    ')}", namespace)
    out = namespace["userCode"](_records())
    buildings = out if isinstance(out, list) else out["data"]
    fc = buildings[1]["geojson"] if isinstance(out, list) else buildings[1]["data"]
    assert _ids(fc) == case["kept"]


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

        art_id = parsers.save_to_duckdb(value, node_id="whatif-data", session_id="s1")
        code = json.loads(CASES.read_text(encoding="utf-8"))["cases"][1]["code"]
        response = self.client.post("/exec", json={
            "code": textwrap.indent(code, "    "),
            "file_path": art_id,
            "nodeType": "curio.builtin/edit-features",
            "dataType": "dict",
            "session_id": "s1",
        })
        self.assertEqual(response.status_code, 200, response.data)
        body = response.get_json()
        self.assertTrue(body["output"]["path"], body)
        return body, parsers.load_from_duckdb(body["output"]["path"], session_id="s1")

    def test_an_autark_data_nodes_layers_are_edited_into_the_envelope_an_autark_node_stores(self):
        body, out = self._run(_records())
        self.assertEqual(body["output"]["dataType"], "dict")
        self.assertEqual([item["layerName"] for item in out["data"]], ["table_osm_roads", "table_osm_buildings"])
        self.assertEqual(_ids(out["data"][1]["data"]), [2])

    def test_an_autark_compute_nodes_envelope_keeps_its_layer_names(self):
        # In process its layers reach the code as tables, named as Curio names
        # a frame; the step hands them on under those names.
        body, out = self._run(_wrapper())
        self.assertEqual(body["output"]["dataType"], "dict")
        self.assertEqual(
            [(item["layerName"], item["layerType"]) for item in out["data"]],
            [("table_osm_roads", "roads"), ("table_osm_buildings", "buildings")],
        )
        self.assertEqual(_ids(out["data"][1]["data"]), [2])
        stdout = "\n".join(body.get("stdout") or [])
        self.assertIn("features matched on building_id: 3 removed.", stdout)


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
