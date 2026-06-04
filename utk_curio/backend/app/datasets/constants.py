"""Shared constants for dataset catalog format detection and mapping."""

from __future__ import annotations

SUPPORTED_SUFFIXES = {
    ".csv": "csv",
    ".geojson": "geojson",
    ".json": "json",
    ".parquet": "parquet",
    ".tif": "geotiff",
    ".tiff": "geotiff",
    ".shp": "shp",
}

# Curio sandbox ``detect_kind`` strings → catalog ``DatasetFormat`` values.
SANDBOX_DATATYPE_TO_FORMAT: dict[str, str] = {
    "raster": "geotiff",
    "geodataframe": "parquet",
    "dataframe": "parquet",
    "dict": "json",
    "list": "json",
    "json": "json",
    "str": "json",
    "int": "json",
    "float": "json",
    "bool": "json",
    "null": "json",
    "unknown": "json",
    "outputs": "bundle",
}
