"""Walker that produces ``Template`` objects for every installed pack kind.

Each kind manifest may carry an optional ``source`` field — a pack-relative
path to a single starter file (any extension: ``.py``, ``.js``,
``.vl.json``, etc.). When present, the file content becomes one
``Template`` entry keyed on the pack's canonical kind id
``<packId>/<kindId>@<major>``. Kinds without ``source`` (e.g. structural
built-ins) contribute no template, and the editor opens empty.
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

    At most one template per kind: the kind's optional ``source`` file.
    """
    out: list[dict] = []
    for pack_path in list_user_packs(user_key):
        try:
            manifest = load_pack_manifest(pack_path)
        except ManifestError as exc:
            log.warning("Skipping malformed pack %s: %s", pack_path.name, exc)
            continue

        for kind in manifest.kinds:
            if not kind.source:
                continue
            parts = [p for p in kind.source.replace("\\", "/").split("/") if p]
            try:
                entry = pack_asset_path(
                    user_key, pack_path.name, *parts, field="source"
                )
            except (ValueError, PermissionError) as exc:
                log.warning(
                    "Pack %s kind %s has unsafe source %r: %s",
                    pack_path.name, kind.kind_id, kind.source, exc,
                )
                continue

            if not entry.is_file():
                continue
            try:
                code = entry.read_text(encoding="utf-8")
            except OSError as exc:
                log.warning("Cannot read %s: %s", entry, exc)
                continue

            canonical = manifest.canonical_for(kind.kind_id)
            name = entry.stem.replace("_", " ")
            out.append(_template_object(canonical, name, code))
    return out
