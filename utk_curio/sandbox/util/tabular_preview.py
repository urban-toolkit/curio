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


def _layer_is_nonempty(layer: dict[str, Any]) -> bool:
    """Mirror the Data Pool's empty-tab drop (``useTableData`` ``tabd.filter``)."""
    if layer.get("dataType") == "geodataframe":
        features = (layer.get("data") or {}).get("features")
        return isinstance(features, list) and len(features) > 0
    if layer.get("dataType") == "dataframe":
        data = layer.get("data") or {}
        columns = list(data.keys()) if isinstance(data, dict) else []
        return bool(columns) and bool(data.get(columns[0]))
    return True


def normalize_pool_layers(payload: Any) -> list[dict[str, Any]] | None:
    """Normalize an autk-grammar pool output into per-layer table wrappers.

    Mirrors the Data Pool's ``useTableData`` normalization so the catalog
    preview shows the same per-layer tables the pool does. autk-grammar emits two
    shapes, both stored as a ``dict``/``list`` artifact (and zlib-compressed):

    - compute / data+compute (``layersToPoolWrapper``):
      ``{dataType: 'outputs', data: [{dataType: 'geodataframe', data: FC,
      layerName, layerType}, ...]}`` (or a single ``geodataframe`` wrapper).
    - data-only (``compileDataSpecToAutkDbJs``): a plain layer array
      ``[{name, type, geojson}, ...]``.

    Returns a list of ``{label, layerType, dataType, data}`` wrappers (each ready
    for :func:`rows_from_parse_output`), with empty layers dropped to match the
    pool. Returns ``None`` when ``payload`` is not a recognizable pool shape, so
    the caller falls back to a plain-JSON preview.
    """
    known = {"geodataframe", "dataframe"}

    def peel(rec: Any) -> Any:
        # parseOutput recursively wraps non-tabular values as {dataType, data};
        # peel those envelopes until a layer record or known wrapper surfaces.
        while (
            isinstance(rec, dict)
            and isinstance(rec.get("dataType"), str)
            and rec["dataType"] not in known
            and "data" in rec
        ):
            rec = rec["data"]
        return rec

    if (
        isinstance(payload, dict)
        and payload.get("dataType") == "outputs"
        and isinstance(payload.get("data"), list)
    ):
        items = payload["data"]
    elif isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and payload.get("dataType") in known:
        items = [payload]
    else:
        return None

    layers: list[dict[str, Any]] = []
    for item in items:
        if item is None:
            continue
        rec = peel(item)
        if not isinstance(rec, dict):
            continue
        geojson = rec.get("geojson")
        if isinstance(geojson, dict) and geojson.get("type") == "FeatureCollection":
            # data-only autk shape: {name, type, geojson}
            layer = {
                "label": rec.get("name"),
                "layerType": rec.get("type"),
                "dataType": "geodataframe",
                "data": geojson,
            }
        elif rec.get("dataType") in known:
            # pool wrapper: {dataType, data, layerName, layerType}
            layer = {
                "label": rec.get("layerName"),
                "layerType": rec.get("layerType"),
                "dataType": rec["dataType"],
                "data": rec.get("data"),
            }
        else:
            continue
        if _layer_is_nonempty(layer):
            layers.append(layer)

    return layers or None


def load_parquet_frame(path: Path) -> tuple[Any, int]:
    """Load a parquet file and return ``(frame, total_row_count)``.

    GeoParquet stores geometry as binary WKB. Reading it with plain pandas leaves
    the geometry column as raw bytes, which the preview later renders as unreadable
    replacement characters. We therefore read with geopandas (decoding WKB into
    shapely geometries) and convert geometry columns to human-readable WKT
    (e.g. ``POLYGON ((...))``) before serialization.
    """
    try:
        # Import inside the try so a deployment without geopandas still previews
        # plain parquet via the pandas fallback below (an unguarded import would
        # break previews of EVERY parquet, even non-geo ones).
        import geopandas as gpd

        frame = gpd.read_parquet(path)
    except Exception:
        # Not a GeoParquet file (no geo metadata), or geopandas is unavailable;
        # read as a plain DataFrame.
        logger.debug(
            "gpd.read_parquet failed for %s; reading as plain parquet",
            path,
            exc_info=True,
        )
        frame = pd.read_parquet(path)
        from utk_curio.sandbox.util.parsers import restore_parquet_sidecar
        frame = restore_parquet_sidecar(frame, path)
        return frame, len(frame)

    from utk_curio.sandbox.util.parsers import restore_parquet_sidecar

    geometry_columns = [
        column for column in frame.columns if str(frame[column].dtype) == "geometry"
    ]
    geometry_col = geometry_columns[0] if geometry_columns else None
    # Decode JSON-encoded object columns from the <file>.decode.json sidecar so
    # list/dict columns render as real objects, not raw JSON text.
    frame = restore_parquet_sidecar(frame, path, geometry_col=geometry_col)
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
