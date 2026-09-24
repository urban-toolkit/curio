"""Filesystem operations for project artifacts.

Every path composed here routes through
:mod:`utk_curio.backend.app.common.safe_paths`, which validates untrusted
segments *and* enforces a proper containment check against the base dir.
Because segment validation rejects ``..`` / path separators before the
filesystem is touched, a traversal attempt like ``project_id="../../etc"``
fails immediately regardless of how deeply the target would have nested
under the users base.

The spec written here is a *trill* document (canonical spec:
``docs/schemas/trill.v1.json``). Note that ``write_spec`` deliberately does not
validate it - the readers downstream are all tolerant of malformed members, and a
save-time gate would reject specs users can currently save. Enforcement lives in
``backend/tests/test_projects/test_trill_schema.py`` and
``scripts/validate_trill.py`` instead.
"""
from __future__ import annotations

import json
import os
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from utk_curio.backend.app.common.file_locks import exclusive_lock

# The two-layer lock (in-process threading lock + cross-process flock) lives in
# ``common.file_locks``; the package seeder needs the identical dance, and one
# implementation means a platform quirk is fixed in one place.
_SPEC_LOCK_NAMESPACE = "spec"

from utk_curio.backend.app.common.safe_paths import (
    PathTraversalError,
    safe_join,
    validate_component,
)
from utk_curio.backend.app.projects.schemas import OutputRef


# Re-exported under the module-private names this file has always used, so the
# ~10 import sites elsewhere are untouched. ``user_storage`` explains why the
# root moves under ``.curio/test/`` for a test rig.
from utk_curio.backend.app.common.user_storage import (
    GUEST_KEY as _GUEST_KEY,
    launch_dir as _launch_dir,
    user_key_segment as _user_key_segment,
    users_base as _users_base,
)


def _shared_data_dir() -> Path:
    rel = os.environ.get("CURIO_SHARED_DATA", "./.curio/data/")
    return (_launch_dir() / rel).resolve()


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


def user_dir(user_key: str) -> Path:
    """The user's own root under ``.curio/users/``."""
    return safe_join(_users_base(), _user_key_segment(user_key), field="user_key")


# ---------------------------------------------------------------------------
# Spec I/O
# ---------------------------------------------------------------------------

#: Where a project's write counter lives (memo dev/124): a one-line file beside
#: the spec rather than a key inside it, for three reasons. A client sends the
#: whole spec, so a key inside it is a number the client can reset — the basis
#: has to be something only the server writes. Reading one small file is
#: cheaper than parsing the previous spec on every write, and every write has
#: to bump it. And it stays invisible to every reader of the spec, so nothing
#: downstream — the trill schema, an export, a copy — grows a field it has no
#: use for.
#:
#: It counts EVERY write, which is the property the ``spec_revision`` column
#: cannot have: that one is bumped by ``repositories.upsert_project``, which
#: runs for a client save and nothing else, so it stays equal across exactly
#: the background writes a client needs to notice (an agent apply, a Solve
#: wave, an install).
SPEC_REVISION_FILE = ".spec.rev"


def spec_revision(user_key: str, project_id: str) -> int:
    """How many times this project's spec has been written.

    ``0`` for a project last written before dev/124, and for one that does not
    exist — both mean "no basis to compare against", which is how the guard
    reads it.
    """
    try:
        path = project_dir(user_key, project_id) / SPEC_REVISION_FILE
    except (PathTraversalError, ValueError):
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0

def _write_json_atomically(path: Path, payload: dict) -> None:
    """Write *payload* so a concurrent reader never sees a half-written file.

    ``Path.write_text`` truncates first and writes second, so any reader that
    arrives between the two gets zero bytes. Readers here take no lock (the
    spec lock serializes writers against writers only), so this is reachable
    from ordinary use: it surfaced as the Agent Catalog 500ing with
    ``Expecting value: line 1 column 1 (char 0)`` while a save was in flight,
    which is ``json.loads("")``.

    A temp file in the SAME directory plus ``os.replace`` makes the swap
    atomic on POSIX and on Windows, so a reader sees either the whole old file
    or the whole new one.
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        # A crash between write and replace would otherwise leave the temp
        # behind; replace() has already consumed it on the happy path.
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def write_spec(user_key: str, project_id: str, spec: dict) -> Path:
    """Persist *spec* and bump the project's write counter.

    The counter is bumped BEFORE the spec is written, so a crash between the
    two leaves it ahead rather than behind: a client is then told its basis is
    stale when it is not, which costs it a reload, where the other order would
    let it silently overwrite the write that did land.
    """
    d = ensure_project_dir(user_key, project_id)
    _bump_spec_revision(d)
    p = d / "spec.trill.json"
    _write_json_atomically(p, spec)
    return p


def _bump_spec_revision(project_dir_path: Path) -> int:
    path = project_dir_path / SPEC_REVISION_FILE
    try:
        current = int(path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        current = 0
    nxt = current + 1
    try:
        path.write_text(f"{nxt}\n", encoding="utf-8")
    except OSError:
        # A counter that cannot be written must not fail the save: the guard
        # reads a missing counter as "no basis", which is today's behaviour.
        return current
    return nxt


def read_spec(user_key: str, project_id: str) -> Optional[dict]:
    d = project_dir(user_key, project_id)
    p = d / "spec.trill.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def list_project_ids(user_key: str) -> list[str]:
    """Project ids (on-disk folder names) that have a saved spec for *user_key*."""
    base = _users_base() / _user_key_segment(user_key) / "projects"
    if not base.is_dir():
        return []
    ids: list[str] = []
    for entry in sorted(base.iterdir()):
        if entry.is_dir() and (entry / "spec.trill.json").is_file():
            ids.append(entry.name)
    return ids


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
    in-process layer alone. Both live in ``common.file_locks``.
    """
    d = ensure_project_dir(user_key, project_id)
    with exclusive_lock(
        d / ".spec.lock",
        namespace=_SPEC_LOCK_NAMESPACE,
        key=f"{user_key}/{project_id}",
    ):
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


def _account_store_computed_file(
    user_key: str,
    project_id: str,
    node_id: str,
) -> Optional[Path]:
    """Resolve a node's computed output in the account store by its deterministic
    dataflow-namespaced dir (``computed.<dataflowId>.<nodeId>@1``).

    Computed outputs are saved to the account store on generation without a
    project ref, so this — not the spec ref — is the authoritative durable copy.
    """
    if not node_id or not project_id:
        return None
    from utk_curio.backend.app.datasets.install.installer import (
        InstallerError,
        computed_dataset_id,
        resolve_installed_data_path,
    )
    from utk_curio.backend.app.common.safe_paths import PathTraversalError
    from utk_curio.backend.app.datasets.domain.manifest import ManifestError, load_dataset_manifest
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

    dir_name = f"{computed_dataset_id(node_id, project_id)}@1"
    try:
        installed_dir = dataset_dir(user_key, dir_name)
        manifest = load_dataset_manifest(installed_dir)
        return resolve_installed_data_path(user_key, manifest)
    except (ManifestError, InstallerError, ValueError, PathTraversalError):
        return None


def installed_dataset_file_for_node(
    user_key: str,
    spec: Optional[dict],
    node_id: str,
) -> Optional[Path]:
    """The installed dataset file *node_id* reads, or ``None``.

    Public name for the resolver :func:`_durable_source_for` uses. The dataset
    installers call it to tell "this node's output IS a dataset the account
    already holds" from "this node computed something new". The first needs no
    computed copy: a reload restores its output from the very dataset the node
    reads, so installing one would leave the user with two rows for one file.
    """
    return _installed_file_for_node(user_key, spec, node_id)


def _durable_source_for(
    user_key: str,
    project_id: str,
    ref: OutputRef,
    *,
    spec: Optional[dict],
) -> Optional[Path]:
    """Resolve *ref* to a DURABLE on-disk source a reload can restore from.

    A source is durable when it survives independently of the shared scratch
    cache: a legacy ``project/data/`` copy, the node's computed output in the
    account store (``computed.<dataflowId>.<nodeId>@1`` — the default home for a
    generated output, no project ref required), or a dataset explicitly
    installed into this dataflow (*spec* ``dataflow.datasets``). The shared cache
    is a global, by-filename dir that gets cleared, so it is intentionally NOT a
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
    account = _account_store_computed_file(user_key, project_id, ref.node_id)
    if account is not None and account.is_file():
        return account
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
    _write_json_atomically(p, manifest)
    return p


def mutate_dataflow_datasets(
    user_key: str,
    project_id: str,
    mutate,
) -> Optional[tuple[dict, bool]]:
    """Atomically read-modify-write ``dataflow.datasets`` (dev/82).

    The dataset endpoints' section writer: under the per-project spec lock,
    re-reads the on-disk spec, hands the dict-filtered current refs to
    *mutate*, and persists the list it returns — so a concurrent mutation of a
    DIFFERENT dataset can never be lost to a stale pre-lock read. Only the
    datasets section is swapped; nodes/edges/agents/packages are untouched.

    *mutate* runs while the spec lock is held: it must be a pure list
    transform (no project I/O, nothing that re-acquires the lock). Returning
    ``None`` means "no change" — nothing is written.

    Returns ``(spec, changed)``, or ``None`` when the project has no spec.
    """
    # Cheap existence check first so we don't create a project dir (and lock
    # file) for a project that doesn't exist.
    if not (project_dir(user_key, project_id) / "spec.trill.json").exists():
        return None
    with spec_write_lock(user_key, project_id):
        spec = read_spec(user_key, project_id)
        if not spec:
            return None
        dataflow = spec.setdefault("dataflow", {})
        current = [r for r in (dataflow.get("datasets") or []) if isinstance(r, dict)]
        new_refs = mutate(current)
        if new_refs is None:
            return spec, False
        dataflow["datasets"] = new_refs
        write_spec(user_key, project_id, spec)
        return spec, True


def replace_dataflow_datasets(
    user_key: str,
    project_id: str,
    refs: list[dict],
) -> Optional[dict]:
    """Replace ``dataflow.datasets`` wholesale (dev/81) — a constant-callback
    :func:`mutate_dataflow_datasets`, kept for whole-list writes (seeding,
    carry-overs) where the caller does not depend on the prior list.
    Returns the written spec, or ``None`` when the project has no spec."""
    result = mutate_dataflow_datasets(user_key, project_id, lambda _current: refs)
    return None if result is None else result[0]


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
