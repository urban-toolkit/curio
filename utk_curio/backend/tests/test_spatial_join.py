"""The Spatial Join pairs two inputs by an operation, on geopandas sjoin (#576).

input_0 (the node's top circle) is the left side of the join and input_1 (the
bottom circle) the right, whatever geometry each holds. The output is one row
per matching pair, input_0's row with input_1's columns added, or input_1's
rows with a count. A point on an edge follows shapely's rule for each
operation. Every test goes through ``POST /spatial_join``, as the node does.

The board most tests share, in plain coordinates:

    A = square (0,0)-(2,2)       B = square (1,1)-(3,3), overlaps A
    C = rectangle (2,-1)-(4,0), meets A at the corner (2,0) only
    "inside A" (0.5,0.5)   "on A's edge" (2,0.5)   "in A and B" (1.5,1.5)
    "far" (10,10)          the line y=1 from x=-1 to x=5
"""
from __future__ import annotations

import pytest


def _fc(features, crs=None):
    fc = {"type": "FeatureCollection", "features": features}
    if crs:
        fc["crs"] = {"type": "name", "properties": {"name": crs}}
    return fc


def _feature(geometry, **props):
    return {"type": "Feature", "geometry": geometry, "properties": props}


def _box(x0, y0, x1, y1, **props):
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return _feature({"type": "Polygon", "coordinates": [ring]}, **props)


def _point(x, y, **props):
    return _feature({"type": "Point", "coordinates": [x, y]}, **props)


SQUARES = _fc([
    _box(0, 0, 2, 2, square="A"),
    _box(1, 1, 3, 3, square="B"),
    _box(2, -1, 4, 0, square="C"),
])
POINTS = _fc([
    _point(0.5, 0.5, point="inside A"),
    _point(2, 0.5, point="on A's edge"),
    _point(1.5, 1.5, point="in A and B"),
    _point(10, 10, point="far"),
])
LINE = _fc([_feature({"type": "LineString", "coordinates": [[-1, 1], [5, 1]]}, line="y=1")])


def _join(client, left, right, **settings):
    response = client.post("/spatial_join", json={"left": left, "right": right, **settings})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _pairs(body, left_key, right_key):
    return sorted((f["properties"][left_key], f["properties"][right_key]) for f in body["features"])


@pytest.mark.parametrize("predicate, expected", [
    # A point on an edge intersects the polygon...
    ("intersects", [("in A and B", "A"), ("in A and B", "B"), ("inside A", "A"), ("on A's edge", "A")]),
    # ...is not within it...
    ("within", [("in A and B", "A"), ("in A and B", "B"), ("inside A", "A")]),
    # ...and is the only point that touches it.
    ("touches", [("on A's edge", "A")]),
])
def test_points_on_input_0_pair_by_the_operation_and_its_boundary_rule(client, predicate, expected):
    """#576: intersects, within and touches, a point on an edge included."""
    body = _join(client, POINTS, SQUARES, predicate=predicate)
    assert _pairs(body, "point", "square") == expected
    assert body["metadata"]["predicate"] == predicate


def test_one_row_per_pair_with_input_1s_columns_and_the_counts_in_metadata(client):
    """#576: a point in two polygons is two rows; a point in none is left out."""
    body = _join(client, POINTS, SQUARES)
    rows = [f for f in body["features"] if f["properties"]["point"] == "in A and B"]
    assert sorted(f["properties"]["square"] for f in rows) == ["A", "B"]
    # The geometry of a pair is input_0's.
    assert all(f["geometry"] == {"type": "Point", "coordinates": [1.5, 1.5]} for f in rows)
    assert body["metadata"] == {
        "name": "spatial_join_result", "output": "pairs", "predicate": "intersects",
        "pairs": 4, "matched_left": 3, "matched_right": 2, "left_rows": 4, "right_rows": 3,
    }


def test_a_polygon_on_input_0_joins_instead_of_failing(client):
    """#576: a polygon on the points side was an HTTP 500. Inputs follow the
    circles now, so polygons on input_0 contain the points on input_1."""
    body = _join(client, SQUARES, POINTS, predicate="contains")
    # The point on A's edge is not contained: the polygon does not hold its boundary.
    assert _pairs(body, "square", "point") == [("A", "in A and B"), ("A", "inside A"), ("B", "in A and B")]
    assert body["features"][0]["geometry"]["type"] == "Polygon"
    intersects = _join(client, SQUARES, POINTS)
    assert _pairs(intersects, "square", "point") == [
        ("A", "in A and B"), ("A", "inside A"), ("A", "on A's edge"), ("B", "in A and B"),
    ]


def test_polygons_with_polygons_overlap_and_touch(client):
    """#576: two polygon inputs join; A and B overlap, A and C meet at a corner."""
    overlaps = _join(client, SQUARES, SQUARES, predicate="overlaps")
    assert _pairs(overlaps, "square", "square_right") == [("A", "B"), ("B", "A")]
    touches = _join(client, SQUARES, SQUARES, predicate="touches")
    assert _pairs(touches, "square", "square_right") == [("A", "C"), ("C", "A")]


def test_a_line_crosses_the_polygon_it_runs_through_not_the_one_it_runs_along(client):
    """#576: y=1 enters and leaves A, but only runs along B's bottom edge."""
    body = _join(client, LINE, SQUARES, predicate="crosses")
    assert _pairs(body, "line", "square") == [("y=1", "A")]


def test_nearest_pairs_each_row_with_the_closest_and_says_how_far_in_meters(client):
    """#576: in Chicago, 0.001 degrees of longitude is about 83 m."""
    stations = _fc([_point(-87.650, 41.90, station="west"), _point(-87.600, 41.90, station="east")])
    photos = _fc([_point(-87.649, 41.90, photo="p1"), _point(-87.601, 41.90, photo="p2")])
    body = _join(client, photos, stations, predicate="nearest")
    assert _pairs(body, "photo", "station") == [("p1", "west"), ("p2", "east")]
    for feature in body["features"]:
        assert 80 < feature["properties"]["distance"] < 86, feature["properties"]


def test_a_column_input_0_already_has_comes_in_with_right(client):
    """#576: input_1's columns never overwrite input_0's."""
    photo = _fc([_point(0.5, 0.5, name="photo-1.jpg", kind="photo")])
    area = _fc([_box(0, 0, 2, 2, name="Loop", zone="Z1")])
    body = _join(client, photo, area)
    assert body["features"][0]["properties"] == {
        "name": "photo-1.jpg", "kind": "photo", "name_right": "Loop", "zone": "Z1",
    }


def test_counts_give_input_1s_rows_each_with_its_own_count(client):
    """#576: the per-polygon counts output stays, counted per row. Two rows
    that share a name (a ZIP drawn as two polygons) used to both get the
    name's total."""
    zips = _fc([_box(0, 0, 2, 2, zip="60643"), _box(5, 5, 6, 6, zip="60643"), _box(1, 1, 3, 3, zip="60652")])
    body = _join(client, POINTS, zips, output="counts")
    assert [(f["properties"]["zip"], f["properties"]["point_count"]) for f in body["features"]] == [
        ("60643", 3), ("60643", 0), ("60652", 1),
    ]
    assert body["features"][0]["geometry"]["type"] == "Polygon"
    assert body["metadata"]["output"] == "counts"
    assert body["metadata"]["matched_right"] == 2


@pytest.mark.parametrize("left, right, predicate, words", [
    (SQUARES, POINTS, "within", ["a polygon is never within a point", "contains", "swap"]),
    (POINTS, SQUARES, "contains", ["a point never contains a polygon", "within", "swap"]),
    (POINTS, SQUARES, "overlaps", ["overlaps pairs shapes of one kind", "intersects"]),
    (SQUARES, _fc([_box(10, 10, 11, 11, square="D")]), "crosses", ["two polygons never cross"]),
])
def test_an_operation_that_can_never_match_these_shapes_says_what_to_pick(client, left, right, predicate, words):
    """#576: no pairs, and a message instead of an empty result to puzzle over."""
    body = _join(client, left, right, predicate=predicate)
    assert body["features"] == []
    assert len(body["metadata"]["warnings"]) == 1
    for word in words:
        assert word in body["metadata"]["warnings"][0], body["metadata"]["warnings"]


def test_an_input_that_is_not_geodata_is_a_400_naming_its_circle(client):
    """#576: a table without geometry on a circle gets a message, never a 500."""
    table = {"dataType": "dataframe", "data": {"a": [1, 2]}}
    left = client.post("/spatial_join", json={"left": table, "right": SQUARES})
    assert left.status_code == 400
    assert "input_0 is not geodata" in left.get_json()["error"]
    right = client.post("/spatial_join", json={"left": POINTS, "right": [1, 2]})
    assert right.status_code == 400
    assert "input_1 is not geodata" in right.get_json()["error"]


def test_an_unknown_operation_or_output_is_a_400_listing_the_choices(client):
    """#576."""
    wrong = client.post("/spatial_join", json={"left": POINTS, "right": SQUARES, "predicate": "near"})
    assert wrong.status_code == 400
    assert "intersects, within, contains, touches, overlaps, crosses, nearest" in wrong.get_json()["error"]
    wrong = client.post("/spatial_join", json={"left": POINTS, "right": SQUARES, "output": "polygons"})
    assert wrong.status_code == 400
    assert "pairs, counts" in wrong.get_json()["error"]


def test_input_1_in_another_crs_is_reprojected_to_input_0s(client):
    """#576: the sandbox writes a GeoDataFrame's CRS as the collection's crs
    member; input_1 in web mercator still pairs with input_0 in degrees."""
    from pyproj import Transformer

    to_mercator = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    corners = [to_mercator.transform(x, y) for x, y in [(-87.7, 41.8), (-87.6, 41.9)]]
    area = _fc([_box(corners[0][0], corners[0][1], corners[1][0], corners[1][1], area="Loop")],
               crs="urn:ogc:def:crs:EPSG::3857")
    photos = _fc([_point(-87.65, 41.85, photo="in"), _point(-87.5, 41.85, photo="out")],
                 crs="urn:ogc:def:crs:EPSG::4326")
    body = _join(client, photos, area)
    assert _pairs(body, "photo", "area") == [("in", "Loop")]
    # The pairs keep input_0's coordinates, and say which system they are in.
    assert body["features"][0]["geometry"]["coordinates"] == [-87.65, 41.85]
    assert body["crs"]["properties"]["name"] == "urn:ogc:def:crs:EPSG::4326"
