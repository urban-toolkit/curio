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
# Single source of truth for the kind→format mapping (do not duplicate per
# module — bundle part installation and computed-output formatting both read
# this).
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

# Catalog ``DatasetFormat`` → canonical single-file extension. The inverse of
# ``SUPPORTED_SUFFIXES`` is ambiguous for geotiff (.tif/.tiff), so the forward
# map is declared explicitly. ``bundle`` is intentionally absent (multi-file).
FORMAT_TO_EXTENSION: dict[str, str] = {
    "csv": ".csv",
    "geojson": ".geojson",
    "json": ".json",
    "parquet": ".parquet",
    "geotiff": ".tif",
    "shp": ".shp",
}
