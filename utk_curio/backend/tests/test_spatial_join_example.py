"""Example 25 runs every Spatial Join operation, one flow each (#576).

Each test takes one flow of ``docs/examples/25-spatial-join-operations.json``.
It runs the example's own loader code on the shipped datasets, with stand-ins
for ``curio_data_path`` and ``curio_load_data``, and the join's own code, its
chips written from its two widgets as a run writes them, on the two loaders'
GeoDataFrames, its circles' inputs, as the sandbox runs node code
(``input_names.call_as_node``), with the built-in package's module
``spatial_join`` staged as the sandbox stages it. It pins what comes out: the
rows, and the line the join prints of what it paired. The line of the other
output, which the test asks of the same call of ``spatial_join``, pins the
counts of the other side, so every count of a flow is pinned.
``test_frontend/test_spatial_join_operations_e2e.py`` runs the same flows in
the browser, and ``test_frontend/test_server_run_spatial_joins_e2e.py`` on the
server.
"""
from __future__ import annotations

import contextlib
import io
import json
import textwrap
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = REPO_ROOT / "docs" / "examples" / "25-spatial-join-operations.json"
PACKAGE = REPO_ROOT / "packages" / "curio.builtin@1"

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


@pytest.fixture(autouse=True)
def spatial_join_module(tmp_path):
    """While the test runs, the built-in package's module imports by name,
    staged into a folder of the run's own as the sandbox stages it."""
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / "run-example-25"
    run.mkdir()
    staged = stage_package_modules({"root": str(PACKAGE / "sources"), "names": ["spatial_join"]}, str(run))
    with importable(str(run / staged["root"]), staged["names"]):
        yield staged


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
    from utk_curio.sandbox.util.input_names import call_as_node

    value = _frame(sources[0]) if sources else None
    scope = {"curio_data_path": _data_path, "curio_load_data": _load_data}
    return call_as_node(textwrap.indent(node["content"], "    "), scope, value, [0] if sources else None)


def _run_join(join_id: str, output: str | None = None):
    """The join's output and the lines it printed: its own code, with its
    widgets' values (*output* in place of its Output's, when given), on the
    loaders' frames on its two circles."""
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.util.input_names import call_as_node

    flow = _dataflow()
    node = next(n for n in flow["nodes"] if n["id"] == join_id)
    circles = {e["targetHandle"]: e["source"] for e in flow["edges"] if e["target"] == join_id}
    assert sorted(circles) == ["in", "in_1"], circles
    widgets = [
        {**widget, "value": output} if output is not None and widget["name"] == "output" else widget
        for widget in node["metadata"]["widgets"]
    ]
    code, problems = resolve_references(node["content"], widgets, "python", [{"slot": 0}, {"slot": 1}])
    assert problems == [], problems
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        result = call_as_node(
            textwrap.indent(code, "    "), {}, [_frame(circles["in"]), _frame(circles["in_1"])], [0, 1],
        )
    return result, printed.getvalue().splitlines()


def _setting(join_id: str, name: str) -> str:
    node = next(n for n in _dataflow()["nodes"] if n["id"] == join_id)
    widget = next(w for w in node["metadata"]["widgets"] if w["name"] == name)
    return widget.get("value", widget["default"])


def _lines(join_id: str) -> tuple[list, list]:
    """What the join printed in pairs and in counts: every count of its flow."""
    return _run_join(join_id, "pairs")[1], _run_join(join_id, "counts")[1]


def _rows(result, key: str, value) -> list:
    return [row for _, row in result.drop(columns=result.geometry.name).iterrows() if row.get(key) == value]


def test_the_joins_hold_the_settings_each_case_shows():
    """Each flow's operation and output, as its two widgets hold them."""
    settings = {
        join: (_setting(join, "operation"), _setting(join, "output"))
        for join in (JOIN_INTERSECTS, JOIN_WITHIN, JOIN_CONTAINS, JOIN_TOUCHES, JOIN_OVERLAPS, JOIN_CROSSES,
                     JOIN_NEAREST, JOIN_EDGE_INTERSECTS, JOIN_EDGE_WITHIN)
    }
    assert settings == {
        JOIN_INTERSECTS: ("intersects", "pairs"),
        JOIN_WITHIN: ("within", "counts"),
        JOIN_CONTAINS: ("contains", "pairs"),
        JOIN_TOUCHES: ("touches", "pairs"),
        JOIN_OVERLAPS: ("overlaps", "pairs"),
        JOIN_CROSSES: ("crosses", "pairs"),
        JOIN_NEAREST: ("nearest", "pairs"),
        JOIN_EDGE_INTERSECTS: ("intersects", "pairs"),
        JOIN_EDGE_WITHIN: ("within", "pairs"),
    }


def test_intersects_pairs_every_green_roof_with_its_neighborhood():
    """#576: points on input_0, polygons on input_1, the default operation."""
    result, printed = _run_join(JOIN_INTERSECTS)
    assert _lines(JOIN_INTERSECTS) == (
        ["359 pairs: 359 of 359 input_0 rows matched."],
        ["69 of 98 input_1 rows have pairs (359 in all); each row carries point_count."],
    )
    assert printed == ["359 pairs: 359 of 359 input_0 rows matched."]
    assert len(_rows(result, "pri_neigh", "Loop")) == 30


def test_within_counts_the_sidewalk_labels_in_each_neighborhood():
    """#576: the counts output, input_1's rows each with point_count."""
    result, printed = _run_join(JOIN_WITHIN)
    assert _lines(JOIN_WITHIN) == (
        ["235 pairs: 235 of 400 input_0 rows matched."],
        ["61 of 98 input_1 rows have pairs (235 in all); each row carries point_count."],
    )
    assert printed == ["61 of 98 input_1 rows have pairs (235 in all); each row carries point_count."]
    assert len(result) == 98
    assert _rows(result, "pri_neigh", "Austin")[0]["point_count"] == 17


def test_contains_takes_the_polygons_on_input_0():
    """#576: a polygon on input_0 joins; it was an HTTP 500 on the points side."""
    result, _printed = _run_join(JOIN_CONTAINS)
    assert _lines(JOIN_CONTAINS) == (
        ["235 pairs: 61 of 98 input_0 rows matched."],
        ["235 of 400 input_1 rows have pairs (235 in all); each row carries point_count."],
    )
    austin = _rows(result, "pri_neigh", "Austin")
    assert len(austin) == 17 and all(row["label_type"] for row in austin)
    assert set(result.geometry.geom_type) <= {"Polygon", "MultiPolygon"}


def test_touches_pairs_each_neighborhood_with_the_ones_it_borders():
    """#576: one loader on both circles; the second copy's columns come in as _right."""
    result, _printed = _run_join(JOIN_TOUCHES)
    assert _lines(JOIN_TOUCHES) == (
        ["484 pairs: 98 of 98 input_0 rows matched."],
        ["98 of 98 input_1 rows have pairs (484 in all); each row carries point_count."],
    )
    neighbors = sorted(row["pri_neigh_right"] for row in _rows(result, "pri_neigh", "Lincoln Park"))
    assert neighbors == ["Bucktown", "Gold Coast", "Lake View", "North Center", "Old Town",
                         "River North", "Sheffield & DePaul", "West Town"]
    # A neighborhood never touches itself: their insides meet.
    assert (result["pri_neigh"] != result["pri_neigh_right"]).all()


def test_overlaps_pairs_each_neighborhood_with_the_zip_codes_it_straddles():
    """#576: polygons with polygons; shape_area clashes and comes in as shape_area_right."""
    result, _printed = _run_join(JOIN_OVERLAPS)
    assert _lines(JOIN_OVERLAPS) == (
        ["311 pairs: 94 of 98 input_0 rows matched."],
        ["61 of 61 input_1 rows have pairs (311 in all); each row carries point_count."],
    )
    lincoln_park = _rows(result, "pri_neigh", "Lincoln Park")
    assert sorted(row["zip"] for row in lincoln_park) == ["60610", "60614", "60618", "60642", "60647", "60657"]
    assert "shape_area_right" in lincoln_park[0]


def test_crosses_pairs_each_zip_border_with_the_neighborhoods_it_runs_through():
    """#576: lines on input_0, polygons on input_1."""
    result, _printed = _run_join(JOIN_CROSSES)
    assert _lines(JOIN_CROSSES) == (
        ["311 pairs: 61 of 61 input_0 rows matched."],
        ["94 of 98 input_1 rows have pairs (311 in all); each row carries point_count."],
    )
    assert set(result.geometry.geom_type) <= {"LineString", "MultiLineString"}
    assert len(_rows(result, "pri_neigh", "Lincoln Park")) == 6


def test_nearest_pairs_each_green_roof_with_the_closest_label_in_meters():
    """#576: every roof gets its nearest label, and the distance between them."""
    result, _printed = _run_join(JOIN_NEAREST)
    assert _lines(JOIN_NEAREST) == (
        ["359 pairs: 359 of 359 input_0 rows matched."],
        ["126 of 400 input_1 rows have pairs (359 in all); each row carries point_count."],
    )
    distances = sorted(result["distance"])
    assert distances[0] == pytest.approx(39.89, abs=0.5)
    assert distances[-1] == pytest.approx(6683.67, abs=5)


def _point_pairs(result) -> list:
    return sorted(zip(result["point"], result["square"]))


def test_a_point_on_a_shared_edge_intersects_both_squares():
    """#576: the boundary rule, as shapely has it: on the edge is intersecting."""
    result, printed = _run_join(JOIN_EDGE_INTERSECTS)
    assert _point_pairs(result) == [("inside", "west"), ("on the edge", "east"), ("on the edge", "west")]
    assert printed == ["3 pairs: 2 of 3 input_0 rows matched."]


def test_a_point_on_a_shared_edge_is_within_neither_square():
    """#576: and on the edge is not within."""
    result, printed = _run_join(JOIN_EDGE_WITHIN)
    assert _point_pairs(result) == [("inside", "west")]
    assert printed == ["1 pair: 1 of 3 input_0 rows matched."]
