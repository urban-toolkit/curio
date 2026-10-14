#!/usr/bin/env python3
"""Build the Data Catalog dataset ``data.curio.lower-manhattan-shadows``.

Lower Manhattan's buildings and parks, as the Discovery Catalog downloads them:
the Financial District to City Hall, some 30 named parks and plazas among very
tall towers. The ShadowsAnywhere test dataflow loads them: SCOUT's rasterizer
and Deep Umbra shadow model on a city SCOUT never shipped, and the minutes of
shadow in each park.

Two boxes: the parks of PARKS_BOX, and the buildings of BUILDINGS_BOX, the
parks' box with about 300 m more on every side, since a tower just outside the
parks' box still shades a park at its edge.

HOW
---
Both layers come through Curio's own Discovery Catalog providers, the code a
**Download** runs, so the files are what a person downloading the box gets:

1. **Buildings** of the ``source.overture.maps`` source (``OvertureService``):
   Overture's buildings whose box meets BUILDINGS_BOX, every column as Overture
   names it, ``height`` in metres among them, as GeoParquet in EPSG:4326.
2. **Parks** of the ``source.osm.openstreetmap`` source (``AutarkOsmService``):
   Autark's parks layer, cut at PARKS_BOX, moved to EPSG:4326 and its number
   tags made numbers as a download does (``to_wgs84``, ``with_numbers``).

They are written as one bundle, ``data/buildings.parquet`` and
``data/parks.geojson``, listed by ``data/bundle.json``, with its manifest.

This is AUTHORING-ONLY tooling. It needs network access to Overture's bucket
and to Overpass, and the repository's Node packages (``npm install`` at the
repository root installs the autk-db build Curio pins)::

    conda run -n curio python scripts/build_lower_manhattan_shadows_dataset.py

Overture's buildings are ODbL 1.0 (https://docs.overturemaps.org/attribution/);
the parks are OpenStreetMap data, (c) OpenStreetMap contributors, ODbL 1.0.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from utk_curio.backend.app.discovery.application.service_acquire import to_wgs84  # noqa: E402
from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest  # noqa: E402
from utk_curio.backend.app.discovery.domain.osm_values import with_numbers  # noqa: E402
from utk_curio.backend.app.discovery.infrastructure.transport import HttpDiscoveryTransport  # noqa: E402
from utk_curio.backend.app.discovery.providers import autark_osm, overture  # noqa: E402

DATASET_ID = "data.curio.lower-manhattan-shadows"
OUT = REPO / "datasets" / f"{DATASET_ID}@1"
#: West, south, east, north: the Financial District to City Hall.
PARKS_BOX = [-74.0180, 40.7000, -74.0040, 40.7130]
#: The parks' box and about 300 m more on every side.
BUILDINGS_BOX = [-74.0215, 40.6973, -74.0005, 40.7157]
PLACE = "Lower Manhattan, the Financial District to City Hall"
OVERTURE = "source.overture.maps@1"
OSM = "source.osm.openstreetmap@1"


def download(work: Path) -> tuple[Path, Path, str]:
    """The Overture buildings' file, the parks' collection file, and the
    Overture release they came from."""
    manifest = load_source_manifest(REPO / "discovery" / OVERTURE)
    service = overture.OvertureService(manifest, transport=HttpDiscoveryTransport())
    (buildings,) = service.load(manifest.resource("buildings"),
                                {"area": {"box": BUILDINGS_BOX, "label": PLACE}}, work, stage=print)

    manifest = load_source_manifest(REPO / "discovery" / OSM)
    (parks,) = autark_osm.AutarkOsmService(manifest).load(manifest.resource("parks"),
                                                          {"area": {"box": PARKS_BOX, "label": PLACE}}, work,
                                                          stage=print)
    collection = with_numbers(to_wgs84(json.loads(parks.path.read_text(encoding="utf-8"))))
    parks_file = work / "parks.wgs84.geojson"
    parks_file.write_text(json.dumps(collection, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"{buildings.features} buildings, {parks.features} parks, Overture release {service.release}")
    return buildings.path, parks_file, service.release


def write(buildings: Path, parks: Path, release: str) -> None:
    import geopandas as gpd

    frame = gpd.read_parquet(buildings)
    park_count = len(json.loads(parks.read_text(encoding="utf-8"))["features"])
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "data").mkdir(parents=True)
    shutil.copyfile(buildings, OUT / "data" / "buildings.parquet")
    shutil.copyfile(parks, OUT / "data" / "parks.geojson")
    bundle = {
        "version": 1,
        "parts": [
            {"index": 0, "label": "Buildings (Overture Maps)", "kind": "geodataframe",
             "format": "parquet", "file": "data/buildings.parquet"},
            {"index": 1, "label": "Parks (OpenStreetMap)", "kind": "geodataframe",
             "format": "geojson", "file": "data/parks.geojson"},
        ],
    }
    (OUT / "data" / "bundle.json").write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    today = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime())
    west, south, east, north = PARKS_BOX
    b_west, b_south, b_east, b_north = BUILDINGS_BOX
    manifest = {
        "id": DATASET_ID,
        "name": "Lower Manhattan Buildings and Parks",
        "version": "1.0.0",
        "format": "bundle",
        "description": (
            "Lower Manhattan, the Financial District to City Hall. Two parts, as the Discovery Catalog "
            f"downloads them: parks.geojson, OpenStreetMap's {park_count} parks, playgrounds and green spaces "
            f"of longitude {west} to {east}, latitude {south} to {north}, as Autark's parks layer cuts them "
            f"at that box; and buildings.parquet, the {len(frame):,} buildings of Overture Maps release "
            f"{release} in a box about 300 m larger on every side (longitude {b_west} to {b_east}, latitude "
            f"{b_south} to {b_north}), so the towers that shade the parks at its edge are there too, every "
            "column as Overture names it, height in metres among them (missing for a few). Both in EPSG:4326. The ShadowsAnywhere test dataflow runs SCOUT's shadow "
            "model on them. Built by scripts/build_lower_manhattan_shadows_dataset.py."
        ),
        "publisher": "Overture Maps Foundation; OpenStreetMap contributors",
        "license": "ODbL-1.0",
        "tags": ["buildings", "parks", "new-york", "manhattan", "overture", "osm", "bundle"],
        "dataFile": "data/bundle.json",
        "compatibility": {"major": 1},
        "sourceLabel": "Discovery Catalog: Overture Maps and OpenStreetMap",
        "rowCount": None,
        "featureCount": None,
        "schema": None,
        "createdAt": today,
        "updatedAt": today,
        "sourceUpdatedAt": None,
        "sourceEncoding": None,
        "groupId": None,
        "layerName": None,
        "producerNodeId": None,
        "producerNodeType": None,
        "producerDataflowId": None,
        "producerDataflowName": None,
        "upstreamInputs": None,
        # Not a download of this account, so no discoverySource: the catalog
        # matches that block when it asks whether a download is already held.
        "discoverySource": None,
        "collection": None,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        write(*download(Path(tmp)))


if __name__ == "__main__":
    main()
