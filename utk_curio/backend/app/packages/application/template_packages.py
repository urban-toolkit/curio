"""Agent-drafted single-template packages (memo dev/48 §3.2b): the namespaced draft envelope built through the factory and enlisted into a project.

Application layer of the packages package (memo dev/143, B2): cut from ``services.py``
by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``packages_<module>.name``) so a test that patches the owner is seen by
every caller, and import order between siblings cannot matter.
"""

from __future__ import annotations

import re

from utk_curio.backend.app.packages.repositories.archive import InstallerError
from utk_curio.backend.app.packages.application import project_packages as packages_project_packages
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.application.store_install import install_package_from_archive
from utk_curio.backend.app.packages.builder.factory import (
    build_package_archive,
    FactoryError,
)


# Agent-drafted packages (memo dev/48 §3.2b) are namespaced so they can never
# collide with the seeded builtin or a catalog publisher's id space.
AGENT_PACKAGE_NAMESPACE = "curio.agent"


_TEMPLATE_SLUG_MAX = 48


def template_slug(label: str) -> str:
    """A ``TEMPLATE_ID_RE``-safe slug from a human label (empty when nothing
    survives normalization)."""

    slug = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:_TEMPLATE_SLUG_MAX].strip("-")
    if slug and not slug[0].isalpha():
        slug = f"n-{slug}".rstrip("-")[:_TEMPLATE_SLUG_MAX]
    return slug


def create_template_package(user_key: str, project_id: str, template: dict) -> dict:
    """Register ONE agent-drafted node template through the EXISTING factory
    (memo dev/48 §3.2b — the reviewed creation fallback's apply half).

    Builds a single-template draft package (the same envelope the palette's
    Save-as flow produces), installs it to the user store via the factory's
    atomic staging, and adds it to *project_id*'s package lockfile. Returns
    the created template entry (``available_templates`` shape, plus
    ``packageDir``). Factory/installer validation failures raise
    :class:`PackageServiceError` with the verbatim message — nothing is ever
    half-registered (the factory stages atomically).
    """
    label = str(template.get("label") or "").strip()
    slug = template_slug(label)
    if not slug:
        raise PackageServiceError("template.label must yield a usable name", 400)
    engine = template.get("engine") or "python"
    description = str(template.get("description") or "").strip()
    code = template.get("content")
    if not isinstance(code, str) or not code.strip():
        raise PackageServiceError("template.content must be a non-empty string", 400)
    filename = f"{slug}.py" if engine == "python" else f"{slug}.js"
    package_id = f"{AGENT_PACKAGE_NAMESPACE}.{slug}"
    template_manifest = {
        "id": slug,
        "label": label,
        "category": str(template.get("category") or "computation"),
        "engine": engine,
        "editor": "code",
        "description": description,
        "inputPorts": template.get("inputPorts") or [],
        "outputPorts": template.get("outputPorts")
        or [{"types": ["JSON"], "cardinality": "1"}],
        "source": f"sources/{filename}",
        "badge": "AGENT",
    }
    draft = {
        "manifest": {
            "id": package_id,
            "version": "1.0.0",
            "name": label,
            "publisher": "Curio Agent",
            "description": description or f"Agent-drafted node type: {label}",
            "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [],
            "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [template_manifest],
        },
        "sources": {slug: {"filename": filename, "code": code}},
    }
    try:
        built = build_package_archive(draft)
        install_package_from_archive(user_key, built.archive, replace=False)
    except (FactoryError, InstallerError) as exc:
        raise PackageServiceError(str(exc), 409) from exc
    dir_name = built.manifest.dir_name
    packages_project_packages.install_to_project(user_key, project_id, dir_name)
    return {
        "id": f"{package_id}/{slug}",
        "label": label,
        "description": description,
        "authorable": True,
        "packageDir": dir_name,
    }
