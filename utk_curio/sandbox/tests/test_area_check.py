"""The check a run skips a Map Editor edit by when the area it gives would make
autk-db refuse its whole layer (#1121), ``utk_curio/sandbox/util/area_check.py``,
on the cases its twin in the browser reads too: ``areaCheck.cases.json``,
which Jest runs through ``utils/editFeatures/areaCheck.ts``, the check the map's
tools refuse a gesture by. Each case's problem is the one both find, null for
a shape GEOS accepts once the map's grid has rounded it, and GEOS, through
shapely, says so of each.

Every test imports the module itself, so a checkout without it fails test by
test rather than at collection.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CASES = REPO_ROOT / "utk_curio/frontend/urban-workflows/src/utils/editFeatures/areaCheck.cases.json"


def _cases():
    """The cases file's cases, read at collection; a checkout without it fails
    this test rather than the whole module."""
    try:
        return json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    except FileNotFoundError:
        return [{"name": "areaCheck.cases.json is missing", "geometry": None, "problem": "missing"}]


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_an_area_as_autk_db_would_get_it(case):
    from utk_curio.sandbox.util.area_check import area_problem

    assert area_problem(case["geometry"], case.get("coordinateFormat")) == case["problem"]


@pytest.mark.parametrize("case", [c for c in _cases() if "unrounded" in c], ids=lambda c: c["name"])
def test_before_the_maps_grid(case):
    from utk_curio.sandbox.util.area_check import shape_problem

    assert shape_problem(case["geometry"]) == case["unrounded"]


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_geos_accepts_exactly_the_areas_with_no_problem(case):
    """GEOS, which autk-db checks a building with, accepts each shape the map
    would hand it whose problem is null, and refuses each other one."""
    from shapely.geometry import shape

    from utk_curio.sandbox.util.area_check import _on_the_grid

    on_the_grid = _on_the_grid(case["geometry"], case.get("coordinateFormat"))
    assert shape(on_the_grid).is_valid == (case["problem"] is None), on_the_grid


def test_the_cases_hold_a_shape_with_each_problem_shapes_geos_accepts_and_one_the_grid_refuses():
    from utk_curio.sandbox.util.area_check import CROSSES, FLAT, HOLE, OVERLAP

    problems = [case["problem"] for case in _cases()]
    assert {CROSSES, FLAT, HOLE, OVERLAP, None} <= set(problems)
    assert any(case.get("unrounded", "absent") is None and case["problem"] is not None for case in _cases())


def test_lines_points_and_what_is_not_a_shape_are_not_checked():
    from utk_curio.sandbox.util.area_check import area_problem

    assert area_problem({"type": "LineString", "coordinates": [[0, 0], [2, 2], [2, 0], [0, 2]]}) is None
    assert area_problem({"type": "MultiLineString", "coordinates": [[[0, 0], [2, 2]], [[2, 0], [0, 2]]]}) is None
    assert area_problem({"type": "MultiPoint", "coordinates": [[0, 0], [0, 0]]}) is None
    assert area_problem({"type": "Point", "coordinates": [0, 0]}) is None
    assert area_problem(None) is None
    assert area_problem({"type": "Polygon", "coordinates": [[[0, 0], [1, "a"], [1, 1], [0, 0]]]}) is None


def test_a_part_with_no_rings_has_no_area_and_overlaps_nothing():
    from utk_curio.sandbox.util.area_check import area_problem

    square = [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
    assert area_problem({"type": "MultiPolygon", "coordinates": [[], square]}) is None
    assert area_problem({"type": "MultiPolygon", "coordinates": [square, []]}) is None


def test_the_grid_rounds_a_half_up_as_javascript_does():
    """``Math.round`` takes a half toward +infinity; Python's ``round`` takes it
    to the even neighbour, which would move a corner the map keeps."""
    from utk_curio.sandbox.util.area_check import _js_round

    assert [_js_round(value) for value in (2.5, 3.5, -2.5, -2.6, 0.49999999999999994)] == [3, 4, -2, -3, 0]


IN_METRES = {"type": "Polygon", "coordinates": [[[-9755000, 5140000], [-9754990, 5140000], [-9754990, 5140010], [-9755000, 5140000]]]}


def test_the_coordinate_format_is_read_from_the_layers_features_or_from_the_shape_while_it_has_none():
    from utk_curio.sandbox.util.area_check import layer_format

    in_degrees = {"features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [-87.6, 41.88]}}]}
    assert layer_format(in_degrees, IN_METRES) == "EPSG:4326"
    assert layer_format({"features": []}, IN_METRES) == "EPSG:3395"
    assert layer_format(None, IN_METRES) == "EPSG:3395"


def test_the_coordinate_format_is_the_one_a_layer_names():
    from utk_curio.sandbox.util.area_check import layer_format

    named = {"features": [], "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}}}
    assert layer_format(named, IN_METRES) == "EPSG:4326"
    assert layer_format({"features": [], "crs": {"type": "name", "properties": {"name": "EPSG:3857"}}}, IN_METRES) == "EPSG:3857"


BOW_TIE = {"type": "Polygon", "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]}
SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}


def test_a_change_is_refused_only_for_a_problem_it_brings():
    """The rule the map's tools refuse a gesture by (``madeProblem``): a shape
    that crosses itself is refused in place of one that does not, or for a
    feature added, and taken in place of one that crosses itself already."""
    from utk_curio.sandbox.util.area_check import CROSSES, made_problem

    assert made_problem(None, SQUARE, BOW_TIE) == CROSSES
    assert made_problem(None, None, BOW_TIE) == CROSSES
    assert made_problem(None, BOW_TIE, BOW_TIE) is None
    assert made_problem(None, BOW_TIE, SQUARE) is None
    assert made_problem(None, SQUARE, SQUARE) is None
