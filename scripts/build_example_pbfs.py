#!/usr/bin/env python3
"""Build the OpenStreetMap extracts the shipped examples load.

This script builds the ``docs/examples/data/*.osm.pbf`` extracts, each from an
area: a place Nominatim finds (its bounding box) or a fixed box.

- The extract holds every OpenStreetMap feature in the area's box. Nothing is
  filtered by tag: an Autark node's data spec picks and filters the layers.
- Lines are cut at the box as SCOUT cuts its road graph: a line keeps its
  points inside the box and, where it crosses the edge, its first point
  outside; a line that leaves the box and comes back becomes one line per
  part.
- Polygons are clipped at the box: a ring that crosses the edge is cut there
  and closed along the edge, with new points on it. A polygon the box cuts
  into several pieces becomes one multipolygon.
- A feature outside the box is dropped.
- The extract also carries, whole, the boundary relations autk-db's ``.pbf``
  loader clips to: a relation with a ``boundary`` tag whose ``name`` equals
  each ``queryArea.areas`` entry of the specs that load the file.
- The header records the box and the date of the OpenStreetMap data.

Authoring only: Curio never imports this script, and pyosmium is not one of
Curio's dependencies.

    conda run -n curio pip install osmium     # once
    conda run -n curio python scripts/build_example_pbfs.py [area ...]

It needs network access to nominatim.openstreetmap.org and to an Overpass API
server. The data is (c) OpenStreetMap contributors, ODbL 1.0.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import time
from typing import NamedTuple

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
OUT_DIR = os.path.join(REPO_ROOT, "docs", "examples", "data")

NOMINATIM = "https://nominatim.openstreetmap.org/search"
#: Tried in turn; a busy or refusing server (406, 429, 5xx) passes to the next.
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
USER_AGENT = {"User-Agent": "curio-example-pbf-builder/2.0 (https://github.com/urban-toolkit/curio)"}
#: An answer from a server whose data is older than this many days is refused.
MAX_DATA_AGE_DAYS = 7
GENERATOR = "curio scripts/build_example_pbfs.py"


class Area(NamedTuple):
    """Where an extract is cut: a Nominatim ``place`` or a ``box`` (south,
    west, north, east), and the names of the boundary relations it carries."""

    boundaries: tuple[str, ...]
    place: str | None = None
    box: tuple[float, float, float, float] | None = None


#: File name (without ``.osm.pbf``) to area. ``boundaries`` lists every
#: ``queryArea.areas`` entry of the shipped specs that load the file.
AREAS = {
    # Example 06.
    "back_bay": Area(place="Back Bay, Boston, Massachusetts, USA", boundaries=("Back Bay",)),
    # Example 07 and Interaction_Autark.
    "chicago_loop": Area(place="Loop, Chicago, Illinois, USA", boundaries=("Loop",)),
    # Example 08 and Regression.
    "niteroi": Area(place="Niterói, Rio de Janeiro, Brazil", boundaries=("Niterói",)),
    # Example 11: the area of the extract it shipped with, reaching 18 m further
    # west so that it holds Battery Park City whole.
    "lower_mnt": Area(box=(40.698762, -74.0194416, 40.756338, -73.962192),
                      boundaries=("Battery Park City", "Financial District")),
    # WeatherRouting: SCOUT's weather routing box, with the Chicago city boundary.
    "chicago_downtown": Area(box=(41.859, -87.662, 41.898, -87.613), boundaries=("Chicago",)),
}

#: A closed way is a polygon when it has one of these keys, with any value but
#: the line values listed for the key, or one of the values of
#: ``AREA_VALUES``. ``area=yes`` makes any closed way a polygon and ``area=no``
#: none; any other closed way, such as a roundabout, is a line.
AREA_KEYS = {
    "building": (), "building:part": (), "landuse": (), "landcover": (), "amenity": (), "shop": (),
    "tourism": (), "historic": (), "military": (), "office": (), "craft": (), "healthcare": (),
    "place": (), "water": (), "area:highway": (),
    "leisure": ("slipway", "track"),
    "natural": ("arete", "cliff", "coastline", "earth_bank", "ridge", "tree_row"),
    "man_made": ("breakwater", "cutline", "dyke", "embankment", "groyne", "pier", "pipeline"),
    "aeroway": ("jet_bridge", "parking_position", "runway", "taxiway"),
    "power": ("cable", "line", "minor_line"),
}
AREA_VALUES = {
    "waterway": ("boatyard", "dock", "riverbank"),
    "railway": ("platform", "station"),
    "public_transport": ("platform", "station"),
    "highway": ("rest_area", "services"),
}


# -- The cut ----------------------------------------------------------------

def in_box(lon: float, lat: float, box) -> bool:
    s, w, n, e = box
    return s <= lat <= n and w <= lon <= e


def is_closed(refs: list[int]) -> bool:
    return len(refs) >= 4 and refs[0] == refs[-1]


def is_area(tags: dict) -> bool:
    """Whether a closed way with *tags* is a polygon (``AREA_KEYS``)."""
    if tags.get("area") in ("yes", "no"):
        return tags["area"] == "yes"
    if any(key in tags and tags[key] not in lines for key, lines in AREA_KEYS.items()):
        return True
    return any(tags.get(key) in values for key, values in AREA_VALUES.items())


def cut_line(refs: list[int], inside: list[bool]) -> list[list[int]]:
    """The parts of a line the box keeps, as SCOUT cuts its road graph: each
    run of points inside the box, with the first point outside on either side.
    *inside* says, per point of *refs*, whether it lies in the box. A part needs
    two points; a line with no point inside gives no part."""
    last = len(refs) - 1
    keep = [inside[i] or (i > 0 and inside[i - 1]) or (i < last and inside[i + 1]) for i in range(len(refs))]
    parts, part = [], []
    for ref, kept in zip(refs, keep):
        if kept:
            part.append(ref)
        elif part:
            parts.append(part)
            part = []
    if part:
        parts.append(part)
    return [p for p in parts if len(p) >= 2]


def segment_meets_box(a, b, box) -> bool:
    """Whether the segment from *a* to *b* (``(lon, lat)`` points) touches the box."""
    return _clip_segment(a, b, box) is not None


def way_reaches_box(refs: list[int], nodes: dict, box) -> bool:
    points = [nodes[r][:2] for r in refs if r in nodes]
    if any(in_box(*p, box) for p in points):
        return True
    return any(segment_meets_box(points[i], points[i + 1], box) for i in range(len(points) - 1))


def _clip_segment(a, b, box):
    """The part of the segment from *a* to *b* (``(lon, lat)``) in the box, as
    the positions ``(t0, t1)`` of its ends along the segment (0 at *a*, 1 at
    *b*), or None when the segment misses the box (Liang and Barsky's clip)."""
    s, w, n, e = box
    (x0, y0), (x1, y1) = a, b
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - w), (dx, e - x0), (-dy, y0 - s), (dy, n - y0)):
        if p == 0:
            if q < 0:
                return None
        elif p < 0:
            t0 = max(t0, q / p)
        else:
            t1 = min(t1, q / p)
        if t0 > t1:
            return None
    return t0, t1


def _edge_point(a, b, t, box) -> tuple[None, float, float]:
    """The point at *t* along the segment from *a* to *b*, which lies on the
    box's edge: put exactly on the nearest edge, its other coordinate rounded
    to seven decimals as OpenStreetMap stores positions."""
    s, w, n, e = box
    x = a[0] + t * (b[0] - a[0])
    y = a[1] + t * (b[1] - a[1])
    edge = min((abs(x - w), "w"), (abs(x - e), "e"), (abs(y - s), "s"), (abs(y - n), "n"))[1]
    if edge in ("w", "e"):
        return None, (w if edge == "w" else e), min(max(round(y, 7), s), n)
    return None, min(max(round(x, 7), w), e), (s if edge == "s" else n)


def _along_edge(a, b, box) -> bool:
    """Whether the segment from *a* to *b* (``(ref, lon, lat)`` points) runs
    along one of the box's edges."""
    s, w, n, e = box
    return (a[1] == b[1] and a[1] in (w, e)) or (a[2] == b[2] and a[2] in (s, n))


def _perimeter_position(point, box) -> float:
    """Where a point on the box's edge lies along it, counterclockwise from
    the south-west corner."""
    s, w, n, e = box
    x, y = point
    width, height = e - w, n - s
    edge = min((abs(y - s), 0), (abs(x - e), 1), (abs(y - n), 2), (abs(x - w), 3))[1]
    return (x - w, width + y - s, width + height + e - x, 2 * width + height + n - y)[edge]


def _dedupe(points: list) -> list:
    """*points* without a point repeating the one before it (a point with a
    ref is kept over one the clip made at the same place)."""
    out = []
    for point in points:
        if out and point[1:] == out[-1][1:]:
            if out[-1][0] is None and point[0] is not None:
                out[-1] = point
            continue
        out.append(point)
    return out


def _closed(points: list) -> list:
    """A ring of *points*, its last point the first one."""
    ring = _dedupe(points)
    if len(ring) > 1 and ring[-1][1:] == ring[0][1:]:
        ring[-1] = ring[0]
    else:
        ring.append(ring[0])
    return ring


def _area(ring: list) -> float:
    """The signed area of a ring of ``(ref, lon, lat)`` points, positive when
    it runs counterclockwise."""
    return sum(x1 * y2 - x2 * y1 for (_a, x1, y1), (_b, x2, y2) in zip(ring, ring[1:])) / 2


def _inside_ring(point, ring) -> bool:
    x, y = point
    inside = False
    for (_a, x1, y1), (_b, x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _on_ring(point, ring) -> bool:
    x, y = point
    return any(
        (x2 - x1) * (y - y1) == (y2 - y1) * (x - x1)
        and min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2)
        for (_a, x1, y1), (_b, x2, y2) in zip(ring, ring[1:])
    )


def _ring_pieces(ring: list, box) -> list | None:
    """The runs of a closed ring inside the box, each from the point where the
    ring enters the box to the point where it leaves it, or None when the
    whole ring is inside. A run that only follows the box's edge is left out:
    it bounds nothing inside the box."""
    pieces, current, whole, first_inside = [], None, True, False
    for i in range(len(ring) - 1):
        a, b = ring[i], ring[i + 1]
        clipped = _clip_segment(a[1:], b[1:], box)
        if clipped is None:
            whole = False
            continue
        t0, t1 = clipped
        if t0 > 0 or t1 < 1:
            whole = False
        start = a if t0 == 0 else b if t0 == 1 else _edge_point(a[1:], b[1:], t0, box)
        end = b if t1 == 1 else a if t1 == 0 else _edge_point(a[1:], b[1:], t1, box)
        if current is None or t0 > 0:
            if current is not None:
                pieces.append(current)
            first_inside = first_inside or (i == 0 and t0 == 0)
            current = [start]
        current.append(end)
        if t1 < 1:
            pieces.append(current)
            current = None
    if whole:
        return None
    if current is not None:
        if first_inside and pieces:
            pieces[0] = current + pieces[0][1:]
        else:
            pieces.append(current)
    pieces = [_dedupe(piece) for piece in pieces]
    return [piece for piece in pieces
            if len(piece) >= 2 and not all(_along_edge(a, b, box) for a, b in zip(piece, piece[1:]))]


def clip_polygon(rings: list, box) -> list:
    """Clip a polygon at the box.

    *rings* are the polygon's outer rings, counterclockwise, and its holes,
    clockwise, each a closed list of ``(ref, lon, lat)`` points. Returns the
    polygons the clip leaves, each a list of closed rings with its outer ring
    first. A point the clip makes on the box's edge has ref None.

    Each run of a ring inside the box goes on along the box's edge,
    counterclockwise, to the next point where a run enters (Weiler and
    Atherton's walk round a rectangle). A ring inside the box is kept as it
    is, and the box itself is the outer ring of a polygon that covers it.
    """
    s, w, n, e = box
    width, height = e - w, n - s
    perimeter = 2 * (width + height)
    corners = [(0.0, (None, w, s)), (width, (None, e, s)), (width + height, (None, e, n)),
               (2 * width + height, (None, w, n))]
    pieces, inside = [], []
    for ring in rings:
        ring_pieces = _ring_pieces(ring, box)
        if ring_pieces is None:
            inside.append(ring)
        else:
            pieces.extend(ring_pieces)

    outers, holes = [], []
    entries = [_perimeter_position(piece[0][1:], box) for piece in pieces]
    done: set = set()
    for first in range(len(pieces)):
        if first in done:
            continue
        ring, k = [], first
        while k not in done:
            done.add(k)
            ring.extend(pieces[k])
            leave = _perimeter_position(pieces[k][-1][1:], box)
            k = min(range(len(pieces)), key=lambda j: (entries[j] - leave) % perimeter)
            gap = (entries[k] - leave) % perimeter
            ring.extend(corner for position, corner in sorted(corners, key=lambda c: (c[0] - leave) % perimeter)
                        if 0 < (position - leave) % perimeter < gap)
        outers.append(_closed(ring))
    if not pieces:
        probes = [((w + e) / 2, s), (e, (s + n) / 2), ((w + e) / 2, n), (w, (s + n) / 2)]
        probe = next((p for p in probes if not any(_on_ring(p, ring) for ring in rings)),
                     ((w + e) / 2, (s + n) / 2))
        if sum(_inside_ring(probe, ring) for ring in rings) % 2:
            outers.append(_closed([corner for _position, corner in corners]))
    for ring in inside:
        (outers if _area(ring) > 0 else holes).append(ring)

    polygons = [[outer] for outer in outers if len(outer) >= 4 and _area(outer) > 0]
    by_size = sorted(polygons, key=lambda polygon: _area(polygon[0]))
    for hole in holes:
        owner = next((polygon for polygon in by_size if _inside_ring(hole[0][1:], polygon[0])), None)
        if owner is not None:
            owner.append(hole)
    return polygons


def _points(refs: list[int], nodes: dict) -> list:
    return [(r, nodes[r][0], nodes[r][1]) for r in refs]


def _oriented(ring: list, counterclockwise: bool) -> list:
    return ring if (_area(ring) > 0) == counterclockwise else ring[::-1]


def _joined_rings(ways_refs: list) -> list | None:
    """Ways joined into closed rings at their shared end nodes, or None when
    they do not close."""
    rings, open_ways, ends = [], [], {}
    for refs in ways_refs:
        if is_closed(refs):
            rings.append(list(refs))
        else:
            ends.setdefault(refs[0], []).append(len(open_ways))
            ends.setdefault(refs[-1], []).append(len(open_ways))
            open_ways.append(list(refs))
    used: set = set()
    for i, refs in enumerate(open_ways):
        if i in used:
            continue
        used.add(i)
        ring = list(refs)
        while len(ring) < 2 or ring[0] != ring[-1]:
            j = next((j for j in ends.get(ring[-1], []) if j not in used), None)
            if j is None:
                return None
            used.add(j)
            way = open_ways[j]
            ring.extend(way[1:] if way[0] == ring[-1] else way[-2::-1])
        if len(ring) < 4:
            return None
        rings.append(ring)
    return rings


def multipolygon_rings(members: list, ways: dict, nodes: dict) -> list | None:
    """A multipolygon's rings, outer rings counterclockwise and holes
    clockwise, as closed lists of ``(ref, lon, lat)`` points, or None when a
    member way is missing or the ways do not close into rings."""
    outer, inner = [], []
    for t, ref, role in members:
        if t != "w":
            continue
        if ref not in ways or any(r not in nodes for r in ways[ref][0]):
            return None
        (inner if role == "inner" else outer).append(ways[ref][0])
    if not outer:
        return None
    rings = []
    for group, counterclockwise in ((outer, True), (inner, False)):
        joined = _joined_rings(group)
        if joined is None:
            return None
        rings.extend(_oriented(_points(refs, nodes), counterclockwise) for refs in joined)
    return rings


def cut(nodes: dict, ways: dict, relations: dict, box, boundaries) -> tuple[dict, dict, dict]:
    """Cut an extract at *box*.

    *nodes* maps an id to ``(lon, lat, tags)``, *ways* an id to ``(refs, tags)``
    and *relations* an id to ``(members, tags)``, a member being ``(type, ref,
    role)`` with type ``"n"``, ``"w"`` or ``"r"``. Returns the three, cut:

    - a relation with a ``boundary`` tag named in *boundaries* is kept whole;
    - a polygon is clipped at the box (``clip_polygon``): a closed way that is
      an area (``is_area``), or has no tags and a building relation lists it
      (a building's untagged part or outline), keeps its id when the clip
      leaves one piece, and
      becomes a multipolygon of its pieces, with its tags, when it leaves
      several; a multipolygon keeps its id and tags, with new ways for its
      clipped rings. A polygon inside the box is kept as it is, and a
      multipolygon whose ways do not close is kept whole when it reaches into
      the box;
    - any other way is cut as a line (``cut_line``): the first part keeps the
      way's id and each later part takes a new one. An untagged way that no
      relation but a multipolygon lists is left out;
    - a node is kept when a kept way uses it, or when it is inside the box and
      tagged. Each place where the clip makes a point is one new node;
    - any other relation is kept when one of its node or way members is. It
      lists only its members that are kept, and every part of a way the cut
      split into parts.
    """
    next_id = {"node": max(nodes, default=0) + 1, "way": max(ways, default=0) + 1,
               "relation": max(relations, default=0) + 1}
    new_nodes: dict = {}
    node_at: dict = {}
    kept_ways: dict = {}
    kept_relations: dict = {}

    def take(kind: str) -> int:
        next_id[kind] += 1
        return next_id[kind] - 1

    def node_id(point) -> int:
        ref, x, y = point
        if ref is None:
            if (x, y) not in node_at:
                node_at[(x, y)] = take("node")
                new_nodes[node_at[(x, y)]] = (x, y, {})
            ref = node_at[(x, y)]
        return ref

    def new_way(ring: list) -> int:
        way_id = take("way")
        kept_ways[way_id] = ([node_id(p) for p in ring], {})
        return way_id

    whole = {rel_id for rel_id, (_members, tags) in relations.items()
             if "boundary" in tags and tags.get("name") in boundaries}
    listed: set = set()
    in_building: set = set()
    for rel_id in sorted(relations):
        members, tags = relations[rel_id]
        if rel_id in whole:
            continue
        if tags.get("type") != "multipolygon":
            listed.update(ref for t, ref, _role in members if t == "w")
            if tags.get("type") == "building":
                in_building.update(ref for t, ref, _role in members if t == "w")
            continue
        rings = multipolygon_rings(members, ways, nodes)
        if rings is None:
            if any(t == "w" and ref in ways and way_reaches_box(ways[ref][0], nodes, box) for t, ref, _r in members):
                whole.add(rel_id)
        elif all(in_box(x, y, box) for ring in rings for _ref, x, y in ring):
            whole.add(rel_id)
        else:
            polygons = clip_polygon(rings, box)
            if polygons:
                kept_relations[rel_id] = ([("w", new_way(ring), "outer" if k == 0 else "inner")
                                           for polygon in polygons for k, ring in enumerate(polygon)], tags)
    whole_ways = {ref for rel_id in whole for t, ref, _role in relations[rel_id][0] if t == "w"}

    parts_of: dict = {}
    for way_id in sorted(ways):
        refs, tags = ways[way_id]
        if way_id in whole_ways:
            kept_ways[way_id] = (refs, tags)
        elif (is_closed(refs) and (is_area(tags) or (not tags and way_id in in_building))
              and all(r in nodes for r in refs)):
            ring = _points(refs, nodes)
            if all(in_box(x, y, box) for _ref, x, y in ring):
                kept_ways[way_id] = (refs, tags)
                continue
            polygons = clip_polygon([_oriented(ring, True)], box)
            if len(polygons) == 1:
                kept_ways[way_id] = ([node_id(p) for p in polygons[0][0]], tags)
            elif polygons:
                kept_relations[take("relation")] = (
                    [("w", new_way(polygon[0]), "outer") for polygon in polygons],
                    {**tags, "type": "multipolygon"},
                )
        elif tags or way_id in listed:
            inside = [r in nodes and in_box(*nodes[r][:2], box) for r in refs]
            parts = cut_line(refs, inside)
            part_ids = [way_id] + [take("way") for _part in parts[1:]]
            for part_id, part in zip(part_ids, parts):
                kept_ways[part_id] = (part, tags)
            if len(parts) > 1:
                parts_of[way_id] = part_ids

    used = {r for refs, _tags in kept_ways.values() for r in refs}
    kept_nodes = {
        node_id_: node for node_id_, node in nodes.items()
        if node_id_ in used or (node[2] and in_box(node[0], node[1], box))
    }
    kept_nodes.update(new_nodes)

    def kept(member) -> bool:
        t, ref, _role = member
        return (t == "n" and ref in kept_nodes) or (t == "w" and ref in kept_ways)

    others = {rel_id for rel_id, (members, tags) in relations.items()
              if rel_id not in kept_relations
              and (rel_id in whole or (tags.get("type") != "multipolygon" and any(kept(m) for m in members)))}
    relation_ids = others | set(kept_relations)
    for rel_id in others:
        members, tags = relations[rel_id]
        listing = []
        for t, ref, role in members:
            if t == "w" and ref in parts_of:
                listing.extend(("w", part_id, role) for part_id in parts_of[ref])
            elif kept((t, ref, role)) or (t == "r" and ref in relation_ids):
                listing.append((t, ref, role))
        kept_relations[rel_id] = (listing, tags)
    return kept_nodes, kept_ways, dict(sorted(kept_relations.items()))


def missing_boundaries(nodes: dict, ways: dict, relations: dict, boundaries) -> list[str]:
    """The names in *boundaries* with no relation that has a ``boundary`` tag,
    that name, and every member way present with all its nodes."""
    found = set()
    for members, tags in relations.values():
        if "boundary" not in tags or tags.get("name") not in boundaries:
            continue
        way_refs = [ref for t, ref, _role in members if t == "w"]
        if way_refs and all(ref in ways and all(r in nodes for r in ways[ref][0]) for ref in way_refs):
            found.add(tags["name"])
    return [name for name in boundaries if name not in found]


# -- Fetching ---------------------------------------------------------------

def place_box(query: str) -> tuple[float, float, float, float]:
    """The bounding box (south, west, north, east) of Nominatim's first match."""
    import requests

    response = requests.get(NOMINATIM, params={"q": query, "format": "json", "limit": 1},
                            headers=USER_AGENT, timeout=60)
    response.raise_for_status()
    time.sleep(1)  # Nominatim's usage policy: at most one request a second.
    hits = response.json()
    if not hits:
        raise SystemExit(f"Nominatim found nothing for {query!r}")
    s, n, w, e = (float(x) for x in hits[0]["boundingbox"])
    return s, w, n, e


def overpass_query(box, boundaries) -> str:
    """Every node and way in *box*, every node of those ways, the relations
    they belong to, and every member of the multipolygons among them and of
    the boundaries named in *boundaries*."""
    s, w, n, e = box
    b = f"{s},{w},{n},{e}"
    named = "".join(f'  rel.rels["name"="{name}"]["boundary"];\n' for name in boundaries)
    return (
        "[out:xml][timeout:600][maxsize:536870912];\n"
        f"(node({b}); way({b});)->.inbox;\n"
        "(rel(bn.inbox); rel(bw.inbox);)->.rels;\n"
        "(\n"
        "  rel.rels[type=multipolygon];\n"
        + named
        + ")->.whole;\n"
        "(.inbox; >; .rels; .whole; .whole >;);\n"
        "out body qt;\n"
    )


def fetch_overpass(query: str, attempts: int = 4) -> bytes:
    """Overpass's answer to *query*, from the first server that gives a
    complete one on data at most ``MAX_DATA_AGE_DAYS`` old."""
    import requests

    last = "no attempt"
    for attempt in range(attempts):
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                # The query's own [timeout:600], and a minute more to send the answer.
                response = requests.post(endpoint, data={"data": query}, headers=USER_AGENT, timeout=(30, 660))
            except requests.RequestException as exc:
                last = f"{endpoint}: {exc}"
            else:
                body = response.content
                if response.status_code != 200 or not body.lstrip().startswith(b"<?xml"):
                    last = f"{endpoint}: HTTP {response.status_code} {response.text[-300:]!r}"
                elif b"<remark>" in body[-4000:]:
                    last = f"{endpoint}: {body[-4000:].decode(errors='replace').split('<remark>')[-1][:300]!r}"
                elif data_age_days(data_date(body)) > MAX_DATA_AGE_DAYS:
                    last = f"{endpoint}: its data is of {data_date(body)}"
                else:
                    print(f"  answered by {endpoint}", flush=True)
                    return body
            print(f"  retry ({last})", flush=True)
        time.sleep(30 * (attempt + 1))
    raise SystemExit(f"Every Overpass server failed. Last: {last}")


def data_date(xml: bytes) -> str:
    """The date of the data in an Overpass answer (``osm_base``)."""
    match = re.search(rb'osm_base="([^"]+)"', xml[:2000])
    return match.group(1).decode() if match else ""


def data_age_days(date: str) -> float:
    """How many days old an ``osm_base`` date is (infinite when there is none)."""
    from datetime import datetime, timezone

    if not date:
        return float("inf")
    then = datetime.fromisoformat(date.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - then).total_seconds() / 86400


# -- Reading and writing ----------------------------------------------------

def read_osm(path: str) -> tuple[dict, dict, dict]:
    """The nodes, ways and relations of an OSM file, as ``cut`` takes them."""
    import osmium

    nodes, ways, relations = {}, {}, {}
    for obj in osmium.FileProcessor(path):
        tags = {t.k: t.v for t in obj.tags}
        if obj.is_node():
            if obj.location.valid():
                nodes[obj.id] = (obj.location.lon, obj.location.lat, tags)
        elif obj.is_way():
            ways[obj.id] = ([nd.ref for nd in obj.nodes], tags)
        else:
            relations[obj.id] = ([(m.type, m.ref, m.role) for m in obj.members], tags)
    return nodes, ways, relations


def write_pbf(path: str, nodes: dict, ways: dict, relations: dict, box, date: str) -> None:
    """Write the extract, sorted by type then id, with *box* and *date* in its header."""
    import osmium

    s, w, n, e = box
    header = osmium.io.Header()
    header.add_box(osmium.osm.Box(w, s, e, n))
    header.set("generator", GENERATOR)
    if date:
        header.set("osmosis_replication_timestamp", date)
    if os.path.exists(path):
        os.unlink(path)
    writer = osmium.SimpleWriter(path, header=header)
    try:
        for node_id in sorted(nodes):
            lon, lat, tags = nodes[node_id]
            writer.add_node(osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags=tags))
        for way_id in sorted(ways):
            refs, tags = ways[way_id]
            writer.add_way(osmium.osm.mutable.Way(id=way_id, nodes=refs, tags=tags))
        for rel_id in sorted(relations):
            members, tags = relations[rel_id]
            writer.add_relation(osmium.osm.mutable.Relation(id=rel_id, members=members, tags=tags))
    finally:
        writer.close()


def build(key: str, area: Area, out_dir: str = OUT_DIR) -> str:
    # Seven decimals, as OpenStreetMap stores positions, so that the points
    # the clip puts on the box's edge are on it in the file too.
    box = tuple(round(v, 7) for v in (area.box or place_box(area.place)))
    print(f"\n=== {key}: {area.place or 'box'} (S, W, N, E) {box}, boundaries {list(area.boundaries)}", flush=True)
    xml = fetch_overpass(overpass_query(box, area.boundaries))
    print(f"  Overpass: {len(xml):,} bytes, data of {data_date(xml)}", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        raw = os.path.join(tmp, "raw.osm")
        with open(raw, "wb") as f:
            f.write(xml)
        nodes, ways, relations = read_osm(raw)
    nodes, ways, relations = cut(nodes, ways, relations, box, area.boundaries)
    missing = missing_boundaries(nodes, ways, relations, area.boundaries)
    if missing:
        raise SystemExit(f"{key}: no whole boundary relation named {missing}")
    out_path = os.path.join(out_dir, f"{key}.osm.pbf")
    write_pbf(out_path, nodes, ways, relations, box, data_date(xml))
    print(f"  wrote {out_path}: {os.path.getsize(out_path):,} bytes, {len(nodes):,} nodes, "
          f"{len(ways):,} ways, {len(relations):,} relations", flush=True)
    return out_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("areas", nargs="*", metavar="area",
                        help=f"areas to build (default: all of {', '.join(AREAS)})")
    args = parser.parse_args(argv)
    unknown = [key for key in args.areas if key not in AREAS]
    if unknown:
        parser.error(f"unknown areas {unknown}; the areas are {', '.join(AREAS)}")
    try:
        import osmium  # noqa: F401
    except ImportError:
        sys.exit("pyosmium is required: conda run -n curio pip install osmium")
    for key in args.areas or AREAS:
        build(key, AREAS[key])
    print("\nDone. Check the sizes, then commit docs/examples/data/*.osm.pbf")
    return 0


if __name__ == "__main__":
    sys.exit(main())
