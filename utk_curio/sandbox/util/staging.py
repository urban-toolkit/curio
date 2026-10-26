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
    session_may_read,
    _make_id,
    _read_json_artifact,
    _resolve_stored_artifact_path,
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
    file, so it can read the contents and nothing more. A file an earlier
    child wrote is no exception, since :func:`persist_output` takes it from
    that child. Falls back to a copy across filesystems, or where the
    platform refuses to link.
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
        if not session_may_read(row[6], session_id):
            raise KeyError(f"No artifact with id {art_id}")
        return row[:6]
    finally:
        try:
            con.close()
        except Exception:
            pass


#: Saved outputs whose file a child reads as it reads the store's own.
_SAVED_FRAME_KINDS = ("dataframe", "geodataframe")
_SAVED_JSON_KINDS = ("dict", "list")
_SAVED_SCALAR_KINDS = ("int", "float", "bool", "str", "null")
_RASTER_SUFFIXES = (".tif", ".tiff", ".vrt")


def stage_saved_output(saved, scratch_dir, *, name, slot="in"):
    """Stage the saved output *name* of the run's dataflow from the file its
    owner's store holds (*saved*, ``{"path", "dataType"}``, as
    ``parsers.shape_saved_paths`` gives it), as its store row would be
    staged, with nothing re-encoded and no row added: a frame, a raster or a
    JSON value is linked, a scalar given by value, and a bundle staged part
    by part from its dataset's folder.

    The parent parses no table here: a frame's kind is the data type the
    manifest records, and its decode metadata the ``.decode.json`` beside it,
    which holds what a row's ``value_json`` holds. Raises ``KeyError`` for a
    file that is not there, or that this cannot stage, so the caller falls
    back as it does for a missing artifact.
    """
    scratch_dir = Path(scratch_dir)
    path = Path(saved["path"])
    if not path.is_file():
        raise KeyError(f"No artifact with id {name}")
    if path.name == "bundle.json":
        return _stage_saved_bundle(path, scratch_dir, name=name, slot=slot)
    kind = str(saved.get("dataType") or "").strip().lower()
    return _stage_saved_file(path, kind, scratch_dir, name=name, slot=slot)


def _stage_saved_file(path, kind, scratch_dir, *, name, slot, in_bundle=False):
    """The input spec of one saved file of kind *kind*: the file itself, or a
    bundle's part (*in_bundle*), whose scalar is kept as ``{"value": ...}``."""
    if kind in _SAVED_FRAME_KINDS and path.suffix == ".parquet":
        target = scratch_dir / f"{slot}.parquet"
        _link_or_copy(path, target)
        sidecar = path.with_name(path.name + codec.PARQUET_DECODE_SIDECAR_SUFFIX)
        meta_json = sidecar.read_text(encoding="utf-8") if sidecar.is_file() else None
        frame_metadata, encoded_object_columns = codec._parse_parquet_meta(meta_json)
        spec = {
            "kind": kind,
            "file": target.name,
            "encoded_object_columns": encoded_object_columns or [],
        }
        if kind == "geodataframe" and frame_metadata:
            spec["frame_metadata"] = frame_metadata
        return spec
    if kind == "raster" or path.suffix.lower() in _RASTER_SUFFIXES:
        target = scratch_dir / f"{slot}{path.suffix or '.tif'}"
        _link_or_copy(path, target)
        return {"kind": "raster", "file": target.name}
    if kind in _SAVED_JSON_KINDS and path.suffix == ".json":
        target = scratch_dir / f"{slot}.json"
        _link_or_copy(path, target)
        return {"kind": "json", "file": target.name}
    if kind in _SAVED_SCALAR_KINDS and path.suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        if in_bundle:
            if not isinstance(value, dict) or "value" not in value:
                raise KeyError(f"No artifact with id {name}")
            value = value["value"]
        if kind == "null" or value is None:
            return {"kind": "null"}
        return {"kind": kind, "value": bool(value) if kind == "bool" else value}
    raise KeyError(f"No artifact with id {name}")


def _stage_saved_bundle(bundle, scratch_dir, *, name, slot):
    """A saved bundle's input spec: each part its ``bundle.json`` lists, from
    its dataset's folder (``catalog_helpers.listed_bundle_parts``), in the
    container it records. A part that is not there, or that holds the
    install's placeholder for a value it could not find, makes the whole
    output missing, as ``parsers.load_saved_output`` reads it."""
    from utk_curio.sandbox.util.catalog_helpers import bundle_container, listed_bundle_parts

    try:
        spec = json.loads(bundle.read_text(encoding="utf-8"))
        named = spec["parts"]
        listed = listed_bundle_parts(bundle)
        if not isinstance(named, list) or not named or len(listed) != len(named):
            raise KeyError(f"No artifact with id {name}")
        listed.sort(key=lambda item: item[0].get("index", 0))
        bundle_container(spec, [part for part, _file in listed])
    except (OSError, TypeError, ValueError):
        raise KeyError(f"No artifact with id {name}")
    items = [
        _stage_saved_file(
            file, str(part.get("kind") or "").strip().lower(), scratch_dir,
            name=name, slot=f"{slot}_{index}", in_bundle=True,
        )
        for index, (part, file) in enumerate(listed)
    ]
    container = spec.get("container") or "tuple"
    if container == "dict":
        return {"kind": "mapping", "items": {part["key"]: item for (part, _f), item in zip(listed, items)}}
    return {"kind": "sequence", "container": container, "items": items}


def stage_input(art_id, scratch_dir, *, session_id=None, slot="in", saved_paths=None):
    """Stage the artifact *art_id* into *scratch_dir* and return its input spec.

    *slot* prefixes the staged filenames so a node's several inputs do
    not collide. Recurses for container kinds, extending the prefix as it goes.
    An artifact this session's store cannot serve that is a saved output of
    the run's dataflow (*saved_paths*) is staged from its own file
    (:func:`stage_saved_output`); one the owner's runs kept is staged from the
    store under the kept session that made it, its parts too.
    """
    scratch_dir = Path(scratch_dir)
    try:
        kind, v_int, v_float, v_str, v_json, blob = _read_row(art_id, session_id)
    except Exception as store_error:
        # The rule parsers.load_artifact applies in-process (#407): a saved
        # output the store cannot serve to this session is read from its own
        # file, staged as it is, with no store row added; a kept output, from
        # the store under the session the backend names.
        saved = (saved_paths or {}).get(art_id)
        if saved:
            try:
                if saved.get("session"):
                    return stage_input(art_id, scratch_dir, session_id=saved["session"], slot=slot)
                return stage_saved_output(saved, scratch_dir, name=art_id, slot=slot)
            except (KeyError, OSError, ValueError):
                pass
        raise store_error

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


def stage_outputs_list(refs, scratch_dir, *, session_id=None, saved_paths=None):
    """Stage the list of upstream references of a node with several inputs.

    ``/exec`` receives ``dataType == 'outputs'`` with a list of ``{'path': id}``
    dicts (or bare ids). This is the entry point for that shape.
    """
    items = []
    for index, ref in enumerate(refs):
        art_id = ref.get("path") if isinstance(ref, dict) else ref
        items.append(
            stage_input(art_id, scratch_dir, session_id=session_id, slot=f"in_{index}",
                        saved_paths=saved_paths)
        )
    return {"kind": "sequence", "container": "tuple", "items": items}


def read_outputs_wrapper(art_id, *, session_id=None):
    """Return the inner ref list when *art_id* holds a persisted input bundle.

    A bundle that was persisted is stored as the whole
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


def outputs_wrapper_names(art_id, saved_path=None):
    """The outputs a persisted ``outputs`` wrapper stored as *art_id* names,
    which a run whose input it is reads too (``worker._expand_outputs_wrapper``,
    ``isolation/runner._build_input_spec``); [] for any other artifact, or
    none. With no row, the saved output's own file the backend names
    (*saved_path*), which a run reads in its place (``parsers.load_artifact``).
    For the backend, which asks before it decides the run's session."""
    try:
        refs = read_outputs_wrapper(art_id, session_id=None)
    except KeyError:
        refs = _saved_wrapper_refs(art_id, saved_path) if saved_path else None
    names = []
    for ref in refs or []:
        name = ref.get("path") if isinstance(ref, dict) else ref
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    return names


def _saved_wrapper_refs(art_id, saved_path):
    """The refs of the wrapper the saved output file *saved_path* holds, read
    as a run reads it (``parsers.load_saved_output``), or None."""
    from utk_curio.sandbox.util.parsers import load_saved_output

    try:
        value = load_saved_output(saved_path, art_id)
    except KeyError:
        return None
    if (isinstance(value, dict)
            and value.get("dataType") == "outputs"
            and isinstance(value.get("data"), list)):
        return value["data"]
    return None


def _stage_with_companions(source: Path, folder: Path) -> None:
    """Link *source* into *folder* with the files read beside it
    (``catalog_helpers.files_read_beside``: a parquet's ``.decode.json``, a
    shapefile's ``.shx``, ``.dbf`` and ``.prj``). A file already staged is
    left as it is."""
    from utk_curio.sandbox.util.catalog_helpers import files_read_beside

    folder.mkdir(parents=True, exist_ok=True)
    for path in [source, *files_read_beside(source)]:
        if not (folder / path.name).exists():
            _link_or_copy(path, folder / path.name)


def _bundle_parts(bundle: Path):
    """The part files a ``bundle.json`` names, with their paths relative to the
    folder the reader resolves them against, the dataset's (two levels up).
    A part outside that folder, or not a regular file, is left out
    (``catalog_helpers.listed_bundle_parts``, the list a part read picks from)."""
    from utk_curio.sandbox.util.catalog_helpers import listed_bundle_parts

    base = bundle.parent.parent.resolve()
    return [(resolved, resolved.relative_to(base)) for _part, resolved in listed_bundle_parts(bundle)]


def stage_dataset_paths(dataset_paths, scratch_dir):
    """Stage the files behind ``curio_data_path`` calls.

    The child cannot reach the dataset stores by path -- ``datasets/`` and
    ``.curio/users`` are 0700 root-owned once isolation is on
    (``hardening.SENSITIVE_PATHS``) -- so each file is linked in and the mapping
    the child receives points at the staged copy. Note the link shares the
    source's inode and therefore its mode: what makes this a boundary is the
    unreachable *path*, not a tighter file. A missing file is dropped rather
    than raised: the injected
    ``curio_data_path`` already raises a clear per-id error, and resolution
    is documented as fail-open (see docs/ARCHITECTURE.md).

    Each dataset gets a folder, ``ds_<i>/``, holding its file and the files
    read beside it (``_stage_with_companions``), never the rest of the folder
    the file sits in, which can be a workspace folder or the artifact store. A
    ``bundle.json`` is staged as ``ds_<i>/data/bundle.json`` with each part it
    names at the same path relative to ``ds_<i>/`` that it has relative to the
    dataset's folder, which is where ``curio_load_data`` looks for them.
    """
    scratch_dir = Path(scratch_dir)
    staged = {}
    for index, (dataset_id, source) in enumerate(dataset_paths.items()):
        try:
            source_path = Path(source)
            if not source_path.exists():
                continue
            folder = Path(f"ds_{index}")
            if source_path.name == "bundle.json":
                for part, relative in _bundle_parts(source_path):
                    _stage_with_companions(part, scratch_dir / folder / relative.parent)
                folder = folder / source_path.parent.name
            _stage_with_companions(source_path, scratch_dir / folder)
            staged[dataset_id] = (folder / source_path.name).as_posix()
        except OSError:
            continue
    return staged


def stage_model_dirs(model_dirs, scratch_dir):
    """Stage the folders behind ``curio_load_model`` calls, as datasets are staged.

    A model is a folder, and its files name each other: an ``.onnx`` graph
    reads its external weights by relative name, a Transformers checkpoint is
    read by ``from_pretrained`` as a folder. So the tree is linked in whole,
    each file at its own relative path under ``model_<i>/``. Only regular
    files inside the folder are linked; a link pointing out of it is skipped.
    A folder that cannot be staged is dropped, and the injected
    ``curio_load_model`` names it.
    """
    scratch_dir = Path(scratch_dir)
    staged = {}
    for index, (model_id, source) in enumerate(model_dirs.items()):
        try:
            root = Path(source).resolve()
            if not root.is_dir():
                continue
            name = f"model_{index}"
            _link_tree(root, scratch_dir / name)
            staged[model_id] = name
        except OSError:
            continue
    return staged


def _link_tree(root: Path, target: Path) -> None:
    """Link every regular file inside the folder *root* into *target*, each at
    its own relative path. A link pointing out of *root* is skipped."""
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if root not in path.resolve().parents:
            continue
        destination = target / path.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _link_or_copy(path, destination)


#: Where a run's package modules are staged, inside the run's own folder.
PACKAGE_MODULES_DIR = "package_modules"


def stage_package_modules(package_modules, run_dir):
    """Stage the modules a node's package ships, as models are staged (#468).

    *package_modules* is ``{"root": <the package's sources folder>, "names":
    [...]}``, or a list of such sources for a node whose package depends on
    other packages that ship modules. Each named module, the file
    ``<name>.py`` or the folder ``<name>/``, is linked into
    ``<run_dir>/package_modules/`` at its own relative path, and nothing else
    in the sources folder is. A name two sources ship is staged from the first.
    Returns ``{"root": "package_modules", "names": [...]}``, relative to
    *run_dir*, with the names that were staged, or None when none was. A
    module that cannot be staged is left out, and the node's import of it
    fails naming it.
    """
    if not package_modules:
        return None
    sources = package_modules if isinstance(package_modules, list) else [package_modules]
    target = Path(run_dir) / PACKAGE_MODULES_DIR
    staged = []
    for source in sources:
        try:
            root = Path(source["root"]).resolve()
        except (KeyError, TypeError, OSError):
            continue
        if not root.is_dir():
            continue
        for name in source.get("names") or []:
            if name in staged:
                continue
            try:
                module_file = root / f"{name}.py"
                folder = root / name
                linked = False
                if module_file.is_file() and not module_file.is_symlink():
                    target.mkdir(parents=True, exist_ok=True)
                    _link_or_copy(module_file, target / module_file.name)
                    linked = True
                if folder.is_dir() and not folder.is_symlink():
                    _link_tree(folder.resolve(), target / name)
                    linked = True
                if linked:
                    staged.append(name)
            except OSError:
                continue
    return {"root": PACKAGE_MODULES_DIR, "names": staged} if staged else None


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


def persist_output(descriptor, *, node_id=None, session_id=None, exec_uid=None, art_id=None):
    """Write a validated child output descriptor into the artifact store.

    *descriptor* must already have been through
    ``protocol.parse_child_result`` (which is what attaches the checked
    absolute ``path`` to each file-backed entry). Returns the new artifact id:
    *art_id* when the run chose it (``util/output_files.py``).

    File-backed payloads are **moved**, not parsed. The parent never reads a
    parquet a child wrote; it only relocates the bytes and records where they
    went. With an execution account (*exec_uid*), each moved file is then
    taken from the child (:func:`_take_from_child`).
    """
    init_db()
    con = get_connection()
    return _persist(con, descriptor, node_id=node_id, session_id=session_id, exec_uid=exec_uid, art_id=art_id)


#: A file a child wrote, once the store holds it: the sandbox's own, readable
#: by every child it is staged for and writable by none.
STORED_FILE_MODE = 0o644


def _take_from_child(path):
    """Make *path*, a file a child wrote that the store now holds, the
    sandbox's own, at :data:`STORED_FILE_MODE`.

    A move keeps the file's owner, the execution account every child runs as.
    Staged for a later run, as a hardlink sharing its inode, it would let that
    run's node code change an output that other runs and readers take as it
    was made. Only the sandbox running as root can take it, and only then does
    a child run as another account. A file that cannot be taken fails the
    persist rather than stay writable, and is removed: no row names it yet.
    """
    if os.geteuid() != 0:
        return
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fchown(descriptor, os.geteuid(), os.getegid())
            os.fchmod(descriptor, STORED_FILE_MODE)
        finally:
            os.close(descriptor)
    except OSError as exc:
        Path(path).unlink(missing_ok=True)
        raise StagingError(f"could not take {Path(path).name} from the child: {exc}") from exc


def _persist(con, descriptor, *, node_id, session_id, exec_uid=None, art_id=None):
    kind = descriptor["kind"]
    art_id = art_id or _make_id()

    if kind == "outputs":
        child_ids = [
            _persist(con, item, node_id=node_id, session_id=session_id, exec_uid=exec_uid)
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
        if exec_uid is not None:
            _take_from_child(target)
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
        if exec_uid is not None:
            _take_from_child(target)
        # Rasters are stored by path rather than by payload, and load_from_duckdb
        # reopens that path with rasterio. Store it absolute: the in-process path
        # stores whatever the user opened (often relative to the launch dir),
        # which only resolves because the sandbox happens to share that cwd. A
        # child does not, so resolve it once here instead.
        _insert_row(con, art_id, "raster", node_id=node_id, session_id=session_id,
                    value_str=str(target))
        return art_id

    raise StagingError(f"cannot persist output of kind {kind!r}")
