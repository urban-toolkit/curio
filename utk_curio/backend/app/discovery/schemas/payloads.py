"""Wire rows, built by explicit allowlist.

Every field that reaches a client is named here. Nothing is spread from a
manifest dict, and there is no ``**manifest`` anywhere in this package - that
is the structural reason a credential cannot leak into a response, as opposed
to the procedural reason (nobody put one there). A new manifest field is
invisible to clients until someone adds it to this file on purpose.
"""

from __future__ import annotations

from typing import Any

from utk_curio.backend.app.discovery.domain.manifest import DiscoverySourceManifest, ResourceSpec
from utk_curio.backend.app.discovery.domain.resource import (
    DiscoveryResource,
    DiscoveryResourceDetail,
)


def source_row(
    manifest: DiscoverySourceManifest,
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
        # ``storage`` sources declare their resources; a ``portal``'s are found
        # by searching it. The root of a folder is NOT sent: it is a path on
        # the server, and the resources say everything a user acts on.
        "kind": "storage" if manifest.is_storage else "portal",
        "resources": [declared_resource_row(spec) for spec in manifest.resources],
        "createdAt": manifest.created_at,
        "updatedAt": manifest.updated_at,
    }


def declared_resource_row(spec: ResourceSpec) -> dict[str, Any]:
    """What a storage manifest says about one resource, before any scan."""
    return {
        "resourceId": spec.id,
        "name": spec.name,
        "description": spec.description,
        "kind": spec.kind,
        # What lands in the Data Catalog: a table's file format, or
        # ``collection``.
        "format": spec.dataset_format,
        "fileFormat": spec.format,
        "path": spec.path,
        "datasets": spec.datasets,
        "splitBy": list(spec.split_by),
        "fields": [
            {"name": capture.name, "type": capture.type}
            for capture in spec.template.captures
        ],
    }


def credential_status_row(secret_id: str, *, present: bool, sources: list[str]) -> dict[str, Any]:
    return {"secretId": secret_id, "present": bool(present), "sources": list(sources)}


def resource_row(
    resource: DiscoveryResource,
    *,
    source_name: str = "",
    acquirable: bool = True,
    already_held_dataset_id: str | None = None,
) -> dict[str, Any]:
    """One search result.

    ``alreadyHeldDatasetId`` is how a row says "you already downloaded this" -
    the UI turns the download button into a link rather than offering a second
    copy. Resolved server-side because only the server can answer it.
    """
    return {
        "sourceId": resource.source_id,
        "sourceName": source_name,
        "resourceId": resource.resource_id,
        "name": resource.name,
        "description": resource.description,
        "publisher": resource.publisher,
        "formats": list(resource.formats),
        "updatedAt": resource.updated_at,
        "landingUrl": resource.landing_url,
        "sizeHint": resource.size_hint,
        "acquirable": bool(acquirable),
        "alreadyHeldDatasetId": already_held_dataset_id,
        "kind": resource.kind,
        "fileCount": resource.file_count,
        "fieldValues": [dict(row) for row in resource.fields],
        "samples": list(resource.samples),
    }


def resource_detail_row(
    detail: DiscoveryResourceDetail,
    *,
    source_name: str = "",
    acquirable: bool = True,
    already_held_dataset_id: str | None = None,
) -> dict[str, Any]:
    row = resource_row(
        detail.resource,
        source_name=source_name,
        acquirable=acquirable,
        already_held_dataset_id=already_held_dataset_id,
    )
    row["fields"] = [
        {"name": f.name, "type": f.type, "description": f.description}
        for f in detail.fields
    ]
    row["license"] = detail.license
    # Provider-specific extras (a WFS layer's CRS and bbox, say). Bounded to
    # simple values: this is the one field not enumerated key by key, so it
    # must not become a way for provider internals to reach a client.
    row["extra"] = {
        str(k): v
        for k, v in (detail.extra or {}).items()
        if isinstance(v, (str, int, float, bool, list)) and len(str(k)) <= 40
    }
    return row


def search_payload(
    rows: list[dict[str, Any]],
    *,
    sources: list[dict[str, Any]],
    next_cursor: str | None = None,
    total_hint: int | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    """A search response, federated or scoped.

    ``sources`` carries one entry per portal consulted with its own status, so
    a partial failure is data the UI can render honestly rather than an error
    that discards the rows that did arrive.
    """
    return {
        "resources": rows,
        "sources": sources,
        "nextCursor": next_cursor,
        "totalHint": total_hint,
        "truncated": bool(truncated),
    }
