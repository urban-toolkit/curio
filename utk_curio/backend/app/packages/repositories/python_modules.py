"""The Python modules an installed package ships in ``sources/``, beside its
templates (#468).

Repositories layer of the packages package: reads one package directory. What
counts as a module is ``domain/python_modules.py``. A template imports these
by name while one of the package's nodes runs (the sandbox stages them for the
run, see ``application/python_modules.py``), and the installer refuses a second
package that ships a module of the same name (``application/store_install.py``).
"""

from __future__ import annotations

import keyword
import os
from pathlib import Path

from utk_curio.backend.app.packages.domain.manifest import PackageManifest
from utk_curio.backend.app.packages.domain.python_modules import SOURCES_DIR, module_names_in

__all__ = ["SOURCES_DIR", "module_files", "module_names"]


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


def module_files(package_root: Path, manifest: PackageManifest) -> list[tuple[str, Path]]:
    """Each ``.py`` file of the package's modules as ``(dotted name, path)``,
    sorted by name: ``sources/heights.py`` is ``heights``,
    ``sources/heights/raster.py`` is ``heights.raster`` and its folder's
    ``__init__.py`` is ``heights``. A file whose path is not a dotted name is
    left out."""
    package_root = Path(package_root)
    names = module_names(package_root, manifest)
    out: list[tuple[str, Path]] = []
    for relative in _source_files(package_root):
        parts = relative.split("/")[1:]
        if parts[0].removesuffix(".py") not in names or not parts[-1].endswith(".py"):
            continue
        parts[-1] = parts[-1][: -len(".py")]
        if parts[-1] == "__init__" and len(parts) > 1:
            parts.pop()
        if all(part.isidentifier() and not keyword.iskeyword(part) for part in parts):
            out.append((".".join(parts), package_root / relative))
    return sorted(out)
