"""The modules a package ships, handed to the sandbox when one of its nodes runs (#468).

Application layer of the packages package. What counts as a module, and the
install-time refusal of a name two packages ship, are
``repositories/python_modules.py``.
"""

from __future__ import annotations

import logging

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


def _installed_dir_for(user_key: str, node_type: str, package_id: str, project_id: str | None) -> str | None:
    """The installed ``<packageId>@<major>`` a node of *node_type* comes from.

    A versioned type names its major. An unversioned one, which is how a
    dataflow stores it, takes the only major installed, else the one the
    dataflow's lockfile pins, else the highest.
    """
    majors = packages_store_reads._installed_majors_by_pkg(user_key).get(package_id) or []
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


def modules_for_node(user_key: str | None, node_type: object, project_id: str | None = None) -> dict | None:
    """What a node of *node_type* may import from its package, for the sandbox.

    ``{"root": <the package's sources folder>, "names": [...]}`` when the
    node's package, in *user_key*'s store, ships modules; ``None`` otherwise,
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
        dir_name = _installed_dir_for(user_key, node_type, package_id, project_id)
        if dir_name is None:
            return None
        with package_seed_lock(user_key):
            root = package_dir(user_key, dir_name)
            manifest = load_package_manifest(root)
            if template_id not in {t.template_id for t in manifest.templates}:
                return None
            names = module_names(root, manifest)
    except Exception as exc:  # noqa: BLE001 - resolution must never fail the execution
        log.warning("Could not resolve the modules of %s for a run: %s", node_type, exc)
        return None
    if not names:
        return None
    return {"root": str(root / SOURCES_DIR), "names": sorted(names)}
