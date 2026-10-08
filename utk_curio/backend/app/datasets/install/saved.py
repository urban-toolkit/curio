"""Install what a node saved with ``curio_save_file`` / ``curio_save_folder``.

The sandbox reports each saved file or folder in the run's
``output["savedFiles"]`` as ``{name, kind, path, file?}``, its files under
``<shared data>/saved/``. Each becomes the computed dataset
``computed.<dataflowId>.files.<name>`` in the account's store, its lineage
naming the node, the dataflow and its name, and replaces the one an earlier
run of it saved. A file keeps its format (csv, json, geojson, parquet,
geotiff, netcdf); a folder is a ``bundle``, its files under ``data/files/``
and listed by ``data/bundle.json``.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utk_curio.backend.app.common.safe_paths import is_within
from utk_curio.backend.app.datasets.domain.manifest import (
    DatasetManifest,
    ManifestError,
    load_dataset_manifest,
    write_manifest,
)
from utk_curio.backend.app.datasets.domain.saved_files import (
    FILE_FORMATS,
    FILES_SEGMENT,
    FOLDER_FILES,
    NAME_RE,
)
from utk_curio.backend.app.datasets.install.installer import (
    InstallerError,
    InstallResult,
    _index,
    _link_or_copy,
    sanitize_node_id_segment,
)
from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir, user_datasets_dir

logger = logging.getLogger(__name__)


def saved_dataset_id(dataflow_id: str, name: str) -> str:
    """``computed.<dataflowSeg>.files.<name>``: the dataset *name* is saved as
    in the dataflow *dataflow_id*."""
    if not NAME_RE.match(name or ""):
        raise ValueError(f"not a saved name: {name!r}")
    return f"{saved_dataset_prefix(dataflow_id)}{name}"


def saved_dataset_prefix(dataflow_id: str) -> str:
    """The id every dataset the dataflow *dataflow_id* saved from code starts with."""
    return f"computed.{sanitize_node_id_segment(dataflow_id)}.{FILES_SEGMENT}."

#: Where the sandbox writes saved files, under the shared data directory.
SAVED_DIRNAME = "saved"


def _saved_root() -> Path:
    from utk_curio.backend.app.datasets.infrastructure.output_paths import _shared_data_dir

    return (_shared_data_dir() / SAVED_DIRNAME).resolve()


def _source(entry: dict) -> Path:
    """The saved file or folder *entry* names, refused unless it sits under
    the shared ``saved/`` folder the sandbox writes to."""
    root = _saved_root()
    path = Path(str(entry.get("path") or "")).resolve()
    if not is_within(path, root) or path == root:
        raise InstallerError(f"saved file {entry.get('name')!r} is not in the sandbox's saved folder")
    return path


def install_saved_files(
    user_key: str,
    entries: list,
    *,
    dataflow_id: str,
    node_id: str | None,
    node_type: str | None = None,
    dataflow_name: str | None = None,
) -> list[dict[str, Any]]:
    """Install each of a run's saved *entries*; returns ``{id, name, kind,
    status, reason?}`` for each. One that cannot be installed is reported,
    never raised: the node's run itself succeeded."""
    results: list[dict[str, Any]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "")
        try:
            if not NAME_RE.match(name):
                raise InstallerError(f"not a saved name: {name!r}")
            result = _install_one(
                user_key, entry, name,
                dataflow_id=dataflow_id, node_id=node_id,
                node_type=node_type, dataflow_name=dataflow_name,
            )
            results.append({
                "id": result.manifest.id, "dirName": result.manifest.dir_name,
                "name": name, "kind": entry.get("kind"), "status": "installed",
            })
        except (InstallerError, OSError, ValueError) as exc:
            logger.warning("Could not install saved file %r of node %s: %s", name, node_id, exc)
            results.append({"name": name, "kind": entry.get("kind"), "status": "failed", "reason": str(exc)})
    _remove_run_folders(entries)
    return results


def _install_one(user_key, entry, name, *, dataflow_id, node_id, node_type, dataflow_name) -> InstallResult:
    source = _source(entry)
    dataset_id = saved_dataset_id(dataflow_id, name)
    dest = dataset_dir(user_key, f"{dataset_id}@1")
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    data = dest / "data"
    data.mkdir(parents=True, exist_ok=True)

    kind = entry.get("kind")
    if kind == "file":
        if not source.is_file():
            raise InstallerError(f"saved file {name!r} was not written")
        ext = source.suffix.lstrip(".").lower()
        fmt = FILE_FORMATS.get(ext)
        if fmt is None or source.stem != name:
            raise InstallerError(f"saved file {source.name!r} is not {name}.<{'|'.join(FILE_FORMATS)}>")
        _link_or_copy(source, data / source.name)
        data_file = f"data/{source.name}"
        description = f"{fmt.upper()} file a node of this dataflow saved as {name}."
        schema = None
    elif kind == "folder":
        if not source.is_dir():
            raise InstallerError(f"saved folder {name!r} was not written")
        parts = []
        for index, path in enumerate(sorted(p for p in source.rglob("*") if p.is_file() and not p.is_symlink())):
            relative = path.relative_to(source)
            target = data / FOLDER_FILES / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            _link_or_copy(path, target)
            parts.append({
                "index": index,
                "label": relative.as_posix(),
                "kind": "file",
                "format": FILE_FORMATS.get(path.suffix.lstrip(".").lower(), path.suffix.lstrip(".").lower() or "file"),
                "file": f"data/{FOLDER_FILES}/{relative.as_posix()}",
            })
        (data / FOLDER_FILES).mkdir(exist_ok=True)
        (data / "bundle.json").write_text(json.dumps({"version": 1, "parts": parts}, indent=2), encoding="utf-8")
        fmt = "bundle"
        data_file = "data/bundle.json"
        description = f"A folder of {len(parts)} files a node of this dataflow saved as {name}."
        schema = {
            "fields": [{"name": "files", "type": "integer", "nullable": False, "sample": len(parts)}],
            "bundleParts": [{"label": p["label"], "format": p["format"], "kind": p["kind"]} for p in parts[:50]],
        }
    else:
        raise InstallerError(f"saved entry {name!r} is neither a file nor a folder")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = DatasetManifest(
        id=dataset_id,
        name=name,
        version="1.0.0",
        format=fmt,
        description=description,
        publisher="User",
        license="",
        tags=[fmt, "computed", "saved"],
        data_file=data_file,
        major=1,
        source_label="Computed",
        created_at=now,
        updated_at=now,
        row_count=None,
        feature_count=None,
        schema=schema,
        producer_node_id=node_id,
        producer_node_type=node_type,
        producer_dataflow_id=dataflow_id,
        producer_dataflow_name=dataflow_name,
        upstream_inputs=None,
    )
    write_manifest(manifest, dest)
    try:
        loaded = load_dataset_manifest(dest)
    except ManifestError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise InstallerError(f"Failed to write the manifest of saved {name!r}: {exc}") from exc
    return _index(user_key, InstallResult(manifest=loaded, dest=dest, replaced=True))


def _remove_run_folders(entries) -> None:
    """Remove the run folders the sandbox wrote the entries in, once installed:
    ``saved/<run>/``, the parent of each entry's ``<name>`` folder."""
    root = _saved_root()
    runs = set()
    for entry in entries if isinstance(entries, list) else []:
        try:
            path = Path(str(entry.get("path") or "")).resolve()
        except (OSError, AttributeError):
            continue
        for parent in path.parents:
            if parent.parent == root:
                runs.add(parent)
                break
    for run in runs:
        shutil.rmtree(run, ignore_errors=True)


def remove_saved_datasets(user_key: str, dataflow_id: str) -> int:
    """Delete every dataset the dataflow *dataflow_id* saved from code: what a
    deleted dataflow takes with it. Returns how many."""
    prefix = saved_dataset_prefix(dataflow_id)
    root = user_datasets_dir(user_key)
    removed = 0
    if not root.is_dir():
        return 0
    for folder in root.iterdir():
        if folder.is_dir() and folder.name.startswith(prefix):
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    if removed:
        _forget_in_index(user_key, prefix)
    return removed


def _forget_in_index(user_key: str, prefix: str) -> None:
    from utk_curio.backend.app.datasets.repositories import index as index_repo

    try:
        index_repo.safe_sync_rows_by_dir(user_key)
    except Exception:  # noqa: BLE001 - the index re-syncs from disk on its next read
        logger.debug("dataset index resync after removing %s* failed", prefix, exc_info=True)
