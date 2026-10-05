#!/usr/bin/env python3
"""Copy SCOUT's Quad Cities flood rasters into the Data Catalog for example 25.

WHY
---
Example 25 runs SCOUT's flood simulation (``scout.flood-simulation@1``) on the
rasters SCOUT's flooding use case reads: a map of nature-based solution (NbS)
classes, and for each of three periods the flood depth with those solutions
in place and without them. They are one input, read together on one grid, so
they are ONE dataset, ``data.scout.quad-cities-flood``: its seven files side
by side in ``data/``, named as SCOUT's catalog names them
(``backend/data/catalog/quad_city_flooding``), and listed by
``data/bundle.json``. A node reads one by name:

    curio_load_data("data.scout.quad-cities-flood", part="2020_2040_NbS.tif")

SCOUT keeps the depths as uncompressed float64, 42 MB a file, too large to
commit; here each is float32 with DEFLATE, at SCOUT's resolution and on its
grid, 10 MB for the seven. SCOUT marks a cell with no depth two ways: NaN,
and in 2050-2080 without NbS the float64 nodata value, -1.8e308. SCOUT's
simulation turns the second into NaN (``combined == flood_nodata``); here both
become NaN before the cast, since -1.8e308 is no float32. The classes stay
uint8, 0 where a cell has none.

HOW
---
Each raster is read from SCOUT's ``models/flooding/data_substitutes`` (the
files its simulation reads), its grid checked against the classes' (SCOUT
asserts the same before combining them), its no-depth cells set to NaN, cast
to float32 and checked against the float64 values (every cell within float32
rounding, NaN in the same cells), and written under SCOUT's catalog name.

This is AUTHORING-ONLY tooling. It is not imported at runtime.

USAGE
-----
    conda run -n curio python scripts/build_example_quad_cities_flood.py \\
        --scout <scout>/backend
    # then review, and commit datasets/data.scout.quad-cities-flood@1/

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

DATASET_ID = "data.scout.quad-cities-flood"
ROOT = REPO_ROOT / "datasets" / f"{DATASET_ID}@1"
SOURCE_DIR = Path("models") / "flooding" / "data_substitutes"
STAMP = "2026-10-05T00:00:00Z"

#: Each file: its name in the dataset (SCOUT's catalog name), its label, and
#: SCOUT's file its simulation reads.
FILES = [
    ("NBS_others_5m.tif", "NbS classes", "NBS_others_5m_4326_cropped_cleaned_resampled.tif"),
    ("2020_2040_NbS.tif", "Flood depth 2020-2040 with NbS", "2020_2040_NbS_4326_cropped.tif"),
    ("2020_2040_noNbS.tif", "Flood depth 2020-2040 without NbS", "2020_2040_noNbS_4326_cropped.tif"),
    ("2050_2080_NbS.tif", "Flood depth 2050-2080 with NbS", "2050_2080_NbS_4326_cropped.tif"),
    ("2050_2080_noNbS.tif", "Flood depth 2050-2080 without NbS", "2050_2080_noNbS_4326_cropped.tif"),
    ("2080_2100_NbS.tif", "Flood depth 2080-2100 with NbS", "2080_2100_NbS_4326_cropped.tif"),
    ("2080_2100_noNbS.tif", "Flood depth 2080-2100 without NbS", "2080_2100_noNbS_4326_cropped.tif"),
]

#: SCOUT ships these rasters with no source or license. Confirm both before
#: committing the dataset, and set them here.
PUBLISHER = "SCOUT (urban-toolkit/scout)"
LICENSE = "Unspecified: SCOUT example data, source and license to be confirmed"
SOURCE_LABEL = "SCOUT flooding use case"


def _values(path, grid):
    """*path*'s cells as Curio stores them, and the profile to write them with."""
    import numpy as np
    import rasterio

    with rasterio.open(path) as src:
        assert (src.crs, src.transform, src.width, src.height) == grid, f"{path.name} is not on the classes' grid"
        values = src.read(1)
        nodata = src.nodata
    profile = {
        "driver": "GTiff", "width": grid[2], "height": grid[3], "count": 1,
        "crs": grid[0], "transform": grid[1], "compress": "deflate",
    }
    if values.dtype == np.uint8:
        return values, {**profile, "dtype": "uint8", "nodata": 0}
    missing = np.isnan(values) | (values == nodata if nodata is not None else False)
    values = np.where(missing, np.nan, values)
    single = values.astype("float32")
    assert np.array_equal(np.isnan(single), missing), path.name
    worst = float(np.nanmax(np.abs(single.astype("float64") - values) / np.maximum(np.abs(values), 1e-12)))
    assert worst <= 2 ** -24, (path.name, worst)
    print(f"  {path.name}: {100 * (~missing).mean():.1f}% of cells hold a depth, "
          f"{np.nanmin(single):.3f} to {np.nanmax(single):.3f} m")
    return single, {**profile, "dtype": "float32", "nodata": float("nan")}


def build(scout: Path) -> None:
    import rasterio

    source = scout / SOURCE_DIR
    if not (source / FILES[0][2]).exists():
        raise SystemExit(f"{source / FILES[0][2]} is missing; pass SCOUT's backend folder")
    with rasterio.open(source / FILES[0][2]) as src:
        grid = (src.crs, src.transform, src.width, src.height)

    if ROOT.exists():
        shutil.rmtree(ROOT)
    (ROOT / "data").mkdir(parents=True)
    parts = []
    for index, (name, label, scout_name) in enumerate(FILES):
        values, profile = _values(source / scout_name, grid)
        with rasterio.open(ROOT / "data" / name, "w", **profile) as target:
            target.write(values, 1)
            target.set_band_description(1, label)
        parts.append({"index": index, "label": label, "kind": "raster", "format": "geotiff", "file": f"data/{name}"})
    (ROOT / "data" / "bundle.json").write_text(json.dumps({"version": 1, "parts": parts}, indent=2) + "\n",
                                                encoding="utf-8")

    manifest = DatasetManifest(
        id=DATASET_ID,
        name="Quad Cities Flood Projections",
        version="1.0.0",
        format="bundle",
        description=(
            "SCOUT's flooding use case over the Quad Cities: seven GeoTIFFs on one grid (EPSG:4326, about "
            "11 m cells). NBS_others_5m.tif is the nature-based solution (NbS) class of each cell: 21 "
            "bioswales/infiltration trenches, 31 permeable pavements, 43 retention ponds, 52 infiltration "
            "trench, 71 and 81 bioswales, 90 and 95 constructed wetlands, 0 none. <period>_NbS.tif and "
            "<period>_noNbS.tif are the projected flood depth in metres for 2020_2040, 2050_2080 and "
            "2080_2100, with NbS and without; NaN where a projection gives no depth. Read one with "
            "curio_load_data(\"data.scout.quad-cities-flood\", part=\"2020_2040_NbS.tif\")."
        ),
        publisher=PUBLISHER,
        license=LICENSE,
        tags=["quad-cities", "flood", "nbs", "scout", "raster", "geotiff"],
        data_file="data/bundle.json",
        major=1,
        created_at=STAMP,
        updated_at=STAMP,
        source_updated_at=None,
        feature_count=None,
        row_count=None,
        schema=None,
        source_label=SOURCE_LABEL,
    )
    (ROOT / "manifest.json").write_text(json.dumps(build_manifest_dict(manifest), indent=2) + "\n", encoding="utf-8")
    assert load_dataset_manifest(ROOT).id == DATASET_ID
    size = sum(p.stat().st_size for p in (ROOT / "data").iterdir())
    print(f"    -> {ROOT.relative_to(REPO_ROOT).as_posix()}/data/: {len(FILES)} files and bundle.json "
          f"({size / 1e6:.1f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scout", type=Path, required=True, help="SCOUT's backend folder")
    build(parser.parse_args().scout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
