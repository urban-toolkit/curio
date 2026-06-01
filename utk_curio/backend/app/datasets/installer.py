"""Install datasets from the shared catalog into a user's dataset store."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from utk_curio.backend.app.datasets.manifest import DatasetManifest, ManifestError, load_dataset_manifest
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
        if not replace:
            return InstallResult(manifest=manifest, dest=dest, replaced=False)
        shutil.rmtree(dest)
        replaced = True

    shutil.copytree(src, dest)
    return InstallResult(manifest=load_dataset_manifest(dest), dest=dest, replaced=replaced)


def resolve_installed_data_path(user_key: str, manifest: DatasetManifest) -> Path:
    root = dataset_dir(user_key, manifest.dir_name)
    data_path = (root / manifest.data_file).resolve()
    if not data_path.is_file():
        raise InstallerError(f"installed dataset is missing data file {manifest.data_file!r}")
    return data_path
