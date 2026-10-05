#!/usr/bin/env python3
"""Cut the Chicago Loop's buildings out of SCOUT's OSM extract for example 24.

WHY
---
Example 24 rasterizes real building heights with ``scout.raster-conversion@1``.
SCOUT's Chicago extract (``backend/data/catalog/osm/chicago/buildings.feather``,
1.1 million footprints with heights in metres) is far too large to commit, so
this script keeps the buildings inside one box over the Loop and writes them
as a small GeoParquet dataset in the committed Data Catalog.

The heights are SCOUT's: OpenStreetMap's ``height`` where a mapper set one,
otherwise an estimate from ``building:levels`` or a default. They are the
heights SCOUT feeds its own rasterizer, which is what the example shows.

HOW
---
The extract is read with GeoPandas (Feather or GeoParquet, by suffix), clipped
to ``BBOX`` with ``.cx`` (a footprint that crosses the box's edge is kept
whole, so the tiles at the edge are drawn as SCOUT draws them), reduced to the
columns the example uses, and written through the sandbox's own Parquet
helpers so the catalog's loader reads it back. Counts in the manifest come from
the frame written.

This is AUTHORING-ONLY tooling. It is not imported at runtime.

USAGE
-----
    conda run -n curio python scripts/build_example_loop_buildings.py \\
        --source <scout>/backend/data/catalog/osm/chicago/buildings.feather
    # then review, and commit datasets/data.osm.chicago-loop-buildings@1/

Idempotent: re-running overwrites the dataset directory.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from utk_curio.backend.app.datasets.domain.manifest import (  # noqa: E402
    DatasetManifest,
    build_manifest_dict,
    load_dataset_manifest,
)
from utk_curio.sandbox.util.codec import _prepare_frame_for_parquet  # noqa: E402

DATASET_ID = "data.osm.chicago-loop-buildings"
ROOT = REPO_ROOT / "datasets" / f"{DATASET_ID}@1"
DATA_FILE = "data/loop-buildings.parquet"

#: West, south, east, north in EPSG:4326: the Loop, from Union Station to
#: Michigan Avenue and from Congress Parkway to the river.
BBOX = (-87.6400, 41.8750, -87.6200, 41.8900)
COLUMNS = ["osm_id", "height", "geometry"]
STAMP = "2026-10-05T00:00:00Z"


def build(source: Path) -> None:
    import geopandas as gpd

    if not source.exists():
        raise SystemExit(f"source {source} is missing; pass SCOUT's Chicago buildings extract")
    print(f"  reading {source}")
    frame = gpd.read_feather(source) if source.suffix == ".feather" else gpd.read_parquet(source)
    west, south, east, north = BBOX
    loop = frame.cx[west:east, south:north][COLUMNS].reset_index(drop=True)
    loop = loop.to_crs("EPSG:4326")
    print(f"    {len(loop)} buildings, heights {loop['height'].min():.1f} to {loop['height'].max():.1f} m")

    if ROOT.exists():
        shutil.rmtree(ROOT)
    dest = ROOT / DATA_FILE
    dest.parent.mkdir(parents=True)
    prepared, encoded = _prepare_frame_for_parquet(loop, geometry_col=loop.geometry.name)
    assert not encoded, encoded  # osm_id, height and geometry: nothing to JSON-encode
    prepared.to_parquet(dest, compression="zstd")

    manifest = DatasetManifest(
        id=DATASET_ID,
        name="Chicago Loop Buildings",
        version="1.0.0",
        format="parquet",
        description=(
            "Building footprints of the Chicago Loop with heights in metres, "
            "cut from SCOUT's OpenStreetMap extract of Chicago. A height is "
            "OpenStreetMap's where a mapper set one, otherwise SCOUT's "
            "estimate from the number of levels or a default, so it is not "
            "always a surveyed measurement."
        ),
        publisher="OpenStreetMap contributors",
        license="ODbL-1.0",
        tags=["chicago", "loop", "osm", "buildings", "height", "parquet"],
        data_file=DATA_FILE,
        major=1,
        created_at=STAMP,
        updated_at=STAMP,
        source_updated_at=None,
        feature_count=len(loop),
        row_count=len(loop),
        schema=None,
        source_label="OpenStreetMap contributors; SCOUT preprocessing",
    )
    (ROOT / "manifest.json").write_text(
        json.dumps(build_manifest_dict(manifest), indent=2) + "\n", encoding="utf-8"
    )
    loaded = load_dataset_manifest(ROOT)
    assert loaded.id == DATASET_ID, loaded.id
    print(f"    -> {dest.relative_to(REPO_ROOT).as_posix()} ({dest.stat().st_size / 1e3:.0f} KB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True, help="SCOUT's Chicago buildings extract")
    build(parser.parse_args().source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
