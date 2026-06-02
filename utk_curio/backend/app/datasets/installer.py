"""Install datasets from the shared catalog into a user's dataset store."""

from __future__ import annotations

import hashlib
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
from utk_curio.backend.app.datasets.storage import catalog_root, dataset_dir


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
            pass
        shutil.rmtree(dest, ignore_errors=True)

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "data").mkdir(exist_ok=True)

    # Write the data file.
    data_path = dest / "data" / safe_filename
    data_path.write_bytes(file_bytes)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    display_title = title or (
        Path(safe_filename).stem.replace("_", " ").replace("-", " ").strip().title()
        or safe_filename
    )
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


