"""The Spatial Join pairs two inputs by an operation, on geopandas sjoin (#576).

The join is ``spatial_join``, the function of the built-in package's module
(``packages/curio.builtin@1/sources/spatial_join.py``), which the Spatial Join
node's code calls with its two circles and its two widgets. input_0 (the
node's top circle) is the left side of the join and input_1 (the bottom
circle) the right, whatever geometry each holds. The output is one row per
matching pair, input_0's row with input_1's columns added, or input_1's rows
with a count; the function prints how many rows it paired, and why an
operation can never match the shapes given when it found no pair. A point on
an edge follows shapely's rule for each operation. Every test calls the
function, staged as the sandbox stages a node's modules.

These are the tests of the route the node used to post to, ``/spatial_join``,
on the same boards, each asserting what the route's answer said: its pairs
and columns as the frame's rows, its counts as the line the function prints,
its warnings as the hints it prints, its 400s as the errors it raises.

The board most tests share, in plain coordinates:

    A = square (0,0)-(2,2)       B = square (1,1)-(3,3), overlaps A
    C = rectangle (2,-1)-(4,0), meets A at the corner (2,0) only
    "inside A" (0.5,0.5)   "on A's edge" (2,0.5)   "in A and B" (1.5,1.5)
    "far" (10,10)          the line y=1 from x=-1 to x=5
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = REPO_ROOT / "packages" / "curio.builtin@1"
MODULE = "spatial_join"


@pytest.fixture()
def join(tmp_path):
    """``spatial_join``, imported from the built-in package's module staged
    into a folder of the run's own, as the sandbox stages it."""
    import importlib

    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / "run-join"
    run.mkdir()
    staged = stage_package_modules({"root": str(PACKAGE / "sources"), "names": [MODULE]}, str(run))
    with importable(str(run / staged["root"]), staged["names"]):
        yield importlib.import_module(MODULE).spatial_join


def _frame(features, crs=None):
    """A GeoDataFrame of GeoJSON features, as a node's output reads in the sandbox."""
    import geopandas as gpd

    return gpd.GeoDataFrame.from_features(features, crs=crs)


def _feature(geometry, **props):
    return {"type": "Feature", "geometry": geometry, "properties": props}


def _box(x0, y0, x1, y1, **props):
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return _feature({"type": "Polygon", "coordinates": [ring]}, **props)


def _point(x, y, **props):
    return _feature({"type": "Point", "coordinates": [x, y]}, **props)


SQUARES = [_box(0, 0, 2, 2, square="A"), _box(1, 1, 3, 3, square="B"), _box(2, -1, 4, 0, square="C")]
POINTS = [
    _point(0.5, 0.5, point="inside A"),
    _point(2, 0.5, point="on A's edge"),
    _point(1.5, 1.5, point="in A and B"),
    _point(10, 10, point="far"),
]
LINE = [_feature({"type": "LineString", "coordinates": [[-1, 1], [5, 1]]}, line="y=1")]


def _run(join, capsys, left, right, **settings):
    """The joined rows and the lines the join printed."""
    result = join(left, right, **settings)
    return result, capsys.readouterr().out.splitlines()


def _pairs(result, left_key, right_key):
    return sorted(zip(result[left_key], result[right_key]))


@pytest.mark.parametrize("operation, expected", [
    # A point on an edge intersects the polygon...
    ("intersects", [("in A and B", "A"), ("in A and B", "B"), ("inside A", "A"), ("on A's edge", "A")]),
    # ...is not within it...
    ("within", [("in A and B", "A"), ("in A and B", "B"), ("inside A", "A")]),
    # ...and is the only point that touches it.
    ("touches", [("on A's edge", "A")]),
])
def test_points_on_input_0_pair_by_the_operation_and_its_boundary_rule(join, capsys, operation, expected):
    """#576: intersects, within and touches, a point on an edge included."""
    result, lines = _run(join, capsys, _frame(POINTS), _frame(SQUARES), operation=operation)
    assert _pairs(result, "point", "square") == expected
    pairs = f"{len(expected)} pair{'' if len(expected) == 1 else 's'}"
    assert lines == [f"{pairs}: {len({p for p, _ in expected})} of 4 input_0 rows matched."]


def test_one_row_per_pair_with_input_1s_columns_and_the_counts_it_prints(join, capsys):
    """#576: a point in two polygons is two rows; a point in none is left out."""
    import geopandas as gpd

    result, lines = _run(join, capsys, _frame(POINTS), _frame(SQUARES))
    assert isinstance(result, gpd.GeoDataFrame)
    assert list(result.columns) == ["geometry", "point", "square"]
    rows = result[result["point"] == "in A and B"]
    assert sorted(rows["square"]) == ["A", "B"]
    # The geometry of a pair is input_0's.
    assert all(geometry.wkt == "POINT (1.5 1.5)" for geometry in rows.geometry)
    # Four pairs of three of the four points, and of two of the three squares.
    assert lines == ["4 pairs: 3 of 4 input_0 rows matched."]
    _counts, counted = _run(join, capsys, _frame(POINTS), _frame(SQUARES), output="counts")
    assert counted == ["2 of 3 input_1 rows have pairs (4 in all); each row carries point_count."]


def test_a_polygon_on_input_0_joins_instead_of_failing(join, capsys):
    """#576: a polygon on the points side was an HTTP 500. Inputs follow the
    circles now, so polygons on input_0 contain the points on input_1."""
    result, _lines = _run(join, capsys, _frame(SQUARES), _frame(POINTS), operation="contains")
    # The point on A's edge is not contained: the polygon does not hold its boundary.
    assert _pairs(result, "square", "point") == [("A", "in A and B"), ("A", "inside A"), ("B", "in A and B")]
    assert result.geometry.iloc[0].geom_type == "Polygon"
    intersects, _lines = _run(join, capsys, _frame(SQUARES), _frame(POINTS))
    assert _pairs(intersects, "square", "point") == [
        ("A", "in A and B"), ("A", "inside A"), ("A", "on A's edge"), ("B", "in A and B"),
    ]


def test_polygons_with_polygons_overlap_and_touch(join, capsys):
    """#576: two polygon inputs join; A and B overlap, A and C meet at a corner."""
    overlaps, _lines = _run(join, capsys, _frame(SQUARES), _frame(SQUARES), operation="overlaps")
    assert _pairs(overlaps, "square", "square_right") == [("A", "B"), ("B", "A")]
    touches, _lines = _run(join, capsys, _frame(SQUARES), _frame(SQUARES), operation="touches")
    assert _pairs(touches, "square", "square_right") == [("A", "C"), ("C", "A")]


def test_a_line_crosses_the_polygon_it_runs_through_not_the_one_it_runs_along(join, capsys):
    """#576: y=1 enters and leaves A, but only runs along B's bottom edge."""
    result, _lines = _run(join, capsys, _frame(LINE), _frame(SQUARES), operation="crosses")
    assert _pairs(result, "line", "square") == [("y=1", "A")]


def test_nearest_pairs_each_row_with_the_closest_and_says_how_far_in_meters(join, capsys):
    """#576: in Chicago, 0.001 degrees of longitude is about 83 m."""
    stations = _frame([_point(-87.650, 41.90, station="west"), _point(-87.600, 41.90, station="east")])
    photos = _frame([_point(-87.649, 41.90, photo="p1"), _point(-87.601, 41.90, photo="p2")])
    result, _lines = _run(join, capsys, photos, stations, operation="nearest")
    assert _pairs(result, "photo", "station") == [("p1", "west"), ("p2", "east")]
    for distance in result["distance"]:
        assert 80 < distance < 86, distance


def test_a_column_input_0_already_has_comes_in_with_right(join, capsys):
    """#576: input_1's columns never overwrite input_0's."""
    photo = _frame([_point(0.5, 0.5, name="photo-1.jpg", kind="photo")])
    area = _frame([_box(0, 0, 2, 2, name="Loop", zone="Z1")])
    result, _lines = _run(join, capsys, photo, area)
    assert json.loads(result.to_json(drop_id=True))["features"][0]["properties"] == {
        "name": "photo-1.jpg", "kind": "photo", "name_right": "Loop", "zone": "Z1",
    }


def test_counts_give_input_1s_rows_each_with_its_own_count(join, capsys):
    """#576: the per-polygon counts output stays, counted per row. Two rows
    that share a name (a ZIP drawn as two polygons) used to both get the
    name's total."""
    zips = _frame([_box(0, 0, 2, 2, zip="60643"), _box(5, 5, 6, 6, zip="60643"), _box(1, 1, 3, 3, zip="60652")])
    result, lines = _run(join, capsys, _frame(POINTS), zips, output="counts")
    assert list(zip(result["zip"], result["point_count"])) == [("60643", 3), ("60643", 0), ("60652", 1)]
    assert result.geometry.iloc[0].geom_type == "Polygon"
    assert lines == ["2 of 3 input_1 rows have pairs (4 in all); each row carries point_count."]


@pytest.mark.parametrize("left, right, operation, words", [
    (SQUARES, POINTS, "within", ["a polygon is never within a point", "contains", "swap"]),
    (POINTS, SQUARES, "contains", ["a point never contains a polygon", "within", "swap"]),
    (POINTS, SQUARES, "overlaps", ["overlaps pairs shapes of one kind", "intersects"]),
    (SQUARES, [_box(10, 10, 11, 11, square="D")], "crosses", ["two polygons never cross"]),
])
def test_an_operation_that_can_never_match_these_shapes_says_what_to_pick(join, capsys, left, right, operation, words):
    """#576: no pairs, and a message instead of an empty result to puzzle over."""
    result, lines = _run(join, capsys, _frame(left), _frame(right), operation=operation)
    assert len(result) == 0
    assert lines[0] == f"0 pairs: 0 of {len(left)} input_0 rows matched."
    assert len(lines) == 2, lines
    for word in words:
        assert word in lines[1], lines


def test_an_input_that_is_not_geodata_is_refused_naming_its_circle(join):
    """#576: a table without geometry on a circle gets a message, never a crash."""
    import pandas as pd

    with pytest.raises(ValueError, match="input_0 is not geodata"):
        join(pd.DataFrame({"a": [1, 2]}), _frame(SQUARES))
    with pytest.raises(ValueError, match="input_1 is not geodata"):
        join(_frame(POINTS), [1, 2])
    # A circle with no edge is None in node code.
    with pytest.raises(ValueError) as unwired:
        join(_frame(POINTS), None)
    assert str(unwired.value) == (
        "input_1 is not geodata: connect a node whose output has a geometry column (a GeoDataFrame) to its circle."
    )


def test_an_input_of_several_layers_is_refused_naming_them_and_the_chip_that_picks_one(join):
    """An Autark node hands on several layers as a list of frames, each named:
    the join takes one, which a layer chip in its code picks."""
    roads, parks = _frame(LINE), _frame(SQUARES)
    roads.__dict__["metadata"] = {"name": "table_osm_roads"}
    parks.__dict__["metadata"] = {"name": "table_osm_parks"}
    with pytest.raises(ValueError) as refused:
        join([roads, parks], _frame(SQUARES))
    assert str(refused.value) == (
        "input_0 holds several layers (table_osm_roads, table_osm_parks): pick one with its layer chip, "
        "such as [!! input_0:table_osm_roads !!]."
    )


def test_an_unknown_operation_or_output_is_refused_listing_the_choices(join):
    """#576."""
    with pytest.raises(ValueError) as wrong:
        join(_frame(POINTS), _frame(SQUARES), operation="near")
    assert str(wrong.value) == (
        "The operation must be one of intersects, within, contains, touches, overlaps, crosses, nearest; got 'near'."
    )
    with pytest.raises(ValueError) as wrong:
        join(_frame(POINTS), _frame(SQUARES), output="polygons")
    assert str(wrong.value) == "The output must be one of pairs, counts; got 'polygons'."


def test_input_1_in_another_crs_is_reprojected_to_input_0s(join, capsys):
    """#576: input_1 in web mercator still pairs with input_0 in degrees."""
    from pyproj import Transformer

    to_mercator = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    corners = [to_mercator.transform(x, y) for x, y in [(-87.7, 41.8), (-87.6, 41.9)]]
    area = _frame([_box(corners[0][0], corners[0][1], corners[1][0], corners[1][1], area="Loop")], crs="EPSG:3857")
    photos = _frame([_point(-87.65, 41.85, photo="in"), _point(-87.5, 41.85, photo="out")], crs="EPSG:4326")
    result, _lines = _run(join, capsys, photos, area)
    assert _pairs(result, "photo", "area") == [("in", "Loop")]
    # The pairs keep input_0's coordinates, and say which system they are in.
    assert (result.geometry.iloc[0].x, result.geometry.iloc[0].y) == (-87.65, 41.85)
    assert result.crs.to_epsg() == 4326


def test_the_inputs_are_left_as_they_were(join, capsys):
    """The join reads its inputs and hands back new rows: a node's input is the
    output of the node that feeds it, which other nodes read too."""
    points, squares = _frame(POINTS), _frame(SQUARES)
    before = (points.to_json(), squares.to_json())
    _run(join, capsys, points, squares, output="counts")
    _run(join, capsys, points, squares, operation="nearest")
    assert (points.to_json(), squares.to_json()) == before


# ---------------------------------------------------------------------------
# The module and the node's code
# ---------------------------------------------------------------------------

def test_the_module_offers_spatial_join_and_says_what_it_does(join):
    """What node code calls is what the module's ``__all__`` names: a function
    it defines, whose docstring's first paragraph says what it does. It
    imports nothing of Curio's and calls no ``curio_`` function."""
    import importlib
    import inspect

    module = importlib.import_module(MODULE)
    assert list(module.__all__) == ["spatial_join"]
    public = sorted(
        attr for attr, value in vars(module).items()
        if inspect.isfunction(value) and value.__module__ == MODULE and not attr.startswith("_")
    )
    assert public == ["spatial_join"]
    first = " ".join((inspect.getdoc(module.spatial_join) or "").split("\n\n")[0].split())
    assert first == (
        "Pair each row of ``left`` with the rows of ``right`` whose shapes meet by ``operation``: "
        "intersects, within, contains, touches, overlaps, crosses or nearest."
    )
    tree = ast.parse(inspect.getsource(module))
    imported = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    imported += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in imported if name.split(".")[0] == "utk_curio"], imported
    assert not [node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id.startswith("curio_")]


def test_the_nodes_code_is_its_settings_and_a_short_call():
    """A node's logic is in functions of its package's modules, and its code
    holds its settings and a short call: the Spatial Join's is the import of
    ``spatial_join`` and the return of its call on both circles with its two
    widgets."""
    code = (PACKAGE / "sources" / "spatial-join.py").read_text(encoding="utf-8")
    assert "utk_curio" not in code
    body = ast.parse("def node():\n" + "\n".join("    " + line.replace("[!! ", "").replace(" !!]", "")
                                                 for line in code.splitlines())).body[0].body
    assert [type(statement).__name__ for statement in body] == ["ImportFrom", "Return"]
    assert ast.unparse(body[0]) == f"from {MODULE} import spatial_join"
    assert ast.unparse(body[1].value) == "spatial_join(input_0, input_1, operation=operation, output=output)"


def test_the_nodes_code_runs_as_the_sandbox_runs_it(join, capsys):
    """The template's code, its chips written as a run writes them from its
    widgets, run as the sandbox runs node code, on the two circles."""
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.util.input_names import call_as_node

    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    template = next(t for t in manifest["templates"] if t["id"] == "spatial-join")
    widgets = [{**template["widgets"][0], "value": "within"}, {**template["widgets"][1], "value": "counts"}]
    code, problems = resolve_references(
        (PACKAGE / "sources" / "spatial-join.py").read_text(encoding="utf-8"), widgets, "python",
        [{"slot": 0}, {"slot": 1}],
    )
    assert problems == []
    body = "\n".join("    " + line for line in code.splitlines())
    result = call_as_node(body, {}, [_frame(POINTS), _frame(SQUARES)], [0, 1])
    assert list(zip(result["square"], result["point_count"])) == [("A", 2), ("B", 1), ("C", 0)]
    assert capsys.readouterr().out.splitlines() == [
        "2 of 3 input_1 rows have pairs (3 in all); each row carries point_count.",
    ]
