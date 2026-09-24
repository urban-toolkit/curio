"""Wire rows, built by explicit allowlist.

Every field that reaches a client is named here. Nothing is spread from a
manifest dict, and there is no ``**manifest`` anywhere in this package - that
is the structural reason a credential cannot leak into a response, as opposed
to the procedural reason (nobody put one there). A new manifest field is
invisible to clients until someone adds it to this file on purpose.
"""

from __future__ import annotations

from typing import Any

from utk_curio.backend.app.datalakes.domain.manifest import LakeSourceManifest


def source_row(
    manifest: LakeSourceManifest,
    *,
    credential_present: bool = False,
    icon_url: str | None = None,
) -> dict[str, Any]:
    auth = manifest.auth
    return {
        "sourceId": manifest.id,
        "dirName": manifest.dir_name,
        "name": manifest.name,
        "version": manifest.version,
        "description": manifest.description,
        "publisher": manifest.publisher,
        "homepage": manifest.homepage,
        "license": manifest.license,
        "tags": list(manifest.tags),
        "iconUrl": icon_url,
        "provider": manifest.provider.type,
        # ``baseUrl`` is shown so a user can see where a download would come
        # from. ``options`` is NOT: it is provider wiring, not information, and
        # keeping it server-side means a provider can gain an option without
        # anyone auditing whether it was safe to publish.
        "baseUrl": manifest.provider.base_url,
        "auth": {
            "mode": auth.mode,
            # Booleans and a help link. Never the token, never the header
            # value; the slot name is shown so the Settings panel can say
            # which credential this source wants.
            "required": auth.needs_token,
            "usesToken": auth.uses_token,
            "secretId": auth.secret_id,
            "present": bool(credential_present),
            "helpUrl": auth.help_url,
        },
        "capabilities": {
            "search": manifest.capabilities.search,
            "describe": manifest.capabilities.describe,
            "download": manifest.capabilities.download,
            "formats": list(manifest.capabilities.formats),
            "maxDownloadBytes": manifest.capabilities.max_download_bytes,
        },
        "createdAt": manifest.created_at,
        "updatedAt": manifest.updated_at,
    }


def credential_status_row(secret_id: str, *, present: bool, sources: list[str]) -> dict[str, Any]:
    return {"secretId": secret_id, "present": bool(present), "sources": list(sources)}
