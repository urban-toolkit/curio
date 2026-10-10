"""Example 25 runs every Spatial Join operation, one flow each (#576).

Each test takes one flow of ``docs/examples/25-spatial-join-operations.json``.
It runs the example's own loader code on the shipped datasets, with stand-ins
for ``curio_data_path`` and ``curio_load_data``. It hands each loader's
GeoDataFrame over as the sandbox does, posts the two inputs on the join's
circles to ``/spatial_join`` with the join's saved settings, and pins what
comes out. ``test_frontend/test_spatial_join_operations_e2e.py`` runs the
same flows in the browser.
"""
from __future__ import annotations

import json
import textwrap
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = REPO_ROOT / "docs" / "examples" / "25-spatial-join-operations.json"

#: The example's joins, one per case.
JOIN_INTERSECTS = "3269d5de-21d6-57e4-b811-e3ee90a27f49"
JOIN_WITHIN = "5ed28c6e-270b-54d5-85e8-3b5973552eab"
JOIN_CONTAINS = "e9c18033-f81d-527c-9624-7bdfb40123ec"
JOIN_TOUCHES = "6e954c1d-9f2d-5e24-9144-22ddefc5d1fd"
JOIN_OVERLAPS = "292f8f9c-9fd8-57a3-8617-cf9aaad9225b"
JOIN_CROSSES = "d604f407-ecab-5495-a9d2-f777300c306d"
JOIN_NEAREST = "0165bd33-0850-5d3e-9b86-fdfb7f359ac5"
JOIN_EDGE_INTERSECTS = "4e8407e1-d56b-59ea-ac6e-c61bdc73e308"
JOIN_EDGE_WITHIN = "ae8ddaa2-f7ff-596f-b229-7789206ad513"


def _dataflow() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))["dataflow"]


def _data_path(dataset_id: str) -> str:
    folder = REPO_ROOT / "datasets" / f"{dataset_id}@1"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    return str(folder / manifest["dataFile"])


def _load_data(dataset_id: str):
    import geopandas as gpd

    return gpd.read_file(_data_path(dataset_id))


@lru_cache(maxsize=None)
def _frame(node_id: str):
    """What a loader or transformation node of the example returns, run on its own code."""
    flow = _dataflow()
    node = next(n for n in flow["nodes"] if n["id"] == node_id)
    sources = [e["source"] for e in flow["edges"] if e["target"] == node_id]
    arg = _frame(sources[0]) if sources else None
    scope = {"curio_data_path": _data_path, "curio_load_data": _load_data}
    exec("def _node(arg):\n" + textwrap.indent(node["content"], "    "), scope)
    return scope["_node"](arg)


def _geojson(gdf) -> dict:
    """What the sandbox hands the browser (``sandbox/util/parsers.py``): the
    GeoJSON, with the frame's CRS as the collection's ``crs`` member."""
    fc = json.loads(gdf.to_json())
    epsg = gdf.crs.to_epsg() if gdf.crs is not None else None
    if epsg is not None:
        fc["crs"] = {"type": "name", "properties": {"name": f"urn:ogc:def:crs:EPSG::{epsg}"}}
    return fc


def _join(client, join_id: str) -> dict:
    flow = _dataflow()
    node = next(n for n in flow["nodes"] if n["id"] == join_id)
    circles = {e["targetHandle"]: e["source"] for e in flow["edges"] if e["target"] == join_id}
    assert sorted(circles) == ["in", "in_1"], circles
    settings = node["metadata"].get("spatialJoin", {})
    response = client.post("/spatial_join", json={
        "left": _geojson(_frame(circles["in"])),
        "right": _geojson(_frame(circles["in_1"])),
        **settings,
    })
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _counts(body: dict) -> dict:
    meta = body["metadata"]
    return {key: meta[key] for key in ("predicate", "output", "pairs", "matched_left", "left_rows",
                                        "matched_right", "right_rows")}


def _rows(body: dict, key: str, value) -> list:
    return [f["properties"] for f in body["features"] if f["properties"].get(key) == value]


def test_intersects_pairs_every_green_roof_with_its_neighborhood(client):
    """#576: points on input 0, polygons on input 1, the default operation."""
    body = _join(client, JOIN_INTERSECTS)
    assert _counts(body) == {"predicate": "intersects", "output": "pairs", "pairs": 359,
                             "matched_left": 359, "left_rows": 359, "matched_right": 69, "right_rows": 98}
    assert len(_rows(body, "pri_neigh", "Loop")) == 30


def test_within_counts_the_sidewalk_labels_in_each_neighborhood(client):
    """#576: the counts output, input 1's rows each with point_count."""
    body = _join(client, JOIN_WITHIN)
    assert _counts(body) == {"predicate": "within", "output": "counts", "pairs": 235,
                             "matched_left": 235, "left_rows": 400, "matched_right": 61, "right_rows": 98}
    assert len(body["features"]) == 98
    assert _rows(body, "pri_neigh", "Austin")[0]["point_count"] == 17


def test_contains_takes_the_polygons_on_input_0(client):
    """#576: a polygon on input 0 joins; it was an HTTP 500 on the points side."""
    body = _join(client, JOIN_CONTAINS)
    assert _counts(body) == {"predicate": "contains", "output": "pairs", "pairs": 235,
                             "matched_left": 61, "left_rows": 98, "matched_right": 235, "right_rows": 400}
    austin = _rows(body, "pri_neigh", "Austin")
    assert len(austin) == 17 and all(row["label_type"] for row in austin)
    assert {f["geometry"]["type"] for f in body["features"]} <= {"Polygon", "MultiPolygon"}


def test_touches_pairs_each_neighborhood_with_the_ones_it_borders(client):
    """#576: one loader on both circles; the second copy's columns come in as _right."""
    body = _join(client, JOIN_TOUCHES)
    assert _counts(body) == {"predicate": "touches", "output": "pairs", "pairs": 484,
                             "matched_left": 98, "left_rows": 98, "matched_right": 98, "right_rows": 98}
    neighbors = sorted(row["pri_neigh_right"] for row in _rows(body, "pri_neigh", "Lincoln Park"))
    assert neighbors == ["Bucktown", "Gold Coast", "Lake View", "North Center", "Old Town",
                         "River North", "Sheffield & DePaul", "West Town"]
    # A neighborhood never touches itself: their insides meet.
    assert all(row["pri_neigh"] != row["pri_neigh_right"] for row in (f["properties"] for f in body["features"]))


def test_overlaps_pairs_each_neighborhood_with_the_zip_codes_it_straddles(client):
    """#576: polygons with polygons; shape_area clashes and comes in as shape_area_right."""
    body = _join(client, JOIN_OVERLAPS)
    assert _counts(body) == {"predicate": "overlaps", "output": "pairs", "pairs": 311,
                             "matched_left": 94, "left_rows": 98, "matched_right": 61, "right_rows": 61}
    lincoln_park = _rows(body, "pri_neigh", "Lincoln Park")
    assert sorted(row["zip"] for row in lincoln_park) == ["60610", "60614", "60618", "60642", "60647", "60657"]
    assert "shape_area_right" in lincoln_park[0]


def test_crosses_pairs_each_zip_border_with_the_neighborhoods_it_runs_through(client):
    """#576: lines on input 0, polygons on input 1."""
    body = _join(client, JOIN_CROSSES)
    assert _counts(body) == {"predicate": "crosses", "output": "pairs", "pairs": 311,
                             "matched_left": 61, "left_rows": 61, "matched_right": 94, "right_rows": 98}
    assert {f["geometry"]["type"] for f in body["features"]} <= {"LineString", "MultiLineString"}
    assert len(_rows(body, "pri_neigh", "Lincoln Park")) == 6


def test_nearest_pairs_each_green_roof_with_the_closest_label_in_meters(client):
    """#576: every roof gets its nearest label, and the distance between them."""
    body = _join(client, JOIN_NEAREST)
    assert _counts(body) == {"predicate": "nearest", "output": "pairs", "pairs": 359,
                             "matched_left": 359, "left_rows": 359, "matched_right": 126, "right_rows": 400}
    distances = sorted(f["properties"]["distance"] for f in body["features"])
    assert distances[0] == pytest.approx(39.89, abs=0.5)
    assert distances[-1] == pytest.approx(6683.67, abs=5)


def _point_pairs(body: dict) -> list:
    return sorted((f["properties"]["point"], f["properties"]["square"]) for f in body["features"])


def test_a_point_on_a_shared_edge_intersects_both_squares(client):
    """#576: the boundary rule, as shapely has it: on the edge is intersecting."""
    body = _join(client, JOIN_EDGE_INTERSECTS)
    assert _point_pairs(body) == [("inside", "west"), ("on the edge", "east"), ("on the edge", "west")]


def test_a_point_on_a_shared_edge_is_within_neither_square(client):
    """#576: and on the edge is not within."""
    body = _join(client, JOIN_EDGE_WITHIN)
    assert _point_pairs(body) == [("inside", "west")]
