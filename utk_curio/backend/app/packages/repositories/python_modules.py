"""The Python modules a package ships in ``sources/``, beside its templates (#468).

Repositories layer of the packages package: reads package directories.

A template imports these by name while one of the package's nodes runs (the
sandbox stages them for the run, see ``application/python_modules.py``), and
no two installed packages may ship a module of the same top-level name.
"""

from __future__ import annotations

import keyword
from pathlib import Path

from utk_curio.backend.app.packages.domain.manifest import ManifestError, PackageManifest
from utk_curio.backend.app.packages.repositories.archive import InstallerError
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.store import list_user_packages

#: The package folder that holds template sources and the modules they import.
SOURCES_DIR = "sources"


def _importable(name: str) -> bool:
    return name.isidentifier() and not keyword.iskeyword(name)


def _template_sources(manifest: PackageManifest) -> set[str]:
    """The files templates name as their ``source``, relative to ``sources/``."""
    out: set[str] = set()
    for template in manifest.templates:
        parts = [p for p in (template.source or "").replace("\\", "/").split("/") if p]
        if len(parts) > 1 and parts[0] == SOURCES_DIR:
            out.add("/".join(parts[1:]))
    return out


def module_names(package_root: Path, manifest: PackageManifest) -> frozenset[str]:
    """The top-level names a template of this package can import.

    A module is a ``<name>.py`` file in ``sources/``, or a ``<name>/`` folder
    there holding a ``.py`` file at any depth, where ``<name>`` is a Python
    identifier. A file a template names as its ``source`` is that template's
    code, not a module: two packages may each have a ``loader`` template, and
    a template named like a library must not hide that library. Links are not
    followed.
    """
    sources = Path(package_root) / SOURCES_DIR
    if not sources.is_dir() or sources.is_symlink():
        return frozenset()
    templates = _template_sources(manifest)
    names: set[str] = set()
    for entry in sources.iterdir():
        if entry.is_symlink():
            continue
        if entry.is_file():
            if entry.suffix == ".py" and _importable(entry.stem) and entry.name not in templates:
                names.add(entry.stem)
        elif entry.is_dir() and _importable(entry.name):
            if any(
                path.is_file() and not path.is_symlink()
                and path.relative_to(sources).as_posix() not in templates
                for path in entry.rglob("*.py")
            ):
                names.add(entry.name)
    return frozenset(names)


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
