#!/usr/bin/env python3
"""Build the parks of Niterói, each with its area, that example 36 loads.

``docs/examples/data/niteroi_parks.geojson`` holds the parks of
``docs/examples/data/niteroi.osm.pbf`` that autk-db's ``parks`` layer takes:
the closed ways and the multipolygon relations tagged ``leisure``,
``landuse`` or ``natural`` with one of the values of ``PARK_TAGS``, autk-db's
own lists. Each is cut to Niterói's boundary, the area the example's data node
loads, and carries its OpenStreetMap element (``osm_type``, ``osm_id``) and
``area``: its area in square metres in an equal-area projection
(``EQUAL_AREA``), from its geometry as the file writes it. Its outline is
simplified within ``SIMPLIFY`` degrees (about 5 m, nothing next to the 500 m
example 36 reaches) and its coordinates keep ``PLACES`` decimals (about 1 m),
so the file stays small; the features are sorted by element, and nothing in
the file depends on when it was built.

Authoring only: Curio never imports this script, and pyosmium is not one of
Curio's dependencies.

    conda run -n curio pip install osmium     # once
    conda run -n curio python scripts/build_example_niteroi_parks.py

The data is (c) OpenStreetMap contributors, ODbL 1.0.
"""
from __future__ import annotations

import argparse
import json
import os

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA = os.path.join(REPO_ROOT, "docs", "examples", "data")
EXTRACT = os.path.join(DATA, "niteroi.osm.pbf")
OUT = os.path.join(DATA, "niteroi_parks.geojson")

#: The boundary relation the example's data node loads (its queryArea's area).
BOUNDARY = "Niterói"
#: The tags of a feature autk-db's parks layer takes: one of these values of
#: one of these keys (autk-db's consts: leisure, landuse and natural values).
PARK_TAGS = {
    "leisure": ("dog_park", "park", "playground", "recreation_ground"),
    "landuse": ("wood", "grass", "forest", "orchard", "village_green", "vineyard", "cemetery", "meadow"),
    "natural": ("wood", "grass", "grassland", "forest", "scrub", "heath", "meadow"),
}
#: The equal-area projection areas are measured in: WGS 84 / NSIDC EASE-Grid
#: 2.0 Global, a cylindrical equal-area projection.
EQUAL_AREA = "EPSG:6933"
#: How far a simplified outline may stray from the park's, in degrees (about 5 m).
SIMPLIFY = 5e-5
#: Decimal places each coordinate keeps (about 1 m).
PLACES = 5


def is_park(tags) -> bool:
    """Whether *tags* (a mapping of OpenStreetMap tags) are a park's, as
    autk-db's parks layer reads them."""
    return any(tags.get(key) in values for key, values in PARK_TAGS.items())


def equal_area(geometry) -> float:
    """The area of *geometry*, in lon/lat (EPSG:4326), in square metres."""
    from pyproj import Transformer
    from shapely.ops import transform

    to_equal_area = Transformer.from_crs("EPSG:4326", EQUAL_AREA, always_xy=True).transform
    return transform(to_equal_area, geometry).area


def _polygonal(geometry):
    """The polygons of *geometry*, a Polygon, a MultiPolygon or a collection,
    as one geometry, or None when it holds none."""
    from shapely.geometry import MultiPolygon

    if geometry.is_empty:
        return None
    if geometry.geom_type in ("Polygon", "MultiPolygon"):
        return geometry
    parts = [part for part in getattr(geometry, "geoms", []) if part.geom_type == "Polygon"]
    for part in getattr(geometry, "geoms", []):
        if part.geom_type == "MultiPolygon":
            parts.extend(part.geoms)
    return MultiPolygon(parts) if parts else None


def park_feature(osm_type: str, osm_id: int, geometry, boundary):
    """The feature of the park *geometry* (EPSG:4326) cut to *boundary*, with
    its element and its area, or None when nothing of it is left."""
    from shapely import set_precision
    from shapely.geometry import mapping
    from shapely.validation import make_valid

    cut = _polygonal(make_valid(geometry).intersection(boundary))
    if cut is None:
        return None
    written = _polygonal(set_precision(cut.simplify(SIMPLIFY, preserve_topology=True), 10 ** -PLACES))
    if written is None:
        return None
    area = round(equal_area(written))
    if area < 1:
        return None
    return {
        "type": "Feature",
        "properties": {"osm_type": osm_type, "osm_id": osm_id, "area": area},
        "geometry": mapping(written),
    }


def build(extract: str = EXTRACT) -> dict:
    """The parks of *extract* inside Niterói's boundary, as a FeatureCollection."""
    import osmium
    from shapely import wkb
    from shapely.ops import unary_union
    from shapely.validation import make_valid

    factory = osmium.geom.WKBFactory()
    parks: list[tuple[str, int, object]] = []
    boundaries: list = []

    class Areas(osmium.SimpleHandler):
        def area(self, a):
            tags = {tag.k: tag.v for tag in a.tags}
            boundary = (not a.from_way() and tags.get("boundary") == "administrative"
                        and tags.get("name") == BOUNDARY)
            if not (boundary or is_park(tags)):
                return
            try:
                geometry = wkb.loads(factory.create_multipolygon(a), hex=True)
            except RuntimeError:
                return
            if boundary:
                boundaries.append(geometry)
            else:
                parks.append(("way" if a.from_way() else "relation", a.orig_id(), geometry))

    Areas().apply_file(extract, locations=True, idx="flex_mem")
    if not boundaries:
        raise SystemExit(f"{extract} holds no boundary relation named {BOUNDARY!r}")
    boundary = make_valid(unary_union(boundaries))
    features = [park_feature(kind, ref, geometry, boundary) for kind, ref, geometry in parks]
    features = sorted((f for f in features if f is not None),
                      key=lambda f: (f["properties"]["osm_type"], f["properties"]["osm_id"]))
    return {"type": "FeatureCollection", "features": features}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extract", default=EXTRACT, help="the OpenStreetMap extract to read")
    parser.add_argument("--out", default=OUT, help="the GeoJSON file to write")
    args = parser.parse_args(argv)
    parks = build(args.extract)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(parks, ensure_ascii=False, separators=(",", ":")) + "\n")
    total = sum(f["properties"]["area"] for f in parks["features"])
    print(f"{len(parks['features'])} parks, {total / 1e6:.2f} km2, {os.path.getsize(args.out) / 1024:.0f} KiB: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
