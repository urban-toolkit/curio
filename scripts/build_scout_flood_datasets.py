#!/usr/bin/env python3
"""Ship SCOUT's flood rasters as one Data Catalog dataset, ``data.scout.quad-cities-flood``.

SCOUT (https://github.com/urban-toolkit/scout) ships its Quad Cities flood
projections in ``backend/compute/quad_city_flooding_simulation/data_substitutes/``:
a class raster of where each nature-based solution (NbS) would go, and, for each
of three periods, the flood depth with and without NbS. Each is a 2592 by 2064
cell GeoTIFF in EPSG:4326 on one grid, uncompressed (the depth rasters 42.8 MB
each). This script writes the seven of them into one bundle,
``datasets/data.scout.quad-cities-flood@1/``:

- ``data/nbs_classes.tif`` and ``data/<period>_NbS.tif`` / ``_noNbS.tif``:
  each raster whole, beside ``data/bundle.json``; the Flood Projection node of
  ``scout.flood@1`` hands SCOUT's function the ``data`` folder, and its copy of
  SCOUT's code opens these names;
- the same CRS, transform, dtype, nodata and tags, every cell kept; compressed
  losslessly (DEFLATE, tiled);
- ``data/bundle.json`` lists them, and ``manifest.json`` describes them.

``--check`` reads every part whole and stops at the first whose cells, grid or
nodata differ from SCOUT's file. ``--pins`` runs SCOUT's original
``simulate_flood_projection`` (the test fixture copy) on SCOUT's files for the
proof cases in ``test_scout_flood.py`` and prints the values that test pins.

This is AUTHORING-ONLY tooling, run once by hand; nothing imports it.

USAGE
-----
    python scripts/build_scout_flood_datasets.py <scout>/backend/compute/quad_city_flooding_simulation/data_substitutes
    python scripts/build_scout_flood_datasets.py <data_substitutes> --check --pins
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from utk_curio.backend.app.datasets.domain.manifest import (  # noqa: E402
    DatasetManifest,
    build_manifest_dict,
)

DATASET_ID = "data.scout.quad-cities-flood"
DATASET_DIR = REPO_ROOT / "datasets" / f"{DATASET_ID}@1"
SCOUT_FUNCTION = (
    REPO_ROOT / "utk_curio" / "backend" / "tests" / "test_packages" / "fixtures" / "scout_flood" / "flood_simulation.py"
)
STAMP = "2026-10-07T00:00:00Z"
PUBLISHER = "SCOUT (urban-toolkit/scout)"

CLASS_FILE = "NBS_others_5m_4326_cropped_cleaned_resampled.tif"
PERIODS = ("2020 - 2040", "2050 - 2080", "2080 - 2100")


def _parts() -> list[dict]:
    """The seven parts: the class raster and each period's two depth rasters,
    each with its name in the bundle (``file``) and SCOUT's (``scout``)."""
    parts = [{"file": "nbs_classes.tif", "scout": CLASS_FILE, "label": "NbS classes"}]
    for period in PERIODS:
        stem = period.replace(" - ", "_")
        for kind, what in (("NbS", "with"), ("noNbS", "without")):
            parts.append({"file": f"{stem}_{kind}.tif", "scout": f"{stem}_{kind}_4326_cropped.tif",
                          "label": f"Flood depth {period} {what} NbS"})
    return parts


DESCRIPTION = (
    "SCOUT's Quad Cities flood projections, the seven rasters SCOUT's simulate_flood_projection reads, "
    "each a 2592 by 2064 cell GeoTIFF on one grid (EPSG:4326, cells of 0.000101 degrees, longitude "
    "-90.6879 to -90.4252 and latitude 41.4150 to 41.6242): "
    "nbs_classes.tif, where nature-based solutions (NbS) would go, as class codes (21 bioswales or "
    "infiltration trenches, 31 permeable pavements, 43 retention ponds, 52 infiltration trench, 71 and 81 "
    "bioswales, 90 and 95 constructed wetlands, and 0 none); and, for 2020-2040, 2050-2080 and 2080-2100, "
    "<period>_NbS.tif and <period>_noNbS.tif, the projected flood depth in metres "
    "with and without NbS. The Flood Projection node of the scout.flood package runs SCOUT's function on "
    "them. Every cell as SCOUT ships it, compressed losslessly. From SCOUT, "
    "https://github.com/urban-toolkit/scout, backend/compute/quad_city_flooding_simulation/data_substitutes, "
    "used with the permission of SCOUT's authors."
)


def _write_manifest() -> None:
    manifest = DatasetManifest(
        id=DATASET_ID,
        name="SCOUT Quad Cities Flood Projections",
        version="1.0.0",
        format="bundle",
        description=DESCRIPTION,
        publisher=PUBLISHER,
        # SCOUT's data is used with its authors' permission and names no license.
        license="to be confirmed",
        tags=["raster", "flood", "depth", "nbs", "scout", "quad-cities", "geotiff"],
        data_file="data/bundle.json",
        major=1,
        created_at=STAMP,
        updated_at=STAMP,
        source_updated_at=None,
        feature_count=None,
        row_count=None,
        schema=None,
        source_label="SCOUT",
    )
    (DATASET_DIR / "manifest.json").write_text(
        json.dumps(build_manifest_dict(manifest), indent=2) + "\n", encoding="utf-8"
    )


def build(scout: Path) -> None:
    import rasterio

    if DATASET_DIR.exists():
        shutil.rmtree(DATASET_DIR)
    parts_dir = DATASET_DIR / "data"
    parts_dir.mkdir(parents=True)
    listed, total = [], 0
    for index, part in enumerate(_parts()):
        target = parts_dir / part["file"]
        with rasterio.open(scout / part["scout"]) as source:
            cells = source.read(1)
            floating = cells.dtype.kind == "f"
            profile = {
                "driver": "GTiff", "width": source.width, "height": source.height, "count": 1,
                "dtype": cells.dtype, "crs": source.crs, "transform": source.transform, "nodata": source.nodata,
                "compress": "deflate", "predictor": 3 if floating else 2, "zlevel": 9,
                "tiled": True, "blockxsize": 256, "blockysize": 256,
            }
            with rasterio.open(target, "w", **profile) as copy:
                copy.write(cells, 1)
                copy.update_tags(**source.tags())
        size = target.stat().st_size
        total += size
        listed.append({
            "index": index, "label": part["label"], "kind": "raster", "format": "geotiff",
            "file": f"data/{part['file']}",
        })
        print(f"{part['file']}: {size} bytes")
    (DATASET_DIR / "data" / "bundle.json").write_text(
        json.dumps({"version": 1, "parts": listed}, indent=2) + "\n", encoding="utf-8"
    )
    _write_manifest()
    print(f"total {total} bytes ({total / 1e6:.1f} MB)")


def check(scout: Path) -> None:
    """Every part holds SCOUT's file's cells on SCOUT's grid."""
    import rasterio

    for part in _parts():
        with rasterio.open(scout / part["scout"]) as theirs, rasterio.open(DATASET_DIR / "data" / part["file"]) as ours:
            a, b = theirs.read(1), ours.read(1)
            if a.dtype != b.dtype or a.shape != b.shape or a.tobytes() != b.tobytes():
                raise SystemExit(f"{part['file']}: the cells differ")
            if (theirs.crs, theirs.transform, theirs.nodata) != (ours.crs, ours.transform, ours.nodata):
                raise SystemExit(f"{part['file']}: the grid or nodata differs")
        print(f"{part['file']}: every cell, the grid and nodata as SCOUT's file")


#: SCOUT's flood example's corners, (top, left, bottom, right): the whole grid.
SCOUT_REGION = (41.6242105, -90.6879323, 41.4150156, -90.4252158)
#: The edges of SCOUT's columns 2061 to 2215 and rows 1599 to 1758.
INNER_REGION = (41.46216878262555, -90.4790717749789, 41.44595447694705, -90.46336416635286)
ALL_NBS = [
    "Bioswales/Infiltration trenches", "Permeable pavements", "Retention ponds",
    "Infiltration trench", "Bioswales", "Constructed wetlands",
]
#: The proof's cases, as ``test_scout_flood.py`` lists them: a region, a
#: period and the chosen NbS.
PROOF_CASES = {
    "scout-2020-none": (SCOUT_REGION, "2020 - 2040", []),
    "scout-2020-all": (SCOUT_REGION, "2020 - 2040", ALL_NBS),
    "scout-2050-none": (SCOUT_REGION, "2050 - 2080", []),
    "scout-2050-all": (SCOUT_REGION, "2050 - 2080", ALL_NBS),
    "scout-2080-none": (SCOUT_REGION, "2080 - 2100", []),
    "scout-2080-all": (SCOUT_REGION, "2080 - 2100", ALL_NBS),
    "inner-2080-some": (INNER_REGION, "2080 - 2100", ["Bioswales", "Constructed wetlands"]),
}


@contextlib.contextmanager
def _scout_layout(folder_of_rasters: Path):
    """A folder laid out as SCOUT's function reads it, entered: SCOUT's
    rasters linked in from *folder_of_rasters*."""
    previous = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="scout-flood-") as folder:
        rasters = Path(folder) / "models" / "flooding" / "data_substitutes"
        rasters.mkdir(parents=True)
        for part in _parts():
            os.symlink(folder_of_rasters / part["scout"], rasters / part["scout"])
        os.chdir(folder)
        try:
            yield Path(folder)
        finally:
            os.chdir(previous)


def _scout_function():
    spec = importlib.util.spec_from_file_location("scout_flood_simulation", SCOUT_FUNCTION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.simulate_flood_projection


def run_scout(folder_of_rasters: Path, region, period, chosen, output="A"):
    """SCOUT's function as SCOUT's example calls it: ``(cells, transform,
    metrics)``, the raster it writes and the text of its metrics file."""
    import rasterio

    top, left, bottom, right = region
    simulate = _scout_function()
    with _scout_layout(folder_of_rasters) as folder:
        simulate(f"{left!r}, {top!r}", f"{right!r}, {bottom!r}", output, year=period, use_NBS_classes=list(chosen))
        with rasterio.open(folder / "data" / "served" / "raster" / f"{output}.tif") as raster:
            cells, transform = raster.read(1), tuple(raster.transform)[:6]
        metrics = (folder / "data" / "served" / "metric" / f"{output}.csv").read_text(encoding="utf-8")
    return cells, transform, metrics


def pins(scout: Path) -> None:
    """The median and mean SCOUT computes, from the cells it writes, and a
    digest of those cells."""
    import numpy as np

    for case, (region, period, chosen) in PROOF_CASES.items():
        cells, transform, metrics = run_scout(scout, region, period, chosen)
        digest = hashlib.sha256(cells.tobytes()).hexdigest()
        median, mean = float(np.nanmedian(cells)), float(np.nanmean(cells))
        print(f'    "{case}": Pin(shape={cells.shape!r}, median={median!r}, mean={mean!r},\n'
              f'        cells="{digest}",\n'
              f"        transform={transform!r}),  # metrics file: {metrics.splitlines()[1]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("scout", type=Path, help="SCOUT's data_substitutes folder")
    parser.add_argument("--check", action="store_true", help="compare the parts with SCOUT's files")
    parser.add_argument("--pins", action="store_true", help="print the proof's values from SCOUT's files")
    args = parser.parse_args()
    if not args.check and not args.pins:
        build(args.scout)
    if args.check:
        check(args.scout)
    if args.pins:
        pins(args.scout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
