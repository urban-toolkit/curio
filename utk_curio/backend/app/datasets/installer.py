"""Install datasets from the shared catalog into a user's dataset store."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from utk_curio.backend.app.datasets.manifest import (
    DatasetManifest,
    ManifestError,
    load_dataset_manifest,
    write_manifest,
)
from utk_curio.backend.app.common.safe_paths import PathTraversalError, validate_component
from utk_curio.backend.app.datasets.catalog_utils import title_from_filename
from utk_curio.backend.app.datasets.storage import catalog_root, dataset_dir


def _validate_store_filename(safe_filename: str) -> str:
    """Reject an output/store filename that isn't a single safe path segment.

    The data file is written to ``<dataset dir>/data/<safe_filename>``; an
    untrusted node-output ref (e.g. ``../../../../etc/foo``) must never escape
    the user's datasets dir. Maps a traversal attempt to ``InstallerError`` so
    callers surface a clean 4xx / skip the bad output rather than 500.
    """
    try:
        return validate_component(safe_filename, field="output filename")
    except PathTraversalError as exc:
        raise InstallerError(str(exc)) from exc

logger = logging.getLogger(__name__)


class InstallerError(Exception):
    """Raised when a dataset install fails."""


@dataclass(frozen=True)
class InstallResult:
    manifest: DatasetManifest
    dest: Path
    replaced: bool


def _is_installed(user_key: str, dir_name: str) -> bool:
    return (dataset_dir(user_key, dir_name) / "manifest.json").is_file()


def install_dataset_from_catalog(
    user_key: str,
    dir_name: str,
    *,
    replace: bool = False,
) -> InstallResult:
    """Copy ``<repo_root>/datasets/<dirName>/`` into the user's dataset store."""
    src = catalog_root() / dir_name
    if not src.is_dir():
        raise InstallerError(f"catalog has no dataset {dir_name}")

    try:
        manifest = load_dataset_manifest(src)
    except ManifestError as exc:
        raise InstallerError(str(exc)) from exc

    dest = dataset_dir(user_key, dir_name)
    replaced = False
    if dest.exists():
        # Check whether the existing install is complete (data file is present).
        # A previous failed copy can leave a partial directory behind, so we
        # treat any incomplete destination the same as a missing one.
        data_file = dest / manifest.data_file
        install_is_complete = data_file.is_file()
        if install_is_complete and not replace:
            return InstallResult(manifest=manifest, dest=dest, replaced=False)
        # Either replace was requested or the previous install was incomplete –
        # remove the stale/partial directory and start fresh.
        shutil.rmtree(dest)
        replaced = True

    try:
        shutil.copytree(src, dest)
    except shutil.Error as exc:
        # copytree() raises shutil.Error (collecting per-file errors) even when
        # individual files fail to copy.  Clean up the partial destination so
        # that the next install attempt can start from scratch.
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise InstallerError(f"Failed to copy dataset files: {exc}") from exc

    return InstallResult(manifest=load_dataset_manifest(dest), dest=dest, replaced=replaced)


def resolve_installed_data_path(user_key: str, manifest: DatasetManifest) -> Path:
    root = dataset_dir(user_key, manifest.dir_name)
    data_path = (root / manifest.data_file).resolve()
    if not data_path.is_file():
        raise InstallerError(f"installed dataset is missing data file {manifest.data_file!r}")
    return data_path


def _sanitize_node_id_segment(node_id: str) -> str:
    """Convert an arbitrary node ID to a valid single-segment string for a dataset dir name.

    Rules (matching ``DATASET_DIR_RE`` segment constraints):
    - Lowercase, replace any non-``[a-z0-9-]`` character with ``-``.
    - Collapse consecutive hyphens and strip leading/trailing hyphens.
    - Truncate to 62 characters (leaving room for mandatory leading letter).
    - Prefix with ``n`` if the result does not start with a letter.
    """
    import re as _re
    seg = _re.sub(r"[^a-z0-9-]", "-", node_id.lower())
    seg = _re.sub(r"-+", "-", seg).strip("-")[:62]
    if not seg or not seg[0].isalpha():
        seg = ("n" + seg)[:63]
    return seg or "node"


# Public alias for use outside this module (e.g. service.py).
sanitize_node_id_segment = _sanitize_node_id_segment


def _link_or_copy(src: Path, dest: Path) -> None:
    """Materialize *dest* from *src* cheaply.

    Hard-links when ``src`` and ``dest`` share a filesystem — avoiding a
    full-file byte copy on the synchronous install path. Computed outputs are
    write-once, so a shared inode is safe and actually keeps the dataset alive
    if the shared-data source is later garbage-collected. Falls back to a copy
    across filesystems or when linking is unsupported (e.g. some Windows setups).
    """
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def install_computed_file_for_node(
    user_key: str,
    file_bytes: bytes | None,
    safe_filename: str,
    fmt: str,
    *,
    node_id: str,
    title: str | None = None,
    source_path: Path | None = None,
) -> InstallResult:
    """Save a node-computed output into the user's dataset store keyed by *node_id*.

    Uses ``computed.<sanitized_node_id>@1`` so re-executing the same node always
    replaces the same dataset folder, keeping a stable dataset identity across
    multiple executions.  The destination is always (re-)written — no fast-path
    skip — so that the latest execution's file is always reflected.

    Provide *source_path* to materialize the data file by hard-linking the
    on-disk artifact (no full-file copy / no read into memory); *file_bytes* is
    used otherwise. Exactly one must be supplied.
    """
    seg = _sanitize_node_id_segment(node_id)
    dataset_id = f"computed.{seg}"
    dir_name = f"{dataset_id}@1"

    dest = dataset_dir(user_key, dir_name)

    # Always replace so the folder reflects the latest execution.
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "data").mkdir(exist_ok=True)

    safe_filename = _validate_store_filename(safe_filename)
    data_path = dest / "data" / safe_filename
    if source_path is not None:
        _link_or_copy(source_path, data_path)
        # Carry the parquet object-column decode sidecar (if any) alongside the
        # data file so the installed dataset round-trips object columns. Distinct
        # suffix from file_meta's ``.meta.json`` counts sidecar (see parsers).
        from utk_curio.sandbox.util.parsers import PARQUET_DECODE_SIDECAR_SUFFIX
        src_sidecar = source_path.with_name(source_path.name + PARQUET_DECODE_SIDECAR_SUFFIX)
        if src_sidecar.is_file():
            _link_or_copy(
                src_sidecar,
                data_path.with_name(data_path.name + PARQUET_DECODE_SIDECAR_SUFFIX),
            )
    elif file_bytes is not None:
        data_path.write_bytes(file_bytes)
    else:
        raise InstallerError("install_computed_file_for_node requires file_bytes or source_path")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    display_title = title or title_from_filename(safe_filename)
    manifest_obj = DatasetManifest(
        id=dataset_id,
        name=display_title,
        version="1.0.0",
        format=fmt,
        description=f"{fmt.upper()} dataset computed by a dataflow node.",
        publisher="User",
        license="",
        tags=[fmt, "computed"],
        data_file=f"data/{safe_filename}",
        major=1,
        source_label="Computed",
        created_at=now,
        updated_at=now,
        row_count=None,
        feature_count=None,
        schema=None,
    )
    write_manifest(manifest_obj, dest)

    try:
        manifest = load_dataset_manifest(dest)
    except ManifestError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise InstallerError(f"Failed to create computed dataset manifest: {exc}") from exc

    return InstallResult(manifest=manifest, dest=dest, replaced=True)


def install_computed_file(
    user_key: str,
    file_bytes: bytes,
    safe_filename: str,
    fmt: str,
    *,
    title: str | None = None,
    node_id: str | None = None,
    replace: bool = False,
) -> InstallResult:
    """Save a node-computed output file into the user's dataset store.

    Similar to :func:`install_imported_file` but uses the ``computed.x{hash}@1``
    naming convention so computed datasets are visually distinct from user-uploaded
    imports.  The *node_id* is stored in the manifest tags for provenance.

    .. deprecated::
        Prefer :func:`install_computed_file_for_node` which keys the dataset
        folder on *node_id* so re-execution replaces the same folder.
    """
    hash_hex = hashlib.sha256(file_bytes).hexdigest()[:8]
    dataset_id = f"computed.x{hash_hex}"
    dir_name = f"{dataset_id}@1"

    dest = dataset_dir(user_key, dir_name)

    # Fast path: already fully installed and no replacement requested.
    if dest.exists() and not replace:
        try:
            manifest = load_dataset_manifest(dest)
            if (dest / manifest.data_file).is_file():
                return InstallResult(manifest=manifest, dest=dest, replaced=False)
        except ManifestError:
            # Corrupt or incomplete prior install; remove and reinstall below.
            logger.debug(
                "Corrupt or incomplete prior install at %s; reinstalling",
                dest,
                exc_info=True,
            )
        shutil.rmtree(dest, ignore_errors=True)

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "data").mkdir(exist_ok=True)

    safe_filename = _validate_store_filename(safe_filename)
    data_path = dest / "data" / safe_filename
    data_path.write_bytes(file_bytes)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    display_title = title or title_from_filename(safe_filename)
    manifest_obj = DatasetManifest(
        id=dataset_id,
        name=display_title,
        version="1.0.0",
        format=fmt,
        description=f"{fmt.upper()} dataset computed by a dataflow node.",
        publisher="User",
        license="",
        tags=[fmt, "computed"],
        data_file=f"data/{safe_filename}",
        major=1,
        source_label="Computed",
        created_at=now,
        updated_at=now,
        row_count=None,
        feature_count=None,
        schema=None,
    )
    write_manifest(manifest_obj, dest)

    try:
        manifest = load_dataset_manifest(dest)
    except ManifestError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise InstallerError(f"Failed to create computed dataset manifest: {exc}") from exc

    return InstallResult(manifest=manifest, dest=dest, replaced=True)


def install_imported_file(
    user_key: str,
    file_bytes: bytes,
    safe_filename: str,
    fmt: str,
    *,
    title: str | None = None,
    replace: bool = False,
) -> InstallResult:
    """Save an uploaded file into the user's dataset store with a generated manifest.

    The dataset folder name is derived from a SHA-256 hash of the file content,
    so re-uploading the same file returns the existing install.
    """
    hash_hex = hashlib.sha256(file_bytes).hexdigest()[:8]
    # The dir-name regex requires each dot-segment to start with [a-z].
    # Prefix with 'x' to guarantee a letter-first segment regardless of the hash.
    dataset_id = f"imported.x{hash_hex}"
    dir_name = f"{dataset_id}@1"

    dest = dataset_dir(user_key, dir_name)

    # Fast path: already fully installed and no replacement requested.
    if dest.exists() and not replace:
        try:
            manifest = load_dataset_manifest(dest)
            if (dest / manifest.data_file).is_file():
                return InstallResult(manifest=manifest, dest=dest, replaced=False)
        except ManifestError:
            # Corrupt or incomplete prior install; remove and reinstall below.
            logger.debug(
                "Corrupt or incomplete prior install at %s; reinstalling",
                dest,
                exc_info=True,
            )
        shutil.rmtree(dest, ignore_errors=True)

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "data").mkdir(exist_ok=True)

    # Write the data file.
    data_path = dest / "data" / safe_filename
    data_path.write_bytes(file_bytes)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    display_title = title or title_from_filename(safe_filename)
    manifest_obj = DatasetManifest(
        id=dataset_id,
        name=display_title,
        version="1.0.0",
        format=fmt,
        description=f"{fmt.upper()} dataset imported by the user.",
        publisher="User",
        license="",
        tags=[fmt, "imported"],
        data_file=f"data/{safe_filename}",
        major=1,
        source_label="Imported",
        created_at=now,
        updated_at=now,
        row_count=None,
        feature_count=None,
        schema=None,
    )
    write_manifest(manifest_obj, dest)

    try:
        manifest = load_dataset_manifest(dest)
    except ManifestError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise InstallerError(f"Failed to create imported dataset manifest: {exc}") from exc

    return InstallResult(manifest=manifest, dest=dest, replaced=dest.exists())


