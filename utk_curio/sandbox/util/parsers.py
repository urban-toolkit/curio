import rasterio
import geopandas as gpd
import pandas as pd
import json
import mmap
import zlib
import os
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

# Utility Functions
# transforms the whole input into a dict (json) in depth
# def toJsonInput(input):
#     print("here", input)
#     parsedJson = input
#     if(parsedJson['dataType'] == 'outputs'):
#         for key, elem in enumerate(parsedJson['data']):
#             parsedJson['data'][key] = toJsonInput(elem)

#     return parsedJson

# I/O Type Checking
def checkIOType(data, nodeType, input=True):
    if input:
        validate_input(data, nodeType)
    else:
        validate_output(data, nodeType)


# Input Validation
def validate_input(data, nodeType):
    if isinstance(data, list):
        return
    if nodeType == 'DATA_EXPORT':
        check_dataframe_input(data, nodeType)
    elif nodeType == 'DATA_TRANSFORMATION':
        check_transformation_input(data, nodeType)

# Output Validation
def validate_output(data, nodeType):
    if nodeType in ['DATA_LOADING', 'DATA_TRANSFORMATION']:
        check_valid_output(data, nodeType)
    elif nodeType == 'DATA_EXPORT':
        if data.get('dataType') in ['', None]:
            return
        raise Exception(f'{nodeType} does not support output')


# Input Type Checks
def check_dataframe_input(data, nodeType):
    if isinstance(data, list):
        return
    if data['dataType'] == 'outputs' and len(data['data']) > 5:
        raise Exception(f'{nodeType} only supports five inputs')

    valid_types = {'dataframe', 'geodataframe'}
    if data['dataType'] == 'outputs':
        for elem in data['data']:
            if elem['dataType'] not in valid_types:
                raise Exception(f'{nodeType} only supports DataFrame and GeoDataFrame as input')
    elif data['dataType'] not in valid_types:
        raise Exception(f'{nodeType} only supports DataFrame and GeoDataFrame as input')

def check_transformation_input(data, nodeType):
    valid_types = {'dataframe', 'geodataframe', 'raster'}
    if data['dataType'] == 'outputs' and len(data['data']) > 2:
        raise Exception(f'{nodeType} only supports one or two inputs')

    if data['dataType'] == 'outputs':
        for elem in data['data']:
            if elem['dataType'] not in valid_types:
                raise Exception(f'{nodeType} only supports DataFrame, GeoDataFrame, and Raster as input')
    elif data['dataType'] not in valid_types:
        raise Exception(f'{nodeType} only supports DataFrame, GeoDataFrame, and Raster as input')

def check_valid_output(data, nodeType):
    if isinstance(data, list):
        return
    valid_types = {'dataframe', 'geodataframe', 'raster'}

    if data['dataType'] == 'outputs':
        if len(data['data']) > 1 and nodeType != 'DATA_LOADING':
            raise Exception(f'{nodeType} only supports one output')

        for elem in data['data']:
            if elem['dataType'] not in valid_types:
                raise Exception(f'{nodeType} only supports DataFrame, GeoDataFrame, and Raster as output')

    elif data['dataType'] not in valid_types:
        raise Exception(f'{nodeType} only supports DataFrame, GeoDataFrame, and Raster as output')

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
    prepared = frame.copy()
    encoded_object_columns = []

    for col in prepared.columns:
        if geometry_col is not None and col == geometry_col:
            continue
        if prepared[col].dtype == object:
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


def normalize_dataframe_for_json(df):
    """Convert DataFrame cells to JSON-safe Python values."""
    normalized = df.copy()

    for col in normalized.columns:
        if normalized[col].dtype == object:
            normalized[col] = normalized[col].apply(safe_json_loads)
        normalized[col] = normalized[col].apply(_make_serializable)

    return normalized.astype(object).where(pd.notnull(normalized), None)


def fix_json_strings(gdf):
    gdf = gdf.copy()
    for col in gdf.columns:
        if col != 'geometry':
            gdf[col] = gdf[col].apply(safe_json_loads)
            gdf[col] = gdf[col].apply(_make_serializable)

    return gdf

# Output Functions
def parseOutput(output):
    json_output = {'data': '', 'dataType': ''}
    if isinstance(output, (int, float, bool, str)):
        json_output['data'] = output
        json_output['dataType'] = type(output).__name__
    elif isinstance(output, list):
        json_output['data'] = [parseOutput(elem) for elem in output]
        json_output['dataType'] = type(output).__name__
    elif isinstance(output, dict):
        json_output['data'] = output
        json_output['dataType'] = type(output).__name__
    elif isinstance(output, pd.DataFrame) and not isinstance(output, gpd.GeoDataFrame):
        clean_df = normalize_dataframe_for_json(output)
        json_output['data'] = clean_df.to_dict(orient='list')
        json_output['dataType'] = 'dataframe'
    elif isinstance(output, gpd.GeoDataFrame):
        # output['geometry'] = output['geometry'].apply(lambda geom: geom.wkt)
        # json_output['data'] = output.to_dict(orient='list')
        gdf = fix_json_strings(output)
        geojson_dict = json.loads(gdf.to_json())
        json_output['data'] = geojson_dict
        json_output['dataType'] = 'geodataframe'
        if hasattr(output, 'metadata') and 'name' in output.metadata:
            parsed_geojson = json_output['data']
            parsed_geojson['metadata'] = {'name': output.metadata['name']}
            json_output['data'] = parsed_geojson
    elif isinstance(output, rasterio.io.DatasetReader):
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
                payload = json.dumps(value)
                con.execute(
                    "INSERT INTO artifacts (id, node_id, kind, value_json) VALUES (?, ?, ?, ?)",
                    [art_id, node_id, 'list', payload]
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
                payload = json.dumps(value)
                con.execute(
                    "INSERT INTO artifacts (id, node_id, kind, value_json) VALUES (?, ?, ?, ?)",
                    [art_id, node_id, 'dict', payload]
                )
            except TypeError:
                # fallback: dict values contain DataFrames/GeoDataFrames/etc.
                child_id_map = {k: save_to_duckdb(v, node_id=node_id, session_id=session_id) for k, v in value.items()}
                con.execute(
                    "INSERT INTO artifacts (id, node_id, kind, value_json) VALUES (?, ?, ?, ?)",
                    [art_id, node_id, 'dict_of_ids', json.dumps(child_id_map)]
                )

        # --- GeoDataFrame MUST come before DataFrame (gpd.GeoDataFrame subclasses pd.DataFrame) ---
        elif isinstance(value, gpd.GeoDataFrame):
            buf = io.BytesIO()
            prepared, encoded_object_columns = _prepare_frame_for_parquet(
                value,
                geometry_col=value.geometry.name,
            )
            prepared.to_parquet(buf)  # GeoParquet — CRS preserved automatically
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
                "INSERT INTO artifacts (id, node_id, kind, blob, value_json) VALUES (?, ?, ?, ?, ?)",
                [art_id, node_id, 'geodataframe', buf.getvalue(), meta_json]
            )

        elif isinstance(value, pd.DataFrame):
            buf = io.BytesIO()
            prepared, encoded_object_columns = _prepare_frame_for_parquet(value)
            prepared.to_parquet(buf, engine='pyarrow', index=False)
            meta_json = _serialize_parquet_meta(
                encoded_object_columns=encoded_object_columns,
            )
            con.execute(
                "INSERT INTO artifacts (id, node_id, kind, blob, value_json) VALUES (?, ?, ?, ?, ?)",
                [art_id, node_id, 'dataframe', buf.getvalue(), meta_json]
            )

        elif isinstance(value, rasterio.io.DatasetReader):
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
            result = json.loads(v_json)
        elif kind == 'dict':
            result = json.loads(v_json)
        # elif kind == 'dataframe':
        #     result = pd.read_parquet(io.BytesIO(blob))
        # elif kind == 'geodataframe':
        #     result = gpd.read_parquet(io.BytesIO(blob))
        elif kind == 'dataframe':
            result = pd.read_parquet(io.BytesIO(blob))
            _, encoded_object_columns = _parse_parquet_meta(v_json)
            result = _restore_frame_from_parquet(result, encoded_object_columns)
        elif kind == 'geodataframe':
            result = gpd.read_parquet(io.BytesIO(blob))
            frame_meta, encoded_object_columns = _parse_parquet_meta(v_json)
            result = _restore_frame_from_parquet(
                result,
                encoded_object_columns,
                geometry_col=result.geometry.name,
            )
            # Restore the .metadata attribute stashed at save time (see save_to_duckdb).
            if frame_meta:
                result.__dict__['metadata'] = frame_meta
        elif kind == 'raster':
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
    if isinstance(obj, rasterio.io.DatasetReader): return 'raster'
    if isinstance(obj, tuple): return 'outputs'
    return 'unknown'
