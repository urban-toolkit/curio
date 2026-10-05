#!/usr/bin/env python3
"""Cut downtown Chicago's roads and SCOUT's WRF weather run for example 26.

WHY
---
Example 26 runs SCOUT's weather-aware routing (``scout.weather-routing@1``)
on what SCOUT's routing reads: its OpenStreetMap road graph of Chicago
(``backend/data/osm/processed/chicago/roads.feather``, 741,271 edges) and a
WRF-Chem run of 6 July 2025 over the Midwest, one NetCDF file per variable
(``backend/models/routing/weather_data/<VARIABLE>.nc``, 375 MB). The date is
SCOUT's: its routing counts time from ``2025-07-06T00:00:00``
(``weather_routing.py``), and the files' ``START_DATE`` is
``2025-07-06_00:00:00`` (Julian day 187). Both are far too large to commit,
so this script writes two datasets:

- ``data.osm.chicago-roads``: the road graph's edges that reach into
  ``ROADS_BBOX``, with SCOUT's graph keys (``u``, ``v``, ``key``) and the
  ``length``, ``speed_kph`` and ``travel_time`` it routes on, as GeoParquet
  (the Data Catalog reads no Feather). The rows keep the extract's order,
  which is the order SCOUT's graph lists its edges in, so the graph the node
  rebuilds from them walks its edges as SCOUT's does (the weather of
  overlapping time zones is laid down in that order).
- ``data.scout.chicago-weather-2025-07-06``: the five files SCOUT reads
  (``RAIN.nc``, ``T2.nc``, ``WSPD10.nc``, ``WDIR10.nc``, ``RH2.nc``), one
  dataset of five files side by side in ``data/``, listed by
  ``data/bundle.json``, each cut to the cells within ``WEATHER_BBOX`` and
  keeping all 49 quarter-hour steps (00:00 to 12:00), ``XLAT``, ``XLONG``,
  every attribute and WRF's float32 values. The box is wider than the roads'
  by several 1 km cells, so each road node's nearest cell is the one it has in
  SCOUT's whole grid. A node reads one file by name:

      curio_load_data("data.scout.chicago-weather-2025-07-06", part="RAIN.nc")

HOW
---
The roads are read with GeoPandas, clipped with ``.cx`` (an edge that crosses
the box's edge is kept whole), and written through the sandbox's own Parquet
helpers so the catalog's loader reads them back. The weather is copied with
netCDF4, the window found from ``XLAT`` and ``XLONG`` at the first step (they
do not change from step to step), and checked against SCOUT's values.

This is AUTHORING-ONLY tooling. It is not imported at runtime.

USAGE
-----
    conda run -n curio python scripts/build_example_weather_routing.py \\
        --scout <scout>/backend
    # then review, and commit datasets/data.osm.chicago-roads@1/ and
    # datasets/data.scout.chicago-weather-2025-07-06@1/

Idempotent: re-running overwrites the two dataset directories.
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

ROADS_ID = "data.osm.chicago-roads"
ROADS_ROOT = REPO_ROOT / "datasets" / f"{ROADS_ID}@1"
ROADS_FILE = "data/chicago-roads.parquet"
WEATHER_ID = "data.scout.chicago-weather-2025-07-06"
WEATHER_ROOT = REPO_ROOT / "datasets" / f"{WEATHER_ID}@1"
#: West, south, east, north in EPSG:4326: the Loop, the West Loop and the
#: Near South Side, around SCOUT's routing example (-87.662, 41.859,
#: -87.613, 41.898).
ROADS_BBOX = (-87.6800, 41.8500, -87.6000, 41.9100)
ROAD_COLUMNS = ["u", "v", "key", "length", "speed_kph", "travel_time", "name", "geometry"]
#: The weather cells kept: the roads' box and about six 1 km cells more.
WEATHER_BBOX = (-87.7500, 41.7950, -87.5300, 41.9650)
#: The variables SCOUT's routing reads, and what each is.
VARIABLES = {
    "RAIN": "Rain",
    "T2": "Temperature at 2 m (K)",
    "WSPD10": "Wind speed at 10 m (m/s)",
    "WDIR10": "Wind direction at 10 m (degrees)",
    "RH2": "Relative humidity at 2 m (%)",
}
STAMP = "2026-10-05T00:00:00Z"
LICENSE = "Unspecified: SCOUT example data, source and license to be confirmed"


def build_roads(scout: Path) -> None:
    import geopandas as gpd

    source = scout / "data" / "osm" / "processed" / "chicago" / "roads.feather"
    if not source.exists():
        raise SystemExit(f"source {source} is missing; pass SCOUT's backend folder")
    print(f"  reading {source}")
    frame = gpd.read_feather(source)
    west, south, east, north = ROADS_BBOX
    roads = frame.cx[west:east, south:north].reset_index()[ROAD_COLUMNS].to_crs("EPSG:4326")

    if ROADS_ROOT.exists():
        shutil.rmtree(ROADS_ROOT)
    dest = ROADS_ROOT / ROADS_FILE
    dest.parent.mkdir(parents=True)
    prepared, encoded = _prepare_frame_for_parquet(roads, geometry_col=roads.geometry.name)
    assert not encoded, encoded
    prepared.to_parquet(dest, compression="zstd")

    manifest = DatasetManifest(
        id=ROADS_ID,
        name="Chicago Roads",
        version="1.0.0",
        format="parquet",
        description=(
            "Chicago's road network as SCOUT routes on it, from its OpenStreetMap extract of "
            "Chicago, cut to downtown: the West Loop to the lake and the river to the Near "
            f"South Side. One row per directed edge, {len(roads):,} of them, with the nodes it "
            "joins (u, v, key), its length in metres, a speed in km/h and a travel time in "
            "seconds. A speed is OpenStreetMap's limit where a mapper set one, otherwise "
            "OSMnx's estimate for the road's class. The rows keep the order of SCOUT's graph."
        ),
        publisher="OpenStreetMap contributors",
        license="ODbL-1.0",
        tags=["chicago", "osm", "roads", "network", "routing", "parquet"],
        data_file=ROADS_FILE,
        major=1,
        created_at=STAMP,
        updated_at=STAMP,
        source_updated_at=None,
        feature_count=len(roads),
        row_count=len(roads),
        schema=None,
        source_label="OpenStreetMap contributors; SCOUT preprocessing",
    )
    (ROADS_ROOT / "manifest.json").write_text(
        json.dumps(build_manifest_dict(manifest), indent=2) + "\n", encoding="utf-8"
    )
    assert load_dataset_manifest(ROADS_ROOT).id == ROADS_ID
    print(f"    -> {dest.relative_to(REPO_ROOT).as_posix()}: {len(roads)} edges "
          f"({dest.stat().st_size / 1e3:.0f} KB)")


def window(path: Path) -> tuple[slice, slice]:
    """The rows and columns of the cells inside ``WEATHER_BBOX``."""
    import netCDF4
    import numpy as np

    with netCDF4.Dataset(path) as ds:
        lats = np.asarray(ds.variables["XLAT"][0])
        lons = np.asarray(ds.variables["XLONG"][0])
    west, south, east, north = WEATHER_BBOX
    rows, cols = np.nonzero((lats >= south) & (lats <= north) & (lons >= west) & (lons <= east))
    return slice(int(rows.min()), int(rows.max()) + 1), slice(int(cols.min()), int(cols.max()) + 1)


def crop_netcdf(source: Path, dest: Path, rows: slice, cols: slice) -> tuple[int, int, int]:
    """*source* cut to *rows* and *cols*, every step and attribute kept, and
    checked against it."""
    import netCDF4
    import numpy as np

    with netCDF4.Dataset(source) as src, netCDF4.Dataset(dest, "w", format="NETCDF4") as out:
        out.setncatts({name: src.getncattr(name) for name in src.ncattrs()})
        sizes = {"south_north": rows.stop - rows.start, "west_east": cols.stop - cols.start}
        for name, dim in src.dimensions.items():
            out.createDimension(name, None if dim.isunlimited() else sizes.get(name, len(dim)))
        for name, var in src.variables.items():
            fill = var.getncattr("_FillValue") if "_FillValue" in var.ncattrs() else None
            copy = out.createVariable(name, var.dtype, var.dimensions, fill_value=fill, zlib=True, complevel=4)
            copy.setncatts({k: var.getncattr(k) for k in var.ncattrs() if k != "_FillValue"})
            index = tuple(
                rows if dim == "south_north" else cols if dim == "west_east" else slice(None)
                for dim in var.dimensions
            )
            var.set_auto_mask(False)
            copy.set_auto_mask(False)
            copy[:] = var[index]
            assert np.array_equal(np.asarray(copy[:]), np.asarray(var[index]), equal_nan=True), name
        return len(src.dimensions["Time"]), sizes["south_north"], sizes["west_east"]


def build_weather(scout: Path) -> None:
    if WEATHER_ROOT.exists():
        shutil.rmtree(WEATHER_ROOT)
    (WEATHER_ROOT / "data").mkdir(parents=True)
    parts = []
    folder = scout / "models" / "routing" / "weather_data"
    rows, cols = window(folder / "RAIN.nc")
    for variable, label in VARIABLES.items():
        source = folder / f"{variable}.nc"
        if not source.exists():
            raise SystemExit(f"source {source} is missing; pass SCOUT's backend folder")
        steps, height, width = crop_netcdf(source, WEATHER_ROOT / "data" / f"{variable}.nc", rows, cols)
        parts.append({"index": len(parts), "label": label, "kind": "netcdf", "format": "netcdf",
                      "file": f"data/{variable}.nc"})
    (WEATHER_ROOT / "data" / "bundle.json").write_text(
        json.dumps({"version": 1, "parts": parts}, indent=2) + "\n", encoding="utf-8"
    )

    manifest = DatasetManifest(
        id=WEATHER_ID,
        name="Chicago Weather, 6 July 2025",
        version="1.0.0",
        format="bundle",
        description=(
            "SCOUT's WRF-Chem weather run of 6 July 2025 over downtown Chicago, the weather its "
            f"weather-aware routing reads: five files, {steps} quarter-hour steps from 00:00 to "
            f"12:00 on a 1 km grid of {height} by {width} cells, each with the cells' XLAT and "
            "XLONG. RAIN.nc is rain, T2.nc the temperature at 2 m in kelvin, WSPD10.nc and "
            "WDIR10.nc the wind speed (m/s) and direction (degrees) at 10 m, and RH2.nc the "
            "relative humidity at 2 m (%). Read one with "
            f'curio_load_data("{WEATHER_ID}", part="RAIN.nc").'
        ),
        publisher="SCOUT (urban-toolkit/scout)",
        license=LICENSE,
        tags=["chicago", "weather", "wrf", "netcdf", "routing", "scout", "2025-07-06"],
        data_file="data/bundle.json",
        major=1,
        created_at=STAMP,
        updated_at=STAMP,
        source_updated_at=None,
        feature_count=None,
        row_count=None,
        schema=None,
        source_label="SCOUT weather-aware routing use case; WRF-Chem V4.5.1",
    )
    (WEATHER_ROOT / "manifest.json").write_text(
        json.dumps(build_manifest_dict(manifest), indent=2) + "\n", encoding="utf-8"
    )
    assert load_dataset_manifest(WEATHER_ROOT).id == WEATHER_ID
    for path in sorted((WEATHER_ROOT / "data").iterdir()):
        print(f"    -> {path.relative_to(REPO_ROOT).as_posix()} ({path.stat().st_size / 1e3:.0f} KB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scout", type=Path, required=True, help="SCOUT's backend folder")
    scout = parser.parse_args().scout
    build_roads(scout)
    build_weather(scout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
