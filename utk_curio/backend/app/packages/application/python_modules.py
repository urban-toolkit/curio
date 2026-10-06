"""The modules a package ships, handed to the sandbox when one of its nodes runs
(#468), or a node of a package that depends on it (``dependencies.packages``).

Application layer of the packages package. What counts as a module is
``domain/python_modules.py``; the install-time refusal of a name two packages
ship is ``store_install.refuse_a_module_name_in_use``, which is also why the
modules of a package and of the packages it depends on never share a name.
"""

from __future__ import annotations

import logging

from utk_curio.backend.app.packages.domain.manifest import ManifestError
from utk_curio.backend.app.packages.domain.package_id import BUILTIN_PACKAGE_ID
from utk_curio.backend.app.packages.domain.spec_packages import dir_name_from_node_type
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.python_modules import (
    SOURCES_DIR,
    module_names,
)
from utk_curio.backend.app.packages.repositories.store import package_dir
from utk_curio.backend.app.packages.application import (
    project_packages as packages_project_packages,
    store_reads as packages_store_reads,
    templates as packages_templates,
)

log = logging.getLogger(__name__)


#: At most this many packages, the node's own and those it depends on, hand
#: their modules to one run.
MAX_MODULE_PACKAGES = 16


def _installed_dir_for(
    user_key: str, node_type: str, package_id: str, project_id: str | None,
    majors_by_pkg: dict[str, list[int]],
) -> str | None:
    """The installed ``<packageId>@<major>`` a node of *node_type* comes from.

    A versioned type names its major. An unversioned one, which is how a
    dataflow stores it, takes the only major installed, else the one the
    dataflow's lockfile pins, else the highest.
    """
    majors = majors_by_pkg.get(package_id) or []
    named = dir_name_from_node_type(node_type)
    if named is not None:
        return named if int(named.rsplit("@", 1)[1]) in majors else None
    if not majors:
        return None
    if len(majors) > 1 and project_id:
        pinned = [
            int(dir_name.rsplit("@", 1)[1])
            for dir_name in packages_project_packages._lockfile_or_empty(user_key, project_id)
            if dir_name.rsplit("@", 1)[0] == package_id
        ]
        if pinned:
            return f"{package_id}@{max(pinned)}"
    return f"{package_id}@{max(majors)}"


def dependency_dirs(package_deps: object, majors_by_pkg: dict[str, list[int]]) -> list[str]:
    """The installed ``<packageId>@<major>`` of each ``dependencies.packages``
    entry, read as the resolver reads them (``resolution``): ``<id>@<major>``
    names a major, a bare id the only major installed. An entry that names no
    installed package, or a bare id with several majors installed, is left
    out."""
    out: list[str] = []
    for key in package_deps or {}:
        package_id, at, major = str(key).strip().partition("@")
        majors = majors_by_pkg.get(package_id.strip()) or []
        if at:
            if major.strip().isdigit() and int(major) in majors:
                out.append(f"{package_id.strip()}@{int(major)}")
        elif len(majors) == 1:
            out.append(f"{package_id.strip()}@{majors[0]}")
    return out


def _module_sources(user_key: str, dir_name: str, manifest, majors_by_pkg: dict[str, list[int]]) -> list[dict]:
    """The modules of the package at *dir_name* and of every package it
    depends on, transitively: one ``{"root", "names"}`` per package that
    ships any, its own first. Called under the store lock."""
    sources: list[dict] = []
    seen = {dir_name}
    queue = [(dir_name, manifest)]
    while queue:
        current, current_manifest = queue.pop(0)
        root = package_dir(user_key, current)
        names = module_names(root, current_manifest)
        if names:
            sources.append({"root": str(root / SOURCES_DIR), "names": sorted(names)})
        for dependency in dependency_dirs(current_manifest.package_deps, majors_by_pkg):
            if dependency in seen or len(seen) >= MAX_MODULE_PACKAGES:
                continue
            seen.add(dependency)
            try:
                queue.append((dependency, load_package_manifest(package_dir(user_key, dependency))))
            except ManifestError:
                continue
    return sources


def dependency_module_names(user_key: str, package_deps: object) -> frozenset[str]:
    """The modules the packages in *package_deps* (a draft's
    ``dependencies.packages``) and their own dependencies ship: a template of
    the dependent package imports them, so nobody installs them with pip."""
    if not isinstance(package_deps, dict) or not package_deps:
        return frozenset()
    majors_by_pkg = packages_store_reads._installed_majors_by_pkg(user_key)
    names: set[str] = set()
    with package_seed_lock(user_key):
        for dir_name in dependency_dirs(package_deps, majors_by_pkg):
            try:
                manifest = load_package_manifest(package_dir(user_key, dir_name))
            except ManifestError:
                continue
            for source in _module_sources(user_key, dir_name, manifest, majors_by_pkg):
                names.update(source["names"])
    return frozenset(names)


def modules_for_node(user_key: str | None, node_type: object, project_id: str | None = None) -> dict | list | None:
    """What a node of *node_type* may import, for the sandbox.

    ``{"root": <the package's sources folder>, "names": [...]}`` when the
    node's package, in *user_key*'s store, ships modules. A package that
    depends on other packages (``dependencies.packages``) also hands its node
    theirs: then each package that ships modules is one such source, and
    there may be a list of them, its own first. ``None`` when there is none,
    and for every built-in node before any disk read. Never raises: a node
    whose modules could not be resolved still runs, and its import fails with
    Python's own message naming the module.
    """
    if not user_key or not isinstance(node_type, str):
        return None
    package_id, _, template_id = packages_templates.canonical_template_id(node_type).partition("/")
    if not template_id or package_id == BUILTIN_PACKAGE_ID:
        return None
    try:
        majors_by_pkg = packages_store_reads._installed_majors_by_pkg(user_key)
        dir_name = _installed_dir_for(user_key, node_type, package_id, project_id, majors_by_pkg)
        if dir_name is None:
            return None
        with package_seed_lock(user_key):
            manifest = load_package_manifest(package_dir(user_key, dir_name))
            if template_id not in {t.template_id for t in manifest.templates}:
                return None
            sources = _module_sources(user_key, dir_name, manifest, majors_by_pkg)
    except Exception as exc:  # noqa: BLE001 - resolution must never fail the execution
        log.warning("Could not resolve the modules of %s for a run: %s", node_type, exc)
        return None
    if not sources:
        return None
    return sources[0] if len(sources) == 1 else sources
