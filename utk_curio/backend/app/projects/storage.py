"""Filesystem operations for project artifacts.

Every path composed here routes through
:mod:`utk_curio.backend.app.common.safe_paths`, which validates untrusted
segments *and* enforces a proper containment check against the base dir.
Because segment validation rejects ``..`` / path separators before the
filesystem is touched, a traversal attempt like ``project_id="../../etc"``
fails immediately regardless of how deeply the target would have nested
under the users base.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:  # POSIX advisory file locking; unavailable on Windows.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

try:  # Windows mandatory file locking; unavailable on POSIX.
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows fallback
    msvcrt = None


# Per-(user, project) in-process locks. flock guards cross-PROCESS contention but
# is a no-op on Windows; this threading lock serializes same-process threads
# (the common Flask-threaded case) on every platform, so a concurrent spec
# read-modify-write doesn't lost-update even where fcntl is absent.
_spec_locks: "Dict[str, threading.Lock]" = {}
_spec_locks_guard = threading.Lock()


def _spec_thread_lock(user_key: str, project_id: str) -> "threading.Lock":
    key = f"{user_key}/{project_id}"
    with _spec_locks_guard:
        lock = _spec_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _spec_locks[key] = lock
        return lock

from utk_curio.backend.app.common.safe_paths import (
    PathTraversalError,
    safe_join,
    validate_component,
)
from utk_curio.backend.app.projects.schemas import OutputRef


def _launch_dir() -> Path:
    return Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd()))


def _shared_data_dir() -> Path:
    rel = os.environ.get("CURIO_SHARED_DATA", "./.curio/data/")
    return (_launch_dir() / rel).resolve()


def _users_base() -> Path:
    return (_launch_dir() / ".curio" / "users").resolve()


_GUEST_KEY = "guest"


def _user_key_segment(user_key: str) -> str:
    """Return the directory segment for a user.

    Accepts either a digit-only string (regular user IDs) or the fixed
    guest sentinel ``'guest'``.  Raises ``ValueError`` for anything else.
    """
    if user_key == _GUEST_KEY or user_key.isdigit():
        return user_key
    raise ValueError(f"Invalid user key for storage: {user_key!r}")


# ---------------------------------------------------------------------------
# Directory management
# ---------------------------------------------------------------------------

def project_dir(user_key: str, project_id: str) -> Path:
    return safe_join(
        _users_base(),
        _user_key_segment(user_key),
        "projects",
        project_id,
        field="project_id",
    )


def ensure_project_dir(user_key: str, project_id: str) -> Path:
    d = project_dir(user_key, project_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "data").mkdir(exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Spec I/O
# ---------------------------------------------------------------------------

def write_spec(user_key: str, project_id: str, spec: dict) -> Path:
    d = ensure_project_dir(user_key, project_id)
    p = d / "spec.trill.json"
    p.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return p


def read_spec(user_key: str, project_id: str) -> Optional[dict]:
    d = project_dir(user_key, project_id)
    p = d / "spec.trill.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


@contextmanager
def spec_write_lock(user_key: str, project_id: str):
    """Serialize read-modify-write of a project's spec across processes.

    Two concurrent saves that both upsert into ``dataflow.datasets`` would
    otherwise race — each reads the spec, mutates its own copy, and the last
    writer clobbers the other's ref (lost update). An exclusive ``flock`` on a
    per-project lock file makes the read+merge+write critical section atomic.

    Serialization has two layers: an in-process threading lock (all platforms,
    same-process threads) and a cross-process file lock (POSIX ``flock`` or, on
    Windows, ``msvcrt.locking``). Only a platform with neither falls back to the
    in-process layer alone.
    """
    d = ensure_project_dir(user_key, project_id)
    lock_path = d / ".spec.lock"
    thread_lock = _spec_thread_lock(user_key, project_id)
    thread_lock.acquire()
    try:
        with _interprocess_spec_lock(lock_path):
            yield
    finally:
        thread_lock.release()


@contextmanager
def _interprocess_spec_lock(lock_path: Path):
    """Best-effort exclusive cross-process lock on *lock_path*.

    POSIX uses ``fcntl.flock``; Windows uses ``msvcrt.locking`` (the previous
    fcntl-only path skipped Windows entirely, leaving multi-process Windows
    saves racing). On the rare platform with neither, the caller's in-process
    threading lock is the only guard and this is a no-op.
    """
    if fcntl is not None:
        with open(lock_path, "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
    elif msvcrt is not None:  # pragma: no cover - exercised only on Windows
        # Lock a 1-byte region at offset 0 to get a cross-process mutex like
        # flock(LOCK_EX). Unlike flock, ``LK_LOCK`` only retries internally for
        # ~10s and then raises OSError; under sustained contention (e.g. a
        # Play-All install racing a save) that uncaught OSError would propagate
        # out to an HTTP 500. Re-issue the blocking lock until it is acquired so
        # the waiter blocks indefinitely like the POSIX path instead of failing
        # the save (#144).
        with open(lock_path, "a+") as handle:
            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    # The ~10s window elapsed without the region freeing; the
                    # call already blocked, so loop straight back into another
                    # blocking attempt (no busy-spin).
                    continue
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:  # pragma: no cover - neither POSIX nor Windows locking available
        yield


# ---------------------------------------------------------------------------
# Output copy / hydration
# ---------------------------------------------------------------------------

def copy_outputs(
    user_key: str,
    project_id: str,
    refs: List[OutputRef],
) -> List[OutputRef]:
    """Copy output files from shared cache into ``project/data/`` (legacy).

    Project save no longer uses this — computed outputs are installed under
    ``users/<user>/datasets/`` and registered in ``spec.trill.json`` instead.
    Kept for tests and one-off migration tooling.

    Returns only the refs that were successfully copied (missing source files
    are skipped so partial saves stay self-consistent).
    """
    from utk_curio.backend.app.datasets.infrastructure.output_paths import resolve_shared_output_path

    d = ensure_project_dir(user_key, project_id)
    copied: List[OutputRef] = []
    for ref in refs:
        validate_component(ref.filename, field="output filename")
        src = resolve_shared_output_path(
            ref.filename,
            data_type=getattr(ref, "data_type", None),
        )
        if src is None:
            continue
        dst = safe_join(d / "data", ref.filename, validate=False, field="output filename")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        copied.append(ref)
    return copied


def _installed_file_for_node(
    user_key: str,
    spec: Optional[dict],
    node_id: str,
) -> Optional[Path]:
    """Resolve an installed dataset file for *node_id* from ``spec.dataflow.datasets``."""
    if not spec or not node_id:
        return None
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict):
        return None

    from utk_curio.backend.app.datasets.install.installer import (
        InstallerError,
        resolve_installed_data_path,
    )
    from utk_curio.backend.app.common.safe_paths import PathTraversalError
    from utk_curio.backend.app.datasets.domain.manifest import ManifestError, load_dataset_manifest
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

    for ds_ref in dataflow.get("datasets") or []:
        if not isinstance(ds_ref, dict):
            continue
        if ds_ref.get("producerNodeId") != node_id:
            continue
        dir_name = ds_ref.get("dirName")
        if not dir_name:
            continue
        try:
            installed_dir = dataset_dir(user_key, dir_name)
            manifest = load_dataset_manifest(installed_dir)
            return resolve_installed_data_path(user_key, manifest)
        except (ManifestError, InstallerError, ValueError, PathTraversalError):
            # A stale/broken/crafted ref for this producer shouldn't abort the
            # search (or 500 the whole project load) — a later ref (e.g. a
            # freshly re-installed output) may still resolve. PathTraversalError
            # is a PermissionError, so it must be named explicitly here.
            continue
    return None


def _durable_source_for(
    user_key: str,
    project_id: str,
    ref: OutputRef,
    *,
    spec: Optional[dict],
) -> Optional[Path]:
    """Resolve *ref* to a DURABLE on-disk source a reload can restore from.

    A source is durable when it survives independently of the shared scratch
    cache: a legacy ``project/data/`` copy, or an installed dataset in the user
    store (registered in *spec* ``dataflow.datasets``). The shared cache is a
    global, by-filename dir that gets cleared, so it is intentionally NOT a
    durable source — it's only a hydrate fast-path.

    This is the single definition of "durable" shared by :func:`hydrate_outputs`
    (which copies the source into the cache) and :func:`persisted_output_refs`
    (which keeps a ref iff a durable source exists). Keeping one resolver stops
    the persist filter and the hydrate path from drifting apart — e.g. a future
    durable source added to one but not the other would otherwise let save drop
    an output reload could restore, or record one it can't.

    Assumes ``ref.filename`` has already been validated by the caller (it is
    joined with ``validate=False``). Returns the source ``Path`` or ``None``.
    """
    d = project_dir(user_key, project_id)
    legacy = safe_join(d / "data", ref.filename, validate=False, field="output filename")
    if legacy.is_file():
        return legacy
    installed = _installed_file_for_node(user_key, spec, ref.node_id)
    if installed is not None and installed.is_file():
        return installed
    return None


def hydrate_outputs(
    user_key: str,
    project_id: str,
    refs: List[OutputRef],
    *,
    spec: Optional[dict] = None,
) -> List[OutputRef]:
    """Copy persisted outputs into the shared cache so sandbox ``/get`` works.

    Sources (first match wins):
    1. Already present in shared data (current session).
    2. A durable source (legacy ``project/data/`` copy or installed dataset) —
       see :func:`_durable_source_for`.
    """
    shared = _shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    hydrated: List[OutputRef] = []
    for ref in refs:
        validate_component(ref.filename, field="output filename")
        dst = safe_join(shared, ref.filename, validate=False, field="output filename")
        if dst.is_file():
            hydrated.append(ref)
            continue

        source = _durable_source_for(user_key, project_id, ref, spec=spec)
        if source is not None:
            shutil.copy2(str(source), str(dst))
            hydrated.append(ref)
    return hydrated


def persisted_output_refs(
    user_key: str,
    project_id: str,
    refs: List[OutputRef],
    *,
    spec: Optional[dict] = None,
) -> List[OutputRef]:
    """Subset of *refs* that a later reload can restore from a DURABLE source.

    ``hydrate_outputs`` resolves an output from one of three places: the shared
    scratch cache, a legacy ``project/data`` copy, or an installed dataset in the
    user store (via *spec* ``dataflow.datasets``). The shared cache is a global,
    by-filename scratch dir that gets cleared and is not a per-project guarantee,
    so it is intentionally *excluded* here: an output backed only by the cache
    silently vanishes once it's evicted.

    The manifest must therefore record only outputs backed by a legacy copy or an
    installed dataset. Recording the raw client list instead lets a swallowed
    auto-install error (or a pruned sink-node dataset) leave a phantom entry the
    manifest claims exists but reload can never restore (issue #144).
    """
    kept: List[OutputRef] = []
    for ref in refs:
        try:
            validate_component(ref.filename, field="output filename")
        except PathTraversalError:
            # An unsafe filename (separator/traversal or a char outside the
            # safe set) can never be durably persisted — the load-path
            # resolvers reject it the same way — so drop it from the manifest
            # instead of letting PathTraversalError (a PermissionError, which
            # the save routes don't catch) bubble up as an HTTP 500 (#144).
            continue
        if _durable_source_for(user_key, project_id, ref, spec=spec) is not None:
            kept.append(ref)
    return kept


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def write_manifest(
    user_key: str,
    project_id: str,
    spec_revision: int,
    refs: List[OutputRef],
    *,
    name: str = "",
    description: Optional[str] = None,
    thumbnail_accent: str = "peach",
) -> Path:
    d = ensure_project_dir(user_key, project_id)
    p = d / "manifest.json"
    entries: List[Dict] = []
    data_dir = d / "data"
    for ref in refs:
        fp = data_dir / ref.filename
        entry: Dict = {"node_id": ref.node_id, "filename": ref.filename}
        if getattr(ref, "data_type", None):
            entry["data_type"] = ref.data_type
        if fp.exists():
            stat = fp.stat()
            entry["size"] = stat.st_size
            entry["mtime"] = stat.st_mtime
        entries.append(entry)
    manifest = {
        "project_id": project_id,
        "user_id": user_key,
        "name": name,
        "description": description,
        "thumbnail_accent": thumbnail_accent,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "spec_revision": spec_revision,
        "outputs": entries,
    }
    p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return p


def merge_dataflow_dataset_ref(
    user_key: str,
    project_id: str,
    ref: dict,
) -> bool:
    """Upsert one lean dataset ref into ``spec.trill.json`` ``dataflow.datasets``.

    Returns True when the spec was updated, False when the project spec is missing.
    """
    # Cheap existence check first so we don't create a project dir (and lock
    # file) for a project that doesn't exist.
    if not (project_dir(user_key, project_id) / "spec.trill.json").exists():
        return False
    # Hold the per-project lock across read+merge+write so a concurrent upsert
    # can't clobber the ref we're adding (lost update).
    with spec_write_lock(user_key, project_id):
        spec = read_spec(user_key, project_id)
        if not spec:
            return False
        dataflow = spec.setdefault("dataflow", {})
        refs: list[dict] = list(dataflow.get("datasets") or [])
        dataset_id = ref.get("datasetId")
        producer = ref.get("producerNodeId")
        updated = False
        for index, existing in enumerate(refs):
            if not isinstance(existing, dict):
                continue
            if (
                (dataset_id and existing.get("datasetId") == dataset_id)
                or (producer and existing.get("producerNodeId") == producer)
            ):
                refs[index] = {**existing, **ref}
                updated = True
                break
        if not updated:
            refs.append(ref)
        dataflow["datasets"] = refs
        write_spec(user_key, project_id, spec)
        return True


def read_manifest(
    user_key: str, project_id: str
) -> Optional[dict]:
    d = project_dir(user_key, project_id)
    p = d / "manifest.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------

def delete_tree(user_key: str, project_id: str) -> None:
    d = project_dir(user_key, project_id)
    if d.exists():
        shutil.rmtree(d)
