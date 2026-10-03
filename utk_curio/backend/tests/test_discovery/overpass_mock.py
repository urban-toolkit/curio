"""Mock Overpass answers for the OpenStreetMap source's tests.

The tests run autk-db's own loader in Node (``providers/autark_osm.mjs``); only
its requests to Overpass are answered here, by what each query asks for. A rule
answers a query that contains every one of its ``when`` texts with its
``elements``, written as Overpass answers them (``out body`` for nodes and
relations, ``out geom`` for ways). The first rule that matches answers.

The loader reads the rules from ``fixtures/overpass/mock.json``, which this
module writes: ``python -m utk_curio.backend.tests.test_discovery.overpass_mock``.
A test checks that the file is current. Recorded answers in ``index.json`` are
looked up first, by exact request.

The elements are made up. They are not OpenStreetMap data.
"""

from __future__ import annotations

import json
from pathlib import Path

MOCK_FILE = Path(__file__).resolve().parent / "fixtures" / "overpass" / "mock.json"


def way(way_id: int, points: list[tuple[float, float]], first_node: int, tags: dict | None = None) -> dict:
    """A way through ``points`` (lon, lat), as ``out geom`` answers it; a closed way repeats its first point."""
    closed = points[0] == points[-1]
    nodes = [first_node + i for i in range(len(points) - (1 if closed else 0))]
    if closed:
        nodes.append(nodes[0])
    element = {
        "type": "way",
        "id": way_id,
        "nodes": nodes,
        "geometry": [{"lat": lat, "lon": lon} for lon, lat in points],
    }
    if tags:
        element["tags"] = tags
    return element


def square(way_id: int, box: tuple[float, float, float, float], first_node: int, tags: dict | None = None) -> dict:
    """A closed way around ``box`` (west, south, east, north)."""
    w, s, e, n = box
    return way(way_id, [(w, s), (e, s), (e, n), (w, n), (w, s)], first_node, tags)


def multipolygon(relation_id: int, outer: dict, tags: dict) -> dict:
    return {
        "type": "relation",
        "id": relation_id,
        "members": [{"type": "way", "ref": outer["id"], "role": "outer"}],
        "tags": {"type": "multipolygon", **tags},
    }


# Golf, Illinois, by name: a made-up boundary and features inside it.
GOLF_OUTLINE = square(9002, (-87.8, 42.05, -87.78, 42.062), 90000)
GOLF_BOUNDARY = [
    {
        "type": "relation",
        "id": 9001,
        "members": [{"type": "way", "ref": 9002, "role": "outer"}],
        "tags": {"type": "boundary", "boundary": "administrative", "admin_level": "8", "name": "Golf"},
    },
    GOLF_OUTLINE,
]

WOOD_OUTER = square(105, (-87.789, 42.052, -87.786, 42.055), 1050)
GOLF_PARKS_AND_WATER = [
    square(101, (-87.798, 42.052, -87.795, 42.054), 1010, {"leisure": "park", "name": "Golf Park"}),
    square(102, (-87.794, 42.052, -87.792, 42.054), 1020, {"landuse": "grass"}),
    square(103, (-87.791, 42.052, -87.79, 42.053), 1030, {"leisure": "playground"}),
    multipolygon(104, WOOD_OUTER, {"natural": "wood", "name": "Golf Woods"}),
    WOOD_OUTER,
    square(106, (-87.785, 42.052, -87.783, 42.054), 1060, {"natural": "water", "name": "Golf Pond"}),
]

GOLF_ROADS = [
    way(201, [(-87.799, 42.056), (-87.79, 42.0562), (-87.781, 42.056)], 2010,
        {"highway": "residential", "name": "Golf Road", "maxspeed": "25 mph", "lanes": "2"}),
    way(202, [(-87.79, 42.051), (-87.7902, 42.061)], 2020,
        {"highway": "secondary", "name": "Harms Road", "maxspeed": "35 mph", "lanes": "4"}),
    way(203, [(-87.797, 42.059), (-87.795, 42.0595)], 2030, {"highway": "service"}),
]

SCHOOL_OUTER = square(307, (-87.786, 42.058, -87.784, 42.0595), 3070)
GOLF_BUILDINGS = [
    square(301, (-87.7985, 42.0575, -87.798, 42.0578), 3010, {"building": "house", "height": "8"}),
    # A garage: autk-db leaves it out of the buildings layer.
    square(302, (-87.7975, 42.0575, -87.7972, 42.0577), 3020, {"building": "garage"}),
    # Two that share a wall (nodes 3030+1 and 3030+2): one Autark building.
    square(303, (-87.7965, 42.0575, -87.796, 42.0578), 3030, {"building": "yes", "building:levels": "2"}),
    way(304, [(-87.796, 42.0575), (-87.7957, 42.0575), (-87.7957, 42.0578), (-87.796, 42.0578), (-87.796, 42.0575)],
        3040, {"building:part": "yes", "height": "5"}),
    square(305, (-87.792, 42.0585, -87.7915, 42.059), 3050,
           {"building": "church", "name": "St. Golf", "building:levels": "1"}),
    multipolygon(306, SCHOOL_OUTER, {"building": "school", "name": "Golf School"}),
    SCHOOL_OUTER,
    # Two row houses, each its own building, that share a wall: one Autark building.
    square(308, (-87.789, 42.0605, -87.7885, 42.0608), 3080, {"building": "yes", "height": "7.1"}),
    square(309, (-87.7885, 42.0605, -87.788, 42.0608), 3090, {"building": "yes", "height": "6.4"}),
]
# Way 304 shares its first and fourth corners with way 303's east side.
GOLF_BUILDINGS[3]["nodes"] = [3031, 3041, 3042, 3032, 3031]
# Way 309 shares its first and fourth corners with way 308's east side.
GOLF_BUILDINGS[8]["nodes"] = [3081, 3091, 3092, 3082, 3081]

def node(node_id: int, lon: float, lat: float, tags: dict) -> dict:
    return {"type": "node", "id": node_id, "lat": lat, "lon": lon, "tags": tags}


#: The box the tag tests ask for, [west, south, east, north]: Chicago's Loop.
LOOP_BOX = [-87.6295, 41.8805, -87.615, 41.8825]
#: How autk-db writes that box into a query: (south,west,north,east).
LOOP_FILTER = "(41.8805,-87.6295,41.8825,-87.615)"

COLLEGE_OUTER = square(7202, (-87.625, 41.8815, -87.624, 41.8823), 72020)
LOOP_POINTS_OF_INTEREST = [
    node(7001, -87.628, 41.881, {"amenity": "cafe", "name": "Loop Cafe"}),
    node(7002, -87.627, 41.8815, {"shop": "books", "name": "Loop Books"}),
    node(7003, -87.6233, 41.882, {"tourism": "attraction", "name": "Cloud Sculpture"}),
    node(7004, -87.62, 41.8812, {"amenity": "bench"}),
    node(7005, -87.619, 41.8818, {"historic": "memorial", "name": "Loop Memorial"}),
    square(7101, (-87.626, 41.8806, -87.6255, 41.881), 71010,
           {"amenity": "parking", "name": "Loop Parking", "capacity": "120"}),
    square(7102, (-87.618, 41.8808, -87.616, 41.8822), 71020, {"leisure": "park", "name": "Loop Park"}),
    way(7103, [(-87.6175, 41.881), (-87.6165, 41.8815)], 71030, {"leisure": "track"}),
    multipolygon(7201, COLLEGE_OUTER, {"amenity": "college", "name": "Loop College"}),
    COLLEGE_OUTER,
]

STATE_STREET = way(7401, [(-87.6278, 41.8806), (-87.6278, 41.8815), (-87.6278, 41.8824)], 74010,
                   {"highway": "primary", "name": "State Street", "lanes": "4", "maxspeed": "30 mph"})
# Its middle vertex is a tagged crossing, which Overpass also lists as a node.
STATE_STREET["nodes"] = [74010, 7402, 74012]
LOOP_STREETS_AND_RAILS = [
    STATE_STREET,
    node(7402, -87.6278, 41.8815, {"highway": "crossing", "crossing": "traffic_signals"}),
    square(7403, (-87.623, 41.8806, -87.622, 41.8812), 74030,
           {"highway": "pedestrian", "area": "yes", "name": "Loop Plaza"}),
    square(7404, (-87.621, 41.8806, -87.6205, 41.881), 74040, {"highway": "service"}),
    way(7405, [(-87.6265, 41.8806), (-87.6265, 41.8824)], 74050, {"railway": "subway", "layer": "-1"}),
    node(7406, -87.6266, 41.8811, {"railway": "station", "name": "Loop Station"}),
]

GOLF_POINTS_OF_INTEREST = [
    node(8001, -87.7917, 42.0586, {"amenity": "place_of_worship", "name": "St. Golf Chapel"}),
    node(8002, -87.7955, 42.0565, {"shop": "convenience"}),
    square(8101, (-87.799, 42.059, -87.794, 42.0615), 81010, {"leisure": "golf_course", "name": "Golf Club"}),
]

RULES: list[dict] = [
    {"name": "loop-points-of-interest", "when": ["->.tagHits", LOOP_FILTER, 'node["amenity"]'],
     "elements": LOOP_POINTS_OF_INTEREST},
    {"name": "loop-streets-and-rails", "when": ["->.tagHits", LOOP_FILTER, 'node["highway"]', 'node["railway"]'],
     "elements": LOOP_STREETS_AND_RAILS},
    {"name": "golf-points-of-interest", "when": ["->.tagHits", 'relation["name"="Golf"]', 'node["amenity"]'],
     "elements": GOLF_POINTS_OF_INTEREST},
    # A tag nothing in the Loop has.
    {"name": "loop-no-lighthouse", "when": ["->.tagHits", LOOP_FILTER, 'node["man_made"="lighthouse"]'], "elements": []},
    {"name": "golf-boundary", "when": ["->.boundaryWays1", 'relation["name"="Golf"]'], "elements": GOLF_BOUNDARY},
    {"name": "golf-parks-and-water", "when": ['"leisure"', 'relation["name"="Golf"]'], "elements": GOLF_PARKS_AND_WATER},
    {"name": "golf-roads", "when": ['way["highway"]["area"!="yes"]', 'relation["name"="Golf"]'], "elements": GOLF_ROADS},
    {"name": "golf-buildings", "when": ['way["building"]', 'relation["name"="Golf"]'], "elements": GOLF_BUILDINGS},
    # No boundary has this name: every request for it gets an empty answer.
    {"name": "nowhere", "when": ['"Nowhere Land"'], "elements": []},
]


def rule(name: str) -> dict:
    return next(r for r in RULES if r["name"] == name)


def mock_document() -> dict:
    return {
        "note": "Made-up Overpass answers for tests, written by overpass_mock.py. Not OpenStreetMap data.",
        "answers": [{"when": r["when"], "elements": r["elements"]} for r in RULES],
    }


def write() -> None:
    MOCK_FILE.write_text(json.dumps(mock_document(), indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write()
