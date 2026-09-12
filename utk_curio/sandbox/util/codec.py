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

def active_geometry_name(frame):
    """The name of ``frame``'s active geometry column, or ``None``.

    ``frame.geometry`` raises ``AttributeError`` when a GeoDataFrame has no
    active geometry column -- which happens for real frames, e.g. one built from
    a plain DataFrame or one whose geometry column was dropped. Every caller
    here wants "the name, if there is one", never an exception, and the private
    attribute is the only way to ask without raising.
    """
    return getattr(frame, "_geometry_column_name", None)


def is_geospatial_frame(value):
    """True for a GeoDataFrame that actually has an active geometry column.

    A GeoDataFrame without one cannot be written as GeoParquet: ``to_parquet``
    emits 'geo' metadata with no ``primary_column``, and reading it back raises
    ``ValueError``. So the artifact saved but could never be loaded again.

    It is also not geospatial in any useful sense -- it is a table. Treating it
    as one everywhere (storage kind, reload, and the payload's ``dataType``)
    keeps those three answers consistent, which is what stops the value from
    changing shape as it moves through the system.
    """
    return isinstance(value, gpd.GeoDataFrame) and active_geometry_name(value) is not None


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
    elif getattr(val, "__geo_interface__", None) is not None:
        # A shapely geometry sitting in an ordinary cell -- which is what every
        # secondary geometry column is (`gdf['centroid'] = gdf.centroid`), and
        # what a plain DataFrame holding shapely objects is made of. Without
        # this it falls through to `return val` and dies at `json.dumps` with
        # "Object of type Point is not JSON serializable".
        #
        # `__geo_interface__` *is* what `shapely.geometry.mapping()` returns, so
        # this needs no shapely import and works for anything implementing the
        # protocol. Recursing converts its coordinate tuples to lists.
        return _make_serializable(dict(val.__geo_interface__))
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
    """Make *frame* writable as parquet, reporting which columns were encoded.

    ``geometry_col`` tells the two storage paths apart, and they want opposite
    things from a geometry column:

    * **GeoParquet** (``geometry_col`` given): every geometry column is written
      natively, the active one and any secondary ``centroid`` / ``bbox`` beside
      it, so none of them is touched here.
    * **Plain parquet via duckdb** (``geometry_col`` is ``None``): duckdb has no
      geometry type and raises ``Not implemented Error: Data type 'geometry' not
      recognized``. A plain DataFrame can still hold geometry-dtype columns -
      ``pd.DataFrame(gdf)`` keeps them, and assigning a GeoSeries onto an
      ordinary frame creates one - so those are JSON-encoded like any other
      unserializable cell and decoded back on the way out.
    """
    prepared = frame
    encoded_object_columns = []

    for col in prepared.columns:
        if geometry_col is not None and col == geometry_col:
            continue
        is_geometry = str(prepared[col].dtype) == "geometry"
        if geometry_col is not None and is_geometry:
            continue  # a secondary geometry column, written as GeoParquet
        needs_encoding = (
            (geometry_col is None and is_geometry)
            or (prepared[col].dtype == object
                and _object_column_needs_json_encoding(prepared[col]))
        )
        if needs_encoding:
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
    if is_geospatial_frame(obj): return 'geodataframe'
    if isinstance(obj, pd.DataFrame): return 'dataframe'
    if 'rasterio' in sys.modules and isinstance(obj, sys.modules['rasterio'].io.DatasetReader): return 'raster'
    if isinstance(obj, tuple): return 'outputs'
    return 'unknown'
