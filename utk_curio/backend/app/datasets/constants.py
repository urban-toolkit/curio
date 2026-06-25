"""Shared constants for dataset catalog format detection and mapping."""

from __future__ import annotations

from utk_curio.backend.app.datasets.file_meta import META_SIDECAR_SUFFIX

SUPPORTED_SUFFIXES = {
    ".csv": "csv",
    ".geojson": "geojson",
    ".json": "json",
    ".parquet": "parquet",
    ".tif": "geotiff",
    ".tiff": "geotiff",
    ".shp": "shp",
}

# Sidecar files written next to dataset files: the row/feature counts cache from
# ``file_meta`` (``<file>.meta.json``) and the parquet object-column decode map
# from ``parsers`` (``<file>.decode.json``). Both end in ``.json``, so a naive
# suffix scan would catalog them as standalone JSON datasets — directory scans
# must skip any filename ending in one of these.
#
# The meta suffix is sourced from ``file_meta.META_SIDECAR_SUFFIX`` so this scan
# can't drift from what ``meta_path()`` actually writes (which would silently
# reopen the unbounded ``.meta.json.meta.json…`` regrowth #145 fixed). The decode
# suffix mirrors ``sandbox.util.parsers.PARQUET_DECODE_SIDECAR_SUFFIX`` — kept as
# a literal here to avoid importing the heavy sandbox ``parsers`` module into
# this lightweight constants leaf; a test asserts the two stay in lockstep.
_DECODE_SIDECAR_SUFFIX = ".decode.json"
SIDECAR_SUFFIXES = (META_SIDECAR_SUFFIX, _DECODE_SIDECAR_SUFFIX)

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

# Generic/auto-generated source labels that must never be persisted as a
# computed dataset's ``sourceLabel`` (they'd read as the global catalog subtitle
# instead of the producing context). Compared case-insensitively. Shared by the
# publish path and catalog dedup so the denylist lives in one place.
JUNK_SOURCE_LABELS: frozenset[str] = frozenset({
    "data catalog",
    "data hub",
    "current dataflow",
    "current workflow",
})
