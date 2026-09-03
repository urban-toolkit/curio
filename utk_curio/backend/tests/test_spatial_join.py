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
    enriched, _ = enrich_points_with_polygons(
        [POINT], {"features": [_square({"pri_neigh": "Loop"})]},
        name_property="pri_neigh", warnings=warnings,
    )
    assert enriched[0]["neighborhood_name"] == "Loop"
    assert warnings == []


def test_a_property_no_polygon_carries_is_reported_with_the_alternatives():
    warnings: list[str] = []
    enriched, _ = enrich_points_with_polygons(
        [POINT], {"features": [_square({"pri_neigh": "Loop", "sec_neigh": "LOOP"})]},
        name_property="name", warnings=warnings,
    )
    # The join still runs, and still falls back - but says so.
    assert enriched[0]["neighborhood_name"] == "polygon_0"
    assert len(warnings) == 1
    assert "No polygon has a 'name' property" in warnings[0]
    assert "pri_neigh" in warnings[0] and "sec_neigh" in warnings[0]


def test_a_partial_miss_counts_the_polygons():
    warnings: list[str] = []
    enrich_points_with_polygons(
        [POINT],
        {"features": [_square({"name": "A"}), _square({"other": "B"})]},
        name_property="name", warnings=warnings,
    )
    assert warnings == ["1 of 2 polygons lack a 'name' property and are tagged polygon_<index>."]


def test_callers_that_pass_no_list_get_the_old_silent_behaviour():
    enriched, _ = enrich_points_with_polygons(
        [POINT], {"features": [_square({"pri_neigh": "Loop"})]},
    )
    assert enriched[0]["neighborhood_name"] == "polygon_0"


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def test_route_passes_the_property_through_and_forwards_warnings(client):
    points = _fc([{"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {}}])
    polygons = _fc([_square({"pri_neigh": "Loop"})])

    ok = client.post("/spatial_join", json={"points": points, "polygons": polygons, "name_property": "pri_neigh"})
    assert ok.status_code == 200, ok.get_json()
    body = ok.get_json()
    assert body["features"][0]["properties"]["neighborhood_name"] == "Loop"
    assert "warnings" not in body["metadata"]

    wrong = client.post("/spatial_join", json={"points": points, "polygons": polygons, "name_property": "name"})
    assert wrong.status_code == 200
    body = wrong.get_json()
    assert body["features"][0]["properties"]["neighborhood_name"] == "polygon_0"
    assert body["metadata"]["warnings"] and "pri_neigh" in body["metadata"]["warnings"][0]
