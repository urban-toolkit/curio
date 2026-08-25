"""Moving artifacts between the store and an isolated child's scratch directory.

The parent owns the artifact store and the child must never touch it, so every
byte crossing the boundary passes through here. Two directions:

``stage_input``
    Store -> scratch. Turns an artifact id into files in the child's scratch
    directory plus an input spec naming them (see ``isolation/protocol.py``).

``persist_output``
    Scratch -> store. Takes a *validated* child output descriptor and writes it
    into DuckDB.

The important property is that neither direction re-encodes a DataFrame.
Frames are already persisted as parquet files under ``.curio/data/artifacts/``
with the relative path in the row's ``value_str`` (see
``parsers._stored_artifact_rel_path``), so staging an input is a hardlink and
persisting an output is a rename. The parent therefore never parses bytes a
child produced, which matters: parsing hostile parquet in the privileged
process would hand back much of what the isolation just removed.

Session scoping stays here in the parent, where a compromised child cannot
reach it: ``stage_input`` refuses an artifact belonging to another session, the
same rule ``load_from_duckdb`` enforces.
"""

import json
import os
import shutil
from pathlib import Path

from utk_curio.sandbox.util.db import get_connection, get_read_connection, init_db
from utk_curio.sandbox.util import codec
from utk_curio.sandbox.util.parsers import (
    _json_artifact_rel_path,
    _make_id,
    _read_json_artifact,
    _resolve_stored_artifact_path,
    _shared_data_dir,
    _stored_artifact_rel_path,
    _write_json_artifact,
)


class StagingError(RuntimeError):
    """An artifact could not be staged for, or persisted from, a child."""


def _link_or_copy(source: Path, destination: Path) -> None:
    """Put *source* at *destination*, preferring a hardlink.

    A hardlink is effectively free and avoids duplicating a multi-gigabyte
    raster or parquet for every node run. It is safe despite sharing an inode
    with the stored artifact: the child's uid has no write permission on the
    file, so it can read the contents and nothing more. Falls back to a copy
    across filesystems, or where the platform refuses to link.
    """
    try:
        os.link(source, destination)
        return
    except (OSError, AttributeError, NotImplementedError):
        shutil.copy2(source, destination)


def _read_row(art_id, session_id):
    """Fetch one artifact row, enforcing session ownership.

    Mirrors ``load_from_duckdb``'s rule: a row tagged with a different session
    is reported as missing rather than forbidden, so a caller cannot probe for
    the existence of another session's artifacts.
    """
    con = get_read_connection()
    try:
        row = con.execute(
            "SELECT kind, value_int, value_float, value_str, value_json, blob, session_id "
            "FROM artifacts WHERE id = ?",
            [art_id],
        ).fetchone()
        if row is None:
            raise KeyError(f"No artifact with id {art_id}")
        stored_session = row[6]
        if (
            session_id is not None
            and stored_session is not None
            and stored_session != session_id
        ):
            raise KeyError(f"No artifact with id {art_id}")
        return row[:6]
    finally:
        try:
            con.close()
        except Exception:
            pass


def stage_input(art_id, scratch_dir, *, session_id=None, slot="in"):
    """Stage the artifact *art_id* into *scratch_dir* and return its input spec.

    *slot* prefixes the staged filenames so a merge node's several inputs do
    not collide. Recurses for container kinds, extending the prefix as it goes.
    """
    scratch_dir = Path(scratch_dir)
    kind, v_int, v_float, v_str, v_json, blob = _read_row(art_id, session_id)

    if kind == "null":
        return {"kind": "null"}
    if kind == "bool":
        return {"kind": "bool", "value": bool(v_int)}
    if kind == "int":
        return {"kind": "int", "value": v_int}
    if kind == "float":
        return {"kind": "float", "value": v_float}
    if kind == "str":
        return {"kind": "str", "value": v_str}

    if kind in ("list", "dict"):
        value = _read_json_artifact(v_str) if v_str else json.loads(v_json)
        name = f"{slot}.json"
        (scratch_dir / name).write_text(
            json.dumps(codec._json_safe_value(value), ensure_ascii=False,
                       allow_nan=False),
            encoding="utf-8",
        )
        return {"kind": "json", "file": name}

    if kind in ("dataframe", "geodataframe"):
        name = f"{slot}.parquet"
        target = scratch_dir / name
        if v_str:
            _link_or_copy(_resolve_stored_artifact_path(v_str), target)
        elif blob is not None:
            # Legacy rows kept the parquet inline as a BLOB.
            target.write_bytes(blob)
        else:
            raise StagingError(f"artifact {art_id} has no parquet payload")
        frame_metadata, encoded_object_columns = codec._parse_parquet_meta(v_json)
        spec = {
            "kind": kind,
            "file": name,
            "encoded_object_columns": encoded_object_columns or [],
        }
        if kind == "geodataframe" and frame_metadata:
            spec["frame_metadata"] = frame_metadata
        return spec

    if kind == "raster":
        source = Path(v_str)
        if not source.is_absolute():
            # Stored relative to the launch directory, which is the sandbox's
            # cwd; the child has a different cwd, so resolve it here.
            source = Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())) / source
        if not source.exists():
            raise StagingError(f"raster artifact {art_id} is missing at {source}")
        name = f"{slot}{source.suffix or '.tif'}"
        _link_or_copy(source, scratch_dir / name)
        return {"kind": "raster", "file": name}

    if kind in ("outputs", "list_of_ids"):
        child_ids = json.loads(v_json)
        return {
            "kind": "sequence",
            "container": "tuple" if kind == "outputs" else "list",
            "items": [
                stage_input(cid, scratch_dir, session_id=session_id,
                            slot=f"{slot}_{index}")
                for index, cid in enumerate(child_ids)
            ],
        }

    if kind == "dict_of_ids":
        child_id_map = json.loads(v_json)
        return {
            "kind": "mapping",
            "items": {
                key: stage_input(cid, scratch_dir, session_id=session_id,
                                 slot=f"{slot}_{index}")
                for index, (key, cid) in enumerate(child_id_map.items())
            },
        }

    raise StagingError(f"cannot stage artifact of unknown kind {kind!r}")


def stage_outputs_list(refs, scratch_dir, *, session_id=None):
    """Stage a merge node's list of upstream references.

    ``/exec`` receives ``dataType == 'outputs'`` with a list of ``{'path': id}``
    dicts (or bare ids). This is the entry point for that shape.
    """
    items = []
    for index, ref in enumerate(refs):
        art_id = ref.get("path") if isinstance(ref, dict) else ref
        items.append(
            stage_input(art_id, scratch_dir, session_id=session_id, slot=f"in_{index}")
        )
    return {"kind": "sequence", "container": "tuple", "items": items}


def read_outputs_wrapper(art_id, *, session_id=None):
    """Return the inner ref list when *art_id* holds a persisted merge output.

    A merge output that was persisted is stored as the whole
    ``{'dataType': 'outputs', 'data': [refs]}`` envelope, and a node downstream
    of it receives one ref to that envelope rather than the list. The parent
    resolves it here -- reading the store is exactly what the child cannot do --
    and hands the child the same per-slot list the live shape produces.

    Returns None when the artifact is anything else, so the caller can fall
    back to staging it as an ordinary input.
    """
    kind, _v_int, _v_float, v_str, v_json, _blob = _read_row(art_id, session_id)
    if kind not in ("list", "dict"):
        return None
    try:
        value = _read_json_artifact(v_str) if v_str else json.loads(v_json)
    except (OSError, ValueError):
        return None
    if (isinstance(value, dict)
            and value.get("dataType") == "outputs"
            and isinstance(value.get("data"), list)):
        return value["data"]
    return None


def stage_dataset_paths(dataset_paths, scratch_dir):
    """Stage the files behind ``curio_dataset_path`` calls.

    The child cannot reach the dataset stores by path -- ``datasets/`` and
    ``.curio/users`` are 0700 root-owned once isolation is on
    (``hardening.SENSITIVE_PATHS``) -- so each file is linked in and the mapping
    the child receives points at the staged copy. Note the link shares the
    source's inode and therefore its mode: what makes this a boundary is the
    unreachable *path*, not a tighter file. A missing file is dropped rather
    than raised: the injected
    ``curio_dataset_path`` already raises a clear per-id error, and resolution
    is documented as fail-open (see docs/ARCHITECTURE.md).
    """
    scratch_dir = Path(scratch_dir)
    staged = {}
    for index, (dataset_id, source) in enumerate(dataset_paths.items()):
        try:
            source_path = Path(source)
            if not source_path.exists():
                continue
            name = f"ds_{index}{source_path.suffix}"
            _link_or_copy(source_path, scratch_dir / name)
            staged[dataset_id] = name
        except OSError:
            continue
    return staged


def _insert_row(con, art_id, kind, *, node_id=None, session_id=None,
                value_int=None, value_float=None, value_str=None,
                value_json=None, blob=None):
    con.execute(
        "INSERT INTO artifacts "
        "(id, node_id, kind, session_id, value_int, value_float, value_str, "
        "value_json, blob) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [art_id, node_id, kind, session_id, value_int, value_float, value_str,
         value_json, blob],
    )


def persist_output(descriptor, *, node_id=None, session_id=None):
    """Write a validated child output descriptor into the artifact store.

    *descriptor* must already have been through
    ``protocol.parse_child_result`` (which is what attaches the checked
    absolute ``path`` to each file-backed entry). Returns the new artifact id.

    File-backed payloads are **moved**, not parsed. The parent never reads a
    parquet a child wrote; it only relocates the bytes and records where they
    went.
    """
    init_db()
    con = get_connection()
    return _persist(con, descriptor, node_id=node_id, session_id=session_id)


def _persist(con, descriptor, *, node_id, session_id):
    kind = descriptor["kind"]
    art_id = _make_id()

    if kind == "outputs":
        child_ids = [
            _persist(con, item, node_id=node_id, session_id=session_id)
            for item in descriptor["items"]
        ]
        _insert_row(con, art_id, "outputs", node_id=node_id, session_id=session_id,
                    value_json=json.dumps(child_ids))
        return art_id

    if kind == "null":
        _insert_row(con, art_id, "null", node_id=node_id, session_id=session_id)
        return art_id
    if kind == "bool":
        _insert_row(con, art_id, "bool", node_id=node_id, session_id=session_id,
                    value_int=int(descriptor["value"]))
        return art_id
    if kind == "int":
        _insert_row(con, art_id, "int", node_id=node_id, session_id=session_id,
                    value_int=descriptor["value"])
        return art_id
    if kind == "float":
        _insert_row(con, art_id, "float", node_id=node_id, session_id=session_id,
                    value_float=descriptor["value"])
        return art_id
    if kind == "str":
        _insert_row(con, art_id, "str", node_id=node_id, session_id=session_id,
                    value_str=descriptor["value"])
        return art_id

    source = descriptor.get("path")
    if not source or not os.path.exists(source):
        raise StagingError(f"child named an output file that is not there: {source!r}")

    if kind in ("list", "dict"):
        # These arrive as plain JSON. Re-encode through the store's own writer
        # so the compression and NaN scrubbing match every other artifact.
        with open(source, encoding="utf-8") as handle:
            value = json.load(handle)
        rel_path = _write_json_artifact(art_id, value)
        _insert_row(con, art_id, kind, node_id=node_id, session_id=session_id,
                    value_str=rel_path)
        return art_id

    if kind in ("dataframe", "geodataframe"):
        rel_path = _stored_artifact_rel_path(art_id)
        target = _resolve_stored_artifact_path(rel_path, create_parent=True)
        shutil.move(source, target)
        meta = descriptor.get("meta") or {}
        value_json = codec._serialize_parquet_meta(
            meta.get("frame_metadata"), meta.get("encoded_object_columns"),
        )
        _insert_row(con, art_id, kind, node_id=node_id, session_id=session_id,
                    value_str=rel_path, value_json=value_json)
        return art_id

    if kind == "raster":
        suffix = Path(source).suffix or ".tif"
        rel_path = _stored_artifact_rel_path(art_id, suffix=suffix)
        target = _resolve_stored_artifact_path(rel_path, create_parent=True)
        shutil.move(source, target)
        # Rasters are stored by path rather than by payload, and load_from_duckdb
        # reopens that path with rasterio. Store it absolute: the in-process path
        # stores whatever the user opened (often relative to the launch dir),
        # which only resolves because the sandbox happens to share that cwd. A
        # child does not, so resolve it once here instead.
        _insert_row(con, art_id, "raster", node_id=node_id, session_id=session_id,
                    value_str=str(target))
        return art_id

    raise StagingError(f"cannot persist output of kind {kind!r}")


def copy_output_dataset(descriptor):
    """Mirror a tabular child output into the Data Catalog's dataset directory.

    The in-process path does this with ``save_dataset_parquet``. Here the child
    already wrote parquet, so this is a copy rather than an encode. Returns the
    dataset filename, or None when the output is not tabular.

    **Call this before :func:`persist_output`**, which moves the scratch file
    into the store and leaves nothing at ``descriptor['path']``.

    Best-effort by design, matching ``save_dataset_parquet``: a failure to
    publish a convenience copy must never fail the node.
    """
    if descriptor.get("kind") not in ("dataframe", "geodataframe"):
        return None
    source = descriptor.get("path")
    if not source or not os.path.exists(source):
        return None
    try:
        name = f"{_make_id()}_output.parquet"
        shutil.copy2(source, _shared_data_dir() / name)
        return name
    except Exception as exc:  # noqa: BLE001 - convenience copy, never fatal
        print(f"[staging] could not publish dataset copy: {exc}", flush=True)
        return None
