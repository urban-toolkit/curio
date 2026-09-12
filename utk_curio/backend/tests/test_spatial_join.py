"""The Spatial Join reports a polygon property that matched nothing (#262).

``enrich_points_with_polygons`` fell back to ``polygon_<index>`` silently, so
the wrong property name looked like a successful join. It now appends a
warning, and ``POST /spatial_join`` forwards it as ``metadata.warnings``.
"""
from __future__ import annotations

import pytest

pytest.importorskip("shapely")

from utk_curio.backend.app.common.spatial import enrich_points_with_polygons


def _square(name_props: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]},
        "properties": name_props,
    }


POINT = {"latitude": 1.0, "longitude": 1.0}


def test_a_matching_property_tags_and_warns_nothing():
    warnings: list[str] = []
    enriched, _, _ = enrich_points_with_polygons(
        [POINT], {"features": [_square({"pri_neigh": "Loop"})]},
        name_property="pri_neigh", warnings=warnings,
    )
    assert enriched[0]["pri_neigh"] == "Loop"
    assert warnings == []


def test_a_property_no_polygon_carries_is_reported_with_the_alternatives():
    warnings: list[str] = []
    enriched, _, _ = enrich_points_with_polygons(
        [POINT], {"features": [_square({"pri_neigh": "Loop", "sec_neigh": "LOOP"})]},
        name_property="name", warnings=warnings,
    )
    # The join still runs, and still falls back - but says so.
    assert enriched[0]["name"] == "polygon_0"
    assert len(warnings) == 1
    assert "No polygon has a 'name' column" in warnings[0]
    assert "pri_neigh" in warnings[0] and "sec_neigh" in warnings[0]


def test_a_partial_miss_counts_the_polygons():
    warnings: list[str] = []
    enrich_points_with_polygons(
        [POINT],
        {"features": [_square({"name": "A"}), _square({"other": "B"})]},
        name_property="name", warnings=warnings,
    )
    assert warnings == ["1 of 2 polygons lack a 'name' column and are tagged polygon_<index>."]


def test_a_join_without_a_dominant_class_adds_the_tag_and_a_count():
    """Roofs tagged with a ZIP code are not a street-vision run.

    The roll-ups (``<tag>_dominant_class`` and friends) exist for points that
    carry a ``dominant_class``; for anything else they used to arrive as three
    empty columns on every point, which is how example 15 showed a roof with a
    ``neighborhood_name`` of "60647" and two null neighborhood fields.
    """
    enriched, aggregates, tag_column = enrich_points_with_polygons(
        [{**POINT, "sqft": 120}], {"features": [_square({"name": "Loop"})]},
        name_property="name",
    )
    assert tag_column == "name"
    assert aggregates == [{"name": "Loop", "point_count": 1}]
    assert enriched[0]["name"] == "Loop"
    assert set(enriched[0]) == {"latitude", "longitude", "sqft", "name", "name_point_count"}


def test_a_column_the_points_already_have_is_not_clobbered():
    enriched, _, tag_column = enrich_points_with_polygons(
        [{**POINT, "name": "roof 12"}], {"features": [_square({"name": "Loop"})]},
        name_property="name",
    )
    assert tag_column == "name_polygon"
    assert enriched[0]["name"] == "roof 12"
    assert enriched[0]["name_polygon"] == "Loop"


def test_the_polygon_output_carries_a_count_per_polygon():
    from utk_curio.backend.app.common.spatial import polygons_with_counts

    far_square = {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]]]},
        "properties": {"name": "Empty"},
    }
    polygons = {"features": [_square({"name": "Loop"}), far_square]}
    _, aggregates, tag_column = enrich_points_with_polygons(
        [POINT, {"latitude": 1.5, "longitude": 1.5}], polygons, name_property="name",
    )

    out = polygons_with_counts(polygons, aggregates, tag_column, "name")

    assert [f["properties"]["point_count"] for f in out] == [2, 0]
    assert out[0]["geometry"]["type"] == "Polygon"
    assert "dominant_class" not in out[0]["properties"]


def test_points_with_a_dominant_class_get_the_roll_ups():
    enriched, aggregates, tag_column = enrich_points_with_polygons(
        [
            {**POINT, "dominant_class": "road", "dominant_pct": 60},
            {"latitude": 1.5, "longitude": 1.5, "dominant_class": "road", "dominant_pct": 40},
        ],
        {"features": [_square({"name": "Loop"})]},
        name_property="name",
    )
    assert aggregates[0]["name"] == "Loop"
    assert enriched[0]["name_dominant_class"] == "road"
    assert enriched[0]["name_dominant_pct"] == 50
    assert enriched[0]["name_point_count"] == 2


def test_callers_that_pass_no_list_get_the_old_silent_behaviour():
    enriched, _, _ = enrich_points_with_polygons(
        [POINT], {"features": [_square({"pri_neigh": "Loop"})]},
    )
    assert enriched[0]["name"] == "polygon_0"


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def test_route_passes_the_property_through_and_forwards_warnings(client):
    points = _fc([{"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {}}])
    polygons = _fc([_square({"pri_neigh": "Loop"})])

    ok = client.post("/spatial_join", json={"points": points, "polygons": polygons, "name_property": "pri_neigh"})
    assert ok.status_code == 200, ok.get_json()
    body = ok.get_json()
    assert body["features"][0]["properties"]["pri_neigh"] == "Loop"
    assert body["metadata"]["tag_column"] == "pri_neigh"
    assert "warnings" not in body["metadata"]

    wrong = client.post("/spatial_join", json={"points": points, "polygons": polygons, "name_property": "name"})
    assert wrong.status_code == 200
    body = wrong.get_json()
    assert body["features"][0]["properties"]["name"] == "polygon_0"
    assert body["metadata"]["warnings"] and "pri_neigh" in body["metadata"]["warnings"][0]
