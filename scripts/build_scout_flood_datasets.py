#!/usr/bin/env python3
"""Write SCOUT's flood rasters, whole, into the Data Catalog's seven ``data.scout.flood-*`` datasets.

SCOUT (https://github.com/urban-toolkit/scout) ships its Quad Cities flood
projections in ``backend/compute/quad_city_flooding_simulation/data_substitutes/``:
a class raster of where each nature-based solution (NbS) would go, and, for each
of three periods, the flood depth with and without NbS. Each is a 2592 by 2064
cell GeoTIFF in EPSG:4326 on one grid, uncompressed (the depth rasters 42.8 MB
each). SCOUT labels its first period 2020 - 2040 and names its files so
(``2020_2040_NbS_4326_cropped.tif``), though its next period starts in 2050:
Curio labels it 2020 - 2050, as komar41, one of SCOUT's authors, says. This
script writes each of them whole into ``datasets/<id>@1/`` with its manifest:

- every cell, the CRS, the transform, the dtype, the nodata and the tags as
  SCOUT's file holds them;
- compressed losslessly (DEFLATE, tiled).

The repository holds these files. Each manifest names its raster in
``downloadOnFirstUse``, so the pip package leaves it out, and a pip install
downloads it the first time Curio reads it.

``--check`` reads every raster whole and stops at the first whose cells, grid,
nodata or tags differ from SCOUT's file. ``--pins`` runs SCOUT's original
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

CATALOG_DIR = REPO_ROOT / "datasets"
SCOUT_FUNCTION = (
    REPO_ROOT / "utk_curio" / "backend" / "tests" / "test_packages" / "fixtures" / "scout_flood" / "flood_simulation.py"
)
STAMP = "2026-10-05T00:00:00Z"
PUBLISHER = "SCOUT (urban-toolkit/scout)"
#: What a dataflow that reads one of them shows on the Projects rail.
DATAFLOW_CATEGORIES = {"tags": ["SCOUT"]}

#: (top, left, bottom, right) in degrees: SCOUT's flood example's corners, the
#: defaults of the quad-cities-flood-vulnerability dataflow's Parameter nodes. They hold every
#: cell of SCOUT's grid.
SCOUT_REGION = (41.6242105, -90.6879323, 41.4150156, -90.4252158)
#: On the edges of SCOUT's cells: columns 2016 to 2271 and rows 1552 to 1807,
#: 256 by 256 cells that hold every NbS class code.
EXAMPLE_REGION = (41.4669317349186, -90.48363204845099, 41.44098884583301, -90.4576891593654)
#: Columns 2061 to 2215 and rows 1599 to 1758 of SCOUT's grid, on cell edges.
INNER_REGION = (41.46216878262555, -90.4790717749789, 41.44595447694705, -90.46336416635286)

CLASS_FILE = "NBS_others_5m_4326_cropped_cleaned_resampled.tif"
#: Each period as Curio labels it, which names its datasets, and as SCOUT
#: labels it, which names SCOUT's files.
PERIODS = {"2020 - 2050": "2020 - 2040", "2050 - 2080": "2050 - 2080", "2080 - 2100": "2080 - 2100"}

CLASS_CODES = (
    "21 bioswales or infiltration trenches, 31 permeable pavements, 43 retention ponds, "
    "52 infiltration trench, 71 and 81 bioswales, 90 and 95 constructed wetlands, and 0 none"
)


def _datasets() -> list[dict]:
    """The seven datasets: the class raster and each period's two depth rasters."""
    entries = [{
        "id": "data.scout.flood-nbs-classes",
        "name": "SCOUT Flood NbS Classes",
        "scout_file": CLASS_FILE,
        "data_file": "data/flood-nbs-classes.tif",
        "what": (
            "Where nature-based solutions (NbS) would go in SCOUT's Quad Cities flood projections, "
            f"as class codes: {CLASS_CODES}."
        ),
        "tags": ["raster", "flood", "nbs", "scout", "quad-cities", "geotiff"],
    }]
    for period, scout_period in PERIODS.items():
        start, end = period.split(" - ")
        stem = scout_period.replace(" - ", "_")
        for nbs in (True, False):
            entries.append({
                "id": f"data.scout.flood-depth-{start}-{end}-{'nbs' if nbs else 'no-nbs'}",
                "name": f"SCOUT Flood Depth {start}-{end} {'with' if nbs else 'without'} NbS",
                "scout_file": f"{stem}_{'NbS' if nbs else 'noNbS'}_4326_cropped.tif",
                "data_file": f"data/flood-depth-{start}-{end}-{'nbs' if nbs else 'no-nbs'}.tif",
                "what": (
                    f"Projected flood depth in metres for {start} to {end} "
                    f"{'with' if nbs else 'without'} nature-based solutions (NbS), from SCOUT's Quad Cities "
                    "flood projections. A cell with no depth holds no value."
                ),
                "tags": ["raster", "flood", "depth", "scout", "quad-cities", "geotiff"],
            })
    return entries


def _describe(entry: dict, raster) -> str:
    bounds = raster.bounds
    return (
        f"{entry['what']} SCOUT's {entry['scout_file']} whole: {raster.width} by {raster.height} cells "
        f"on its grid (EPSG:4326, cells of 0.000101 degrees), longitude {bounds.left:.4f} to "
        f"{bounds.right:.4f} and latitude {bounds.bottom:.4f} to {bounds.top:.4f}, every cell as SCOUT "
        "ships it, compressed losslessly. The quad-cities-flood-vulnerability test dataflow reads it. From SCOUT, "
        "https://github.com/urban-toolkit/scout, backend/compute/quad_city_flooding_simulation/data_substitutes, "
        "used with the permission of SCOUT's authors."
    )


def _write_manifest(entry: dict, root: Path, description: str) -> None:
    manifest = DatasetManifest(
        id=entry["id"],
        name=entry["name"],
        version="1.0.0",
        format="geotiff",
        description=description,
        publisher=PUBLISHER,
        # SCOUT's data is used with its authors' permission and names no license.
        license="",
        tags=list(entry["tags"]),
        data_file=entry["data_file"],
        major=1,
        download_on_first_use=(entry["data_file"],),
        created_at=STAMP,
        updated_at=STAMP,
        source_updated_at=None,
        feature_count=None,
        row_count=None,
        schema=None,
        source_label="SCOUT",
        dataflow_categories=DATAFLOW_CATEGORIES,
    )
    (root / "manifest.json").write_text(json.dumps(build_manifest_dict(manifest), indent=2) + "\n", encoding="utf-8")


def build(scout: Path) -> None:
    import rasterio

    with rasterio.open(scout / CLASS_FILE) as classes:
        grid = (classes.crs, classes.transform, classes.width, classes.height)
    total = 0
    for entry in _datasets():
        root = CATALOG_DIR / f"{entry['id']}@1"
        if root.exists():
            shutil.rmtree(root)
        (root / "data").mkdir(parents=True)
        target = root / entry["data_file"]
        with rasterio.open(scout / entry["scout_file"]) as source:
            if (source.crs, source.transform, source.width, source.height) != grid:
                raise SystemExit(f"{entry['scout_file']} is not on the class raster's grid")
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
        with rasterio.open(target) as written:
            _write_manifest(entry, root, _describe(entry, written))
        size = target.stat().st_size
        total += size
        print(f"{entry['id']}: {target.relative_to(REPO_ROOT)}, {size} bytes")
    print(f"total {total} bytes ({total / 1e6:.3f} MB)")


def _same_cells(a, b) -> bool:
    return a.shape == b.shape and a.dtype == b.dtype and a.tobytes() == b.tobytes()


def check(scout: Path) -> None:
    """Every raster holds SCOUT's file's cells on SCOUT's grid, with its nodata
    and tags, compressed losslessly."""
    import rasterio

    for entry in _datasets():
        ours_path = CATALOG_DIR / f"{entry['id']}@1" / entry["data_file"]
        with rasterio.open(scout / entry["scout_file"]) as theirs, rasterio.open(ours_path) as ours:
            if not _same_cells(theirs.read(1), ours.read(1)):
                raise SystemExit(f"{entry['id']}: the cells differ")
            if (theirs.crs, theirs.transform, theirs.nodata) != (ours.crs, ours.transform, ours.nodata):
                raise SystemExit(f"{entry['id']}: the grid or nodata differs")
            if theirs.tags() != ours.tags():
                raise SystemExit(f"{entry['id']}: the tags differ")
            if ours.profile.get("compress") != "deflate":
                raise SystemExit(f"{entry['id']}: not compressed with DEFLATE")
        print(f"{entry['id']}: every cell, the grid, nodata and tags as SCOUT's file")


#: The proof's cases, as ``test_scout_flood.py`` lists them (``CASES``):
#: SCOUT's function's calls, a region (top, left, bottom, right), SCOUT's
#: label of the period and SCOUT's names of the chosen NbS.
ALL_NBS = [
    "Bioswales/Infiltration trenches", "Permeable pavements", "Retention ponds",
    "Infiltration trench", "Bioswales", "Constructed wetlands",
]
PROOF_CASES = {
    "scout-2020-none": (SCOUT_REGION, "2020 - 2040", []),
    "scout-2020-all": (SCOUT_REGION, "2020 - 2040", ALL_NBS),
    "scout-2050-none": (SCOUT_REGION, "2050 - 2080", []),
    "scout-2050-all": (SCOUT_REGION, "2050 - 2080", ALL_NBS),
    "scout-2080-none": (SCOUT_REGION, "2080 - 2100", []),
    "scout-2080-all": (SCOUT_REGION, "2080 - 2100", ALL_NBS),
    "example-2020-all": (EXAMPLE_REGION, "2020 - 2040", ALL_NBS),
    "example-2020-none": (EXAMPLE_REGION, "2020 - 2040", []),
    "example-2050-none": (EXAMPLE_REGION, "2050 - 2080", []),
    "example-2050-all": (EXAMPLE_REGION, "2050 - 2080", ALL_NBS),
    "example-2080-some": (EXAMPLE_REGION, "2080 - 2100", ["Bioswales", "Constructed wetlands"]),
    "inner-2020-some": (INNER_REGION, "2020 - 2040", ["Retention ponds", "Permeable pavements"]),
}


@contextlib.contextmanager
def _scout_layout(files: dict):
    """A folder laid out as SCOUT's function reads it, entered: *files* maps
    SCOUT's file names to the files to read under them."""
    previous = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="scout-flood-") as folder:
        rasters = Path(folder) / "models" / "flooding" / "data_substitutes"
        rasters.mkdir(parents=True)
        for name, path in files.items():
            os.symlink(path, rasters / name)
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


def run_scout(files: dict, region, period, chosen, output="A"):
    """SCOUT's function as SCOUT's example calls it: ``(cells, transform,
    metrics)``, the raster it writes and the text of its metrics file."""
    import rasterio

    top, left, bottom, right = region
    simulate = _scout_function()
    with _scout_layout(files) as folder:
        simulate(f"{left!r}, {top!r}", f"{right!r}, {bottom!r}", output, year=period, use_NBS_classes=list(chosen))
        with rasterio.open(folder / "data" / "served" / "raster" / f"{output}.tif") as raster:
            cells, transform = raster.read(1), tuple(raster.transform)[:6]
        metrics = (folder / "data" / "served" / "metric" / f"{output}.csv").read_text(encoding="utf-8")
    return cells, transform, metrics


def pins(scout: Path) -> None:
    """The median and mean SCOUT computes, from the cells it writes (its
    metrics file rounds them), and a digest of those cells."""
    import numpy as np

    files = {entry["scout_file"]: str(scout / entry["scout_file"]) for entry in _datasets()}
    for case, (region, period, chosen) in PROOF_CASES.items():
        cells, transform, metrics = run_scout(files, region, period, chosen)
        digest = hashlib.sha256(cells.tobytes()).hexdigest()
        median, mean = float(np.nanmedian(cells)), float(np.nanmean(cells))
        print(f'    "{case}": Pin(shape={cells.shape!r}, median={median!r}, mean={mean!r},\n'
              f'        cells="{digest}",\n'
              f"        transform={transform!r}),  # metrics file: {metrics.splitlines()[1]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("scout", type=Path, help="SCOUT's data_substitutes folder")
    parser.add_argument("--check", action="store_true", help="compare the catalog's rasters with SCOUT's files")
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
