import geopandas as gpd
import pandas as pd
import json
import math
import mmap
import zlib
import os
import sys
import time
import hashlib
import ast
import datetime
import numpy as np

from shapely import wkt
from pathlib import Path

#DuckDB imports:
import io
import duckdb
from utk_curio.sandbox.util.db import get_connection, get_read_connection, init_db
# Value <-> bytes conversion lives in codec.py, which deliberately has no access
# to the artifact store. Re-exported here so existing imports of these names
# from parsers keep working (worker.py seeds detect_kind into every node's
# namespace, and test_sandbox_namespace.py pins that).
from utk_curio.sandbox.util.codec import (
    PARQUET_DECODE_SIDECAR_SUFFIX,
    _decode_object_cell_from_parquet,
    _encode_object_cell_for_parquet,
    _is_missing_value,
    _json_safe_value,
    _make_serializable,
    _object_column_needs_json_encoding,
    _parse_parquet_meta,
    _prepare_frame_for_parquet,
    _restore_frame_from_parquet,
    _serialize_parquet_meta,
    _write_dataframe_parquet,
    active_geometry_name,
    is_geospatial_frame,
    detect_kind,
    make_json_safe,
    safe_json_loads,
)


# Utility Functions
# transforms the whole input into a dict (json) in depth
# def toJsonInput(input):
#     print("here", input)
#     parsedJson = input
#     if(parsedJson['dataType'] == 'outputs'):
#         for key, elem in enumerate(parsedJson['data']):
#             parsedJson['data'][key] = toJsonInput(elem)

#     return parsedJson

# I/O type checking — RETIRED (memo dev/120).
#
# ``checkIOType`` used to dispatch on the legacy uppercase node names
# (DATA_LOADING / DATA_TRANSFORMATION / DATA_EXPORT) and refuse inputs and
# outputs outside a hand-typed copy of the builtin manifest's port types. Every
# caller has sent the namespaced id (``curio.builtin/data-loading``) since the
# package registry landed, so the check has been a no-op on the browser path,
# the agents' runner and the e2e runner for as long as those ids have existed.
# A node's type contract is its template's declared ports (DEC-062/076),
# enforced by the canvas at connect time; the validators are gone.
#
# The NAME stays, and stays seeded into every node namespace (owner decision
# 2026-09-09): the #158 contract promises that every name the old star import
# leaked keeps resolving in node code. Calling it does nothing, which is what
# it did for every namespaced id already.
def checkIOType(data, nodeType, input=True):
    """No-op kept for the #158 namespace contract — see the note above."""
    return None


def save_memory_mapped_file(data):
    """
    Saves the input data as a memory-mapped JSON file with a unique name.

    Args:
        input_data (dict): The data to be saved.
        shared_disk_path (str): Path to the directory for saving the file.

    Returns:
        str: The path of the saved memory-mapped file.
    """
    launch_dir = Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())).resolve()
    shared_disk_path = os.environ.get("CURIO_SHARED_DATA", "./.curio/data/")
    save_dir = (launch_dir / shared_disk_path).resolve()
    # Ensure the directory exists
    os.makedirs(save_dir, exist_ok=True)

    # Prepare hash before adding filepath
    json_bytes_initial = json.dumps(data, ensure_ascii=False).encode('utf-8')
    input_hash = hashlib.sha256(json_bytes_initial[:1024]).digest()[:4].hex()
    timestamp = str(int(time.time()))
    unique_filename = f"{timestamp}_{input_hash[:25]}.data"

    # Inject the filename into the data
    data['filename'] = unique_filename

    # Now serialize the updated data
    json_bytes = json.dumps(data, ensure_ascii=False).encode('utf-8')
    compressed_data = zlib.compress(json_bytes)

    full_path = save_dir / unique_filename
    with open(full_path, "wb") as file:
        file.write(compressed_data)
        file.flush()

    relative_path = full_path.relative_to(shared_disk_path)
    return str(relative_path).replace("\\", "/")


def load_memory_mapped_file(file_path):
    """
    Loads the JSON data from the specified memory-mapped JSON file.

    Args:
        file_path (str): The path of the memory-mapped JSON file to load.

    Returns:
        dict: The loaded JSON data.
    """
    launch_dir = Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())).resolve()
    shared_disk_path = os.environ.get("CURIO_SHARED_DATA", "./.curio/data/")
    lod_dir = (launch_dir / shared_disk_path).resolve()

    # Ensure file_path is relative, then join and resolve
    requested_path = Path(file_path)
    full_path = (lod_dir / requested_path).resolve()

    # Security check to prevent directory traversal
    if not str(full_path).startswith(str(lod_dir)):
        raise PermissionError(f"Access to path '{full_path}' is not allowed.")

    # Normalize the path
    # file_path = Path(file_path).resolve()

    if not full_path.exists():
        raise FileNotFoundError(f"The file {full_path} does not exist.")

    # Using mmap for efficient memory-mapped loading
    with open(full_path, "rb") as file:
        with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as mmapped_file:
            # Decompress and decode directly from the memory-mapped file
            decompressed_data = zlib.decompress(mmapped_file[:])
            data = json.loads(decompressed_data.decode('utf-8'))
    return data


def parse_primitive(data_type, data_value):
    try:
        return ast.literal_eval(data_value)
    except (ValueError, SyntaxError):
        return data_value

def parse_list(data_type, data_value):
    values = []
    for elem in data_value:
        if type(elem) == dict and 'dataType' in elem:
            values.append(parseInput(elem))
        else:
            values.append(elem)
    return values

def parse_dataframe(data_value):
    # return pd.DataFrame.from_dict(data_value)
    df = pd.DataFrame.from_dict(data_value)
    return df.astype(object).where(pd.notnull(df), np.nan)

def parse_geodataframe(data_value):
    # df = pd.DataFrame.from_dict(data_value)
    # df['geometry'] = df['geometry'].apply(wkt.loads)
    # gdf = gpd.GeoDataFrame(df, geometry='geometry')
    gdf = gpd.GeoDataFrame.from_features(data_value["features"])
    if 'metadata' in data_value and 'name' in data_value['metadata']:
        gdf.__dict__['metadata'] = {'name': data_value['metadata']['name']}
    
    return gdf

def parse_raster(data_value):
    # rasterio is optional — provided by raster-capable packages
    # (curio.weather, ai.urbanlab.uhvi), not by curio.builtin.
    import rasterio
    return rasterio.open(data_value)

# Parsing Functions
def parseInput(parsed_json):
    # parsed_json = json.loads(input_str)

    data_type = parsed_json.get('dataType')
    data_value = parsed_json.get('data')

    if data_type in ['int', 'float', 'bool', 'dict', 'str']:
        return parse_primitive(data_type, data_value)
    elif data_type == 'list':
        return parse_list(data_type, data_value)
    elif data_type == 'dataframe':
        return parse_dataframe(data_value)
    elif data_type == 'geodataframe':
        return parse_geodataframe(data_value)
    elif data_type == 'raster':
        return parse_raster(data_value)
    elif data_type == 'outputs':
        return tuple(parseInput(elem) for elem in data_value)

    return None


def _read_parquet_sidecar_meta(path):
    """Return ``(frame_metadata, encoded_object_columns)`` from a parquet file's
    ``<file>.decode.json`` decode sidecar, or ``(None, [])`` when it's absent."""
    import os

    meta_path = str(path) + PARQUET_DECODE_SIDECAR_SUFFIX
    if not os.path.exists(meta_path):
        return None, []
    with open(meta_path, encoding="utf-8") as handle:
        return _parse_parquet_meta(handle.read())


def restore_parquet_sidecar(frame, path, *, geometry_col=None):
    """Decode JSON-encoded object columns recorded in a parquet file's
    ``<file>.decode.json`` sidecar (written by :func:`save_dataset_parquet`).

    No-op when the sidecar is absent or records no encoded columns — so it never
    touches columns that weren't encoded. Used by the preview and export paths
    so they show/emit real objects instead of raw JSON strings.
    """
    _frame_metadata, encoded_object_columns = _read_parquet_sidecar_meta(path)
    if encoded_object_columns:
        frame = _restore_frame_from_parquet(
            frame, encoded_object_columns, geometry_col=geometry_col
        )
    return frame


def load_dataset_parquet(path):
    """Read a dataset parquet written by :func:`save_dataset_parquet`, restoring
    any JSON-encoded object columns recorded in the ``<file>.decode.json`` sidecar.

    Reads as a GeoDataFrame when the file is GeoParquet, otherwise a plain
    DataFrame. The inverse of :func:`save_dataset_parquet`.
    """
    try:
        frame = gpd.read_parquet(path)
        geometry_col = active_geometry_name(frame)
    except Exception:
        frame = pd.read_parquet(path)
        geometry_col = None

    frame_metadata, _encoded = _read_parquet_sidecar_meta(path)
    frame = restore_parquet_sidecar(frame, path, geometry_col=geometry_col)
    if frame_metadata is not None:
        try:
            frame.metadata = frame_metadata
        except Exception:  # noqa: BLE001 - metadata is best-effort
            pass

    return frame


def normalize_dataframe_for_json(df):
    """Convert DataFrame cells to JSON-safe Python values."""
    normalized = df.copy()

    for col in normalized.columns:
        if normalized[col].dtype == object:
            normalized[col] = normalized[col].apply(safe_json_loads)
        normalized[col] = normalized[col].apply(_make_serializable)

    return normalized.astype(object).where(pd.notnull(normalized), None)


def fix_json_strings(gdf):
    """Make every non-active column of a GeoDataFrame JSON-safe.

    Two things here are easy to get wrong. The column to skip is the frame's
    *active* geometry column, whatever it is called -- keying off the literal
    'geometry' mangles a frame whose geometry is named `geom`, and leaves a
    plain string column that happens to be called 'geometry' untouched when it
    should be processed.

    And a *secondary* geometry column (a `centroid`, an `envelope`) is a normal
    column here: it must not go through `safe_json_loads`, which only makes
    sense for strings, but it does need `_make_serializable` to turn its shapely
    objects into GeoJSON dicts.
    """
    gdf = gdf.copy()
    active = active_geometry_name(gdf)

    for col in gdf.columns:
        if col == active:
            continue
        if str(gdf[col].dtype) != 'geometry':
            gdf[col] = gdf[col].apply(safe_json_loads)
        gdf[col] = gdf[col].apply(_make_serializable)

    return gdf

def _frame_schema(frame):
    """Column name -> pandas dtype string, e.g. ``{'pop': 'int64'}``.

    The same shape the `data-summary` node already produces and renders. It
    travels with the payload so that consumers do not have to sniff values:
    telling a date from a string, or a zip code from a measurement, is exactly
    where guessing goes wrong.
    """
    return frame.dtypes.astype(str).to_dict()


# Output Functions
def parseOutput(output):
    import math
    json_output = {'data': '', 'dataType': ''}
    if isinstance(output, float) and not math.isfinite(output):
        # NaN / +Inf / -Inf are not valid JSON; emit null so simplejson-strict
        # clients (the e2e test client) can parse the response.
        json_output['data'] = None
        json_output['dataType'] = 'float'
    elif isinstance(output, (int, float, bool, str)):
        json_output['data'] = output
        json_output['dataType'] = type(output).__name__
    elif isinstance(output, list):
        json_output['data'] = [parseOutput(elem) for elem in output]
        json_output['dataType'] = type(output).__name__
    elif isinstance(output, dict):
        json_output['data'] = output
        json_output['dataType'] = type(output).__name__
    elif isinstance(output, pd.DataFrame) and not is_geospatial_frame(output):
        clean_df = normalize_dataframe_for_json(output)
        json_output['data'] = clean_df.to_dict(orient='list')
        json_output['dataType'] = 'dataframe'
        json_output['schema'] = _frame_schema(output)
    elif is_geospatial_frame(output):
        gdf = fix_json_strings(output)
        # `is_geospatial_frame` guarantees an active column, so `.to_json()`,
        # `.crs` and `.geometry` are all safe from here on. A GeoDataFrame
        # without one took the `dataframe` branch above.
        active = active_geometry_name(output)
        geojson_dict = json.loads(gdf.to_json())
        # geopandas ≥1.0 removed the non-standard 'crs' key from to_json() output
        # (deprecated since 0.9, following RFC 7946). Re-inject it so that
        # JavaScript consumers (e.g. the autk-grammar behavior) can determine
        # the coordinate reference system without guessing from coordinate values.
        if output.crs is not None:
            epsg = output.crs.to_epsg()
            if epsg is not None:
                geojson_dict['crs'] = {
                    'type': 'name',
                    'properties': {'name': f'urn:ogc:def:crs:EPSG::{epsg}'},
                }
        # Which column holds the geometry, under its own pandas name. Without
        # this the browser has to guess, and cannot tell a frame whose geometry
        # is called `geom` from one that has no geometry at all.
        geojson_dict['geometry_name'] = active
        json_output['data'] = geojson_dict
        json_output['dataType'] = 'geodataframe'
        # Top level, exactly as on the dataframe branch: the column types are a
        # property of the frame, not of the GeoJSON, and a consumer should not
        # have to know which branch it is on to read them.
        json_output['schema'] = _frame_schema(output)
        if hasattr(output, 'metadata') and 'name' in output.metadata:
            parsed_geojson = json_output['data']
            parsed_geojson['metadata'] = {'name': output.metadata['name']}
            json_output['data'] = parsed_geojson
    # A DatasetReader can only exist if user code already imported rasterio,
    # so the sys.modules guard is exact without importing the optional lib.
    elif 'rasterio' in sys.modules and isinstance(output, sys.modules['rasterio'].io.DatasetReader):
        json_output['data'] = output.name
        json_output['dataType'] = 'raster'
    elif isinstance(output, tuple):
        json_output['data'] = [parseOutput(elem) for elem in output]
        json_output['dataType'] = 'outputs'

    return json_output

#DuckDB handlers:
def _make_id():
    """Generate a unique id: {timestamp}_{hash}."""
    timestamp = str(int(time.time() * 1000))  # millisecond precision to avoid collisions
    random_part = hashlib.sha256(os.urandom(16)).digest()[:4].hex()
    return f"{timestamp}_{random_part}"


def _shared_data_dir() -> Path:
    launch_dir = Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())).resolve()
    shared_data = os.environ.get("CURIO_SHARED_DATA", "./.curio/data/")
    data_dir = (launch_dir / shared_data).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _stored_artifact_rel_path(art_id, suffix=".parquet"):
    return f"artifacts/{art_id}{suffix}"


def _resolve_stored_artifact_path(rel_path, *, create_parent=False) -> Path:
    data_dir = _shared_data_dir()
    full_path = (data_dir / rel_path).resolve()
    try:
        full_path.relative_to(data_dir)
    except ValueError:
        raise PermissionError(f"Access to artifact path '{full_path}' is not allowed.")
    if create_parent:
        full_path.parent.mkdir(parents=True, exist_ok=True)
    return full_path


def _parquet_source(value_str, blob):
    if value_str:
        return _resolve_stored_artifact_path(value_str)
    if blob is None:
        raise ValueError("Artifact has no parquet payload")
    return io.BytesIO(blob)


def _json_artifact_rel_path(art_id):
    return f"artifacts/{art_id}.json.zlib"


def _write_json_artifact(art_id, value):
    # allow_nan=False makes invalid floats a hard error instead of silently
    # emitting bare NaN/Infinity tokens; _json_safe_value scrubs them to null
    # first so a legitimate non-finite value persists as null rather than raising.
    payload = json.dumps(
        _json_safe_value(value), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    rel_path = _json_artifact_rel_path(art_id)
    full_path = _resolve_stored_artifact_path(rel_path, create_parent=True)
    full_path.write_bytes(zlib.compress(payload))
    return rel_path


def _read_json_artifact(rel_path):
    payload = _resolve_stored_artifact_path(rel_path).read_bytes()
    return json.loads(zlib.decompress(payload).decode("utf-8"))


def save_to_duckdb(value, node_id=None, session_id=None):
    """
    Save a Python value to the artifacts table.

    Args:
        value: the raw Python object (DataFrame, GeoDataFrame, int, str, list, dict, tuple, rasterio dataset, etc.)
               OR a parsed output dict (from parseOutput) for compatibility.
        node_id: the workflow node id that produced this artifact.
        session_id: Bearer token of the session that produced this artifact.
                    Used to scope artifact access so concurrent sessions are isolated.

    Returns:
        str: the id of the new artifact row.
    """
    init_db()
    con = get_connection()
    try:
        art_id = _make_id()

        if value is None:
            con.execute(
                "INSERT INTO artifacts (id, node_id, kind) VALUES (?, ?, ?)",
                [art_id, node_id, 'null']
            )

        # --- Tuple: split into children + parent pointer row ---
        elif isinstance(value, tuple):
            child_ids = [save_to_duckdb(child, node_id=node_id, session_id=session_id) for child in value]
            con.execute(
                "INSERT INTO artifacts (id, node_id, kind, value_json) VALUES (?, ?, ?, ?)",
                [art_id, node_id, 'outputs', json.dumps(child_ids)]
            )

        # --- bool MUST come before int (bool is a subclass of int) ---
        elif isinstance(value, bool):
            con.execute(
                "INSERT INTO artifacts (id, node_id, kind, value_int) VALUES (?, ?, ?, ?)",
                [art_id, node_id, 'bool', 1 if value else 0]
            )

        elif isinstance(value, int):
            con.execute(
                "INSERT INTO artifacts (id, node_id, kind, value_int) VALUES (?, ?, ?, ?)",
                [art_id, node_id, 'int', value]
            )

        elif isinstance(value, float):
            con.execute(
                "INSERT INTO artifacts (id, node_id, kind, value_float) VALUES (?, ?, ?, ?)",
                [art_id, node_id, 'float', value]
            )

        elif isinstance(value, str):
            con.execute(
                "INSERT INTO artifacts (id, node_id, kind, value_str) VALUES (?, ?, ?, ?)",
                [art_id, node_id, 'str', value]
            )

        elif isinstance(value, list):
            try:
                # fast path: list of JSON-native values (ints, strs, simple nested lists/dicts)
                rel_path = _write_json_artifact(art_id, value)
                con.execute(
                    "INSERT INTO artifacts (id, node_id, kind, value_str) VALUES (?, ?, ?, ?)",
                    [art_id, node_id, 'list', rel_path]
                )
            except TypeError:
                # fallback: list contains DataFrames/GeoDataFrames/etc.
                # recursively save each element as its own artifact, store the IDs here
                child_ids = [save_to_duckdb(child, node_id=node_id, session_id=session_id) for child in value]
                con.execute(
                    "INSERT INTO artifacts (id, node_id, kind, value_json) VALUES (?, ?, ?, ?)",
                    [art_id, node_id, 'list_of_ids', json.dumps(child_ids)]
                )

        elif isinstance(value, dict):
            try:
                rel_path = _write_json_artifact(art_id, value)
                con.execute(
                    "INSERT INTO artifacts (id, node_id, kind, value_str) VALUES (?, ?, ?, ?)",
                    [art_id, node_id, 'dict', rel_path]
                )
            except TypeError:
                # fallback: dict values contain DataFrames/GeoDataFrames/etc.
                child_id_map = {k: save_to_duckdb(v, node_id=node_id, session_id=session_id) for k, v in value.items()}
                con.execute(
                    "INSERT INTO artifacts (id, node_id, kind, value_json) VALUES (?, ?, ?, ?)",
                    [art_id, node_id, 'dict_of_ids', json.dumps(child_id_map)]
                )

        # --- GeoDataFrame MUST come before DataFrame (gpd.GeoDataFrame subclasses pd.DataFrame) ---
        elif is_geospatial_frame(value):
            prepared, encoded_object_columns = _prepare_frame_for_parquet(
                value,
                geometry_col=active_geometry_name(value),
            )
            rel_path = _stored_artifact_rel_path(art_id)
            parquet_path = _resolve_stored_artifact_path(rel_path, create_parent=True)
            prepared.to_parquet(parquet_path)  # GeoParquet — CRS preserved automatically
            # parquet drops Python-side attributes like ``gdf.metadata`` (set by
            # parse_geodataframe when upstream JSON carried a metadata.name).
            # Grammar visualizers historically depended on this name, so stash it
            # in value_json and restore on load to preserve compatibility.
            meta = getattr(value, 'metadata', None)
            meta_json = _serialize_parquet_meta(
                frame_metadata=meta,
                encoded_object_columns=encoded_object_columns,
            )
            con.execute(
                "INSERT INTO artifacts (id, node_id, kind, value_str, value_json) VALUES (?, ?, ?, ?, ?)",
                [art_id, node_id, 'geodataframe', rel_path, meta_json]
            )

        elif isinstance(value, pd.DataFrame):
            prepared, encoded_object_columns = _prepare_frame_for_parquet(value)
            rel_path = _stored_artifact_rel_path(art_id)
            parquet_path = _resolve_stored_artifact_path(rel_path, create_parent=True)
            _write_dataframe_parquet(prepared, parquet_path)
            meta_json = _serialize_parquet_meta(
                encoded_object_columns=encoded_object_columns,
            )
            con.execute(
                "INSERT INTO artifacts (id, node_id, kind, value_str, value_json) VALUES (?, ?, ?, ?, ?)",
                [art_id, node_id, 'dataframe', rel_path, meta_json]
            )

        elif 'rasterio' in sys.modules and isinstance(value, sys.modules['rasterio'].io.DatasetReader):
            con.execute(
                "INSERT INTO artifacts (id, node_id, kind, value_str) VALUES (?, ?, ?, ?)",
                [art_id, node_id, 'raster', value.name]
            )

        else:
            raise TypeError(f"save_to_duckdb: unsupported type {type(value)}")

        if session_id is not None:
            con.execute(
                "UPDATE artifacts SET session_id = ? WHERE id = ?",
                [session_id, art_id]
            )

        return art_id

    finally:
        con.close()


def load_from_duckdb(art_id, session_id=None):
    """
    Load an artifact by id.

    If session_id is provided, the artifact must belong to that session (or have
    no session_id, for backward compatibility with pre-isolation artifacts).

    Returns the reconstructed Python value (DataFrame, GeoDataFrame, tuple, int, etc.).
    """
    # Reuse the persistent R/W connection (sandbox) or open a fresh R/O connection
    # (backend) — avoids conflicting connection modes on the same file.
    con = get_read_connection()
    try:
        row = con.execute(
            "SELECT kind, value_int, value_float, value_str, value_json, blob "
            "FROM artifacts WHERE id = ?",
            [art_id]
        ).fetchone()

        if row is None:
            raise KeyError(f"No artifact with id {art_id}")

        # Enforce session isolation: reject artifacts owned by a different session.
        # Artifacts with session_id=NULL are pre-isolation rows; allow them through.
        if session_id is not None:
            sid_row = con.execute(
                "SELECT session_id FROM artifacts WHERE id = ?", [art_id]
            ).fetchone()
            stored_sid = sid_row[0] if sid_row else None
            if stored_sid is not None and stored_sid != session_id:
                raise KeyError(f"No artifact with id {art_id}")

        kind, v_int, v_float, v_str, v_json, blob = row

        if kind == 'null':
            result = None
        elif kind == 'bool':
            result = bool(v_int)
        elif kind == 'int':
            result = v_int
        elif kind == 'float':
            result = v_float
        elif kind == 'str':
            result = v_str
        elif kind == 'list':
            result = _read_json_artifact(v_str) if v_str else json.loads(v_json)
        elif kind == 'dict':
            result = _read_json_artifact(v_str) if v_str else json.loads(v_json)
        # elif kind == 'dataframe':
        #     result = pd.read_parquet(io.BytesIO(blob))
        # elif kind == 'geodataframe':
        #     result = gpd.read_parquet(io.BytesIO(blob))
        elif kind == 'dataframe':
            result = pd.read_parquet(_parquet_source(v_str, blob))
            _, encoded_object_columns = _parse_parquet_meta(v_json)
            result = _restore_frame_from_parquet(result, encoded_object_columns)
        elif kind == 'geodataframe':
            result = gpd.read_parquet(_parquet_source(v_str, blob))
            frame_meta, encoded_object_columns = _parse_parquet_meta(v_json)
            result = _restore_frame_from_parquet(
                result,
                encoded_object_columns,
                geometry_col=active_geometry_name(result),
            )
            # Restore the .metadata attribute stashed at save time (see save_to_duckdb).
            if frame_meta:
                result.__dict__['metadata'] = frame_meta
        elif kind == 'raster':
            import rasterio  # optional dep — see parse_raster
            result = rasterio.open(v_str)
        elif kind == 'list_of_ids':
            child_ids = json.loads(v_json)
            con.close()                       # close before recursing — one conn per call
            return [load_from_duckdb(cid, session_id=session_id) for cid in child_ids]
        elif kind == 'dict_of_ids':
            child_id_map = json.loads(v_json)
            con.close()
            return {k: load_from_duckdb(cid, session_id=session_id) for k, cid in child_id_map.items()}
        elif kind == 'outputs':
            child_ids = json.loads(v_json)
            # Close this connection before recursing (one connection per call)
            con.close()
            return tuple(load_from_duckdb(cid, session_id=session_id) for cid in child_ids)
        else:
            raise ValueError(f"Unknown kind: {kind}")

        return result

    finally:
        try:
            con.close()
        except Exception:
            pass


# Arrow type -> the dtype string the JSON path sends, for the cases the two
# spell differently. Everything else (int64, int32, bool, ...) is already the
# same word on both sides, so it passes through.
#
# Needed because the two writers disagree: a GeoDataFrame goes through pandas
# ``to_parquet`` and carries ``b'pandas'`` metadata, while a DataFrame is
# written by DuckDB's ``COPY TO PARQUET``, which carries none. Rather than
# make the client guess from Arrow types -- where a mistake is silent and
# per-column -- the translation lives here, next to ``_frame_schema``, with a
# test comparing both kinds against what the JSON path actually sends.
_ARROW_DTYPE_NAMES = {
    "double": "float64",
    "float": "float32",
    "halffloat": "float16",
    "string": "str",
    "large_string": "str",
    "binary": "object",
    "large_binary": "object",
}


def _dtype_name_for(arrow_type):
    name = str(arrow_type)
    if name in _ARROW_DTYPE_NAMES:
        return _ARROW_DTYPE_NAMES[name]
    if name.startswith("timestamp["):
        # timestamp[us] -> datetime64[us], timezone suffix dropped the same
        # way ``frame.dtypes`` drops it for a naive column.
        unit = name[len("timestamp["):].split(",")[0].rstrip("]")
        return f"datetime64[{unit}]"
    if name.startswith("date"):
        return "object"
    return name


def arrow_frame_schema(table):
    """``{column: dtype}`` for an Arrow table, matching the JSON path's schema.

    The same mapping ``_frame_schema`` produces from a live DataFrame, which
    is what the JSON envelope sends as ``schema`` and what ``vegaBehavior``
    reads to choose a starter spec. Built without materialising anything, so
    the Arrow route keeps the property that makes it worth having.

    Two sources, because the two writers differ: a GeoDataFrame reaches
    parquet through pandas ``to_parquet`` and carries ``b'pandas'`` metadata,
    which is authoritative; a DataFrame is written by DuckDB's ``COPY TO
    PARQUET``, which carries none, so its dtypes are derived from the Arrow
    types instead.
    """
    named = {}
    raw = (table.schema.metadata or {}).get(b"pandas")
    if raw:
        try:
            named = {
                column["name"]: column.get("numpy_type")
                for column in (json.loads(raw).get("columns") or [])
                if column.get("name") and column.get("numpy_type")
            }
        except (ValueError, AttributeError):
            named = {}
    if not named:
        named = {
            name: _dtype_name_for(table.schema.field(name).type)
            for name in table.schema.names
        }
    # Whichever source it came from, every geometry column needs the same
    # correction: GeoParquet stores them as WKB, so pandas metadata calls them
    # ``object`` and the Arrow type is binary, while the JSON path reports
    # geopandas' own ``geometry`` dtype. Say what the column means.
    #
    # All of them, not just the active one: a frame can carry a second
    # geometry column (``gdf["bbox"] = gdf.geometry.envelope``), and it is a
    # geometry in both paths.
    for column in _geoparquet_geometry_columns(table):
        if column in named:
            named[column] = "geometry"
    return named


def _geoparquet_geometry_columns(table):
    """Every geometry column named by GeoParquet metadata, active or not."""
    raw = (table.schema.metadata or {}).get(b"geo")
    if not raw:
        return ()
    try:
        metadata = json.loads(raw)
    except (ValueError, AttributeError):
        return ()
    columns = metadata.get("columns")
    if isinstance(columns, dict) and columns:
        return tuple(columns)
    primary = metadata.get("primary_column")
    return (primary,) if primary else ()


def load_tabular_arrow_from_duckdb(art_id, session_id=None, *, allow_geometry=False):
    """Load a tabular artifact as a pyarrow.Table read directly from its stored
    parquet payload — no pandas materialization.

    Supports kind in ('dataframe', 'geodataframe'). For GeoDataFrames the
    geometry column is binary WKB (GeoParquet's standard encoding).

    Returns:
        (table, kind, frame_metadata, encoded_object_columns)

    Raises:
        KeyError: artifact does not exist or belongs to a different session.
        ValueError: artifact kind is not tabular (caller should map to 415).
    """
    import pyarrow.parquet as pq
    con = get_read_connection()
    try:
        row = con.execute(
            "SELECT kind, value_json, blob, value_str, session_id "
            "FROM artifacts WHERE id = ?",
            [art_id],
        ).fetchone()
        if row is None:
            raise KeyError(f"No artifact with id {art_id}")
        kind, v_json, blob, v_str, stored_sid = row
        if session_id is not None and stored_sid is not None and stored_sid != session_id:
            raise KeyError(f"No artifact with id {art_id}")
        if kind not in ('dataframe', 'geodataframe'):
            raise ValueError(
                f"Arrow IPC only supports tabular kinds; got {kind!r}"
            )
        if kind == 'geodataframe' and not allow_geometry:
            # Geometry rides as binary WKB here, where the JSON path sends
            # GeoJSON. A client that cannot decode WKB would render nothing
            # and say nothing, so it has to ask for it explicitly
            # (X-Curio-Accept-Geometry: wkb) and gets a 415 otherwise. The
            # check is before read_table, so the refusal costs nothing.
            raise ValueError(
                "Arrow IPC serves geodataframe geometry as WKB; send "
                "X-Curio-Accept-Geometry: wkb to accept it"
            )
        table = pq.read_table(_parquet_source(v_str, blob))
        frame_metadata, encoded_object_columns = _parse_parquet_meta(v_json)
        return table, kind, frame_metadata, encoded_object_columns
    finally:
        try:
            con.close()
        except Exception:
            pass


def load_tabular_preview_from_duckdb(art_id, max_rows, session_id=None):
    """Load only the first rows of a DataFrame artifact from parquet.

    Returns ``(preview_df, total_rows)`` for DataFrame artifacts, ``None`` for
    non-DataFrame artifacts so callers can fall back to the full loader.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    con = get_read_connection()
    try:
        row = con.execute(
            "SELECT kind, value_json, blob, value_str, session_id "
            "FROM artifacts WHERE id = ?",
            [art_id],
        ).fetchone()
        if row is None:
            raise KeyError(f"No artifact with id {art_id}")
        kind, v_json, blob, v_str, stored_sid = row
        if session_id is not None and stored_sid is not None and stored_sid != session_id:
            raise KeyError(f"No artifact with id {art_id}")
        if kind != 'dataframe':
            return None

        parquet_file = pq.ParquetFile(_parquet_source(v_str, blob))
        total_rows = parquet_file.metadata.num_rows
        batches = []
        if max_rows > 0 and total_rows > 0:
            for batch in parquet_file.iter_batches(batch_size=max_rows):
                batches.append(batch)
                break
        table = pa.Table.from_batches(batches, schema=parquet_file.schema_arrow)
        preview = table.to_pandas()
        _, encoded_object_columns = _parse_parquet_meta(v_json)
        preview = _restore_frame_from_parquet(preview, encoded_object_columns)
        return preview, total_rows
    finally:
        try:
            con.close()
        except Exception:
            pass


def load_shared_output_file(file_name):
    """Load a project output hydrated into the shared data directory.

    The DuckDB artifact store is the primary source and the caller tries it
    first; this is the fallback for a name it does not know. That is the normal
    state for a saved output read outside the session that produced it: the
    artifact row is session-tagged (see :func:`load_from_duckdb`) and may have
    been pruned entirely, while the hydrated file is the durable copy the
    project owns. It is what a project load writes here for every output the
    manifest records (``backend/app/projects/storage.hydrate_outputs``).

    No session check, deliberately. The file is in this directory only because
    a project load put it there, so the authorization already happened at
    ``GET /api/projects/<id>`` (owner) or ``GET /api/projects/<id>/shared``
    (link). Holding the project is what grants its outputs.

    The name alone does not say what the bytes are - a dataset parquet keeps
    its generated ``<ms>_<hex>_output.parquet`` name, while a computed dataset
    installed from a JSON or parquet artifact lands under the bare artifact id
    - so the content is sniffed.

    Raises ``KeyError`` for an unsafe name, a missing file, or bytes this
    cannot decode, so callers can treat it exactly like a missing artifact.
    """
    missing = KeyError(f"No artifact with id {file_name}")

    name = str(file_name or "").strip()
    # One safe path component, mirroring the backend's ``validate_component``:
    # a separator or a dot entry would address something other than a hydrated
    # output. The containment check below is the second line of defence.
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
        raise missing

    data_dir = _shared_data_dir()
    try:
        path = (data_dir / name).resolve()
        path.relative_to(data_dir)
    except (OSError, ValueError):
        raise missing
    if not path.is_file():
        raise missing

    with open(path, "rb") as handle:
        header = handle.read(4)

    # Parquet, by magic or by name. ``load_dataset_parquet`` reads GeoParquet as
    # a GeoDataFrame and restores the ``.decode.json`` sidecar, so object columns
    # come back as objects rather than JSON strings.
    if header[:4] == b"PAR1" or name.endswith(".parquet"):
        try:
            return load_dataset_parquet(path)
        except Exception:
            raise missing

    payload = path.read_bytes()
    # dict/list artifacts are stored zlib-compressed (see _write_json_artifact);
    # an installed copy of one keeps those bytes.
    if name.endswith(".json.zlib") or header[:1] == b"\x78":
        try:
            return json.loads(zlib.decompress(payload).decode("utf-8"))
        except Exception:
            pass
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception:
        raise missing


def save_dataset_parquet(output, kind):
    """Save a DataFrame or GeoDataFrame as a named Parquet file in the shared data
    directory (top-level, not inside ``artifacts/``).

    This file is tracked as a *dataset* by the catalog (via liveOutputs / copy_outputs)
    so it appears immediately after node execution and is persisted on project save.

    Args:
        output: the raw Python object (DataFrame or GeoDataFrame).
        kind:   the Curio kind string ('dataframe' or 'geodataframe').

    Returns:
        str: The bare filename (e.g. ``1718123456789_ab12cd34_output.parquet``), or
             ``None`` if saving failed or the kind is not tabular.
    """
    if kind not in ('dataframe', 'geodataframe'):
        return None

    data_dir = _shared_data_dir()
    timestamp = str(int(time.time() * 1000))
    rand = hashlib.sha256(os.urandom(8)).digest()[:4].hex()
    filename = f"{timestamp}_{rand}_output.parquet"
    full_path = data_dir / filename

    try:
        if is_geospatial_frame(output):
            # GeoParquet preserves CRS and geometry column automatically.
            prepared, encoded_object_columns = _prepare_frame_for_parquet(
                output, geometry_col=active_geometry_name(output)
            )
            prepared.to_parquet(full_path)
            meta_json = _serialize_parquet_meta(
                frame_metadata=getattr(output, 'metadata', None),
                encoded_object_columns=encoded_object_columns,
            )
        else:
            prepared, encoded_object_columns = _prepare_frame_for_parquet(output)
            _write_dataframe_parquet(prepared, full_path)
            meta_json = _serialize_parquet_meta(
                encoded_object_columns=encoded_object_columns,
            )
        # Object columns (dict/list cells) are JSON-encoded for parquet; the artifacts
        # path stashes the decode list in DuckDB, but a named dataset file has no such
        # row, so persist it in a ``<file>.decode.json`` sidecar instead. Without it the
        # columns reload as JSON strings instead of the original objects. (Distinct
        # from file_meta's ``.meta.json`` counts sidecar so neither clobbers the other.)
        if meta_json:
            (data_dir / (filename + PARQUET_DECODE_SIDECAR_SUFFIX)).write_text(
                meta_json, encoding="utf-8"
            )
        return filename
    except Exception as exc:
        print(f"[save_dataset_parquet] Could not save dataset file: {exc}", file=sys.stderr)
        return None

