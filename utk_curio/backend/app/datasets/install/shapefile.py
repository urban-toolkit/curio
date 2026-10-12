"""Shapefile -> GeoParquet, for every path that brings a shapefile into the
Data Catalog: a zip imported from the user's computer (``datasets/application/
mutations.py``), a zip the Discovery Catalog downloaded
(``discovery/application/archives.py``), and a shapefile staged from a storage
source (``discovery/application/storage_acquire.py``).

The ``.shp`` must have its ``.dbf`` and ``.shx`` beside it with the same name;
a ``.prj`` and ``.cpg`` are read when they are there.
"""

from __future__ import annotations

from pathlib import Path


def shapefile_to_parquet(shp: Path, dest: Path) -> int:
    """Convert a shapefile with its siblings to GeoParquet in EPSG:4326 at
    *dest*, and return how many features it holds."""
    import geopandas as gpd

    frame = gpd.read_file(shp)
    if frame.crs is not None and frame.crs.to_epsg() != 4326:
        frame = frame.to_crs(4326)
    frame.to_parquet(dest)
    return int(len(frame))
