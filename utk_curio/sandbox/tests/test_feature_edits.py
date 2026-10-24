"""The Map Edits node's step (#662; its type is still
``curio.builtin/edit-features``), ``curio_edit_features``.

The node keeps a log of edits made on features picked on the map it feeds or
by a condition, and its code hands the log to this step with the node's
input, the column that identifies a feature and the layer to edit. The step
applies the edits by that column, never by a feature's place, reports ids no
feature has, and hands on a new value: an Autark node's layers as the envelope
``persistLayersToBackend`` stores, with every feature, property and layer it
did not edit as it came, or a table as a table.

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
#: The expressions and edit logs this step shares with the node's table in the
#: browser (``utils/editFeatures/editExpr.ts`` and ``applyEdits.ts``, in Jest).
EXPR_CASES = REPO_ROOT / "utk_curio/frontend/urban-workflows/src/utils/editFeatures/editExpr.cases.json"
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

    def test_the_report_of_ids_no_feature_has_is_the_line_agents_are_held_to(self, capsys):
        """``UNKNOWN_IDS_LINE``, which Solve reads a run's made-up ids by,
        matches each line the step prints for ids no feature has, and no other
        line: an add of a feature the layer has already is not one."""
        from utk_curio.sandbox.util.feature_edits import UNKNOWN_IDS_LINE

        point = {"type": "Point", "coordinates": [0, 0]}
        _edit(_records(), [
            {"op": "remove", "ids": [1, 999, "w7"]},
            {"op": "set", "ids": [998], "column": "height", "value": 3},
            {"op": "add", "id": 2, "geometry": point},
        ], **BUILDINGS)
        printed = [line for line in capsys.readouterr().out.split("\n") if line]
        reported = [line for line in printed if UNKNOWN_IDS_LINE.fullmatch(line)]
        assert reported == [
            "Map Edits: layer table_osm_buildings has no feature with building_id 999, w7; the remove skips them.",
            "Map Edits: layer table_osm_buildings has no feature with building_id 998; the set skips it.",
        ], printed
        assert any("already has a feature with building_id 2" in line for line in printed), printed


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

    @pytest.mark.parametrize("edit", [
        {"op": "delete", "ids": [1]},
        {"op": "remove", "ids": []},
        {"op": "set", "ids": [1], "value": 2},
        "remove 1",
        {"op": "remove", "ids": [1], "where": "height > 1"},
        {"op": "remove", "where": "  "},
        {"op": "offset", "ids": [1], "value": 3},
        {"op": "expr", "ids": [1], "value": "height * 2"},
    ])
    def test_an_edit_the_node_does_not_make_is_refused(self, edit):
        with pytest.raises(ValueError, match=r"Map Edits: edit 0 "):
            _edit(_records(), [edit], **BUILDINGS)

    def test_no_input_says_so(self):
        with pytest.raises(ValueError, match=r"Map Edits has no input"):
            _edit(None, REMOVE_1, **BUILDINGS)

    def test_a_condition_or_an_expression_that_is_not_one_is_refused_before_anything_runs(self):
        with pytest.raises(ValueError, match=r"Map Edits: edit 0: "):
            _edit(_records(), [{"op": "remove", "where": "height >"}], **BUILDINGS)
        with pytest.raises(ValueError, match=r"Map Edits: edit 1: "):
            _edit(_records(), [REMOVE_1[0], {"op": "expr", "ids": [1], "column": "h", "value": "open('x')"}], **BUILDINGS)

    @pytest.mark.parametrize("value", ["x", None, True, float("nan")])
    def test_a_scale_or_an_offset_by_what_is_not_a_number_is_refused(self, value):
        for op in ("scale", "offset"):
            with pytest.raises(ValueError, match=r"Map Edits: edit 0 .*not a number"):
                _edit(_records(), [{"op": op, "ids": [1], "column": "height", "value": value}], **BUILDINGS)

    def test_an_entry_switched_off_is_never_checked_or_applied(self, capsys):
        out = _edit(_records(), [
            {"op": "remove", "where": "height >", "enabled": False},
            {"op": "remove", "ids": [2], "label": "The tower"},
        ], **BUILDINGS)
        assert _ids(out["data"][1]["data"]) == [1, 1, 3]
        assert "1 removed" in capsys.readouterr().out


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


class TestByInput:
    """The node fed by several data nodes, one per circle (``by_input``): it
    names each unnamed layer after its circle, as the Autark map it feeds
    does, and hands every layer on under that name."""

    def _tables(self):
        roads = gpd.GeoDataFrame({"osm_id": [7, 8]}, geometry=[Point(0, 2), Point(1, 2)], crs=3395)
        buildings = gpd.GeoDataFrame({"building_id": [1, 2]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)], crs=3395)
        return roads, buildings

    def test_each_circles_table_is_named_input_k_and_edited_by_that_name(self):
        roads, buildings = self._tables()
        out = _edit([roads, buildings], [{"op": "remove", "layer": "input_1", "ids": [1]}],
                    keys={"input_1": "building_id"}, by_input=True)
        assert [item["layerName"] for item in out["data"]] == ["input_0", "input_1"]
        assert [f["properties"]["osm_id"] for f in out["data"][0]["data"]["features"]] == [7, 8]
        assert [f["properties"]["building_id"] for f in out["data"][1]["data"]["features"]] == [2]

    def test_with_no_edits_every_layer_is_still_handed_on_by_its_name(self, capsys):
        roads, buildings = self._tables()
        out = _edit([roads, buildings], [], by_input=True)
        assert out["dataType"] == "outputs"
        assert [item["layerName"] for item in out["data"]] == ["input_0", "input_1"]
        assert "no edits yet" in capsys.readouterr().out
        # Every edit switched off hands them on the same way.
        out = _edit([roads, buildings], [{"op": "remove", "layer": "input_1", "ids": [1], "enabled": False}],
                    keys={"input_1": "building_id"}, by_input=True)
        assert [item["layerName"] for item in out["data"]] == ["input_0", "input_1"]

    def test_a_layer_with_a_name_keeps_it_and_more_layers_on_one_circle_are_counted(self):
        roads, _ = self._tables()
        unnamed = {"dataType": "outputs", "data": [
            {"dataType": "geodataframe", "data": _buildings()},
            {"dataType": "geodataframe", "data": _roads()},
        ]}
        out = _edit([roads, _wrapper(), unnamed], [], by_input=True)
        assert [item["layerName"] for item in out["data"]] == [
            "input_0", "table_osm_roads", "table_osm_buildings", "input_2", "input_2_1",
        ]

    def test_a_circle_with_nothing_yet_is_left_out_and_none_at_all_says_so(self):
        roads, _ = self._tables()
        out = _edit([None, roads], [], by_input=True)
        assert [item["layerName"] for item in out["data"]] == ["input_1"]
        with pytest.raises(ValueError, match="Map Edits has no input"):
            _edit([None, None], [], by_input=True)


SQUARE = {"type": "Polygon", "coordinates": [[[9, 0], [10, 0], [10, 1], [9, 1], [9, 0]]]}


class TestDrawnOnTheMap:
    """The edits the node's map makes: a feature added, a shape redrawn, a
    column added, and layers the node makes."""

    def test_a_drawn_feature_is_added_with_its_values_and_its_id(self, capsys):
        out = _edit(_records(), [{"op": "add", "id": "new-1", "geometry": SQUARE, "values": {"height": 20.0}}], **BUILDINGS)
        fc = out["data"][1]["data"]
        assert _ids(fc) == [1, 1, 2, 3, "new-1"]
        added = fc["features"][-1]
        assert added["geometry"] == SQUARE and added["properties"] == {"height": 20.0, "building_id": "new-1"}
        assert fc["crs"] == CRS
        assert "1 added" in capsys.readouterr().out

    def test_an_add_with_an_id_the_layer_has_is_skipped(self, capsys):
        out = _edit(_records(), [{"op": "add", "id": 2, "geometry": SQUARE}], **BUILDINGS)
        assert _ids(out["data"][1]["data"]) == [1, 1, 2, 3]
        assert "already has a feature with building_id 2" in capsys.readouterr().out

    def test_an_added_feature_can_be_edited_removed_and_restored_away(self):
        add = {"op": "add", "id": "new-1", "geometry": SQUARE, "values": {"height": 20.0}}
        out = _edit(_records(), [add, {"op": "set", "ids": ["new-1"], "column": "height", "value": 9.0}], **BUILDINGS)
        assert out["data"][1]["data"]["features"][-1]["properties"]["height"] == 9.0
        gone = _edit(_records(), [add, {"op": "restore", "ids": ["new-1"]}], **BUILDINGS)
        assert _ids(gone["data"][1]["data"]) == [1, 1, 2, 3]

    def test_a_shape_redrawn_replaces_the_geometry_of_the_features_it_names(self):
        out = _edit(_records(), [{"op": "geometry", "ids": [2], "geometry": SQUARE}], **BUILDINGS)
        fc = out["data"][1]["data"]
        assert [f["geometry"] for f in fc["features"] if f["properties"]["building_id"] == 2] == [SQUARE]
        back = _edit(_records(), [{"op": "geometry", "ids": [2], "geometry": SQUARE}, {"op": "restore", "ids": [2]}], **BUILDINGS)
        assert back["data"][1]["data"]["features"][2]["geometry"] != SQUARE

    def test_a_column_is_added_to_every_feature_that_holds_no_value_there(self):
        out = _edit(_records(), [{"op": "add_column", "column": "height", "value": 4.0}], **BUILDINGS)
        heights = [f["properties"]["height"] for f in out["data"][1]["data"]["features"]]
        assert heights == [10.0, 12.0, 30.0, 4.0]

    def test_a_new_layer_is_made_and_handed_on_after_the_inputs_with_its_drawn_features(self):
        new = [{"name": "cooling_centers", "geometry": "Point",
                "properties": [{"name": "name", "type": "text", "required": True}]}]
        point = {"type": "Point", "coordinates": [3, 3]}
        out = _edit(_wrapper(), [{"op": "add", "layer": "cooling_centers", "id": "c1", "geometry": point,
                                  "values": {"name": "Library"}}], new_layers=new, **BUILDINGS)
        made = out["data"][-1]
        assert (made["layerName"], made["layerType"]) == ("cooling_centers", "points")
        assert made["data"]["features"] == [{"type": "Feature", "geometry": point, "properties": {"name": "Library", "id": "c1"}}]
        assert made["data"]["crs"] == CRS
        # The input's layers are handed on as they came.
        assert [item["layerName"] for item in out["data"][:2]] == ["table_osm_roads", "table_osm_buildings"]

    def test_a_new_layer_with_no_features_yet_is_handed_on_empty(self, capsys):
        out = _edit(_wrapper(), [], new_layers=[{"name": "sketch", "geometry": "Polygon"}], **BUILDINGS)
        assert out["data"][-1]["layerType"] == "polygons" and out["data"][-1]["data"]["features"] == []
        assert "new layer sketch has no features yet" in capsys.readouterr().out

    def test_a_new_layer_named_like_an_input_layer_is_refused(self):
        with pytest.raises(ValueError, match="already has a layer table_osm_roads"):
            _edit(_wrapper(), [], new_layers=[{"name": "table_osm_roads", "geometry": "Point"}], **BUILDINGS)

    def test_edits_on_several_layers_each_use_their_own_id_column(self):
        roads = _roads()
        roads["features"][0]["properties"]["osm_id"] = 7
        wrapper = _wrapper()
        wrapper["data"][0]["data"] = roads
        edits = [{"op": "remove", "ids": [1]},
                 {"op": "set", "layer": "table_osm_roads", "ids": [7], "column": "highway", "value": "service"}]
        out = _edit(wrapper, edits, keys={"table_osm_roads": "osm_id"}, **BUILDINGS)
        assert out["data"][0]["data"]["features"][0]["properties"]["highway"] == "service"
        assert _ids(out["data"][1]["data"]) == [2, 3]

    def test_a_table_takes_a_drawn_feature_in_its_own_crs(self):
        buildings = gpd.GeoDataFrame({"building_id": [1], "height": [5.0]}, geometry=[box(0, 0, 1, 1)], crs=4326)
        # Drawn on the map in Mercator metres; the table is in degrees.
        metres = {"type": "Point", "coordinates": [111319.49, 0.0]}
        out = _edit(buildings, [
            {"op": "add", "id": 2, "geometry": metres, "values": {"height": 8.0}},
            {"op": "add_column", "column": "kind", "value": "office"},
            {"op": "geometry", "ids": [1], "geometry": metres},
        ], key="building_id", crs="EPSG:3395")
        assert list(out["building_id"]) == [1, 2] and list(out["height"]) == [5.0, 8.0]
        assert list(out["kind"]) == ["office", "office"]
        assert round(out.geometry.iloc[1].x, 4) == 1.0 and round(out.geometry.iloc[0].x, 4) == 1.0

    def test_the_unnamed_tables_a_map_hands_on_are_named_by_their_place(self):
        """An Autark map hands on its inputs as they came: tables with no
        name, which the node's map calls input_0, input_0_1, ..."""
        roads = gpd.GeoDataFrame({"osm_id": [7, 8]}, geometry=[Point(0, 2), Point(1, 2)], crs=3395)
        buildings = gpd.GeoDataFrame({"building_id": [1, 2]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)], crs=3395)
        out = _edit([roads, buildings], [
            {"op": "remove", "ids": [7]},
            {"op": "remove", "layer": "input_0_1", "ids": [2]},
        ], key="osm_id", layer="input_0", keys={"input_0_1": "building_id"})
        first, second = out["data"]
        assert [f["properties"]["osm_id"] for f in first["data"]["features"]] == [8]
        assert [f["properties"]["building_id"] for f in second["data"]["features"]] == [1]
        # One table per input circle is called input_<k>.
        out = _edit([roads, buildings], [{"op": "remove", "layer": "input_1", "ids": [1]}],
                    key="osm_id", layer="input_0", keys={"input_1": "building_id"})
        assert [f["properties"]["building_id"] for f in out["data"][1]["data"]["features"]] == [2]

    @pytest.mark.parametrize("edit", [
        {"op": "add", "id": "x", "geometry": {"type": "Circle"}},
        {"op": "add", "geometry": SQUARE},
        {"op": "geometry", "ids": [1]},
        {"op": "add_column", "value": 1},
    ])
    def test_a_drawn_edit_that_is_not_whole_is_refused(self, edit):
        with pytest.raises(ValueError, match="Map Edits: edit 0"):
            _edit(_records(), [edit], **BUILDINGS)


def test_the_node_names_the_edits_the_step_makes():
    """The node's edits (``EDIT_OPS`` in ``editFeatures.ts``, which Jest pins to
    the cases file's ``ops``) are the step's, in its order."""
    from utk_curio.sandbox.util.feature_edits import OPS

    assert tuple(json.loads(CASES.read_text(encoding="utf-8"))["ops"]) == OPS


def _code_cases(part="cases"):
    """One part of the cases file; read at collection, so a checkout without it
    fails this test rather than the whole module."""
    try:
        return json.loads(CASES.read_text(encoding="utf-8"))[part]
    except FileNotFoundError:
        return [{"name": "editFeaturesCode.cases.json is missing", "code": None, "kept": None}]


@pytest.mark.parametrize("case", _code_cases(), ids=lambda c: c["name"])
def test_the_code_the_node_writes_runs_its_edits(case):
    """Each code ``editFeaturesCode.cases.json`` holds (Jest checks the node
    writes it) runs as a Python node's code does, with the helper in scope: on
    the roads and the buildings as one input, or one circle each."""
    from utk_curio.sandbox.util.feature_edits import edit_features
    from utk_curio.sandbox.util.input_names import call_as_node

    assert case["code"] is not None, case["name"]
    namespace = {"curio_edit_features": edit_features}
    records = _records()
    if case.get("circles", 1) > 1:
        out = call_as_node(textwrap.indent(case["code"], "    "), namespace, [[layer] for layer in records], [0, 1])
    else:
        out = call_as_node(textwrap.indent(case["code"], "    "), namespace, records, [0])
    buildings = out if isinstance(out, list) else out["data"]
    fc = buildings[1]["geojson"] if isinstance(out, list) else buildings[1]["data"]
    assert _ids(fc) == case["kept"]


@pytest.mark.parametrize("case", _code_cases() + _code_cases("read"), ids=lambda c: c["name"])
def test_python_calls_the_step_with_what_the_node_reads(case):
    """Each code the node writes, and each other code its reader takes, run as
    a Python node's code runs, calls the step once, as its signature has it,
    with what the node reads from the code, which the sandbox's reader
    (``feature_edits_code``) reads too: its inputs, one per circle in order,
    its edits and each keyword."""
    import inspect

    from utk_curio.sandbox.util.feature_edits import edit_features
    from utk_curio.sandbox.util.feature_edits_code import read_edit_features_code
    from utk_curio.sandbox.util.input_names import call_as_node

    assert case["code"] is not None, case["name"]
    read = read_edit_features_code(case["code"])
    assert "problem" not in read, read
    calls = []

    def step(value, edits, **keywords):
        calls.append({"value": value, "edits": edits, "keywords": keywords})
        return value

    circles = read["circles"]
    inputs = [f"input-{k}" for k in range(circles)]
    value = inputs if circles > 1 else inputs[0]
    call_as_node(textwrap.indent(case["code"], "    "), {"curio_edit_features": step}, value, list(range(circles)))
    [call] = calls
    keywords = call["keywords"]
    assert set(keywords) <= set(inspect.signature(edit_features).parameters) - {"value", "edits"}, keywords
    assert call["value"] == value
    assert bool(keywords.get("by_input")) == (circles > 1)
    settings = read["settings"] or {}
    assert call["edits"] == settings.get("edits", [])
    assert keywords.get("key") == settings.get("key")
    assert keywords.get("layer") == settings.get("layer")
    assert (keywords.get("keys") or None) == settings.get("keys")
    assert (keywords.get("new_layers") or None) == settings.get("newLayers")
    assert keywords.get("crs") == settings.get("crs")


def _expr_cases(part):
    """One part of ``editExpr.cases.json``; read at collection, so a checkout
    without it fails these tests rather than the whole module."""
    try:
        return json.loads(EXPR_CASES.read_text(encoding="utf-8"))[part]
    except FileNotFoundError:
        return [None]


@pytest.mark.parametrize("case", _expr_cases("expressions"), ids=lambda c: c["expr"] if c else "missing")
def test_an_expression_reads_a_feature_as_the_nodes_table_does(case):
    from utk_curio.sandbox.util import edit_expr

    assert case is not None, "editExpr.cases.json is missing"
    value = edit_expr.evaluate(edit_expr.parse(case["expr"]), case["row"])
    assert value == case["value"], (case["expr"], value)
    # Booleans stay booleans, never 1 or 0, and nothing else is one.
    assert isinstance(value, bool) == isinstance(case["value"], bool), (case["expr"], value)


@pytest.mark.parametrize("text", _expr_cases("refusals"), ids=lambda t: repr(t)[:40])
def test_what_is_not_an_expression_is_refused(text):
    from utk_curio.sandbox.util import edit_expr

    assert text is not None, "editExpr.cases.json is missing"
    with pytest.raises(edit_expr.ExprError):
        edit_expr.parse(text)


def test_an_expression_is_read_by_its_own_parser_never_by_eval():
    import ast

    tree = ast.parse((REPO_ROOT / "utk_curio/sandbox/util/edit_expr.py").read_text(encoding="utf-8"))
    called = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not called & {"eval", "exec", "compile", "__import__"}, called


@pytest.mark.parametrize("case", _expr_cases("edits"), ids=lambda c: c["name"] if c else "missing")
def test_an_edit_log_is_applied_as_the_nodes_table_applies_it(case, capsys):
    assert case is not None, "editExpr.cases.json is missing"
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [i, 0]}, "properties": properties}
        for i, properties in enumerate(case["features"])
    ]}
    out = _edit({"dataType": "geodataframe", "data": fc}, case["edits"], key=case["key"])
    assert [feature["properties"] for feature in out["data"]["features"]] == case["expected"]
    said = capsys.readouterr().out
    words = {"remove": "removed", "set": "changed", "restore": "restored"}
    for op, count in case["counts"].items():
        if count:
            assert f"{count} {words[op]}" in said, said
        else:
            assert f" {words[op]}" not in said, said


class TestTablesTakeTheNewEdits:
    """A table (a DataFrame or a GeoDataFrame) takes conditions, numbers and
    expressions too, and keeps its columns' types."""

    def _frame(self):
        frame = gpd.GeoDataFrame(
            {"osm_id": [10, 11, 12], "height": [100.0, 40.0, 70.0], "levels": [30, 12, 20], "kind": ["tower", "house", "tower"]},
            geometry=[Point(0, 0), Point(1, 1), Point(2, 2)],
            crs=3395,
        )
        frame.__dict__["metadata"] = {"name": "table_osm_buildings", "layerType": "buildings"}
        return frame

    def test_a_scale_where_a_condition_holds_keeps_a_column_of_floats(self, capsys):
        table = _edit(self._frame(), [{"op": "scale", "where": "height > 50", "column": "height", "value": 0.5}], key="osm_id")
        assert table["height"].tolist() == [50.0, 40.0, 35.0]
        assert str(table["height"].dtype).startswith("float")
        assert table.metadata == {"name": "table_osm_buildings", "layerType": "buildings"}
        assert "2 changed" in capsys.readouterr().out

    def test_an_offset_by_a_whole_number_keeps_a_column_of_integers(self):
        table = _edit(self._frame(), [{"op": "offset", "ids": [11], "column": "levels", "value": 3}], key="osm_id")
        assert table["levels"].tolist() == [30, 15, 20]
        assert str(table["levels"].dtype).startswith("int")

    def test_an_expression_writes_a_new_column_from_each_row(self):
        table = _edit(self._frame(), [
            {"op": "expr", "where": "kind == 'tower'", "column": "floor_height", "value": "round(height / levels, 2)"},
        ], key="osm_id")
        assert table["floor_height"].tolist()[0] == 3.33
        assert table["floor_height"].tolist()[2] == 3.5
        assert table["floor_height"].isna().tolist() == [False, True, False]

    def test_a_condition_reads_the_rows_as_the_edits_before_left_them_and_a_restore_reads_the_input(self):
        table = _edit(self._frame(), [
            {"op": "remove", "where": "kind == 'tower'"},
            {"op": "offset", "where": "height > 0", "column": "height", "value": 1},
            {"op": "restore", "where": "levels >= 30"},
        ], key="osm_id")
        # 10 comes back as the input has it; 12 stays removed; 11 was raised.
        assert table["osm_id"].tolist() == [10, 11]
        assert table["height"].tolist() == [100.0, 41.0]

    def test_an_entry_switched_off_is_skipped_on_a_table(self):
        table = _edit(self._frame(), [{"op": "remove", "ids": [10], "enabled": False}], key="osm_id")
        assert table["osm_id"].tolist() == [10, 11, 12]

    def test_a_number_edit_skips_a_row_that_holds_no_number(self):
        frame = gpd.GeoDataFrame({"osm_id": [10, 11], "height": [1.0, None]}, geometry=[Point(0, 0), Point(1, 1)], crs=3395)
        table = _edit(frame, [{"op": "scale", "ids": [10, 11], "column": "height", "value": 2}], key="osm_id")
        assert table["height"].tolist()[0] == 2.0
        assert table["height"].isna().tolist() == [False, True]


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
