"""The packages an add brings, read from the user's store and the shared catalog: the one closure (``domain/package_closure.required_packages``) every path that adds a package asks.

Application layer of the packages package. It reaches nothing above the store
reads, so the store installer, the seeder, the resolver and the dataflow check
all import it.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Iterable, Iterator

from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.domain.manifest import ManifestError, PackageManifest
from utk_curio.backend.app.packages.domain.package_closure import UnmetPackageDependency, required_packages
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.repositories import catalog_dir as packages_catalog_dir
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.application import store_reads as packages_store_reads

log = logging.getLogger(__name__)

#: What an add answers when a package it needs cannot be had.
REFUSED_STATUS = 409


class PackageFolder(Mapping):
    """The packages in one folder, ``dirName -> manifest``, each manifest read the
    first time it is asked for. A folder whose manifest does not read is not
    there. Listing it reads every manifest; looking one up reads only that one."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._names: list[str] | None = None
        self._read: dict[str, PackageManifest | None] = {}

    def _listed(self) -> list[str]:
        if self._names is None:
            self._names = sorted(
                entry.name for entry in self._root.iterdir()
                if entry.is_dir() and PACKAGE_DIR_RE.match(entry.name)
            ) if self._root.is_dir() else []
        return self._names

    def __getitem__(self, dir_name: str) -> PackageManifest:
        if dir_name not in self._read:
            manifest = None
            if dir_name in self._listed():
                try:
                    manifest = load_package_manifest(self._root / dir_name)
                except (ManifestError, OSError):
                    manifest = None
            self._read[dir_name] = manifest
        manifest = self._read[dir_name]
        if manifest is None:
            raise KeyError(dir_name)
        return manifest

    def __iter__(self) -> Iterator[str]:
        return iter([dir_name for dir_name in self._listed() if dir_name in self])

    def __len__(self) -> int:
        return len(list(iter(self)))

    def snapshot(self) -> dict[str, PackageManifest]:
        """Every package that reads, read now."""
        return {dir_name: self[dir_name] for dir_name in self}


def catalog() -> PackageFolder:
    """The shared catalog (``catalog_root()``), read as it is asked."""
    return PackageFolder(packages_catalog_dir.catalog_root())


def readable(index: Mapping[str, object]) -> dict[str, PackageManifest]:
    """A store index (``store_reads._store_index``) without the packages that do not read."""
    return {dir_name: manifest for dir_name, manifest in index.items() if isinstance(manifest, PackageManifest)}


def packages_to_add(user_key: str, dir_name: str) -> list[str]:
    """*dir_name* and every package it needs, those it needs first, read from
    *user_key*'s store and the shared catalog. A package it needs that neither
    holds at a version its entry allows refuses the add: a
    :class:`PackageServiceError` (409) naming that package and what needs it."""
    copies = catalog()
    store = readable(packages_store_reads._locked_store_index(user_key))
    try:
        return required_packages([dir_name], store, copies)
    except UnmetPackageDependency as exc:
        raise PackageServiceError(str(exc), REFUSED_STATUS) from exc


def lacks_a_package(
    dir_name: str,
    store: Mapping[str, PackageManifest],
    copies: Mapping[str, PackageManifest],
    in_store: set[str],
) -> bool:
    """Whether *dir_name*, which the store holds, needs a package the store does
    not hold. Adding it again brings that package. One that cannot be had
    counts too, so the add says why."""
    try:
        needed = required_packages([dir_name], store, copies)
    except UnmetPackageDependency:
        return True
    return any(other not in in_store for other in needed)


def catalog_packages_to_add(dir_names: Iterable[str]) -> list[str]:
    """*dir_names* and every package they need, from the shared catalog alone, in
    order and each once: what the examples' seeding adds for the packages the
    shipped dataflows declare. A package whose needs cannot be had keeps only
    itself, and the reason is logged."""
    copies = catalog()
    out: list[str] = []
    for dir_name in dir_names:
        try:
            brought = required_packages([dir_name], {}, copies)
        except UnmetPackageDependency as exc:
            log.warning("Seeding %s without the packages it needs: %s", dir_name, exc)
            brought = [dir_name]
        out += [other for other in brought if other not in out]
    return out
