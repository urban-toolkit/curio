"""The one script that builds the examples' OpenStreetMap extracts.

``scripts/build_example_pbfs.py`` has an area for every
``docs/examples/data/*.osm.pbf`` (a place search or a box). It keeps every
feature in the area's box and cuts it there: a line as SCOUT cuts its road
graph, keeping its points inside and, where it crosses the edge, its first
point outside; a polygon clipped at the edge, with new points on it. Anything
outside is dropped. The boundary relations autk-db's loader clips to stay whole.

The cut runs here on small hand-made extracts, in a box from (0, 0) to (1, 1).
Then each committed extract is read (``_support/osm_pbf.py``, no pyosmium): it
holds, whole, each boundary relation the shipped specs that load it clip to,
it is the script's and records its box, and cutting it again at that box
changes nothing. A shipped spec whose area is a box (``queryArea.bbox``) loads
the box its extract is cut at.

The script is loaded inside each test: it must load without pyosmium, which
is not one of Curio's dependencies.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from utk_curio.backend.tests._support.osm_pbf import read_pbf

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "build_example_pbfs.py"
EXAMPLES = REPO_ROOT / "docs" / "examples"
DATA = EXAMPLES / "data"
#: South, west, north, east.
BOX = (0.0, 0.0, 1.0, 1.0)
#: SCOUT's weather routing box.
SCOUT_ROUTING_BOX = (41.859, -87.662, 41.898, -87.613)


def _script():
    spec = importlib.util.spec_from_file_location("_scripts_build_example_pbfs", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit as exc:
        raise AssertionError(f"the script must load without pyosmium: {exc}") from None
    return module


def _pbf_loads():
    """(dataflow, node id, extract path, queryArea) of every shipped node that loads a .pbf."""
    loads = []
    for path in sorted(EXAMPLES.rglob("*.json")):
        if "expected_outputs" in path.parts:
            continue
        try:
            flow = json.loads(path.read_text(encoding="utf-8")).get("dataflow")
        except (ValueError, AttributeError):
            continue
        if not isinstance(flow, dict):
            continue
        for node in flow.get("nodes", []):
            content = node.get("content")
            if not isinstance(content, str) or "pbfFileUrl" not in content:
                continue
            for source in json.loads(content).get("data", []):
                if source.get("pbfFileUrl"):
                    loads.append((path.relative_to(EXAMPLES).as_posix(), node["id"], source["pbfFileUrl"],
                                  source["queryArea"]))
    return loads


PBF_LOADS = _pbf_loads()
#: The loads whose area is named, by boundaries autk-db clips to: (dataflow,
#: node id, extract path, queryArea.areas). A box area names none.
NAMED_LOADS = [(dataflow, node_id, extract, tuple(area["areas"]))
               for dataflow, node_id, extract, area in PBF_LOADS if "bbox" not in area]
NAMED_LOAD_IDS = [f"{dataflow}:{node_id}" for dataflow, node_id, _extract, _names in NAMED_LOADS]
EXTRACTS = sorted(path.name for path in DATA.glob("*.osm.pbf"))


def _ring(nodes, refs):
    """A closed way's positions, from its lowest one on (rings compare by shape)."""
    assert refs[0] == refs[-1], f"{refs} is not closed"
    points = [nodes[r][:2] for r in refs[:-1]]
    start = points.index(min(points))
    return points[start:] + points[:start]


def _on_the_edge(point):
    (x, y) = point
    return x in (0.0, 1.0) or y in (0.0, 1.0)


def _square(x0, y0, x1, y1, first=1):
    """The four corners of a square as nodes, counterclockwise, and its closed refs."""
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    nodes = {first + i: (x, y, {}) for i, (x, y) in enumerate(corners)}
    return nodes, [first, first + 1, first + 2, first + 3, first]


def test_a_line_crossing_the_box_keeps_its_points_inside_and_its_first_point_outside():
    nodes = {1: (-2.0, 0.5, {}), 2: (-1.0, 0.5, {}), 3: (0.25, 0.5, {}), 4: (0.75, 0.5, {}),
             5: (1.5, 0.5, {}), 6: (3.0, 0.5, {})}
    ways = {10: ([1, 2, 3, 4, 5, 6], {"highway": "primary"})}

    kept_nodes, kept_ways, _ = _script().cut(nodes, ways, {}, BOX, ())

    assert kept_ways == {10: ([2, 3, 4, 5], {"highway": "primary"})}
    assert sorted(kept_nodes) == [2, 3, 4, 5]


def test_a_line_inside_the_box_is_unchanged():
    nodes = {1: (0.1, 0.1, {}), 2: (0.5, 0.5, {"highway": "crossing"}), 3: (0.9, 0.2, {})}
    ways = {10: ([1, 2, 3], {"highway": "service"})}

    kept_nodes, kept_ways, _ = _script().cut(nodes, ways, {}, BOX, ())

    assert kept_ways == ways
    assert kept_nodes == nodes


def test_a_line_outside_the_box_is_dropped_with_its_points():
    nodes = {1: (2.0, 2.0, {}), 2: (3.0, 2.0, {}), 3: (0.2, 0.2, {}), 4: (0.4, 0.4, {})}
    ways = {10: ([1, 2], {"highway": "path"}), 11: ([3, 4], {"highway": "path"})}

    kept_nodes, kept_ways, _ = _script().cut(nodes, ways, {}, BOX, ())

    assert sorted(kept_ways) == [11]
    assert sorted(kept_nodes) == [3, 4]


def test_a_line_passing_the_box_with_no_point_inside_is_dropped():
    # SCOUT keeps a road's point outside only next to a point inside.
    nodes = {1: (-0.5, 0.5, {}), 2: (1.5, 0.5, {})}
    ways = {10: ([1, 2], {"highway": "primary"})}

    kept_nodes, kept_ways, _ = _script().cut(nodes, ways, {}, BOX, ())

    assert kept_ways == {}
    assert kept_nodes == {}


def test_a_line_that_leaves_the_box_and_comes_back_becomes_one_line_per_part():
    nodes = {1: (0.2, 0.5, {}), 2: (0.8, 0.5, {}), 3: (1.5, 0.5, {}), 4: (2.0, 0.5, {}),
             5: (2.0, 0.8, {}), 6: (1.5, 0.8, {}), 7: (0.8, 0.8, {})}
    ways = {10: ([1, 2, 3, 4, 5, 6, 7], {"highway": "tertiary", "name": "Loop Road"})}

    kept_nodes, kept_ways, _ = _script().cut(nodes, ways, {}, BOX, ())

    assert kept_ways == {
        10: ([1, 2, 3], {"highway": "tertiary", "name": "Loop Road"}),
        11: ([6, 7], {"highway": "tertiary", "name": "Loop Road"}),
    }
    assert sorted(kept_nodes) == [1, 2, 3, 6, 7]


def test_a_polygon_crossing_the_box_is_clipped_at_its_edge_with_new_points_on_it():
    nodes, refs = _square(0.5, 0.5, 1.5, 1.5)
    ways = {20: (refs, {"building": "yes"})}

    kept_nodes, kept_ways, _ = _script().cut(nodes, ways, {}, BOX, ())

    assert list(kept_ways) == [20] and kept_ways[20][1] == {"building": "yes"}
    assert _ring(kept_nodes, kept_ways[20][0]) == [(0.5, 0.5), (1.0, 0.5), (1.0, 1.0), (0.5, 1.0)]
    new = set(kept_nodes) - set(nodes)
    assert len(new) == 3 and all(_on_the_edge(kept_nodes[i][:2]) for i in new)
    assert 1 in kept_nodes and not {2, 3, 4} & set(kept_nodes)


def test_a_polygon_inside_the_box_is_unchanged_and_one_outside_is_dropped():
    # The one inside runs clockwise, as a way may: it is kept as it is.
    nodes = {1: (0.2, 0.2, {}), 2: (0.2, 0.6, {}), 3: (0.6, 0.6, {}), 4: (0.6, 0.2, {}),
             5: (2.0, 2.0, {}), 6: (3.0, 2.0, {}), 7: (3.0, 3.0, {})}
    ways = {20: ([1, 2, 3, 4, 1], {"building": "yes"}), 21: ([5, 6, 7, 5], {"building": "yes"})}

    kept_nodes, kept_ways, _ = _script().cut(nodes, ways, {}, BOX, ())

    assert kept_ways == {20: ([1, 2, 3, 4, 1], {"building": "yes"})}
    assert sorted(kept_nodes) == [1, 2, 3, 4]


def test_a_polygon_over_the_box_edge_with_no_point_inside_is_clipped_to_the_box():
    nodes = {1: (-0.5, 0.4, {}), 2: (-0.5, -1.0, {}), 3: (1.5, -1.0, {}), 4: (1.5, 0.4, {})}
    ways = {20: ([1, 2, 3, 4, 1], {"landuse": "grass"})}

    kept_nodes, kept_ways, _ = _script().cut(nodes, ways, {}, BOX, ())

    assert _ring(kept_nodes, kept_ways[20][0]) == [(0.0, 0.0), (1.0, 0.0), (1.0, 0.4), (0.0, 0.4)]


def test_a_polygon_wrapping_round_two_box_corners_takes_both():
    nodes, refs = _square(0.5, -0.5, 1.5, 1.5)
    ways = {20: (refs, {"landuse": "grass"})}

    kept_nodes, kept_ways, _ = _script().cut(nodes, ways, {}, BOX, ())

    assert _ring(kept_nodes, kept_ways[20][0]) == [(0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)]


def test_a_polygon_cut_across_a_box_corner_keeps_the_corner():
    # The triangle's long side runs across the south-east corner.
    nodes = {1: (0.4, -0.1, {}), 2: (1.5, -0.1, {}), 3: (1.5, 1.1, {})}
    ways = {20: ([1, 2, 3, 1], {"landuse": "grass"})}

    kept_nodes, kept_ways, _ = _script().cut(nodes, ways, {}, BOX, ())

    assert _ring(kept_nodes, kept_ways[20][0]) == [(0.4916667, 0.0), (1.0, 0.0), (1.0, 0.5545455)]


def test_a_polygon_covering_the_box_is_clipped_to_the_box():
    nodes, refs = _square(-1.0, -1.0, 2.0, 2.0)
    ways = {20: (refs, {"landuse": "residential"})}

    kept_nodes, kept_ways, _ = _script().cut(nodes, ways, {}, BOX, ())

    assert _ring(kept_nodes, kept_ways[20][0]) == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def test_a_polygon_outside_that_only_touches_the_box_edge_is_dropped():
    # Two buildings share a wall on the box's south edge; only the one inside stays.
    nodes = {1: (0.3, 0.0, {}), 2: (0.7, 0.0, {}), 3: (0.7, 0.4, {}), 4: (0.3, 0.4, {}),
             5: (0.7, -0.5, {}), 6: (0.3, -0.5, {})}
    ways = {20: ([1, 2, 3, 4, 1], {"building": "yes"}), 21: ([2, 1, 6, 5, 2], {"building": "yes"})}

    _, kept_ways, _ = _script().cut(nodes, ways, {}, BOX, ())

    assert kept_ways == {20: ([1, 2, 3, 4, 1], {"building": "yes"})}


def test_a_polygon_the_box_cuts_in_two_becomes_one_multipolygon_of_the_pieces():
    # A U whose bottom is below the box: its two arms are left.
    u = [(0.1, -0.5), (0.9, -0.5), (0.9, 0.5), (0.7, 0.5), (0.7, -0.2), (0.3, -0.2), (0.3, 0.5), (0.1, 0.5)]
    nodes = {i + 1: (x, y, {}) for i, (x, y) in enumerate(u)}
    ways = {20: ([1, 2, 3, 4, 5, 6, 7, 8, 1], {"building": "yes"})}

    kept_nodes, kept_ways, kept_relations = _script().cut(nodes, ways, {}, BOX, ())

    assert 20 not in kept_ways
    ((members, tags),) = kept_relations.values()
    assert tags == {"building": "yes", "type": "multipolygon"}
    assert [role for _t, _ref, role in members] == ["outer", "outer"]
    assert all(kept_ways[ref][1] == {} for _t, ref, _role in members)
    assert sorted(_ring(kept_nodes, kept_ways[ref][0]) for _t, ref, _role in members) == [
        [(0.1, 0.0), (0.3, 0.0), (0.3, 0.5), (0.1, 0.5)],
        [(0.7, 0.0), (0.9, 0.0), (0.9, 0.5), (0.7, 0.5)],
    ]


def test_a_multipolygon_crossing_the_box_is_clipped_with_its_rings_assembled_and_its_hole_kept():
    # The outer ring is two open ways; the hole is a closed way inside the box.
    nodes = {1: (-0.5, -0.5, {}), 2: (0.5, -0.5, {}), 3: (0.5, 0.8, {}), 4: (-0.5, 0.8, {}),
             5: (0.1, 0.1, {}), 6: (0.3, 0.1, {}), 7: (0.3, 0.3, {}), 8: (0.1, 0.3, {})}
    ways = {30: ([1, 2, 3], {}), 31: ([3, 4, 1], {}), 32: ([5, 6, 7, 8, 5], {})}
    tags = {"type": "multipolygon", "natural": "water"}
    relations = {40: ([("w", 30, "outer"), ("w", 31, "outer"), ("w", 32, "inner")], tags)}

    kept_nodes, kept_ways, kept_relations = _script().cut(nodes, ways, relations, BOX, ())

    members, kept_tags = kept_relations[40]
    assert kept_tags == tags
    assert [role for _t, _ref, role in members] == ["outer", "inner"]
    (outer, inner) = (kept_ways[ref][0] for _t, ref, _role in members)
    assert _ring(kept_nodes, outer) == [(0.0, 0.0), (0.5, 0.0), (0.5, 0.8), (0.0, 0.8)]
    # The hole keeps its nodes, clockwise.
    assert set(inner) == {5, 6, 7, 8}
    assert _ring(kept_nodes, inner) == [(0.1, 0.1), (0.1, 0.3), (0.3, 0.3), (0.3, 0.1)]
    # The member ways that only drew the multipolygon go with it.
    assert not {30, 31, 32} & set(kept_ways)


def test_a_hole_across_the_box_edge_notches_the_polygon_that_covers_the_box():
    nodes = {1: (-1.0, -1.0, {}), 2: (2.0, -1.0, {}), 3: (2.0, 2.0, {}), 4: (-1.0, 2.0, {}),
             5: (-0.5, 0.25, {}), 6: (0.5, 0.25, {}), 7: (0.5, 0.75, {}), 8: (-0.5, 0.75, {})}
    ways = {30: ([1, 2, 3], {}), 31: ([3, 4, 1], {}), 32: ([5, 6, 7, 8, 5], {})}
    relations = {40: ([("w", 30, "outer"), ("w", 31, "outer"), ("w", 32, "inner")],
                      {"type": "multipolygon", "leisure": "park"})}

    kept_nodes, kept_ways, kept_relations = _script().cut(nodes, ways, relations, BOX, ())

    ((_t, ref, role),) = kept_relations[40][0]
    assert role == "outer"
    assert _ring(kept_nodes, kept_ways[ref][0]) == [
        (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.75), (0.5, 0.75), (0.5, 0.25), (0.0, 0.25),
    ]


def test_a_multipolygon_whose_ways_do_not_close_is_kept_whole_where_it_reaches_the_box():
    nodes = {1: (-0.5, 0.5, {}), 2: (0.5, 0.5, {}), 3: (0.5, 2.0, {}), 4: (3.0, 3.0, {}), 5: (4.0, 3.0, {})}
    ways = {30: ([1, 2, 3], {}), 31: ([4, 5], {})}
    relations = {40: ([("w", 30, "outer"), ("w", 31, "outer")], {"type": "multipolygon", "natural": "wood"})}

    kept_nodes, kept_ways, kept_relations = _script().cut(nodes, ways, relations, BOX, ())

    assert kept_relations == relations
    assert kept_ways == ways
    assert kept_nodes == nodes


def test_a_building_relation_keeps_its_clipped_parts_and_loses_those_outside():
    nodes, outline = _square(0.5, 0.5, 1.5, 0.8)
    far, part = _square(2.0, 2.0, 3.0, 3.0, first=5)
    nodes.update(far)
    ways = {81: (outline, {"building": "yes"}), 82: (part, {"building:part": "yes"})}
    relations = {80: ([("w", 81, "outline"), ("w", 82, "part")], {"type": "building"})}

    kept_nodes, kept_ways, kept_relations = _script().cut(nodes, ways, relations, BOX, ())

    assert kept_relations == {80: ([("w", 81, "outline")], {"type": "building"})}
    assert _ring(kept_nodes, kept_ways[81][0]) == [(0.5, 0.5), (1.0, 0.5), (1.0, 0.8), (0.5, 0.8)]
    assert 82 not in kept_ways


def test_an_untagged_closed_way_a_building_relation_lists_is_clipped_as_a_polygon():
    """A closed way with no tags is a polygon when a building relation lists it,
    as River North Point's part (way 1276517180) in the Loop's box: the box
    clips it, and never cuts it open as a line."""
    nodes = {1: (0.5, 0.5, {}), 2: (1.5, 0.5, {}), 3: (2.0, 0.65, {}), 4: (1.5, 0.8, {}), 5: (0.5, 0.8, {})}
    ways = {81: ([1, 2, 3, 4, 5, 1], {})}
    relations = {80: ([("w", 81, "part")], {"type": "building"})}

    kept_nodes, kept_ways, kept_relations = _script().cut(nodes, ways, relations, BOX, ())

    assert kept_relations == relations
    assert list(kept_ways) == [81] and kept_ways[81][1] == {}
    assert _ring(kept_nodes, kept_ways[81][0]) == [(0.5, 0.5), (1.0, 0.5), (1.0, 0.8), (0.5, 0.8)]


def test_neighbours_clipped_at_one_place_share_its_new_node():
    nodes = {1: (0.5, 0.2, {}), 2: (1.5, 0.2, {}), 3: (1.5, 0.5, {}), 4: (0.5, 0.5, {}),
             5: (1.5, 0.8, {}), 6: (0.5, 0.8, {})}
    ways = {20: ([1, 2, 3, 4, 1], {"building": "yes"}), 21: ([4, 3, 5, 6, 4], {"building": "yes"})}

    kept_nodes, kept_ways, _ = _script().cut(nodes, ways, {}, BOX, ())

    shared = set(kept_ways[20][0]) & set(kept_ways[21][0])
    assert sorted(kept_nodes[r][:2] for r in shared) == [(0.5, 0.5), (1.0, 0.5)]


def test_a_closed_road_is_cut_as_a_line_not_clipped_as_a_polygon():
    nodes = {1: (0.5, 0.5, {}), 2: (2.0, 0.5, {}), 3: (3.0, 0.5, {}), 4: (3.0, 3.0, {}), 5: (2.0, 3.0, {})}
    tags = {"highway": "primary", "junction": "roundabout"}
    ways = {10: ([1, 2, 3, 4, 5, 1], tags)}

    _, kept_ways, _ = _script().cut(nodes, ways, {}, BOX, ())

    assert kept_ways == {10: ([1, 2], tags), 11: ([5, 1], tags)}


def test_the_boundary_relation_the_specs_clip_to_is_kept_whole():
    nodes = {1: (0.5, 0.5, {}), 2: (0.5, 3.0, {}), 3: (3.0, 3.0, {}), 4: (3.0, 0.5, {}),
             5: (5.0, 5.0, {}), 6: (6.0, 5.0, {})}
    ways = {50: ([1, 2, 3], {}), 51: ([3, 4, 1], {}), 52: ([5, 6], {})}
    relations = {
        60: ([("w", 50, "outer"), ("w", 51, "outer")],
             {"type": "boundary", "boundary": "administrative", "name": "Loop"}),
        61: ([("w", 52, "outer"), ("w", 50, "outer")],
             {"type": "boundary", "boundary": "administrative", "name": "Chicago"}),
    }

    _, kept_ways, kept_relations = _script().cut(nodes, ways, relations, BOX, ("Loop",))

    assert kept_relations[60] == relations[60]
    assert kept_ways[50] == ways[50] and kept_ways[51] == ways[51]
    # Another boundary is not kept whole: its far member goes.
    assert 52 not in kept_ways
    assert kept_relations[61] == ([("w", 50, "outer")], relations[61][1])


def test_a_tagged_point_inside_the_box_is_kept_and_points_outside_or_untagged_are_dropped():
    nodes = {1: (0.5, 0.5, {"amenity": "cafe"}), 2: (2.0, 2.0, {"amenity": "cafe"}), 3: (0.5, 0.6, {})}

    kept_nodes, _, _ = _script().cut(nodes, {}, {}, BOX, ())

    assert kept_nodes == {1: (0.5, 0.5, {"amenity": "cafe"})}


def test_a_relation_keeps_only_its_kept_members_and_goes_with_none():
    nodes = {1: (0.2, 0.5, {}), 2: (1.5, 0.5, {}), 3: (2.0, 0.5, {}), 4: (3.0, 3.0, {}), 5: (4.0, 3.0, {}),
             6: (0.5, 0.5, {"highway": "bus_stop"})}
    ways = {10: ([1, 2, 3], {"highway": "primary"}), 11: ([4, 5], {"highway": "primary"})}
    relations = {
        70: ([("n", 6, "stop"), ("w", 10, ""), ("w", 11, "")], {"type": "route", "route": "bus"}),
        71: ([("w", 11, "")], {"type": "route", "route": "bicycle"}),
    }

    _, kept_ways, kept_relations = _script().cut(nodes, ways, relations, BOX, ())

    assert kept_ways == {10: ([1, 2], {"highway": "primary"})}
    assert kept_relations == {70: ([("n", 6, "stop"), ("w", 10, "")], {"type": "route", "route": "bus"})}


def test_a_relation_lists_every_part_of_a_way_the_box_splits():
    # An untagged way of a boundary the specs do not name leaves the box and comes back.
    nodes = {1: (0.2, 0.5, {}), 2: (0.8, 0.5, {}), 3: (1.5, 0.5, {}), 4: (2.0, 0.5, {}),
             5: (2.0, 0.8, {}), 6: (1.5, 0.8, {}), 7: (0.8, 0.8, {})}
    ways = {10: ([1, 2, 3, 4, 5, 6, 7], {})}
    tags = {"type": "boundary", "boundary": "administrative", "name": "Elsewhere"}
    relations = {70: ([("w", 10, "outer")], tags)}

    _, kept_ways, kept_relations = _script().cut(nodes, ways, relations, BOX, ())

    assert kept_ways == {10: ([1, 2, 3], {}), 11: ([6, 7], {})}
    assert kept_relations == {70: ([("w", 10, "outer"), ("w", 11, "outer")], tags)}


def test_every_shipped_extract_is_an_area_of_the_script():
    areas = _script().AREAS

    assert EXTRACTS == sorted(f"{key}.osm.pbf" for key in areas)


def test_scouts_routing_box_is_an_area_with_the_chicago_boundary():
    areas = _script().AREAS

    assert [(area.box, area.boundaries) for area in areas.values() if area.box == SCOUT_ROUTING_BOX] == [
        (SCOUT_ROUTING_BOX, ("Chicago",)),
    ]


@pytest.mark.parametrize("dataflow, node_id, extract, names", NAMED_LOADS, ids=NAMED_LOAD_IDS)
def test_the_script_carries_every_boundary_a_spec_clips_to(dataflow, node_id, extract, names):
    areas = _script().AREAS
    key = Path(extract).name.removesuffix(".osm.pbf")

    assert key in areas, f"{dataflow} ({node_id}) loads {extract}, which no area of the script builds"
    assert set(names) <= set(areas[key].boundaries)


@pytest.mark.parametrize("name", EXTRACTS)
def test_every_committed_extract_is_the_scripts(name):
    """Every committed extract is one the script built: its header names the
    script, the date of the data and the box it was cut at, and cutting it
    again at that box changes nothing."""
    script = _script()
    key = name.removesuffix(".osm.pbf")
    area = script.AREAS.get(key)
    assert area is not None, f"no area of the script builds {name}"
    extract = read_pbf(DATA / name)

    assert extract.generator == script.GENERATOR
    assert extract.timestamp, "the header records the date of the data"
    assert extract.box is not None, "the header records the box the extract was cut at"
    if area.box is not None:
        assert extract.box == pytest.approx(area.box, abs=1e-7)
    assert script.cut(extract.nodes, extract.ways, extract.relations, extract.box, area.boundaries) == (
        extract.nodes, extract.ways, extract.relations,
    ), "cutting the extract again at its box changes it"


def test_a_box_spec_loads_the_box_its_extract_is_cut_at_or_one_inside_it():
    """A shipped spec whose area is a box (``queryArea.bbox``: west, south,
    east, north) loads the box its extract is cut at, the box the extract's
    header records, or a box inside it, so the extract holds every feature
    the load keeps. chicago-rain-wind-routing's loader and chicago-loop-layers'
    OpenStreetMap layers load SCOUT's routing box, their extract's own. The
    park shade test dataflow's loader loads two boxes of Lower Manhattan's
    extract: its parks' box, and the box of the buildings around them, which
    reaches the extract's edge."""
    boxes = [(dataflow, node_id, extract, area["bbox"])
             for dataflow, node_id, extract, area in PBF_LOADS if "bbox" in area]

    assert [(dataflow, extract) for dataflow, _node_id, extract, _bbox in boxes] == [
        ("dataflows/chicago-loop-layers.json", "docs/examples/data/chicago_downtown.osm.pbf"),
        ("dataflows/chicago-rain-wind-routing.json", "docs/examples/data/chicago_downtown.osm.pbf"),
        ("dataflows/lower-manhattan-park-shade.json", "docs/examples/data/lower_mnt.osm.pbf"),
        ("dataflows/lower-manhattan-park-shade.json", "docs/examples/data/lower_mnt.osm.pbf"),
    ]
    for dataflow, node_id, extract, (west, south, east, north) in boxes:
        cut = read_pbf(REPO_ROOT / extract).box
        if dataflow in ("dataflows/chicago-loop-layers.json", "dataflows/chicago-rain-wind-routing.json"):
            assert cut == pytest.approx((south, west, north, east), abs=1e-7), (
                f"{dataflow} ({node_id}) loads the box {[west, south, east, north]}, not the box {extract} is cut at"
            )
            continue
        cut_south, cut_west, cut_north, cut_east = cut
        inside = (cut_west - 1e-7 <= west < east <= cut_east + 1e-7
                  and cut_south - 1e-7 <= south < north <= cut_north + 1e-7)
        assert inside, (
            f"{dataflow} ({node_id}) loads the box {[west, south, east, north]}, "
            f"outside the box {extract} is cut at, {cut}"
        )


@pytest.mark.parametrize("dataflow, node_id, extract, names", NAMED_LOADS, ids=NAMED_LOAD_IDS)
def test_each_spec_finds_its_boundary_relations_whole_in_its_extract(dataflow, node_id, extract, names):
    data = read_pbf(REPO_ROOT / extract)

    for name in names:
        boundaries = [(members, tags) for members, tags in data.relations.values()
                      if "boundary" in tags and tags.get("name") == name]
        assert boundaries, f"{extract} has no boundary relation named {name!r} ({dataflow}, {node_id})"
        for members, _tags in boundaries:
            way_refs = [ref for kind, ref, _role in members if kind == "w"]
            assert way_refs, f"{name!r} in {extract} has no member ways"
            assert all(ref in data.ways for ref in way_refs), f"{name!r} in {extract} misses member ways"
            assert all(node in data.nodes for ref in way_refs for node in data.ways[ref][0]), (
                f"{name!r} in {extract} misses nodes of its ways"
            )
