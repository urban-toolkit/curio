#!/usr/bin/env python3
"""Record SCOUT's own flood projections for the scout.flood-simulation@1 tests.

WHY
---
``test_scout_flood_simulation.py`` proves the package's port of SCOUT's
``simulate_flood_projection`` reproduces SCOUT. The reference has to be
SCOUT's code on SCOUT's data, so this script imports SCOUT's
``backend/models/flooding/scripts/flood_simulation.py`` unchanged and runs it
on a 200 by 200 cell block of SCOUT's float64 rasters, and keeps what it
writes. Beside it, it keeps the same block of Curio's dataset
``data.scout.quad-cities-flood`` (the float32 copies the package reads).

HOW
---
The block is the one, on a 50-cell step, with the most cells that hold a
depth and an NbS class. SCOUT's function reads fixed relative paths, so the
block's seven float64 rasters are written where it looks, under a temporary
folder that becomes the working directory, and the function is called with
the block's corners. Its raster and metrics CSV are copied into
``fixtures/scout/flood/`` as ``scout_<case>.tif`` and ``scout_<case>.csv``.
The block of Curio's dataset is kept in ``block/data/``, its seven files and
its ``bundle.json``, the layout of the dataset itself.

Cases (``CASES``): 2020-2040 with every NbS and with none, and 2050-2080 with
none, the period whose no-NbS raster marks no depth with -1.8e308 rather
than NaN.

This is AUTHORING-ONLY tooling. Run it after
scripts/build_example_quad_cities_flood.py:

    conda run -n curio python scripts/generate_scout_flood_fixture.py --scout <scout>/backend
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import shutil
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET = REPO_ROOT / "datasets" / "data.scout.quad-cities-flood@1" / "data"
FIXTURES = REPO_ROOT / "utk_curio" / "backend" / "tests" / "test_packages" / "fixtures" / "scout" / "flood"
SOURCE_DIR = Path("models") / "flooding" / "data_substitutes"
SIZE = 200
STEP = 50
ALL_NBS = [
    "Bioswales/Infiltration trenches",
    "Permeable pavements",
    "Retention ponds",
    "Infiltration trench",
    "Bioswales",
    "Constructed wetlands",
]
#: name: (SCOUT's year, the solutions used)
CASES = {
    "2020_2040_all": ("2020 - 2040", ALL_NBS),
    "2020_2040_none": ("2020 - 2040", []),
    "2050_2080_none": ("2050 - 2080", []),
}
FILES = [
    "NBS_others_5m_4326_cropped_cleaned_resampled.tif",
    "2020_2040_NbS_4326_cropped.tif",
    "2020_2040_noNbS_4326_cropped.tif",
    "2050_2080_NbS_4326_cropped.tif",
    "2050_2080_noNbS_4326_cropped.tif",
    "2080_2100_NbS_4326_cropped.tif",
    "2080_2100_noNbS_4326_cropped.tif",
]


@contextlib.contextmanager
def _cwd(path):
    before = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(before)


def _block(source):
    """``Window`` of the richest SIZE by SIZE block."""
    import numpy as np
    import rasterio
    from rasterio.windows import Window

    with rasterio.open(source / FILES[0]) as src:
        classes = src.read(1)
    with rasterio.open(source / FILES[2]) as src:
        depth = src.read(1)
    rich = (classes > 0) & np.isfinite(depth) & (np.abs(depth) < 1e300)
    best = max(
        ((row, col) for row in range(0, rich.shape[0] - SIZE + 1, STEP)
         for col in range(0, rich.shape[1] - SIZE + 1, STEP)),
        key=lambda rc: int(rich[rc[0]:rc[0] + SIZE, rc[1]:rc[1] + SIZE].sum()),
    )
    return Window(best[1], best[0], SIZE, SIZE)


def _crop(path, window, dest):
    import rasterio

    with rasterio.open(path) as src:
        profile = dict(src.profile)
        profile.update(width=SIZE, height=SIZE, transform=src.window_transform(window),
                       compress="deflate", tiled=False)
        values = src.read(window=window)
        descriptions = src.descriptions
    with rasterio.open(dest, "w", **profile) as out:
        out.write(values)
        for index, description in enumerate(descriptions, start=1):
            if description:
                out.set_band_description(index, description)
    return profile["transform"]


def record(scout: Path) -> None:
    source = scout / SOURCE_DIR
    spec = importlib.util.spec_from_file_location(
        "scout_flood_simulation_original", scout / "models" / "flooding" / "scripts" / "flood_simulation.py"
    )
    scout_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scout_module)

    window = _block(source)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    # Only what this script writes; ATTRIBUTION.md beside it is authored.
    for stale in [*FIXTURES.glob("scout_*"), FIXTURES / "block.json"]:
        stale.unlink(missing_ok=True)
    # The block of Curio's dataset: its seven files and its bundle.json, laid
    # out as the dataset is, so a node reads them with part= as it reads it.
    block = FIXTURES / "block" / "data"
    if block.parent.exists():
        shutil.rmtree(block.parent)
    block.mkdir(parents=True)
    shutil.copy(DATASET / "bundle.json", block / "bundle.json")
    for part in json.loads((DATASET / "bundle.json").read_text(encoding="utf-8"))["parts"]:
        name = Path(part["file"]).name
        transform = _crop(DATASET / name, window, block / name)
    west, north = transform * (0, 0)
    east, south = transform * (SIZE, SIZE)
    # SCOUT's corners: the block's own edges. SCOUT's from_bounds window keeps
    # fractional offsets, so corners inside a cell shift its output's grid by
    # the fraction and drop a column; on the edges it reads the block's
    # SIZE by SIZE cells, as Curio's cell-centre window does, its origin off
    # by float noise (about 1e-14 degrees).
    topleft = f"{west!r}, {north!r}"
    bottomright = f"{east!r}, {south!r}"

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / SOURCE_DIR).mkdir(parents=True)
        for name in FILES:
            _crop(source / name, window, work / SOURCE_DIR / name)
        with _cwd(work):
            for case, (year, nbs) in CASES.items():
                scout_module.simulate_flood_projection(topleft, bottomright, case, year=year, use_NBS_classes=nbs)
                shutil.copy(work / "data" / "served" / "raster" / f"{case}.tif", FIXTURES / f"scout_{case}.tif")
                shutil.copy(work / "data" / "served" / "metric" / f"{case}.csv", FIXTURES / f"scout_{case}.csv")

    (FIXTURES / "block.json").write_text(json.dumps({
        "window": {"col_off": int(window.col_off), "row_off": int(window.row_off), "width": SIZE, "height": SIZE},
        "topleft": topleft,
        "bottomright": bottomright,
        "bounds": [west, south, east, north],
        "cases": {case: {"year": year, "nbs": nbs} for case, (year, nbs) in CASES.items()},
    }, indent=2) + "\n", encoding="utf-8")
    for path in sorted(FIXTURES.iterdir()):
        print(f"  {path.relative_to(REPO_ROOT).as_posix()} ({path.stat().st_size / 1e3:.0f} KB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scout", type=Path, required=True, help="SCOUT's backend folder")
    record(parser.parse_args().scout.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
