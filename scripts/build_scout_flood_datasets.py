#!/usr/bin/env python3
"""Cut SCOUT's flood rasters down to the area the scout.flood package's example reads.

SCOUT (https://github.com/urban-toolkit/scout) ships its Quad Cities flood
projections in ``backend/compute/quad_city_flooding_simulation/data_substitutes/``:
a class raster of where each nature-based solution (NbS) would go, and, for each
of three periods, the flood depth with and without NbS. Each is a 2592 by 2064
cell GeoTIFF in EPSG:4326 (the depth rasters 42.8 MB each), too large for the
repository. This script writes a crop of each into ``datasets/<id>@1/`` with its
manifest:

- the crop is the example's region (``EXAMPLE_REGION``, the scout.flood
  template's default corners) plus ``MARGIN`` cells on every side;
- it keeps SCOUT's grid: the same CRS, cell size and cell edges, dtype and
  nodata, so a window read on a crop gives the cells the same window read on
  SCOUT's file gives;
- it is compressed losslessly (DEFLATE).

``--check`` reads the example region and 400 random windows inside the crop
from each crop and from SCOUT's file and stops at the first window whose cells
or transform differ. ``--pins`` runs SCOUT's original ``simulate_flood_projection``
(the test fixture copy) on SCOUT's files for the proof cases in
``test_scout_flood.py`` and prints the values that test pins.

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
import math
import os
import random
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

#: (top, left, bottom, right) in degrees: the scout.flood template's default
#: corners, 256 by 256 cells that hold every NbS class code.
EXAMPLE_REGION = (41.4669, -90.4836, 41.4410, -90.4577)
#: Cells kept on every side of the region.
MARGIN = 32

CLASS_FILE = "NBS_others_5m_4326_cropped_cleaned_resampled.tif"
PERIODS = ("2020 - 2040", "2050 - 2080", "2080 - 2100")

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
    for period in PERIODS:
        start, end = period.split(" - ")
        for nbs in (True, False):
            entries.append({
                "id": f"data.scout.flood-depth-{start}-{end}-{'nbs' if nbs else 'no-nbs'}",
                "name": f"SCOUT Flood Depth {start}-{end} {'with' if nbs else 'without'} NbS",
                "scout_file": f"{start}_{end}_{'NbS' if nbs else 'noNbS'}_4326_cropped.tif",
                "data_file": f"data/flood-depth-{start}-{end}-{'nbs' if nbs else 'no-nbs'}.tif",
                "what": (
                    f"Projected flood depth in metres for {start} to {end} "
                    f"{'with' if nbs else 'without'} nature-based solutions (NbS), from SCOUT's Quad Cities "
                    "flood projections. A cell with no depth holds no value."
                ),
                "tags": ["raster", "flood", "depth", "scout", "quad-cities", "geotiff"],
            })
    return entries


def _crop_window(transform):
    """The crop's window on SCOUT's grid: the example region plus the margin,
    on whole cells."""
    from rasterio.windows import Window, from_bounds

    top, left, bottom, right = EXAMPLE_REGION
    region = from_bounds(left, bottom, right, top, transform=transform)
    col0 = math.floor(region.col_off) - MARGIN
    row0 = math.floor(region.row_off) - MARGIN
    col1 = math.ceil(region.col_off + region.width) + MARGIN
    row1 = math.ceil(region.row_off + region.height) + MARGIN
    return Window(col0, row0, col1 - col0, row1 - row0)


def _describe(entry: dict, window, bounds) -> str:
    return (
        f"{entry['what']} A {window.width} by {window.height} cell crop of SCOUT's {entry['scout_file']} "
        f"on its own grid (EPSG:4326, cells of 0.000101 degrees), longitude {bounds.left:.4f} to "
        f"{bounds.right:.4f} and latitude {bounds.bottom:.4f} to {bounds.top:.4f}: the area the "
        "scout.flood package's example reads. From SCOUT, https://github.com/urban-toolkit/scout, "
        "backend/compute/quad_city_flooding_simulation/data_substitutes."
    )


def _write_manifest(entry: dict, root: Path, description: str) -> None:
    manifest = DatasetManifest(
        id=entry["id"],
        name=entry["name"],
        version="1.0.0",
        format="geotiff",
        description=description,
        publisher="SCOUT",
        license="Research use",
        tags=list(entry["tags"]),
        data_file=entry["data_file"],
        major=1,
        created_at=STAMP,
        updated_at=STAMP,
        source_updated_at=None,
        feature_count=None,
        row_count=None,
        schema=None,
        source_label="SCOUT",
    )
    (root / "manifest.json").write_text(json.dumps(build_manifest_dict(manifest), indent=2) + "\n", encoding="utf-8")


def build(scout: Path) -> None:
    import rasterio

    with rasterio.open(scout / CLASS_FILE) as classes:
        window = _crop_window(classes.transform)
        grid = (classes.crs, classes.transform)
    total = 0
    for entry in _datasets():
        root = CATALOG_DIR / f"{entry['id']}@1"
        if root.exists():
            shutil.rmtree(root)
        (root / "data").mkdir(parents=True)
        target = root / entry["data_file"]
        with rasterio.open(scout / entry["scout_file"]) as source:
            if (source.crs, source.transform) != grid:
                raise SystemExit(f"{entry['scout_file']} is not on the class raster's grid")
            cells = source.read(1, window=window)
            floating = cells.dtype.kind == "f"
            profile = {
                "driver": "GTiff", "width": window.width, "height": window.height, "count": 1,
                "dtype": cells.dtype, "crs": source.crs, "transform": source.window_transform(window),
                "nodata": source.nodata, "compress": "deflate", "predictor": 3 if floating else 2, "zlevel": 9,
            }
            with rasterio.open(target, "w", **profile) as crop:
                crop.write(cells, 1)
                crop.update_tags(**source.tags())
        with rasterio.open(target) as crop:
            bounds = crop.bounds
        _write_manifest(entry, root, _describe(entry, window, bounds))
        size = target.stat().st_size
        total += size
        print(f"{entry['id']}: {target.relative_to(REPO_ROOT)}, {window.width} by {window.height} cells "
              f"from column {window.col_off}, row {window.row_off}; {size} bytes")
    print(f"crop bounds: left {bounds.left!r}, bottom {bounds.bottom!r}, right {bounds.right!r}, top {bounds.top!r}")
    print(f"total {total} bytes ({total / 1e6:.3f} MB)")


def _same_cells(a, b) -> bool:
    return a.shape == b.shape and a.dtype == b.dtype and a.tobytes() == b.tobytes()


def check(scout: Path, windows: int = 400) -> None:
    """Every crop reads like SCOUT's file, window for window."""
    import rasterio
    from rasterio.windows import from_bounds

    rng = random.Random(662)
    for entry in _datasets():
        crop_path = CATALOG_DIR / f"{entry['id']}@1" / entry["data_file"]
        with rasterio.open(scout / entry["scout_file"]) as full, rasterio.open(crop_path) as crop:
            res = crop.transform.a
            b = crop.bounds
            regions = [EXAMPLE_REGION]
            for _ in range(windows):
                width, height = rng.uniform(3, 250) * res, rng.uniform(3, 250) * res
                left = rng.uniform(b.left + 2 * res, b.right - 2 * res - width)
                top = rng.uniform(b.bottom + 2 * res + height, b.top - 2 * res)
                regions.append((top, left, top - height, left + width))
            for top, left, bottom, right in regions:
                on_full = from_bounds(left, bottom, right, top, transform=full.transform)
                on_crop = from_bounds(left, bottom, right, top, transform=crop.transform)
                if not _same_cells(full.read(1, window=on_full), crop.read(1, window=on_crop)):
                    raise SystemExit(f"{entry['id']}: the cells of {(top, left, bottom, right)} differ")
                if tuple(full.window_transform(on_full)) != tuple(crop.window_transform(on_crop)):
                    raise SystemExit(f"{entry['id']}: the transform of {(top, left, bottom, right)} differs")
        print(f"{entry['id']}: {len(regions)} windows read the same cells and transform as SCOUT's file")


#: The proof's cases, as ``test_scout_flood.py`` lists them: a region
#: (top, left, bottom, right), a period and the chosen NbS.
ALL_NBS = [
    "Bioswales/Infiltration trenches", "Permeable pavements", "Retention ponds",
    "Infiltration trench", "Bioswales", "Constructed wetlands",
]
PROOF_CASES = {
    "example-2020-all": (EXAMPLE_REGION, "2020 - 2040", ALL_NBS),
    "example-2020-none": (EXAMPLE_REGION, "2020 - 2040", []),
    "example-2050-none": (EXAMPLE_REGION, "2050 - 2080", []),
    "example-2050-all": (EXAMPLE_REGION, "2050 - 2080", ALL_NBS),
    "example-2080-some": (EXAMPLE_REGION, "2080 - 2100", ["Bioswales", "Constructed wetlands"]),
    "inner-2020-some": ((41.46213, -90.47912, 41.44587, -90.46345), "2020 - 2040", ["Retention ponds", "Permeable pavements"]),
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
    parser.add_argument("--check", action="store_true", help="compare the crops with SCOUT's files")
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
