"""Shared tabular preview helpers for sandbox /get-preview and dataset catalog."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from utk_curio.sandbox.util.parsers import parseOutput

logger = logging.getLogger(__name__)


def rows_from_parse_output(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a ``parseOutput`` payload into row records for table UIs."""
    data_type = parsed.get("dataType")
    data = parsed.get("data")
    if data_type == "dataframe" and isinstance(data, dict) and data:
        columns = list(data.keys())
        first = data[columns[0]]
        if isinstance(first, dict):
            indices = list(first.keys())
        elif isinstance(first, list):
            indices = range(len(first))
        else:
            return []
        rows: list[dict[str, Any]] = []
        for index in indices:
            row: dict[str, Any] = {}
            for column in columns:
                column_data = data[column]
                if isinstance(column_data, dict):
                    row[column] = column_data.get(index)
                elif isinstance(column_data, list):
                    row[column] = column_data[index] if index < len(column_data) else None
                else:
                    row[column] = None
            rows.append(row)
        return rows

    if data_type == "geodataframe" and isinstance(data, dict):
        features = data.get("features") or []
        return [{**(feature.get("properties") or {})} for feature in features]

    return []


def load_parquet_frame(path: Path) -> tuple[Any, int]:
    """Load a parquet file and return ``(frame, total_row_count)``.

    GeoParquet stores geometry as binary WKB. Reading it with plain pandas leaves
    the geometry column as raw bytes, which the preview later renders as unreadable
    replacement characters. We therefore read with geopandas (decoding WKB into
    shapely geometries) and convert geometry columns to human-readable WKT
    (e.g. ``POLYGON ((...))``) before serialization.
    """
    import geopandas as gpd

    try:
        frame = gpd.read_parquet(path)
    except Exception:
        # Not a GeoParquet file (no geo metadata); read as a plain DataFrame.
        logger.debug(
            "gpd.read_parquet failed for %s; reading as plain parquet",
            path,
            exc_info=True,
        )
        frame = pd.read_parquet(path)
        return frame, len(frame)

    geometry_columns = [
        column for column in frame.columns if str(frame[column].dtype) == "geometry"
    ]
    if geometry_columns:
        # Drop GeoDataFrame typing and emit WKT strings so parseOutput serializes
        # the geometry as readable text instead of binary WKB.
        frame = pd.DataFrame(frame).copy()
        for column in geometry_columns:
            frame[column] = gpd.GeoSeries(frame[column]).to_wkt()

    return frame, len(frame)


def preview_parquet_file(
    path: Path,
    *,
    row_limit: int,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """Read a parquet page and serialize with ``parseOutput``."""
    frame, total_rows = load_parquet_frame(path)
    if offset >= total_rows:
        page = frame.iloc[0:0]
    else:
        page = frame.iloc[offset : offset + row_limit]
    parsed = parseOutput(page)
    return rows_from_parse_output(parsed), total_rows, parsed
