"""A dataset's extent: the WGS84 box its features or pixels cover.

What the Discovery Catalog's area field offers as "the extent of a dataset":
pick a geo dataset already in your Data Catalog, and its box becomes the area.
Read from what the file already says about itself wherever it can be:

- GeoParquet keeps a ``bbox`` in its ``geo`` metadata, so a Parquet dataset
  (an OSM layer, a combined table, a collection's index) is read without
  touching its rows;
- a GeoJSON, shapefile or GeoPackage is asked through GDAL, which knows its
  extent;
- a GeoTIFF's bounds come from its georeferencing.

A box in another CRS is transformed to WGS84. A dataset with no geometry has
no extent, which is an answer, not an error.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VECTOR_FORMATS = ("geojson", "shp", "gpkg")
PARQUET_FORMATS = ("parquet", "collection")


def dataset_extent(path: Path, fmt: str) -> list[float] | None:
    """``[west, south, east, north]`` in WGS84, or None when it has no extent."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        if fmt in PARQUET_FORMATS:
            found = _parquet_extent(path)
        elif fmt in VECTOR_FORMATS:
            found = _vector_extent(path)
        elif fmt == "geotiff":
            found = _raster_extent(path)
        else:
            return None
    except Exception:  # noqa: BLE001 - an unreadable extent is "no extent", logged
        logger.warning("could not read the extent of %s", path.name, exc_info=True)
        return None
    if found is None:
        return None
    box, crs = found
    return _to_wgs84(box, crs)


def _parquet_extent(path: Path):
    import pyarrow.parquet as pq

    metadata = pq.read_metadata(path).metadata or {}
    raw = metadata.get(b"geo")
    if not raw:
        return None
    geo = json.loads(raw)
    primary = geo.get("primary_column") or "geometry"
    column = (geo.get("columns") or {}).get(primary) or {}
    # GeoParquet: no ``crs`` means OGC:CRS84, longitude and latitude.
    crs = column.get("crs")
    bbox = column.get("bbox")
    if not bbox:
        import geopandas as gpd

        frame = gpd.read_parquet(path, columns=[primary])
        if frame.empty:
            return None
        bbox = list(frame.total_bounds)
        crs = frame.crs.to_json_dict() if frame.crs is not None else crs
    return [float(v) for v in bbox[:4]], crs


def _vector_extent(path: Path):
    import pyogrio

    info = pyogrio.read_info(path, force_total_bounds=True)
    bounds = info.get("total_bounds")
    if bounds is None or any(v != v for v in bounds):  # NaN: no features
        return None
    return [float(v) for v in bounds], info.get("crs")


def _raster_extent(path: Path):
    import rasterio

    with rasterio.open(path) as src:
        if src.crs is None:
            return None
        b = src.bounds
        return [b.left, b.bottom, b.right, b.top], src.crs.to_wkt()


def _to_wgs84(box: list[float], crs: Any) -> list[float] | None:
    west, south, east, north = box
    if crs is not None:
        from pyproj import CRS, Transformer

        source = CRS.from_user_input(crs)
        target = CRS.from_user_input("OGC:CRS84")
        if not source.equals(target) and not source.equals(CRS.from_epsg(4326)):
            transformer = Transformer.from_crs(source, target, always_xy=True)
            west, south, east, north = transformer.transform_bounds(west, south, east, north)
    if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
        return None
    return [round(west, 6), round(south, 6), round(east, 6), round(north, 6)]
