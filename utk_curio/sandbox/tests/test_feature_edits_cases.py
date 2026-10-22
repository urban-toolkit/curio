"""The Map Edits node's edit log as a run applies it (``curio_edit_features``),
on the cases the browser applies too: ``editFeaturesApply.cases.json``, which
Jest runs through the one module the browser applies the log with, which the
map the node feeds draws before Commit edits (``tests/utils/mapEditsApply.test.ts``).
The layer each case expects is the one a run hands on, so this pins it.

And a feature drawn on the map over tables: the new layer it lands in is in
the coordinates the map drew the tables in. A shape redrawn on a layer in
metres, beside one in degrees, is read in its own layer's CRS, which its edit
names.

Every test imports the step itself, so a checkout without it fails test by
test rather than at collection.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CASES = REPO_ROOT / "utk_curio/frontend/urban-workflows/src/utils/editFeatures/editFeaturesApply.cases.json"


def _cases():
    """The cases file's cases, each with its input layer; read at collection,
    so a checkout without it fails this test rather than the whole module."""
    try:
        shared = json.loads(CASES.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [{"name": "editFeaturesApply.cases.json is missing", "input": None}]
    return [{**case, "input": shared["layers"][case["layer"]]} for case in shared["cases"]]


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_a_run_hands_on_the_layer_the_case_expects(case):
    from utk_curio.sandbox.util.feature_edits import edit_features

    assert case["input"] is not None, case["name"]
    layer = copy.deepcopy(case["input"])
    out = edit_features({"dataType": "geodataframe", "data": layer}, copy.deepcopy(case["edits"]), key=case["key"])
    assert out["data"] == case["expected"]
    # The input is never changed.
    assert layer == case["input"]


#: A layer the node makes, and a point drawn into it on the map, in the
#: map's longitude-latitude coordinates (``crs``, as the node writes it).
NEW_LAYERS = [{"name": "cooling_centers", "geometry": "Point", "properties": [{"name": "name", "type": "text"}]}]
DRAWN = {"type": "Point", "coordinates": [-87.631, 41.881]}
ADD = {"op": "add", "layer": "cooling_centers", "id": "c1", "geometry": DRAWN, "values": {"name": "Library"}}


def _names_wgs84(crs) -> bool:
    """Whether a GeoJSON ``crs`` names EPSG:4326, in any of its spellings."""
    text = json.dumps(crs)
    return "4326" in text or "CRS84" in text


@pytest.mark.parametrize("by_input", [False, True], ids=["one table", "a table per circle"])
def test_a_feature_drawn_over_table_inputs_keeps_the_maps_crs(by_input):
    """Tables in EPSG:4326, as a Python node hands them on: the node's map
    draws them in longitude and latitude, and a point drawn into a new layer
    is in them too. The new layer says so, as the tables' layers do, so the
    map it feeds draws the point where it was drawn."""
    import geopandas as gpd
    from shapely.geometry import Point, box
    from utk_curio.sandbox.util.feature_edits import edit_features

    roads = gpd.GeoDataFrame({"osm_id": [7, 8]}, geometry=[Point(-87.632, 41.880), Point(-87.630, 41.880)], crs=4326)
    buildings = gpd.GeoDataFrame({"building_id": [1]}, geometry=[box(-87.634, 41.879, -87.633, 41.880)], crs=4326)
    value = [roads, buildings] if by_input else roads
    out = edit_features(value, [ADD], new_layers=NEW_LAYERS, crs="EPSG:4326", by_input=by_input)

    made = out["data"][-1]
    assert (made["layerName"], made["layerType"]) == ("cooling_centers", "points")
    assert made["data"]["features"] == [{"type": "Feature", "geometry": DRAWN, "properties": {"name": "Library", "id": "c1"}}]
    # The tables' layers name their CRS; the new layer names the same one.
    assert all(_names_wgs84(item["data"].get("crs")) for item in out["data"][:-1])
    assert _names_wgs84(made["data"].get("crs")), made["data"].get("crs")


#: A road redrawn on the map, in its own layer's Web Mercator metres.
REDRAWN = {"type": "LineString", "coordinates": [[-9755300.0, 5143300.0], [-9755200.0, 5143350.0]]}


def _flat(coordinates):
    return [value for point in coordinates for value in point]


def test_a_road_redrawn_in_metres_beside_a_layer_in_degrees_keeps_its_coordinates():
    """The node's first drawn shape was on trees in degrees, so the node names
    EPSG:4326, and a road in metres is redrawn after it. Each drawn edit names
    the CRS of its own layer, so the road is read in metres, as it was drawn,
    and not as degrees, which handed it on at infinity."""
    import geopandas as gpd
    from shapely.geometry import LineString, Point
    from utk_curio.sandbox.util.feature_edits import edit_features

    trees = gpd.GeoDataFrame({"osm_id": [1]}, geometry=[Point(-87.631, 41.881)], crs=4326)
    roads = gpd.GeoDataFrame(
        {"osm_id": [7, 8]},
        geometry=[
            LineString([(-9755400.0, 5143200.0), (-9755300.0, 5143200.0)]),
            LineString([(-9755300.0, 5143250.0), (-9755200.0, 5143250.0)]),
        ],
        crs=3857,
    )
    redraw = {"op": "geometry", "layer": "input_1", "ids": [8], "geometry": REDRAWN, "crs": "EPSG:3857"}
    out = edit_features(
        [trees, roads], [redraw], key="osm_id", layer="input_0", keys={"input_1": "osm_id"},
        crs="EPSG:4326", by_input=True,
    )

    features = out["data"][1]["data"]["features"]
    road = next(f for f in features if f["properties"]["osm_id"] == 8)
    assert _flat(road["geometry"]["coordinates"]) == pytest.approx(_flat(REDRAWN["coordinates"]))
    # The other road, and the trees in degrees, are as they came.
    other = next(f for f in features if f["properties"]["osm_id"] == 7)
    assert _flat(other["geometry"]["coordinates"]) == pytest.approx([-9755400.0, 5143200.0, -9755300.0, 5143200.0])
    assert out["data"][0]["data"]["features"][0]["geometry"]["coordinates"] == pytest.approx([-87.631, 41.881])
