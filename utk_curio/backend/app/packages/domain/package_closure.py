"""The packages an add brings: the package, each package its manifest names in ``dependencies.packages``, and the packages those name in turn. Pure.

Domain layer of the packages package. An entry is
``"<packageId>@<major>": "<range>"``, or ``"<packageId>": "<range>"`` for any
major, with a range in the grammar ``versions.parse_range`` reads. A copy meets
it when the range allows its version: the user's store copy of that
``<packageId>@<major>`` when the store holds one, else the shared catalog's. A
store copy comes first and is never replaced, since other dataflows use it,
and a bare id takes the highest major the range allows.

Every path that adds a package asks :func:`required_packages`, through
``application/package_dependencies.py``, which reads the two folders it takes.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from utk_curio.backend.app.packages.domain.manifest import PackageManifest
from utk_curio.backend.app.packages.domain.versions import (
    Range,
    ResolverError,
    parse_range,
    parse_version,
)


class UnmetPackageDependency(ResolverError):
    """A package names in ``dependencies.packages`` a package no copy meets: the
    store and the catalog hold none at a version the entry allows, or the entry
    names its range in a way Curio does not read. The message names both
    packages."""


def required_packages(
    roots: Iterable[str],
    installed: Mapping[str, PackageManifest],
    catalog: Mapping[str, PackageManifest],
) -> list[str]:
    """*roots* and every package they need, transitively, each once: a package
    comes after the packages it needs.

    *installed* is the user's store and *catalog* the shared catalog, each
    ``dirName -> manifest``. A package's entries are read from its store copy,
    else its catalog copy, and a root neither holds needs nothing. A cycle
    stops where it closes. Raises :class:`UnmetPackageDependency` for an entry
    no copy meets.
    """
    order: list[str] = []
    seen: set[str] = set()

    def visit(dir_name: str) -> None:
        if dir_name in seen:
            return
        seen.add(dir_name)
        manifest = installed.get(dir_name) or catalog.get(dir_name)
        entries = manifest.package_deps if manifest is not None else {}
        for key, wanted in sorted(entries.items()):
            visit(_meeting_copy(dir_name, str(key).strip(), wanted, installed, catalog))
        order.append(dir_name)

    for root in roots:
        visit(root)
    return order


def _meeting_copy(
    needer: str,
    key: str,
    wanted: object,
    installed: Mapping[str, PackageManifest],
    catalog: Mapping[str, PackageManifest],
) -> str:
    """The ``<packageId>@<major>`` that meets *needer*'s entry ``key: wanted``."""
    allowed = _range(needer, key, wanted)
    package_id, at, major = key.partition("@")
    package_id = package_id.strip()
    if at:
        candidates = [f"{package_id}@{int(major)}"] if major.strip().isdigit() else []
    else:
        candidates = sorted(
            {dir_name for dir_name in (*installed, *catalog) if dir_name.rpartition("@")[0] == package_id},
            key=_major,
            reverse=True,
        )
    copies = {dir_name: installed.get(dir_name) or catalog.get(dir_name) for dir_name in candidates}
    fits = [dir_name for dir_name, copy in copies.items() if copy is not None and _allows(allowed, copy.version)]
    for dir_name in fits:
        if dir_name in installed:
            return dir_name
    if fits:
        return fits[0]
    raise UnmetPackageDependency(_refusal(needer, key, wanted, allowed, copies, installed, catalog))


def _range(needer: str, key: str, wanted: object) -> Range:
    """The versions *needer*'s entry for *key* allows; no range is any version."""
    try:
        return parse_range("*" if wanted is None else wanted)
    except ResolverError as exc:
        raise UnmetPackageDependency(
            f"{needer} names {key} with the range {wanted!r}, which Curio does not read: {exc}"
        ) from exc


def _allows(allowed: Range, version: str) -> bool:
    try:
        parsed = parse_version(version)
    except ResolverError:
        return False
    return allowed.lo <= parsed and (allowed.hi is None or parsed < allowed.hi)


def _major(dir_name: str) -> int:
    return int(dir_name.rpartition("@")[2])


def _refusal(
    needer: str,
    key: str,
    wanted: object,
    allowed: Range,
    copies: Mapping[str, PackageManifest | None],
    installed: Mapping[str, PackageManifest],
    catalog: Mapping[str, PackageManifest],
) -> str:
    """Why no copy meets *needer*'s entry for *key*, and what would."""
    found = {dir_name: copy for dir_name, copy in copies.items() if copy is not None}
    if not found:
        return f"{needer} needs the package {key}, which is in neither your account nor the catalog"
    for dir_name, copy in found.items():
        newer = catalog.get(dir_name) if dir_name in installed else None
        if newer is not None and _allows(allowed, newer.version):
            return (
                f"{needer} needs {key} at {wanted}, and your account has {dir_name} {copy.version}: "
                f"update it from the catalog first"
            )
    there = ", ".join(
        f"{dir_name} {copy.version} in {'your account' if dir_name in installed else 'the catalog'}"
        for dir_name, copy in found.items()
    )
    return f"{needer} needs {key} at {wanted}, which neither your account nor the catalog has: there is {there}"
