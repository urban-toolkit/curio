#!/usr/bin/env python3
"""Generate the West Loop's street corners, a committed dataset the SideSeeing
frames example cuts its walk at.

A corner is a point two named streets share in the West Loop extract the
SideSeeing examples map, ``docs/examples/data/west_loop.osm.pbf``: a node of
OpenStreetMap that ways of two different names pass through, of the street
classes below. Each corner keeps its node's id, its point and the names of its
streets, sorted, so the example can tell which street a block of the walk runs
along and which streets it runs from and to:

    datasets/data.sideseeing.west-loop-corners@1/  the corners, as GeoJSON

The extract is read with pyosmium, as ``build_example_pbfs.py`` reads OSM; it
is not one of Curio's libraries, so install it once in the environment that
runs this script. Every date the dataset records is pinned, so a rebuild of the
same extract writes the same files. Run from the repository root:

    conda run -n curio pip install osmium     # once
    python scripts/build_example_sideseeing_corners.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXTRACT = REPO / "docs" / "examples" / "data" / "west_loop.osm.pbf"
DATASET = REPO / "datasets" / "data.sideseeing.west-loop-corners@1"
DATA_FILE = "data/corners.geojson"

#: The street classes a corner joins: those people walk along, leaving out
#: footways, paths and service roads, whose names are not streets'.
STREETS = {
    "primary", "secondary", "tertiary", "residential", "unclassified", "living_street",
    "primary_link", "secondary_link", "tertiary_link",
}

#: Every date the dataset records, the day it was built.
PINNED_ISO = "2026-11-17T00:00:00Z"

MANIFEST = {
    "id": "data.sideseeing.west-loop-corners",
    "name": "West Loop street corners",
    "version": "1.0.0",
    "format": "geojson",
    "description": (
        "The corners of the named streets in the West Loop extract the SideSeeing examples map: each "
        "corner's point, where two named streets meet, with their names sorted in street_a and street_b, "
        "and its OpenStreetMap node in corner_id. The SideSeeing frames example cuts its walk where it "
        "passes one."
    ),
    "publisher": "OpenStreetMap contributors",
    "license": "ODbL-1.0 (OpenStreetMap)",
    "tags": ["sideseeing", "chicago", "streets", "osm"],
    "dataFile": DATA_FILE,
    "compatibility": {"major": 1},
    "sourceLabel": "OpenStreetMap",
    "createdAt": PINNED_ISO,
    "updatedAt": PINNED_ISO,
    "rowCount": None,
    "schema": None,
}


def corners_of(extract: Path) -> list[dict]:
    """Each node two differently named streets of ``STREETS`` share, with its
    point and the names, sorted by node id."""
    import osmium

    class Streets(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.names_at = defaultdict(set)
            self.where = {}

        def way(self, way):
            name = way.tags.get("name")
            if way.tags.get("highway") in STREETS and name:
                for node in way.nodes:
                    self.names_at[node.ref].add(name)
                    if node.location.valid():
                        self.where[node.ref] = (round(node.location.lon, 7), round(node.location.lat, 7))

    streets = Streets()
    streets.apply_file(str(extract), locations=True)
    corners = []
    for ref in sorted(streets.names_at):
        names = sorted(streets.names_at[ref])
        if len(names) < 2 or ref not in streets.where:
            continue
        if len(names) > 2:
            raise SystemExit(f"node {ref} joins {len(names)} named streets, {names}: say which two it is the corner of")
        corners.append({"corner_id": ref, "street_a": names[0], "street_b": names[1], "point": streets.where[ref]})
    return corners


def build() -> int:
    corners = corners_of(EXTRACT)
    collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"corner_id": c["corner_id"], "street_a": c["street_a"], "street_b": c["street_b"]},
                "geometry": {"type": "Point", "coordinates": list(c["point"])},
            }
            for c in corners
        ],
    }
    (DATASET / "data").mkdir(parents=True, exist_ok=True)
    (DATASET / DATA_FILE).write_text(json.dumps(collection, indent=1) + "\n", encoding="utf-8")
    manifest = {**MANIFEST, "featureCount": len(corners)}
    (DATASET / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {DATASET.relative_to(REPO)}: {len(corners)} corners")
    for c in corners:
        print(f"  {c['corner_id']}: {c['street_a']} & {c['street_b']} at {c['point']}")
    return 0


if __name__ == "__main__":
    sys.exit(build())
