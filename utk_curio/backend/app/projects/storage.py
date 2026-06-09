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
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from utk_curio.backend.app.common.safe_paths import safe_join, validate_component
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
    from utk_curio.backend.app.datasets.output_paths import resolve_shared_output_path

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

    from utk_curio.backend.app.datasets.installer import (
        InstallerError,
        resolve_installed_data_path,
    )
    from utk_curio.backend.app.datasets.manifest import ManifestError, load_dataset_manifest
    from utk_curio.backend.app.datasets.storage import dataset_dir

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
        except (ManifestError, InstallerError, ValueError):
            return None
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
    2. Legacy ``project/data/`` copies from older saves.
    3. User dataset store paths registered in *spec* ``dataflow.datasets``.
    """
    shared = _shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    d = project_dir(user_key, project_id)
    hydrated: List[OutputRef] = []
    for ref in refs:
        validate_component(ref.filename, field="output filename")
        dst = safe_join(shared, ref.filename, validate=False, field="output filename")
        if dst.is_file():
            hydrated.append(ref)
            continue

        legacy_src = safe_join(d / "data", ref.filename, validate=False, field="output filename")
        if legacy_src.is_file():
            shutil.copy2(str(legacy_src), str(dst))
            hydrated.append(ref)
            continue

        installed_src = _installed_file_for_node(user_key, spec, ref.node_id)
        if installed_src is not None and installed_src.is_file():
            shutil.copy2(str(installed_src), str(dst))
            hydrated.append(ref)
    return hydrated


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
