#!/usr/bin/env python3
"""Build example 10's street photos: ``datasets/data.curio.mapillary-sample@1``.

A few dozen Mapillary photos around Lincoln Park, Chicago, fetched once
through the Discovery Catalog's own Mapillary source and committed, so the
example runs with no token and no network. Mapillary imagery is CC BY-SA 4.0:
every photo keeps its photographer in ``metadata.csv`` and in
``mapillary-ATTRIBUTION.md``, and the dataset's license says so.

    docs/examples/data/storage/mapillary/<image_id>.jpg
    docs/examples/data/storage/mapillary/metadata.csv     a row per photo
    docs/examples/data/mapillary-ATTRIBUTION.md         beside, so a scan of
                                                        the folder skips it

The photos are a resource of the example storage source
(``source.curio.example-storage@1``, resource ``mapillary``), added to the
Data Catalog through the add path ``build_example_storage.py`` uses.

Needs a Mapillary access token of your own, in ``CURIO_MAPILLARY_TOKEN``; it
is sent as a header and written nowhere. Run from the repository root:

    CURIO_MAPILLARY_TOKEN=MLY|... PYTHONPATH=$PWD python scripts/build_example_mapillary.py
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
FOLDER = REPO / "docs" / "examples" / "data" / "storage" / "mapillary"
DATASET_ID = "data.curio.mapillary-sample"
MAPILLARY = REPO / "discovery" / "source.mapillary.imagery@1"

#: Lincoln Park and the neighbourhoods around it, asked as a grid of boxes so
#: the photos spread across them rather than along one drive.
AREA = (-87.66, 41.91, -87.63, 41.94)
GRID = 4
PER_BOX = 3
MOST = 40

#: The columns ``metadata.csv`` carries, joined onto each photo's row.
COLUMNS = ("file_name", "creator", "captured_at", "compass_angle", "is_pano", "sequence",
           "mapillary_url", "lat", "lon")


def _storage_builder():
    spec = importlib.util.spec_from_file_location("build_example_storage", REPO / "scripts" / "build_example_storage.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fetch(token: str) -> list:
    from utk_curio.backend.app.discovery.domain import parameters as P
    from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
    from utk_curio.backend.app.discovery.infrastructure.transport import (
        CredentialedTransport,
        HttpDiscoveryTransport,
    )
    from utk_curio.backend.app.discovery.providers import build_service

    manifest = load_source_manifest(MAPILLARY)
    credential = f"{manifest.auth.header_name}:{manifest.auth.value_prefix}{token}"
    transport = CredentialedTransport(
        HttpDiscoveryTransport(), credential, hosts=(urlsplit(manifest.provider.base_url).hostname,)
    )
    service = build_service(manifest, transport)
    spec = manifest.resource("images")
    west, south, east, north = AREA
    width, height = (east - west) / GRID, (north - south) / GRID
    images, seen = [], set()
    work = Path(tempfile.mkdtemp(prefix="curio-mapillary-"))
    for row in range(GRID):
        for col in range(GRID):
            box = [round(west + col * width, 5), round(south + row * height, 5),
                   round(west + (col + 1) * width, 5), round(south + (row + 1) * height, 5)]
            values = P.validate_values(manifest.declared_parameters("images"),
                                       {"area": {"box": box}, "size": "1024", "maxImages": PER_BOX})
            answer = service.load(spec, values, work / f"{row}-{col}")
            for image in answer.images:
                if image.image_id not in seen and len(images) < MOST:
                    seen.add(image.image_id)
                    images.append(image)
    return images


def write(images) -> None:
    if FOLDER.exists():
        shutil.rmtree(FOLDER)
    FOLDER.mkdir(parents=True)
    rows = []
    for image in images:
        name = f"{image.image_id}.jpg"
        shutil.copyfile(image.path, FOLDER / name)
        columns = image.columns
        rows.append({
            "file_name": name,
            "creator": columns.get("creator") or "",
            "captured_at": columns["captured_at"].strftime("%Y-%m-%dT%H:%M:%SZ") if columns.get("captured_at") else "",
            "compass_angle": columns.get("compass_angle"),
            "is_pano": bool(columns.get("is_pano")),
            "sequence": columns.get("sequence") or "",
            "mapillary_url": columns.get("mapillary_url"),
            "lat": columns.get("gps_lat"),
            "lon": columns.get("gps_lon"),
        })
    with (FOLDER / "metadata.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Mapillary photos in `storage/mapillary/`",
        "",
        "Street-level photos from [Mapillary](https://www.mapillary.com), licensed",
        "[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Each is credited",
        "to its photographer below and in `metadata.csv`.",
        "",
        "| Photo | Photographer | On Mapillary |",
        "|---|---|---|",
    ]
    lines += [f"| {r['file_name']} | {r['creator'] or 'unnamed'} | {r['mapillary_url']} |" for r in rows]
    (FOLDER.parent.parent / "mapillary-ATTRIBUTION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def add_to_catalog() -> str:
    storage = _storage_builder()
    storage.pin_times(FOLDER)
    saved = storage.DATASETS
    storage.DATASETS = [(
        "mapillary", DATASET_ID, "Mapillary street photos, Lincoln Park",
        "Street-level photos around Lincoln Park, Chicago, from Mapillary, with each photographer, "
        "capture time and place.",
    )]
    try:
        (name,) = storage.build_datasets()
    finally:
        storage.DATASETS = saved
    path = REPO / "datasets" / name / "manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.update({
        "publisher": "Mapillary contributors",
        "license": "CC-BY-SA-4.0",
        "tags": ["example", "mapillary", "street-level", "images"],
        "sourceLabel": "Mapillary (sample)",
    })
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return name


def main() -> None:
    token = os.environ.get("CURIO_MAPILLARY_TOKEN")
    if not token:
        raise SystemExit("set CURIO_MAPILLARY_TOKEN to your own Mapillary access token")
    images = fetch(token)
    write(images)
    name = add_to_catalog()
    total = sum(p.stat().st_size for p in FOLDER.iterdir())
    print(json.dumps({"photos": len(images), "bytes": total, "dataset": name}))


if __name__ == "__main__":
    main()
