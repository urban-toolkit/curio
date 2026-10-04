"""The Python modules an installed package ships in ``sources/``, beside its
templates (#468).

Repositories layer of the packages package: reads package directories. What
counts as a module is ``domain/python_modules.py``. A template imports these
by name while one of the package's nodes runs (the sandbox stages them for the
run, see ``application/python_modules.py``), and no two installed packages may
ship a module of the same top-level name.
"""

from __future__ import annotations

import os
from pathlib import Path

from utk_curio.backend.app.packages.domain.manifest import ManifestError, PackageManifest
from utk_curio.backend.app.packages.domain.python_modules import SOURCES_DIR, module_names_in
from utk_curio.backend.app.packages.repositories.archive import InstallerError
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.store import list_user_packages

__all__ = ["SOURCES_DIR", "module_names", "refuse_a_module_name_in_use"]


def _source_files(package_root: Path) -> list[str]:
    """The regular files under ``sources/``, as package-relative paths. Links
    are not followed."""
    sources = package_root / SOURCES_DIR
    if sources.is_symlink() or not sources.is_dir():
        return []
    out: list[str] = []
    for folder, _dirs, files in os.walk(sources):
        for name in files:
            path = Path(folder) / name
            if path.is_file() and not path.is_symlink():
                out.append(path.relative_to(package_root).as_posix())
    return out


def module_names(package_root: Path, manifest: PackageManifest) -> frozenset[str]:
    """The top-level names a template of the package at *package_root* can
    import (``domain.python_modules.module_names_in``)."""
    package_root = Path(package_root)
    return module_names_in(
        _source_files(package_root), [template.source for template in manifest.templates],
    )


def refuse_a_module_name_in_use(user_key: str, package_root: Path, manifest: PackageManifest) -> None:
    """Raise :class:`InstallerError` when the package at *package_root* ships a
    module another package in *user_key*'s store ships, naming both packages
    and the module.

    The package's own other majors are not another package: a node runs with
    its own package's modules only, so two majors of one package can keep the
    same module names. The installer calls this under the store lock.
    """
    names = module_names(package_root, manifest)
    if not names:
        return
    for path in list_user_packages(user_key):
        if path.name.rsplit("@", 1)[0] == manifest.package_id:
            continue
        try:
            other = load_package_manifest(path)
        except (ManifestError, OSError):
            continue
        shared = sorted(names & module_names(path, other))
        if shared:
            raise InstallerError(
                f"package {manifest.dir_name} ships the Python module {shared[0]!r}, which the "
                f"installed package {path.name} also ships. Two installed packages cannot ship "
                f"a module of the same name: rename the module in one of them, or remove "
                f"{path.name} first."
            )
