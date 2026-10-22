"""A node's own template, found where a run finds its package.

A run finds the package a node comes from in the account's store: the major
its type names, else the one the dataflow's lockfile pins, else the only or
the highest one installed (``python_modules._installed_dir_for``, which hands
a node its package's modules). What the node's template declares is read
from that copy, so a template a user made counts as Curio's own do; when the
account has no copy of it, from the package catalog's copy.
"""
from __future__ import annotations

import logging

from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.store import package_dir
from utk_curio.backend.app.packages.application import (
    python_modules as packages_python_modules,
    store_reads as packages_store_reads,
    templates as packages_templates,
)

log = logging.getLogger(__name__)


def installed_template(user_key: str | None, node_type: object, project_id: str | None = None):
    """The template (a ``TemplateManifest``) a node of *node_type* comes from
    in *user_key*'s store, found as a run finds its package; None when the
    store holds no such template. Never raises: a store that cannot be read
    holds none."""
    canonical = packages_templates.canonical_template_id(node_type)
    package_id, _, template_id = canonical.partition("/")
    if not user_key or not template_id:
        return None
    try:
        majors_by_pkg = packages_store_reads._installed_majors_by_pkg(user_key)
        pins = packages_python_modules._dataflow_pins(user_key, project_id, majors_by_pkg)
        dir_name = packages_python_modules._installed_dir_for(node_type, package_id, majors_by_pkg, pins)
        if dir_name is None:
            return None
        with package_seed_lock(user_key):
            manifest = load_package_manifest(package_dir(user_key, dir_name))
    except Exception as exc:  # noqa: BLE001 - an unreadable store holds no template
        log.warning("Could not read the template of %s in the account's store: %s", node_type, exc)
        return None
    return next((template for template in manifest.templates if template.template_id == template_id), None)


def template_behavior(user_key: str | None, project_id: str | None, node_type: object) -> str | None:
    """The behavior the template of a node of *node_type* names (a manifest
    template's ``behavior``, such as ``edit-features``): the account's copy's,
    found as a run finds it, else the package catalog's copy's; None when it
    names none. A feature's checks are keyed by it, so a template that names
    a built-in behavior gets them too."""
    template = installed_template(user_key, node_type, project_id)
    if template is not None:
        return template.behavior if isinstance(template.behavior, str) and template.behavior else None
    canonical = packages_templates.canonical_template_id(node_type)
    return packages_templates.catalog_template_behaviors().get(canonical) if canonical else None
