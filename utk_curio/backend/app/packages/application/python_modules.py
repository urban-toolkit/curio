"""The modules a package ships, handed to the sandbox when one of its nodes runs
(#468), or a node of a package that depends on it (``dependencies.packages``).

Application layer of the packages package. What counts as a module is
``domain/python_modules.py``; the install-time refusal of a name two packages
ship is ``store_install.refuse_a_module_name_in_use``, which is also why the
modules of a package and of the packages it depends on never share a name.
:func:`module_index` lists every module by name, with the nodes a run hands
it to, for the agents' grounding gate.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import AbstractSet

from utk_curio.backend.app.packages.domain.manifest import ManifestError
from utk_curio.backend.app.packages.domain.package_id import BUILTIN_PACKAGE_ID, PACKAGE_DIR_RE
from utk_curio.backend.app.packages.domain.spec_packages import dir_name_from_node_type
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.repositories import catalog_dir as packages_catalog_dir
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


def _dataflow_pins(user_key: str, project_id: str | None, majors_by_pkg: dict[str, list[int]]) -> set[str]:
    """The dataflow's lockfile, read only when it can decide something: when
    some package has several majors installed. Read before the store lock is
    taken, since reading it takes that lock."""
    if not project_id or all(len(majors) < 2 for majors in majors_by_pkg.values()):
        return set()
    return packages_project_packages._lockfile_or_empty(user_key, project_id)


def _pinned_major(package_id: str, pins: AbstractSet[str]) -> int | None:
    """The major of *package_id* the dataflow's lockfile names, the highest
    when it names several."""
    majors = [int(dir_name.rsplit("@", 1)[1]) for dir_name in pins if dir_name.rsplit("@", 1)[0] == package_id]
    return max(majors) if majors else None


def _installed_dir_for(
    node_type: str, package_id: str, majors_by_pkg: dict[str, list[int]], pins: AbstractSet[str],
) -> str | None:
    """The installed ``<packageId>@<major>`` a node of *node_type* comes from.

    A versioned type names its major. An unversioned one, which is how a
    dataflow stores it, takes the only major installed, else the one the
    dataflow's lockfile pins (*pins*, :func:`_dataflow_pins`), else the highest.
    """
    majors = majors_by_pkg.get(package_id) or []
    named = dir_name_from_node_type(node_type)
    if named is not None:
        return named if int(named.rsplit("@", 1)[1]) in majors else None
    return _dir_for_package(package_id, majors_by_pkg, pins)


def _dir_for_package(package_id: str, majors_by_pkg: dict[str, list[int]], pins: AbstractSet[str]) -> str | None:
    """The installed ``<packageId>@<major>`` an unversioned node type of
    *package_id* comes from: the only major installed, else the one the
    dataflow's lockfile pins, else the highest."""
    majors = majors_by_pkg.get(package_id) or []
    if not majors:
        return None
    pinned = _pinned_major(package_id, pins) if len(majors) > 1 else None
    if pinned is not None:
        return f"{package_id}@{pinned}"
    return f"{package_id}@{max(majors)}"


def dependency_dirs(
    package_deps: object, majors_by_pkg: dict[str, list[int]], pins: AbstractSet[str] = frozenset(),
) -> list[str]:
    """The installed ``<packageId>@<major>`` of each ``dependencies.packages``
    entry, read as the resolver reads them (``resolution``): ``<id>@<major>``
    names a major, a bare id the only major installed. With several majors
    installed, a bare id takes the one the dataflow's lockfile pins (*pins*),
    as a node's own package is found (:func:`_installed_dir_for`); an add
    writes it there. An entry that names no installed package, or a bare id
    with several majors installed and none pinned, is left out."""
    out: list[str] = []
    for key in package_deps or {}:
        package_id, at, major = str(key).strip().partition("@")
        majors = majors_by_pkg.get(package_id.strip()) or []
        if at:
            if major.strip().isdigit() and int(major) in majors:
                out.append(f"{package_id.strip()}@{int(major)}")
        elif len(majors) == 1:
            out.append(f"{package_id.strip()}@{majors[0]}")
        else:
            pinned = _pinned_major(package_id.strip(), pins)
            if pinned in majors:
                out.append(f"{package_id.strip()}@{pinned}")
    return out


def _module_sources(
    user_key: str, dir_name: str, manifest, majors_by_pkg: dict[str, list[int]],
    pins: AbstractSet[str] = frozenset(),
) -> list[dict]:
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
        for dependency in dependency_dirs(current_manifest.package_deps, majors_by_pkg, pins):
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
        pins = _dataflow_pins(user_key, project_id, majors_by_pkg)
        dir_name = _installed_dir_for(node_type, package_id, majors_by_pkg, pins)
        if dir_name is None:
            return None
        with package_seed_lock(user_key):
            manifest = load_package_manifest(package_dir(user_key, dir_name))
            if template_id not in {t.template_id for t in manifest.templates}:
                return None
            sources = _module_sources(user_key, dir_name, manifest, majors_by_pkg, pins)
    except Exception as exc:  # noqa: BLE001 - resolution must never fail the execution
        log.warning("Could not resolve the modules of %s for a run: %s", node_type, exc)
        return None
    if not sources:
        return None
    return sources[0] if len(sources) == 1 else sources


def _python_code_templates(manifest) -> list[dict]:
    """``{"id", "label"}`` of each template of *manifest* whose nodes hold
    Python code: the nodes that can import a module."""
    return [
        {"id": f"{manifest.package_id}/{template.template_id}", "label": template.label or template.template_id}
        for template in manifest.templates
        if template.engine == "python"
        and packages_templates.template_content_kind(template) == packages_templates.CONTENT_KIND_CODE
    ]


def _store_modules(user_key: str, project_id: str | None, majors_by_pkg: dict[str, list[int]]) -> dict[str, dict]:
    """:func:`module_index` for the packages of *user_key*'s store: each
    package as an unversioned node type finds it, with the modules a run
    hands its nodes (:func:`_module_sources`)."""
    pins = _dataflow_pins(user_key, project_id, majors_by_pkg)
    index: dict[str, dict] = {}
    with package_seed_lock(user_key):
        held = []
        for package_id in sorted(majors_by_pkg):
            dir_name = _dir_for_package(package_id, majors_by_pkg, pins)
            if package_id == BUILTIN_PACKAGE_ID or dir_name is None:
                continue
            try:
                held.append((dir_name, load_package_manifest(package_dir(user_key, dir_name))))
            except ManifestError:
                continue
        for dir_name, manifest in held:
            templates = _python_code_templates(manifest)
            for source in _module_sources(user_key, dir_name, manifest, majors_by_pkg, pins):
                shipper = Path(source["root"]).parent.name
                for name in source["names"]:
                    entry = index.setdefault(name, {"package": shipper, "added": True, "templates": []})
                    entry["templates"].extend(t for t in templates if t not in entry["templates"])
    return index


#: ``_catalog_modules``'s last reading, keyed by the catalog folder and its
#: modification time, so a package published into it is read again.
_CATALOG_MODULES: dict[tuple[str, int], dict[str, dict]] = {}


def _catalog_modules() -> dict[str, dict]:
    """:func:`module_index` for the packages of the catalog, each with its
    own templates; the highest major of a package names a module first."""
    root = packages_catalog_dir.catalog_root()
    try:
        key = (str(root), root.stat().st_mtime_ns)
    except OSError:
        return {}
    cached = _CATALOG_MODULES.get(key)
    if cached is not None:
        return cached
    index: dict[str, dict] = {}
    for folder in sorted((f for f in root.iterdir() if f.is_dir() and PACKAGE_DIR_RE.match(f.name)), reverse=True):
        try:
            manifest = load_package_manifest(folder)
        except (ManifestError, OSError, ValueError):
            continue
        if manifest.package_id == BUILTIN_PACKAGE_ID:
            continue
        for name in module_names(folder, manifest):
            index.setdefault(name, {"package": folder.name, "added": False, "templates": _python_code_templates(manifest)})
    _CATALOG_MODULES.clear()
    _CATALOG_MODULES[key] = index
    return index


def module_index(user_key: str | None, project_id: str | None = None) -> dict[str, dict]:
    """Every module a package ships, by its name: ``{"package", "added",
    "templates"}``.

    *package* is the ``<packageId>@<major>`` that ships it, and *added* says
    whether *user_key*'s store holds it. *templates* are the templates whose
    nodes import it, ``{"id", "label"}`` each: for a package of the store, as
    :func:`modules_for_node` hands modules to a run, the Python code templates
    of that package and of every package that depends on it; for a package of
    the catalog the store does not hold, its own. The built-in package ships
    none. Never raises: what cannot be read adds nothing."""
    index: dict[str, dict] = {}
    installed: set[str] = set()
    if user_key:
        try:
            majors_by_pkg = packages_store_reads._installed_majors_by_pkg(user_key)
            installed = set(majors_by_pkg)
            index = _store_modules(user_key, project_id, majors_by_pkg)
        except Exception as exc:  # noqa: BLE001 - an unreadable store ships no module
            log.warning("Could not read the modules of %s's packages: %s", user_key, exc)
    try:
        catalog = _catalog_modules()
    except Exception as exc:  # noqa: BLE001 - an unreadable catalog ships no module
        log.warning("Could not read the modules of the catalog's packages: %s", exc)
        catalog = {}
    for name, entry in catalog.items():
        if name not in index and entry["package"].rsplit("@", 1)[0] not in installed:
            index[name] = {**entry, "templates": list(entry["templates"])}
    return index
