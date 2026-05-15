"""Sibling to ``api.routes.generate_templates()`` that walks installed packs.

The built-in walker reads ``<CURIO_LAUNCH_CWD>/templates/<node_type_lower>/*.py``
and emits ``Template`` objects keyed on the upper-snake ``NodeType``.

This walker reads **only inside each pack's own directory** and emits
``Template`` objects keyed on the pack's canonical id
``<packId>/<kindId>@<major>``. That id is the same string the frontend
registry uses for the pack descriptor, so the existing
``TemplateProvider.getTemplates(type, ...)`` filter just works.
"""

from __future__ import annotations

import logging
import uuid

from utk_curio.backend.app.packs.manifest import ManifestError, load_pack_manifest
from utk_curio.backend.app.packs.storage import list_user_packs, pack_asset_path

log = logging.getLogger(__name__)


def _template_object(canonical_id: str, name: str, code: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "type": canonical_id,
        "name": name,
        "description": "",
        "accessLevel": "ANY",
        "code": code,
        "custom": False,
    }


def generate_pack_templates(user_key: str) -> list[dict]:
    """Return ``Template`` objects for every installed pack of *user_key*.

    Each ``.py`` file under ``<pack_dir>/<kind.templateDir>/`` produces one
    template entry, with ``type`` set to the pack's canonical kind id. If
    a kind omits ``templateDir`` we skip it silently — pack-driven nodes
    may legitimately ship without any preset (the editor falls back to an
    empty buffer, exactly like a freshly dropped built-in code node).
    """
    out: list[dict] = []
    for pack_path in list_user_packs(user_key):
        try:
            manifest = load_pack_manifest(pack_path)
        except ManifestError as exc:
            log.warning("Skipping malformed pack %s: %s", pack_path.name, exc)
            continue

        for kind in manifest.kinds:
            if not kind.template_dir:
                continue
            # ``templateDir`` is a pack-relative path. Split it into
            # path components so each one passes through validate_component.
            parts = [p for p in kind.template_dir.replace("\\", "/").split("/") if p]
            try:
                tdir = pack_asset_path(
                    user_key, pack_path.name, *parts, field="templateDir"
                )
            except (ValueError, PermissionError) as exc:
                log.warning(
                    "Pack %s kind %s has unsafe templateDir %r: %s",
                    pack_path.name, kind.kind_id, kind.template_dir, exc,
                )
                continue

            if not tdir.is_dir():
                continue

            canonical = manifest.canonical_for(kind.kind_id)
            for entry in sorted(tdir.iterdir()):
                if not entry.is_file() or entry.suffix != ".py":
                    continue
                try:
                    code = entry.read_text(encoding="utf-8")
                except OSError as exc:
                    log.warning("Cannot read %s: %s", entry, exc)
                    continue
                name = entry.stem.replace("_", " ")
                out.append(_template_object(canonical, name, code))
    return out
