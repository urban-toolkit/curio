"""A table an Autark node hands on from a workspace (autk-grammar 5.0.0's
``workspace``) keeps it on the Python side.

A node that reads such a table finds the workspace in the frame's ``metadata``,
beside its name and layer type; a frame that carries it hands it on; and the
Map Editor's step hands every layer on in its workspace, edited or not, so the
Autark node after it loads each table there. Every test imports what it tests,
so a checkout without it fails test by test.
"""
from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString

CRS = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3395"}}


def _lines(*xs: float) -> dict:
    return {"type": "FeatureCollection", "crs": CRS, "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[x, 0], [x + 1, 1]]},
         "properties": {"line_id": i}}
        for i, x in enumerate(xs)
    ]}


def test_a_layer_an_autark_node_hands_on_keeps_its_workspace_in_its_metadata():
    from utk_curio.sandbox.util.stored_inputs import read_stored

    wrapper = {"dataType": "outputs", "data": [
        {"dataType": "geodataframe", "data": _lines(0), "layerName": "lines", "layerType": "polylines"},
        {"dataType": "geodataframe", "data": _lines(5, 6), "layerName": "lines", "layerType": "polylines",
         "workspace": "east"},
    ]}
    default, east = read_stored(wrapper)
    assert default.__dict__["metadata"] == {"name": "lines", "layerType": "polylines"}
    assert east.__dict__["metadata"] == {"name": "lines", "layerType": "polylines", "workspace": "east"}
    assert len(east) == 2
    one = read_stored(wrapper["data"][1])
    assert one.__dict__["metadata"]["workspace"] == "east"


def test_a_layer_chip_reads_a_layer_with_its_workspace():
    from utk_curio.sandbox.util.input_layers import curio_layer

    records = [{"name": "roads", "type": "roads", "geojson": _lines(0), "workspace": "east"}]
    frame = curio_layer(records, "roads", 0)
    assert frame.__dict__["metadata"] == {"name": "roads", "layerType": "roads", "workspace": "east"}


def test_a_frame_hands_on_the_workspace_its_metadata_names():
    from utk_curio.sandbox.util.parsers import parseOutput

    frame = gpd.GeoDataFrame({"line_id": [0]}, geometry=[LineString([(0, 0), (1, 1)])], crs="EPSG:3395")
    frame.__dict__["metadata"] = {"name": "lines", "layerType": "polylines", "workspace": "east"}
    out = parseOutput(frame)
    assert out["data"]["metadata"] == {"name": "lines", "layerType": "polylines", "workspace": "east"}


def test_the_map_editor_hands_each_layer_on_in_its_workspace():
    from utk_curio.sandbox.util.feature_edits import edit_features

    records = [
        {"name": "lines", "type": "polylines", "geojson": _lines(0)},
        {"name": "east_lines", "type": "polylines", "geojson": _lines(5, 6), "workspace": "east"},
    ]
    edited = edit_features(records, [{"op": "remove", "ids": [0]}], key="line_id", layer="east_lines")
    default, east = edited["data"]
    assert "workspace" not in default
    assert east["workspace"] == "east"
    assert [feature["properties"]["line_id"] for feature in east["data"]["features"]] == [1]
    # A layer it does not edit keeps its workspace too.
    other = edit_features(records, [{"op": "remove", "ids": [0]}], key="line_id", layer="lines")
    assert other["data"][1]["workspace"] == "east"
    assert "workspace" not in other["data"][0]
