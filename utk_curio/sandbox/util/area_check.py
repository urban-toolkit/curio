"""Whether autk-db would load an area a Map Editor edit gives (#1112, #1121).

autk-db checks each building it loads with GEOS's ``ST_IsValid``, on the
coordinates the map hands it, and refuses the whole layer for one shape that
fails: the map then draws none of it. So the node's map tools refuse such a
gesture, and a run skips such an edit, typed into the node's code, written by
an agent or put back from Provenance (``feature_edits``). Its twin is
``utils/editFeatures/areaCheck.ts`` in the frontend, which the map's tools and
its preview check with; both read the cases in
``utils/editFeatures/areaCheck.cases.json``, so they refuse the same areas.

A shape is checked as autk-db gets it: in its layer's own coordinates, rounded
by the map's own grid (``snapSourceToGrid`` in ``utils/geoPrecision.ts``),
each test exact on the numbers GEOS reads. An area is refused for a ring whose
sides cross or touch, a ring with no area, a hole that crosses or leaves its
outline (or overlaps another hole, or cuts the area in two with the rings it
touches), and two parts that overlap. What GEOS accepts passes: neighbouring
sides meeting at the corner they share, a corner repeated where it is, a hole
touching its outline at one point, parts touching at corners. Lines and points
are not checked.
"""
from __future__ import annotations

import math
import re

#: Why an area would be refused: a ring whose sides cross or touch, a ring
#: with no area, a hole that crosses or leaves its outline, two parts that
#: overlap (``AreaProblem`` in ``areaCheck.ts``).
CROSSES = "crosses"
FLAT = "flat"
HOLE = "hole"
OVERLAP = "overlap"

#: The map's grid: 1 cm in metres (EPSG:3395, the workspace CRS), and about
#: 1 cm at the equator in degrees (EPSG:4326) (``utils/geoPrecision.ts``).
GRID_METERS = 0.01
GRID_DEGREES = 1e-7

#: Longitude and latitude bounds, outside which coordinates are not degrees,
#: and how many shapes of a layer its coordinate format is read from
#: (``utils/geoCrs.ts``).
_LON_MAX = 180
_LAT_MAX = 90
_SAMPLE = 5
_EPSG = re.compile(r"EPSG:{1,2}(\d+)", re.IGNORECASE)
_DEGREES = re.compile(r"(^|:)4326$")

#: How two sides, or two rings, meet when they cross or run along each other.
_CROSS = "cross"


def area_problem(geometry, coordinate_format=None):
    """Why *geometry*, a GeoJSON shape of a layer whose coordinates are in
    *coordinate_format* (autk-db's, as ``layer_format`` reads it; EPSG:4326
    when None), would be refused once the map hands it to autk-db; None when it
    would load, or is not an area."""
    if not _is_area(geometry):
        return None
    return shape_problem(_on_the_grid(geometry, coordinate_format))


def made_problem(fc, before, after):
    """The problem *after*, a shape of the layer *fc*, would bring that
    *before*, the shape it replaces (None for a feature added), does not have;
    None when it brings none. A shape its layer already holds with a problem,
    which a layer autk-db does not check can, still takes every change, as the
    map's tools let it (``madeProblem`` in ``areaCheck.ts``)."""
    problem = area_problem(after, layer_format(fc, after)) if after else None
    if problem and before and area_problem(before, layer_format(fc, before)):
        return None
    return problem


def shape_problem(geometry):
    """Why *geometry* would be refused as it is, its coordinates exactly as
    given, before any rounding; None when it would load, or is not an area."""
    if not _is_area(geometry):
        return None
    coordinates = geometry.get("coordinates")
    parts = _exactly([coordinates] if geometry["type"] == "Polygon" else coordinates)
    if parts is None:
        return None
    rings = [ring for part in parts for ring in part]
    if any(_flat(ring) for ring in rings):
        return FLAT
    met = _meetings(rings)
    if met == CROSSES:
        return CROSSES
    # Each part's rings are numbered after the rings of the parts before it.
    firsts = [sum(len(part) for part in parts[:p]) for p in range(len(parts))]
    if any(_hole_problem(part, firsts[p], met) for p, part in enumerate(parts)):
        return HOLE
    for p in range(len(parts)):
        for q in range(p + 1, len(parts)):
            if _overlap(parts[p], firsts[p], parts[q], firsts[q], met):
                return OVERLAP
    return None


def layer_format(fc, geometry):
    """The coordinate format the map hands autk-db the layer *fc* in
    (``detect_coordinate_format``), for a shape of it, *geometry*: read from
    the layer's features, or from the shape while the layer has none
    (``layerFormat`` in ``areaCheck.ts``)."""
    fc = fc if isinstance(fc, dict) else {}
    features = fc.get("features")
    if not isinstance(features, list) or not features:
        features = [{"type": "Feature", "properties": {}, "geometry": geometry}]
    return detect_coordinate_format({**fc, "features": features})


def detect_coordinate_format(fc):
    """autk-db's ``coordinateFormat`` for the FeatureCollection *fc*, as the map
    reads a layer (``detectCoordinateFormat`` in ``utils/geoCrs.ts``): the EPSG
    code its ``crs`` names, else EPSG:3395 when a coordinate of its first
    shapes lies outside longitude and latitude, else EPSG:4326."""
    fc = fc if isinstance(fc, dict) else {}
    crs = fc.get("crs")
    properties = crs.get("properties") if isinstance(crs, dict) else None
    name = properties.get("name") if isinstance(properties, dict) else None
    match = _EPSG.search(name) if isinstance(name, str) else None
    if match:
        return f"EPSG:{int(match.group(1))}"
    features = fc.get("features") if isinstance(fc.get("features"), list) else []
    geometries = [f.get("geometry") for f in features[:_SAMPLE] if isinstance(f, dict) and f.get("geometry")]
    for geometry in geometries:
        coordinate = _first_coordinate(geometry)
        if coordinate is None or len(coordinate) < 2:
            continue
        x, y = coordinate[0], coordinate[1]
        if _finite(x) and _finite(y) and (abs(x) > _LON_MAX or abs(y) > _LAT_MAX):
            return "EPSG:3395"
    return "EPSG:4326"


def _first_coordinate(value):
    """The first position inside a geometry or a nesting of coordinates,
    looking into a GeometryCollection's geometries too (``firstCoordinate``)."""
    if isinstance(value, dict):
        if isinstance(value.get("geometries"), list):
            for geometry in value["geometries"]:
                found = _first_coordinate(geometry)
                if found:
                    return found
            return None
        if "coordinates" in value:
            return _first_coordinate(value["coordinates"])
        return None
    if not isinstance(value, (list, tuple)) or len(value) == 0:
        return None
    if _number(value[0]):
        return value
    return _first_coordinate(value[0])


def _is_area(geometry) -> bool:
    return isinstance(geometry, dict) and geometry.get("type") in ("Polygon", "MultiPolygon")


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _finite(value) -> bool:
    return _number(value) and math.isfinite(value)


def _js_round(value):
    """*value* rounded as JavaScript's ``Math.round`` does: to the nearest whole
    number, a half toward +infinity. Python's ``round`` takes a half to the
    even one, which moves a corner the map's grid keeps."""
    whole = math.floor(value)
    return whole + 1 if value - whole >= 0.5 else whole


def _on_the_grid(geometry, coordinate_format):
    """*geometry* as autk-db gets it: each coordinate rounded by the map's own
    grid for *coordinate_format* (``snapSourceToGrid``)."""
    grid = GRID_DEGREES if _DEGREES.search("EPSG:4326" if coordinate_format is None else str(coordinate_format)) else GRID_METERS
    scale = _js_round(1 / grid)

    def snap(value):
        if _number(value):
            return _js_round(float(value) * scale) / scale if math.isfinite(value) else value
        if isinstance(value, (list, tuple)):
            return [snap(item) for item in value]
        return value

    return {**geometry, "coordinates": snap(geometry.get("coordinates"))}


def _exactly(polygons):
    """*polygons*, an area's parts as GeoJSON holds them, with each coordinate a
    whole number: the coordinate times the least power of two that makes every
    coordinate whole, times two more, so the middle of two corners is whole
    too. None when a ring is not a list of positions of finite numbers."""
    if not isinstance(polygons, (list, tuple)):
        return None
    numbers = []
    for rings in polygons:
        if not isinstance(rings, (list, tuple)):
            return None
        for ring in rings:
            if not isinstance(ring, (list, tuple)):
                return None
            for position in ring:
                if not isinstance(position, (list, tuple)) or len(position) < 2:
                    return None
                if not _finite(position[0]) or not _finite(position[1]):
                    return None
                numbers.extend((position[0], position[1]))
    # Every coordinate is a whole number over a power of two, so the largest
    # of those powers makes each of them whole.
    scale = 2 * max((value.as_integer_ratio()[1] for value in numbers), default=1)

    def whole(value):
        top, bottom = value.as_integer_ratio()
        return top * (scale // bottom)

    return [
        [_corners_of([(whole(position[0]), whole(position[1])) for position in ring]) for ring in rings]
        for rings in polygons
    ]


def _distinct(points):
    """*points*, each once, in their order."""
    out = []
    for point in points:
        if point not in out:
            out.append(point)
    return out


def _corners_of(points):
    """*points* as a ring's corners: none repeated next to itself, and the
    corner that closes it dropped."""
    out = []
    for point in points:
        if not out or out[-1] != point:
            out.append(point)
    while len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def _turn(a, b, c) -> int:
    """Which side of the line from *a* to *b* the point *c* is on: 1 to its
    left, -1 to its right, 0 on it."""
    d = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return 1 if d > 0 else -1 if d < 0 else 0


def _between(u, v, w) -> bool:
    return u <= w <= v or v <= w <= u


def _on_side(a, b, p) -> bool:
    """Whether *p* lies on the side from *a* to *b*, its ends included."""
    return _between(a[0], b[0], p[0]) and _between(a[1], b[1], p[1]) and _turn(a, b, p) == 0


def _meeting(a, b, c, d):
    """Where the sides *a*-*b* and *c*-*d* meet: ``_CROSS`` when they cross or
    run along each other (share two points), else the point where one touches
    the other, or none."""
    if _turn(a, b, c) * _turn(a, b, d) < 0 and _turn(c, d, a) * _turn(c, d, b) < 0:
        return _CROSS
    touching = _distinct([p for p in (c, d) if _on_side(a, b, p)] + [p for p in (a, b) if _on_side(c, d, p)])
    return _CROSS if len(touching) > 1 else touching


def _flat(ring) -> bool:
    """Whether *ring* encloses no area: fewer than three corners, or all of
    them on one line."""
    return len(ring) < 3 or all(_turn(ring[0], ring[1], p) == 0 for p in ring)


def _meetings(rings):
    """How the sides of *rings* meet, each pair whose boxes meet looked at
    exactly: ``CROSSES`` when two sides of one ring meet that are not
    neighbours, or two neighbours run back along each other; else how each
    two rings that meet do, by ``(i, j)``, the lower number first."""
    sides = []
    for r, ring in enumerate(rings):
        for at, a in enumerate(ring):
            b = ring[(at + 1) % len(ring)]
            sides.append((min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1]), a, b, r, at))
    sides.sort(key=lambda side: side[0])
    met = {}
    for i, (x0, x1, y0, y1, a, b, ring, at) in enumerate(sides):
        for t_x0, _t_x1, t_y0, t_y1, c, d, t_ring, t_at in sides[i + 1:]:
            if t_x0 > x1:
                break
            if t_y0 > y1 or y0 > t_y1:
                continue
            here = _meeting(a, b, c, d)
            if ring == t_ring:
                gap = abs(at - t_at)
                neighbours = gap == 1 or gap == len(rings[ring]) - 1
                if here == _CROSS or (not neighbours and here):
                    return CROSSES
                continue
            if here != _CROSS and not here:
                continue
            key = (min(ring, t_ring), max(ring, t_ring))
            before = met.get(key, [])
            met[key] = _CROSS if here == _CROSS or before == _CROSS else _distinct(before + here)
    return met


def _meeting_of(met, i, j):
    """How rings *i* and *j* of *met* meet."""
    return met.get((min(i, j), max(i, j)), [])


def _place_in(p, ring) -> str:
    """Where *p* is from the area *ring* bounds: "in", "out" or "on"."""
    inside = False
    for i, a in enumerate(ring):
        b = ring[(i + 1) % len(ring)]
        if _on_side(a, b, p):
            return "on"
        # A side across the line through p, to its right: up with p on its
        # left, or down with p on its right.
        if (a[1] > p[1]) != (b[1] > p[1]) and _turn(a, b, p) == (1 if b[1] > a[1] else -1):
            inside = not inside
    return "in" if inside else "out"


def _place_in_part(p, part) -> str:
    """Where *p* is from a part's area: inside its outline and outside its
    holes is in."""
    outline, *holes = part
    at = _place_in(p, outline)
    if at != "in":
        return at
    for hole in holes:
        there = _place_in(p, hole)
        if there != "out":
            return "on" if there == "on" else "out"
    return "in"


def _stretches_of(ring, cuts):
    """A point of each stretch of *ring* between the points *cuts* on it: a
    corner when there are none, else the middle of the piece after each cut.
    An area whose boundary meets the ring at those points alone, crossing it
    nowhere, has each stretch all inside it or all outside it."""
    if not cuts:
        return [ring[0]]
    out = []
    for i, a in enumerate(ring):
        b = ring[(i + 1) % len(ring)]
        on = [p for p in cuts if _on_side(a, b, p)]
        if not on:
            continue
        stops = sorted(
            _distinct([a, *on, b]),
            key=lambda p: (p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1]),
        )
        for k in range(len(stops) - 1):
            if stops[k] in cuts:
                # Every corner is even, so the middle of two is whole.
                out.append(((stops[k][0] + stops[k + 1][0]) // 2, (stops[k][1] + stops[k + 1][1]) // 2))
    return out


def _touches_of(met, i, j):
    """The points where rings *i* and *j* of *met* touch: none when they cross."""
    here = _meeting_of(met, i, j)
    return [] if here == _CROSS else here


def _hole_problem(part, first, met) -> bool:
    """Whether a hole of *part*, whose rings are *met*'s from *first* on,
    crosses or leaves its outline, overlaps another hole or lies in one, or the
    rings that touch cut the area in two: two rings that touch twice, or rings
    that touch in a loop."""
    if len(part) < 2:
        return False
    # The rings and the points where they touch, joined: a loop cuts the area in two.
    joined_to = {}

    def root(node):
        at = node
        while at in joined_to:
            at = joined_to[at]
        return at

    links = set()
    for i in range(len(part)):
        for j in range(i + 1, len(part)):
            here = _meeting_of(met, first + i, first + j)
            if here == _CROSS:
                return True
            for p in here:
                point = ("point", p[0], p[1])
                for ring in (i, j):
                    link = (ring, point)
                    if link in links:
                        continue
                    links.add(link)
                    a = root(("ring", ring))
                    b = root(point)
                    if a == b:
                        return True
                    joined_to[a] = b
    # Each hole lies inside its outline, and outside every other hole.
    for j in range(1, len(part)):
        if any(_place_in(p, part[0]) == "out" for p in _stretches_of(part[j], _touches_of(met, first, first + j))):
            return True
        for i in range(1, j):
            cuts = _touches_of(met, first + i, first + j)
            if any(_place_in(p, part[i]) == "in" for p in _stretches_of(part[j], cuts)):
                return True
            if any(_place_in(p, part[j]) == "in" for p in _stretches_of(part[i], cuts)):
                return True
    return False


def _overlap(p, first_p, q, first_q, met) -> bool:
    """Whether the parts *p* and *q*, whose rings are *met*'s from *first_p* and
    *first_q* on, overlap: sides of theirs cross or run along each other, or a
    stretch of a ring of one lies inside the other's area."""
    for i in range(len(p)):
        for j in range(len(q)):
            if _meeting_of(met, first_p + i, first_q + j) == _CROSS:
                return True

    def in_area(ring, r, area, first_area):
        # A part with no rings (an empty polygon among others) has no area.
        if not area:
            return False
        cuts = _distinct([point for k in range(len(area)) for point in _touches_of(met, r, first_area + k)])
        return any(_place_in_part(x, area) == "in" for x in _stretches_of(ring, cuts))

    return any(in_area(ring, first_p + i, q, first_q) for i, ring in enumerate(p)) or any(
        in_area(ring, first_q + j, p, first_p) for j, ring in enumerate(q)
    )
