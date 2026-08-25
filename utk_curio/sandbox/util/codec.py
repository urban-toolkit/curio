"""Value <-> bytes conversion for Curio artifacts.

Split out of ``parsers.py`` so that converting a Python value to its stored
representation (and back) no longer drags in the artifact store. Nothing here
opens DuckDB, resolves a path under ``.curio/data``, or touches the shared
connection in ``util/db.py`` - it only maps values to parquet/JSON bytes and
reports what kind of thing a value is.

That separation is the point: ``parsers.py`` keeps the persistence half
(``save_to_duckdb`` / ``load_from_duckdb`` and the artifact path helpers) and
imports the conversion half from here. A process that must convert values
without any access to the artifact store can import this module alone.

``parsers.py`` re-exports every name below, so existing imports of
``detect_kind`` and friends from there keep working unchanged.
"""

import datetime
import json
import math
import sys

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd


def make_json_safe(obj):
    if isinstance(obj, (dict, list)):
        return obj
    elif isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    elif isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    elif obj is None:
        return None
    elif isinstance(obj, (float, int)) and pd.isnull(obj):  # Only apply pd.isnull to scalars
        return None
    return obj  # Fallback for str, bool, etc.

def safe_json_loads(val):
    try:
        if isinstance(val, str) and val.strip().startswith('{'):
            return json.loads(val)
    except Exception as e:
        print("Exception in safe_json_loads", e)
    return val

def _make_serializable(val):
    """Recursively convert numpy/pandas types to native Python types."""
    if isinstance(val, np.ndarray):
        return [_make_serializable(v) for v in val.tolist()]
    elif isinstance(val, tuple):
        return [_make_serializable(v) for v in val]
    elif isinstance(val, set):
        return [_make_serializable(v) for v in sorted(val, key=repr)]
    elif isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    elif isinstance(val, (np.integer,)):
        return int(val)
    elif isinstance(val, (np.floating,)):
        return float(val)
    elif isinstance(val, (np.bool_,)):
        return bool(val)
    elif isinstance(val, (pd.Timestamp, datetime.datetime, datetime.date)):
        return val.isoformat()
    elif isinstance(val, dict):
        return {k: _make_serializable(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_make_serializable(v) for v in val]
    return val

def _is_missing_value(val):
    if val is None:
        return True
    try:
        missing = pd.isna(val)
    except Exception:
        return False
    return isinstance(missing, (bool, np.bool_)) and bool(missing)

def _encode_object_cell_for_parquet(val):
    if _is_missing_value(val):
        return None
    normalized = _make_serializable(val)
    return json.dumps(normalized, ensure_ascii=False, default=str)

def _decode_object_cell_from_parquet(val):
    if _is_missing_value(val):
        return None
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return safe_json_loads(val)
    return val

def _prepare_frame_for_parquet(frame, geometry_col=None):
    prepared = frame
    encoded_object_columns = []

    for col in prepared.columns:
        if geometry_col is not None and col == geometry_col:
            continue
        if prepared[col].dtype == object and _object_column_needs_json_encoding(prepared[col]):
            if prepared is frame:
                prepared = frame.copy(deep=False)
            prepared[col] = prepared[col].apply(_encode_object_cell_for_parquet)
            encoded_object_columns.append(col)

    return prepared, encoded_object_columns

def _serialize_parquet_meta(frame_metadata=None, encoded_object_columns=None):
    payload = {}
    if frame_metadata:
        payload["frame_metadata"] = frame_metadata
    if encoded_object_columns:
        payload["encoded_object_columns"] = encoded_object_columns
    return json.dumps(payload) if payload else None

def _parse_parquet_meta(meta_json):
    if not meta_json:
        return None, []

    try:
        payload = json.loads(meta_json)
    except Exception:
        return None, []

    if isinstance(payload, dict) and (
        "frame_metadata" in payload or "encoded_object_columns" in payload
    ):
        return payload.get("frame_metadata"), payload.get("encoded_object_columns", [])

    # Backward compatibility: older geodataframe rows stored only ``gdf.metadata``.
    return payload, []

def _restore_frame_from_parquet(frame, encoded_object_columns, geometry_col=None):
    if encoded_object_columns:
        for col in encoded_object_columns:
            if col in frame.columns:
                frame[col] = frame[col].apply(_decode_object_cell_from_parquet)
        return frame

    for col in frame.columns:
        if geometry_col is not None and col == geometry_col:
            continue
        if frame[col].dtype == object:
            frame[col] = frame[col].apply(safe_json_loads)

    return frame

# Suffix for the parquet object-column decode sidecar. Distinct from
# ``file_meta``'s ``<file>.meta.json`` counts sidecar. They live next to the
# same data file and must not clobber each other.
PARQUET_DECODE_SIDECAR_SUFFIX = ".decode.json"

def _json_safe_value(value):
    """Recursively replace JSON-invalid floats (NaN, +Inf, -Inf) with ``None``.

    ``json.dumps`` defaults to ``allow_nan=True``, which emits bare ``NaN`` /
    ``Infinity`` tokens, accepted by Python's lenient ``json.loads`` on the
    round-trip back, but *invalid* JSON that the browser's strict parser (and any
    other conformant reader, e.g. a published bundle part) rejects. Scrub the
    value here so artifacts are always valid JSON at rest. ``np.float64`` is a
    ``float`` subclass so it is covered; ``np.float32`` and friends are caught via
    the explicit ``np.floating`` check.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.floating):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe_value(sub) for key, sub in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(sub) for sub in value]
    return value

def _object_column_needs_json_encoding(series):
    inferred = pd.api.types.infer_dtype(series, skipna=True)
    return inferred not in {
        "empty",
        "string",
        "unicode",
        "bytes",
        "integer",
        "floating",
        "boolean",
        "date",
        "datetime",
        "datetime64",
        "timedelta",
        "timedelta64",
        "decimal",
    }

def _write_dataframe_parquet(frame, parquet_path):
    writer = duckdb.connect(database=":memory:")
    try:
        writer.register("curio_frame", frame)
        escaped_path = str(parquet_path).replace("'", "''")
        writer.execute(f"COPY curio_frame TO '{escaped_path}' (FORMAT PARQUET)")
    finally:
        try:
            writer.unregister("curio_frame")
        except Exception:
            pass
        writer.close()

def detect_kind(obj):
    """Return the Curio 'kind' string for a Python object (no conversion)."""
    if obj is None: return 'null'
    # bool MUST come before int
    if isinstance(obj, bool): return 'bool'
    if isinstance(obj, int): return 'int'
    if isinstance(obj, float): return 'float'
    if isinstance(obj, str): return 'str'
    if isinstance(obj, list): return 'list'
    if isinstance(obj, dict): return 'dict'
    # GeoDataFrame MUST come before DataFrame
    if isinstance(obj, gpd.GeoDataFrame): return 'geodataframe'
    if isinstance(obj, pd.DataFrame): return 'dataframe'
    if 'rasterio' in sys.modules and isinstance(obj, sys.modules['rasterio'].io.DatasetReader): return 'raster'
    if isinstance(obj, tuple): return 'outputs'
    return 'unknown'
