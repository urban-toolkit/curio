"""Walker that produces ``Starter`` objects for every installed package template.

A starter is the optional starter source-code body associated with a package
template (the renamed-from-``kind`` concept). Each template manifest may carry
an optional ``source`` field — a package-relative path to a single starter
file (any extension: ``.py``, ``.js``, ``.vl.json``, etc.). When present, the
file content becomes one ``Starter`` entry keyed on the package's canonical
template id ``<packageId>/<templateId>@<major>``. Templates without ``source``
(e.g. structural built-ins) contribute no starter, and the editor opens empty.
"""

from __future__ import annotations

import logging
import uuid

from utk_curio.backend.app.packages.manifest import ManifestError, load_packageage_manifest
from utk_curio.backend.app.packages.storage import list_user_packageages, package_asset_path

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


def generate_packageage_starters(user_key: str) -> list[dict]:
    """Return ``Starter`` objects for every installed package of *user_key*.

    At most one starter per template: the template's optional ``source`` file.
    """
    out: list[dict] = []
    for package_path in list_user_packageages(user_key):
        try:
            manifest = load_packageage_manifest(package_path)
        except ManifestError as exc:
            log.warning("Skipping malformed package %s: %s", package_path.name, exc)
            continue

        for template in manifest.templates:
            if not template.source:
                continue
            parts = [p for p in template.source.replace("\\", "/").split("/") if p]
            try:
                entry = package_asset_path(
                    user_key, package_path.name, *parts, field="source"
                )
            except (ValueError, PermissionError) as exc:
                log.warning(
                    "Package %s template %s has unsafe source %r: %s",
                    package_path.name, template.template_id, template.source, exc,
                )
                continue

            if not entry.is_file():
                continue
            try:
                code = entry.read_text(encoding="utf-8")
            except OSError as exc:
                log.warning("Cannot read %s: %s", entry, exc)
                continue

            canonical = manifest.canonical_for(template.template_id)
            name = entry.stem.replace("_", " ")
            out.append(_starter_object(canonical, name, code))
    return out
