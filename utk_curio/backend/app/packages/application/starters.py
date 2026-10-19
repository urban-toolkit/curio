"""Walker that produces ``Starter`` objects for every installed package template.

A starter is the optional starter source-code body associated with a package
template (the renamed-from-``kind`` concept). Each template manifest may carry
an optional ``source`` field — a package-relative path to a single starter
file (any extension: ``.py``, ``.js``, ``.vl.json``, etc.). When present, the
file content becomes one ``Starter`` entry keyed on the package's canonical
template id ``<packageId>/<templateId>@<major>``, named for the file.

A model package's template without ``source`` opens with the cell Curio
writes for the package's model type (``model_packages.model_default_cell``),
named for the template's id. Other templates without ``source`` (e.g.
structural built-ins) contribute no starter, and the editor opens empty.

A template whose starter is a node's whole content (``starterIsContent``)
gives it to a node an agent's plan creates too: :func:`content_starters`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Iterable

from utk_curio.backend.app.execution.code_references import normalize_widgets
from utk_curio.backend.app.packages.application import (
    project_packages as packages_project_packages,
    store_reads as packages_store_reads,
    templates as packages_templates,
)
from utk_curio.backend.app.packages.application.model_packages import model_default_cell
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.domain.manifest import ManifestError, TemplateManifest
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.store import (
    list_user_packages,
    package_asset_path,
)

log = logging.getLogger(__name__)


def _starter_object(canonical_id: str, name: str, code: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "type": canonical_id,
        "name": name,
        "description": "",
        "accessLevel": "ANY",
        "code": code,
        "custom": False,
    }


def generate_package_starters(user_key: str) -> list[dict]:
    """Return ``Starter`` objects for every installed package of *user_key*.

    At most one starter per template: the template's optional ``source`` file,
    or, for a model package's template without one, its model's default cell.

    The whole read — enumeration, manifests, source files — is one snapshot
    under the per-user seed lock (memo dev/99): the returned starters carry
    the code as text, so nothing here outlives the lock as a live path.
    """
    with package_seed_lock(user_key):
        return _generate_unlocked(user_key)


def _generate_unlocked(user_key: str) -> list[dict]:
    out: list[dict] = []
    for package_path in list_user_packages(user_key):
        try:
            manifest = load_package_manifest(package_path)
        except ManifestError as exc:
            log.warning("Skipping malformed package %s: %s", package_path.name, exc)
            continue

        for template in manifest.templates:
            if not template.source:
                if manifest.kind == "model" and manifest.model is not None:
                    out.append(_starter_object(
                        manifest.canonical_for(template.template_id), template.template_id,
                        model_default_cell(manifest, package_path),
                    ))
                continue
            read = _read_source(user_key, package_path.name, template)
            if read is None:
                continue
            name, code = read
            out.append(_starter_object(manifest.canonical_for(template.template_id), name, code))
    return out


def _read_source(user_key: str, dir_name: str, template: TemplateManifest) -> tuple[str, str] | None:
    """``(name, text)`` of *template*'s ``source`` file in the installed
    package *dir_name*: the name the starters feed lists it under, the file's
    stem with ``_`` read as a space. None when the path is unsafe, missing or
    unreadable."""
    parts = [p for p in (template.source or "").replace("\\", "/").split("/") if p]
    try:
        entry = package_asset_path(user_key, dir_name, *parts, field="source")
    except (ValueError, PermissionError) as exc:
        log.warning(
            "Package %s template %s has unsafe source %r: %s",
            dir_name, template.template_id, template.source, exc,
        )
        return None
    if not entry.is_file():
        return None
    try:
        code = entry.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("Cannot read %s: %s", entry, exc)
        return None
    return entry.stem.replace("_", " "), code


def content_starters(user_key: str, project_id: str, node_types: Iterable[object]) -> dict[str, dict]:
    """What a node of each of *node_types* starts with when an agent's plan
    creates it, for the templates whose starter is a node's whole content
    (``starterIsContent``): ``{"content", "widgets"}`` by canonical template
    id, the ``source`` file's text and the template's widgets. A node of any
    other template is created empty and Solve writes its content; one whose
    source cannot be read is left out too.

    A template resolves as :func:`templates.available_templates` resolves it,
    to the first package in the project's scope that holds it. One snapshot
    under the per-user seed lock, the source files included (memo dev/99).
    """
    wanted = {packages_templates.canonical_template_id(t) for t in node_types} - {""}
    if not wanted:
        return {}
    scope = packages_project_packages._lockfile_or_empty(user_key, project_id)  # project-spec I/O: outside
    out: dict[str, dict] = {}
    seen: set[str] = set()
    with package_seed_lock(user_key):
        store = packages_store_reads._store_index(user_key)
        for dir_name, manifest in packages_templates._in_scope(scope, store):
            if isinstance(manifest, Exception):
                continue
            for template in manifest.templates:
                canonical = f"{manifest.package_id}/{template.template_id}"
                if canonical in seen:
                    continue
                seen.add(canonical)
                if canonical not in wanted or not template.starter_is_content:
                    continue
                read = _read_source(user_key, dir_name, template)
                if read is not None:
                    out[canonical] = {
                        "content": read[1],
                        "widgets": [dict(w) for w in normalize_widgets(template.widgets)],
                    }
    return out
