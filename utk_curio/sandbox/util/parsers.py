import geopandas as gpd
import pandas as pd
import contextlib
import json
import math
import re
import zlib
import os
import sys
import time
import hashlib
import ast
import numpy as np

from pathlib import Path

#DuckDB imports:
import io
import duckdb
from utk_curio.common.kept_sessions import is_kept_session
from utk_curio.sandbox.util.db import get_connection, get_read_connection, init_db
# Value <-> bytes conversion lives in codec.py, which deliberately has no access
# to the artifact store. Re-exported here so existing imports of these names
# from parsers keep working (worker.py seeds detect_kind into every node's
# namespace, and test_sandbox_namespace.py pins that).
from utk_curio.sandbox.util.codec import (
    PARQUET_DECODE_SIDECAR_SUFFIX,
    PARQUET_ROW_GROUP_ROWS,
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
    # (curio.weather, ai.utk.uhvi), not by curio.builtin.
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
        # A path is a Python node's raster. Anything else is the collection an
        # Autark node hands on, kept as its envelope: a Python node gets it as
        # a rasterio dataset (util/rasters.rasters_for_python), a JavaScript
        # node as the JSON it is.
        if isinstance(data_value, str):
            return parse_raster(data_value)
        return parsed_json
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
    ``<file>.decode.json`` sidecar (written beside a saved table from its
    artifact's row by the Data Catalog's install, or by
    :func:`save_dataset_parquet`).

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


def _frame_columns(frame):
    """The frame's columns, in its own order. ``schema`` and a DataFrame's
    ``data`` are JSON objects, whose order Flask's ``jsonify`` drops: it sorts
    their keys. A list keeps it, so a chip's preview and the header's lists
    show a frame's columns as its code made them."""
    return [str(column) for column in frame.columns]


def _is_frame_or_raster(value):
    """Whether *value* is a DataFrame, a GeoDataFrame or a rasterio dataset:
    what JSON cannot carry, and ``parseOutput`` sends as an envelope."""
    return isinstance(value, pd.DataFrame) or (
        'rasterio' in sys.modules and isinstance(value, sys.modules['rasterio'].io.DatasetReader)
    )


def _holds_frames(mapping):
    """Whether the dict *mapping* holds a frame or a raster: as one of its
    values, as an item of a list or tuple value, or in a dict value that holds
    one by this same test. That is a dict of frames, which the store keeps as
    ``dict_of_ids``. Lists are looked into one level only, so a large JSON
    dict, such as a FeatureCollection, costs a pass over its own values and
    its lists' items, never a walk of every coordinate."""
    for value in mapping.values():
        if _is_frame_or_raster(value):
            return True
        if isinstance(value, dict) and _holds_frames(value):
            return True
        if isinstance(value, (list, tuple)) and any(_is_frame_or_raster(item) for item in value):
            return True
    return False


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
        # A dict of frames is answered as a list or a tuple of them is: each
        # value as parseOutput answers it, under its key. Any other dict is
        # the JSON it already is.
        json_output['data'] = (
            {key: parseOutput(value) for key, value in output.items()}
            if _holds_frames(output) else output
        )
        json_output['dataType'] = type(output).__name__
    elif isinstance(output, pd.DataFrame) and not is_geospatial_frame(output):
        clean_df = normalize_dataframe_for_json(output)
        json_output['data'] = clean_df.to_dict(orient='list')
        json_output['dataType'] = 'dataframe'
        json_output['schema'] = _frame_schema(output)
        json_output['columns'] = _frame_columns(output)
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
        json_output['columns'] = _frame_columns(output)
        # The frame's own name and Autark layer type, as the Arrow path sends
        # them in its X-Curio-Frame-Metadata header.
        frame_metadata = getattr(output, 'metadata', None)
        if isinstance(frame_metadata, dict):
            kept = {key: frame_metadata[key] for key in ('name', 'layerType') if key in frame_metadata}
            if kept:
                json_output['data']['metadata'] = kept
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


def save_to_duckdb(value, node_id=None, session_id=None, art_id=None):
    """
    Save a Python value to the artifacts table.

    Args:
        value: the raw Python object (DataFrame, GeoDataFrame, int, str, list, dict, tuple, rasterio dataset, etc.)
               OR a parsed output dict (from parseOutput) for compatibility.
        node_id: the workflow node id that produced this artifact.
        session_id: Bearer token of the session that produced this artifact.
                    Used to scope artifact access so concurrent sessions are isolated.
        art_id: the id to store it as, when the run chose it before it ran
                (its output folder is named after it, util/output_files.py).

    Returns:
        str: the id of the new artifact row.
    """
    init_db()
    con = get_connection()
    try:
        art_id = art_id or _make_id()

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
            # GeoParquet: CRS preserved automatically.
            prepared.to_parquet(parquet_path, row_group_size=PARQUET_ROW_GROUP_ROWS)
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


def session_may_read(stored_session, session_id) -> bool:
    """Whether *session_id* may read an artifact row tagged *stored_session*:
    its own, or a row from before rows carried a session.

    A kept run's step (``common/kept_sessions.py``), a dashboard viewer's
    among them, also reads what that dataflow's other kept steps made. The
    backend runs each step in a session of its own and hands it only outputs
    of that dataflow: its run's earlier steps and the outputs kept from
    earlier runs. No session of another shape reads theirs, and they read no
    other session's.
    """
    if session_id is None or stored_session is None or stored_session == session_id:
        return True
    return is_kept_session(session_id) and is_kept_session(stored_session)


def readable_artifacts(reads, sessions=()) -> list:
    """The artifact ids among *reads*, ``{id: the session it is read under,
    or a list of sessions}``, whose rows one of its sessions or of *sessions*,
    which every id is read under, may read (:func:`session_may_read`).

    An id read under no session (None) is not among them, though a read under
    none reads any row. One read under a list reads a row that carries no
    session whatever the list holds, so an empty list reads only such a row.
    An id with no row is never among them. A kept run's session among
    *sessions* reads nothing: it would read what every kept run made, so it
    reads only the ids it is named for."""
    shared = [session for session in sessions or () if session and not is_kept_session(session)]
    asked = {}
    for art_id, own in reads.items():
        if isinstance(own, str):
            own = [own] if own else None
        if not art_id or own is None:
            continue
        asked[art_id] = [session for session in own if session] + shared
    if not asked:
        return []
    placeholders = ",".join("?" for _ in asked)
    con = get_read_connection()
    try:
        rows = con.execute(
            f"SELECT id, session_id FROM artifacts WHERE id IN ({placeholders})", list(asked),
        ).fetchall()
    finally:
        con.close()
    return [
        art_id for art_id, stored in rows
        if stored is None or any(session_may_read(stored, session) for session in asked[art_id])
    ]


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
            if not session_may_read(stored_sid, session_id):
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
    # A pyarrow Schema or anything carrying one (a Table): the streamed route
    # has only the parquet file's schema, and reads no rows to answer this.
    schema = getattr(table, "schema", table)
    named = {}
    raw = (schema.metadata or {}).get(b"pandas")
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
            name: _dtype_name_for(schema.field(name).type)
            for name in schema.names
        }
    # Whichever source it came from, every geometry column needs the same
    # correction: GeoParquet stores them as WKB, so pandas metadata calls them
    # ``object`` and the Arrow type is binary, while the JSON path reports
    # geopandas' own ``geometry`` dtype. Say what the column means.
    #
    # All of them, not just the active one: a frame can carry a second
    # geometry column (``gdf["bbox"] = gdf.geometry.envelope``), and it is a
    # geometry in both paths.
    for column in _geoparquet_geometry_columns(schema):
        if column in named:
            named[column] = "geometry"
    return named


def _geoparquet_geometry_columns(table):
    """Every geometry column named by GeoParquet metadata, active or not."""
    schema = getattr(table, "schema", table)
    raw = (schema.metadata or {}).get(b"geo")
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


def open_tabular_arrow_from_duckdb(art_id, session_id=None, *, allow_geometry=False):
    """Open a tabular artifact's stored parquet payload, reading no rows.

    Supports kind in ('dataframe', 'geodataframe'); for GeoDataFrames the
    geometry column is binary WKB (GeoParquet's standard encoding). The Arrow
    route streams from the returned file batch by batch, so a fetch holds one
    batch at a time rather than the whole table (#408).

    Returns:
        (parquet_file, kind, frame_metadata, encoded_object_columns)

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
        if not session_may_read(stored_sid, session_id):
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
            # check comes before the file is opened, so the refusal costs nothing.
            raise ValueError(
                "Arrow IPC serves geodataframe geometry as WKB; send "
                "X-Curio-Accept-Geometry: wkb to accept it"
            )
        # pre_buffer off: it reads a whole row group's column chunks ahead,
        # which is most of what a streamed fetch would otherwise hold.
        parquet_file = pq.ParquetFile(_parquet_source(v_str, blob), pre_buffer=False)
        frame_metadata, encoded_object_columns = _parse_parquet_meta(v_json)
        return parquet_file, kind, frame_metadata, encoded_object_columns
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
        if not session_may_read(stored_sid, session_id):
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


#: The first four bytes of a TIFF, little- and big-endian, then of a BigTIFF.
_TIFF_SIGNATURES = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")

#: How a GDAL virtual raster starts, such as the VRT Mosaic Rasters writes.
_VRT_START = b"<VRTDataset"


def load_saved_output(path, name):
    """A dataflow's saved output *name*, read in place from *path*, the file
    its owner's store holds for it, which the backend resolved
    (``projects/storage.saved_output_file``) and the only caller may send.
    Nothing is copied.

    That is the normal state for a saved output read outside the session that
    produced it: the artifact row is session-tagged (see
    :func:`load_from_duckdb`) and may have been pruned entirely, while this
    file is what the dataflow saved.

    The name alone does not say what the bytes are - a computed dataset is
    named after the JSON, parquet or raster artifact it was installed from,
    and a table saved before that keeps its generated
    ``<ms>_<hex>_output.parquet`` name - so the content is sniffed: a frame
    with its ``.decode.json``,
    a raster (a GeoTIFF or a VRT, opened as the store opens a raster
    artifact: a rasterio dataset), a JSON value, or a bundle's
    ``bundle.json``, which reads as the tuple, list or dict its parts make,
    from the dataset's own folder (two levels up, :func:`_load_bundle`).

    Raises ``KeyError`` when the file is not there or cannot be read, so
    callers treat it exactly like a missing artifact.
    """
    missing = KeyError(f"No artifact with id {name}")
    try:
        path = Path(path).resolve()
    except (OSError, TypeError, ValueError):
        raise missing
    if not path.is_file():
        raise missing
    if path.name == "bundle.json":
        return _load_bundle(path, path.parent.parent, missing)
    return _decode_output_file(path, name, missing)


def _decode_output_file(path, name, missing):
    """The value the output file at *path* holds, the output being called
    *name*; ``missing`` raised for bytes this cannot decode."""
    with open(path, "rb") as handle:
        header = handle.read(64)

    # Parquet, by magic or by name. ``load_dataset_parquet`` reads GeoParquet as
    # a GeoDataFrame and restores the ``.decode.json`` sidecar, so object columns
    # come back as objects rather than JSON strings.
    if header[:4] == b"PAR1" or path.name.endswith(".parquet"):
        try:
            return load_dataset_parquet(path)
        except Exception:
            raise missing

    # A raster, by its first bytes: what load_from_duckdb returns for one.
    if header[:4] in _TIFF_SIGNATURES or header.lstrip().startswith(_VRT_START):
        try:
            import rasterio  # optional dep - see parse_raster

            return rasterio.open(str(path))
        except Exception:
            raise missing

    payload = path.read_bytes()
    # dict/list artifacts are stored zlib-compressed (see _write_json_artifact);
    # an installed copy of one keeps those bytes.
    if path.name.endswith(".json.zlib") or header[:1] == b"\x78":
        try:
            return json.loads(zlib.decompress(payload).decode("utf-8"))
        except Exception:
            pass
    try:
        value = json.loads(payload.decode("utf-8"))
    except Exception:
        raise missing
    if _is_bundle_description(value, name):
        # A bundle's bundle.json describes the output and is never its value.
        raise missing
    return value


def _is_bundle_description(value, name) -> bool:
    """Whether *value* is the ``bundle.json`` of the bundle installed for the
    output *name* (``datasets/install/bundle.py`` names the output as its
    ``parentArtifactId``) rather than a value the output holds."""
    return (
        isinstance(value, dict)
        and value.get("parentArtifactId") == name
        and isinstance(value.get("parts"), list)
    )


def _is_install_placeholder(value, part) -> bool:
    """Whether *value* is what the bundle install writes for a part whose
    value it could not find (its artifact id and kind) rather than the value."""
    art_id = part.get("artifactId")
    return (
        bool(art_id)
        and isinstance(value, dict)
        and value.get("artifactId") == art_id
        and set(value) <= {"artifactId", "kind", "note"}
    )


def _load_bundle(bundle, data_dir, missing):
    """The value a bundle holds, as the store gives it, read from a saved
    output's own dataset folder, *data_dir* being the folder it must lie in.
    Its parts go in the container its
    ``bundle.json`` records (``catalog_helpers.bundle_container``), a tuple,
    a list, or a dict with its keys in their order, and a tuple when it
    records none.

    Each part is read as ``curio_load_data`` reads one
    (``catalog_helpers.read_bundle_part``): a frame with its ``.decode.json``,
    a GeoTIFF with rasterio, a JSON value or a scalar as it was returned. Only
    the files ``listed_bundle_parts`` gives are read, the regular files inside
    the bundle's own folder: this read has no session check, so a part named
    anywhere else is not followed. A part that is not there, cannot be read,
    or is the install's placeholder for a value it could not find makes the
    whole output missing, never a shorter one, and so does a container that a
    bundle cannot be.
    """
    from utk_curio.sandbox.util.catalog_helpers import (
        bundle_container,
        listed_bundle_parts,
        read_bundle_part,
    )
    from utk_curio.sandbox.util.rasters import close_datasets

    try:
        bundle = bundle.resolve()
        bundle.relative_to(data_dir)
        spec = json.loads(bundle.read_text(encoding="utf-8"))
        named = spec["parts"]
    except (OSError, ValueError, KeyError, TypeError):
        raise missing
    listed = listed_bundle_parts(bundle)
    if not isinstance(named, list) or not named or len(listed) != len(named):
        raise missing
    values = []
    try:
        listed.sort(key=lambda item: item[0].get("index", 0))
        rebuild = bundle_container(spec, [part for part, _file in listed])
        for part, file in listed:
            values.append(read_bundle_part(str(file), part))
            if _is_install_placeholder(values[-1], part):
                raise missing
        return rebuild(values)
    except Exception:
        close_datasets(values)
        raise missing


#: The most saved outputs one request names (``shape_saved_paths``).
MAX_SAVED_PATHS = 64


def shape_saved_paths(raw):
    """``{name: {"path" or "session", "dataType"}}`` from a request: the
    inputs of the run's dataflow that the backend resolved for it
    (``execution/node_exec``). A saved output names the file its owner's store
    holds (``path``). An output the owner's runs kept, named as the input of a
    run that is not kept, names the kept session that made it (``session``),
    which the run's own session cannot read (``common/kept_sessions.py``).
    Anything else is dropped, a session that is not a kept one among them."""
    if not isinstance(raw, dict):
        return {}
    shaped = {}
    for name, saved in list(raw.items())[:MAX_SAVED_PATHS]:
        if not (isinstance(name, str) and name and isinstance(saved, dict)):
            continue
        data_type = saved.get("dataType")
        data_type = data_type if isinstance(data_type, str) else ""
        path, session = saved.get("path"), saved.get("session")
        if isinstance(path, str) and path:
            shaped[name] = {"path": path, "dataType": data_type}
        elif isinstance(session, str) and is_kept_session(session):
            shaped[name] = {"session": session, "dataType": data_type}
    return shaped


def load_artifact(art_id, session_id=None, saved_paths=None):
    """An artifact by id: the store first, then, for a saved output of the
    run's dataflow, the file its owner's store holds, or, for an output the
    owner's runs kept, the store under the kept session that made it
    (*saved_paths*, see :func:`shape_saved_paths`).

    The one rule every reader of a saved output follows, ``/get`` and node
    inputs alike (#407, #408). The store is session-tagged, so after a reopen
    under a new sign-in it cannot serve an output the canvas is showing as done
    - nor when the row was pruned or the database is momentarily locked. The
    saved output's own file can (:func:`load_saved_output`), read in place.
    When neither has it, the store's error is the one raised: for a missing
    artifact that is the familiar "No artifact with id", and for a locked
    database it keeps the real diagnostic.
    """
    try:
        return load_from_duckdb(art_id, session_id=session_id)
    except Exception as store_error:
        saved = (saved_paths or {}).get(art_id)
        if saved:
            try:
                if saved.get("session"):
                    return load_from_duckdb(art_id, session_id=saved["session"])
                return load_saved_output(saved["path"], art_id)
            except KeyError:
                pass
        raise store_error


#: The kinds whose ``value_str`` names the file this store wrote the value to,
#: under ``artifacts/``. Any other kind keeps its value in the row, or, for a
#: raster, names a file the node's own code wrote, which is never deleted here.
_STORED_FILE_KINDS = ("dataframe", "geodataframe", "list", "dict")


def _stored_file(kind, value_str):
    """The file an artifact row's value lives in, or None when the row holds it."""
    if kind not in _STORED_FILE_KINDS or not isinstance(value_str, str):
        return None
    if not value_str.startswith("artifacts/"):
        return None
    try:
        return _resolve_stored_artifact_path(value_str)
    except PermissionError:
        return None


def _session_rows(con, session_ids):
    placeholders = ",".join("?" for _ in session_ids)
    return con.execute(
        "SELECT id, session_id, kind, value_str, octet_length(blob), "
        "strlen(CAST(value_json AS VARCHAR)) "
        f"FROM artifacts WHERE session_id IN ({placeholders})",
        list(session_ids),
    ).fetchall()


def describe_session_artifacts(session_ids) -> dict:
    """``{session id: {"bytes", "ids"}}``: the artifacts each session made, by
    id, and how many bytes they hold, the files they were written to, the
    files their runs wrote (``output_files``) and the values their rows keep."""
    from utk_curio.sandbox.util.output_files import folder_bytes

    session_ids = list(session_ids)
    described = {session_id: {"bytes": 0, "ids": []} for session_id in session_ids}
    if not session_ids:
        return described
    init_db()
    con = get_connection()
    try:
        rows = _session_rows(con, session_ids)
    finally:
        con.close()
    for art_id, session_id, kind, value_str, blob_bytes, json_bytes in rows:
        size = (blob_bytes or 0) + (json_bytes or 0) + folder_bytes(str(art_id))
        path = _stored_file(kind, value_str)
        if path is not None:
            try:
                size += path.stat().st_size
            except OSError:
                pass
        elif isinstance(value_str, str):
            size += len(value_str.encode("utf-8"))
        entry = described.setdefault(session_id, {"bytes": 0, "ids": []})
        entry["bytes"] += size
        entry["ids"].append(art_id)
    return described


def _rows_naming_run_files(con) -> list:
    """``(kind, value_str)`` of the rows that name a file in a run's folder."""
    from utk_curio.sandbox.util.output_files import outputs_root

    return con.execute(
        "SELECT kind, value_str FROM artifacts WHERE kind IN ('raster', 'str') AND starts_with(value_str, ?)",
        [str(outputs_root()) + os.sep],
    ).fetchall()


def forget_session_artifacts(session_ids) -> int:
    """Delete every artifact the sessions made: its row, the file the store
    wrote its value to, and the folder of the files its run wrote, unless a
    remaining row names a file there. Returns how many rows went."""
    from utk_curio.sandbox.util.output_files import folders_named_by, forget_run_output

    session_ids = list(session_ids)
    if not session_ids:
        return 0
    init_db()
    con = get_connection()
    try:
        rows = _session_rows(con, session_ids)
        placeholders = ",".join("?" for _ in session_ids)
        con.execute(f"DELETE FROM artifacts WHERE session_id IN ({placeholders})", session_ids)
        named = folders_named_by(_rows_naming_run_files(con))
    finally:
        con.close()
    for art_id, _session_id, kind, value_str, _blob, _json in rows:
        path = _stored_file(kind, value_str)
        if path is not None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        if str(art_id) not in named:
            forget_run_output(str(art_id))
    return len(rows)


#: An artifact id: the millisecond it was made, then a random part (``_make_id``).
_ARTIFACT_ID_MS = re.compile(r"(\d{13})_[0-9a-f]{8}")
#: The kinds whose row lists the artifacts it holds (``save_to_duckdb``).
_CONTAINER_KINDS = ("outputs", "list_of_ids", "dict_of_ids")
#: What a run or a load wrote at the top of the shared data directory before a
#: saved output was the store's own file: a run's second encode of a table,
#: ``<id>_output.parquet`` with its decode and counts sidecars, and a load's
#: copy of a saved output, named after its artifact.
_LEFTOVER_FILE = re.compile(r"\d{13}_[0-9a-f]{8}(?:_output\.parquet)?(?:\.[A-Za-z0-9.]+)?")
#: Where a load put the parts of a saved bundle it copied.
_LEFTOVER_BUNDLES = "bundles"
#: How many rows one ``DELETE`` names.
_DELETE_BATCH = 500
#: How much longer than the rest a kept run's rows are left to their entries,
#: which go when their days are up and take the rows with them; a row whose
#: entry was never written, or whose forget failed, goes this much later.
_KEPT_MARGIN_MS = 24 * 3600 * 1000


def _made_before(art_id, cutoff_ms) -> bool:
    match = _ARTIFACT_ID_MS.fullmatch(str(art_id))
    return match is not None and int(match.group(1)) < cutoff_ms


def _parts_of(value_json) -> list:
    """The artifact ids a container row holds."""
    try:
        parts = json.loads(value_json) if isinstance(value_json, str) else value_json
    except (TypeError, ValueError):
        return []
    if isinstance(parts, dict):
        parts = list(parts.values())
    return [str(part) for part in parts or [] if part] if isinstance(parts, list) else []


def _file_under(folder: Path, value_str):
    """The file *value_str* names, when it is inside *folder*; else None."""
    if not isinstance(value_str, str) or not value_str:
        return None
    try:
        path = Path(value_str)
        path = (path if path.is_absolute() else _shared_data_dir() / path).resolve()
        path.relative_to(folder)
    except (OSError, ValueError):
        return None
    return path


def _older_than(path: Path, cutoff_ms) -> bool:
    """Whether *path* was last written, and last moved or linked, before
    *cutoff_ms*. A file's own time can be set by whoever wrote it; the change
    of its entry, which a move into the store makes, cannot."""
    try:
        status = path.lstat()
    except OSError:
        return False
    return max(status.st_mtime, status.st_ctime) * 1000 < cutoff_ms


def forget_made_before(cutoff_ms) -> int:
    """Delete what the store holds that was made before *cutoff_ms*. A kept
    run's artifacts (``common/kept_sessions.py``) go with their entries, so
    they are left a day longer (:data:`_KEPT_MARGIN_MS`), and then go too:
    no entry outlives that. Returns how many rows went.

    - An artifact goes with its row: by the time in its id, and a part of a
      tuple, list or dict output by its whole output's, so a bundle goes whole.
      A part belongs to one output: every writer of such a row stores its
      parts anew (``save_to_duckdb``, ``staging.persist_output``).
    - Only files under ``artifacts/`` are removed: the files the store wrote
      the values to, a raster's own file when it is there, and any file there
      that nothing has used since the cutoff. A file a remaining row names
      stays, and a file the Data Catalog linked keeps its other name.
    - The folder of the files a run wrote (``output_files``) goes with the
      run's row, or past the cutoff when no row was stored for it, unless a
      remaining row names a file in it.
    - So do the files earlier versions wrote at the top of the shared data
      directory (:data:`_LEFTOVER_FILE`, :data:`_LEFTOVER_BUNDLES`), once
      their time is past the cutoff.
    """
    import shutil

    init_db()
    con = get_connection()
    artifacts = (_shared_data_dir() / "artifacts").resolve()
    try:
        rows = con.execute(
            "SELECT id, session_id, kind, value_str, value_json FROM artifacts"
        ).fetchall()
        holder = {}
        for art_id, _session, kind, _value_str, value_json in rows:
            if kind in _CONTAINER_KINDS:
                for part in _parts_of(value_json):
                    holder.setdefault(part, str(art_id))
        sessions = {str(art_id): session for art_id, session, *_rest in rows}

        def whole(art_id):
            seen = set()
            while art_id in holder and art_id not in seen:
                seen.add(art_id)
                art_id = holder[art_id]
            return art_id

        going = set()
        for art_id, *_rest in rows:
            art_id = str(art_id)
            top = whole(art_id)
            kept = is_kept_session(sessions.get(top)) or is_kept_session(sessions.get(art_id))
            if _made_before(top, cutoff_ms - _KEPT_MARGIN_MS if kept else cutoff_ms):
                going.add(art_id)
        ordered = sorted(going)
        for start in range(0, len(ordered), _DELETE_BATCH):
            batch = ordered[start:start + _DELETE_BATCH]
            con.execute(
                f"DELETE FROM artifacts WHERE id IN ({','.join('?' for _ in batch)})", batch,
            )
    finally:
        con.close()

    def row_file(kind, value_str):
        if kind in _STORED_FILE_KINDS:
            return _stored_file(kind, value_str)
        return _file_under(artifacts, value_str) if kind == "raster" else None

    # Two passes: a raster an in-process run rebuilt is one file, named by
    # every row that returned it, so a row that goes removes its file only
    # when no remaining row, a kept run's among them, names it too.
    staying_ids, staying_files = set(), set()
    for art_id, _session, kind, value_str, _value_json in rows:
        if str(art_id) not in going:
            staying_ids.add(str(art_id))
            path = row_file(kind, value_str)
            if path is not None:
                staying_files.add(path)
    for art_id, _session, kind, value_str, _value_json in rows:
        path = row_file(kind, value_str) if str(art_id) in going else None
        if path is not None and path not in staying_files:
            with contextlib.suppress(OSError):
                path.unlink()
    if artifacts.is_dir():
        for path in artifacts.iterdir():
            if not path.is_file() or path.name.split(".")[0] in staying_ids:
                continue
            if path.resolve() not in staying_files and _older_than(path, cutoff_ms):
                with contextlib.suppress(OSError):
                    path.unlink()

    # The folder of the files a run wrote (``output_files``) goes with its
    # row, and one no row was stored for goes once its time is past the
    # cutoff. A folder a remaining row names a file in stays.
    from utk_curio.sandbox.util import output_files

    every_id = {str(art_id) for art_id, *_rest in rows}
    named = staying_ids | output_files.folders_named_by(
        (kind, value_str) for art_id, _session, kind, value_str, _value_json in rows
        if str(art_id) not in going
    )
    runs = output_files.outputs_root()
    if runs.is_dir() and not runs.is_symlink():
        for folder in runs.iterdir():
            if not output_files.is_artifact_id(folder.name) or folder.name in named:
                continue
            if folder.is_symlink() or not folder.is_dir():
                continue
            if folder.name in going or (folder.name not in every_id and _older_than(folder, cutoff_ms)):
                shutil.rmtree(folder, ignore_errors=True)

    shared = _shared_data_dir()
    for path in shared.iterdir() if shared.is_dir() else ():
        if path.is_file() and _LEFTOVER_FILE.fullmatch(path.name) and _older_than(path, cutoff_ms):
            with contextlib.suppress(OSError):
                path.unlink()
    bundles = shared / _LEFTOVER_BUNDLES
    if bundles.is_dir() and not bundles.is_symlink():
        for folder in bundles.iterdir():
            if folder.is_dir() and not folder.is_symlink() and _older_than(folder, cutoff_ms):
                shutil.rmtree(folder, ignore_errors=True)
        with contextlib.suppress(OSError):
            bundles.rmdir()
    return len(going)


def save_dataset_parquet(output, kind):
    """Save a DataFrame or GeoDataFrame as a named Parquet file in the shared data
    directory (top-level, not inside ``artifacts/``).

    In-process node code can call it. A node's run does not: a saved output is
    its artifact's own file, which the Data Catalog links with the decode the
    artifact's row keeps (``backend/app/datasets/install/bundle.install_node_output``).

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
            prepared.to_parquet(full_path, row_group_size=PARQUET_ROW_GROUP_ROWS)
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

