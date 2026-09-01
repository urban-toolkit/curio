"""Present the per-layer datasets of one OSM PBF import as a single grouped,
bundle-shaped catalog entry.

The layers are stored as independent GeoParquet datasets (each with a shared
``groupId``); this module folds them into one synthetic catalog item whose id IS
the group id and whose ``format`` is ``"bundle"`` - so the existing bundle card
and tabbed preview UI render it, and install/uninstall expand to the members.
"""

from __future__ import annotations

import re
from typing import Any

from utk_curio.backend.app.datasets.domain.catalog_item import base_item
from utk_curio.backend.app.datasets.domain.constants import OSM_LAYER_ORDER
from utk_curio.backend.app.datasets.infrastructure.catalog_utils import iso_from_timestamp

# Strips a trailing " (points)" / " (multipolygons)" layer suffix from a member
# title to recover the import's base name.
_LAYER_SUFFIX_RE = re.compile(r"\s*\([^)]*\)\s*$")


def sort_group_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order members by the canonical OSM layer order for stable tabs."""
    return sorted(
        members,
        key=lambda m: (
            OSM_LAYER_ORDER.get((m.get("layerName") or "").lower(), 99),
            m.get("layerName") or "",
        ),
    )


def group_base_title(members: list[dict[str, Any]], group_id: str) -> str:
    raw = (members[0].get("title") or "") if members else ""
    return _LAYER_SUFFIX_RE.sub("", raw).strip() or group_id


def build_osm_group_item(group_id: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the synthetic bundle-shaped catalog item for an OSM layer group.

    ``installed`` is true only when *every* layer is installed in the open
    dataflow, so the group's install pill reflects the "install all layers"
    action. Does not set ``groupId`` on the group item itself (its id is the
    group id) so re-collapsing is a no-op.
    """
    members = sort_group_members(members)
    total_features = sum(m.get("featureCount") or 0 for m in members) or None
    total_size = sum(m.get("sizeBytes") or 0 for m in members) or None
    updated = max((m.get("updatedAt") or "" for m in members), default="") or iso_from_timestamp()
    installed = bool(members) and all(m.get("installed") for m in members)
    bundle_parts = [
        {
            "label": m.get("layerName") or m.get("title"),
            "format": m.get("format"),
            "kind": "geodataframe",
        }
        for m in members
    ]
    return base_item(
        id=group_id,
        title=group_base_title(members, group_id),
        description=f"OpenStreetMap import - {len(members)} layer(s).",
        origin="imported",
        # Displayed as an OSM PBF type (not a generic bundle); the tabbed preview
        # is driven by the preview response's ``bundle`` flag, not this format.
        format="osm",
        uri=f"curio://osm/{group_id}",
        sizeBytes=total_size,
        featureCount=total_features,
        updatedAt=updated,
        sourceLabel="OSM Import",
        tags=["osm", "pbf"],
        schema={"bundleParts": bundle_parts},
        installed=installed,
        # Real per-layer dataset ids, so the client can install/uninstall each
        # member (keeping its dataflow refs accurate) rather than the synthetic
        # group id.
        groupLayerIds=[m.get("id") for m in members if m.get("id")],
    )


def collapse_osm_groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace each set of grouped member items with one synthetic group item,
    preserving first-seen order. Items without a ``groupId`` pass through."""
    out: list[dict[str, Any]] = []
    members_by_group: dict[str, list[dict[str, Any]]] = {}
    slot_by_group: dict[str, int] = {}
    for item in items:
        group_id = item.get("groupId")
        if not group_id:
            out.append(item)
            continue
        if group_id not in members_by_group:
            members_by_group[group_id] = []
            slot_by_group[group_id] = len(out)
            out.append(item)  # placeholder, replaced below
        members_by_group[group_id].append(item)
    for group_id, members in members_by_group.items():
        out[slot_by_group[group_id]] = build_osm_group_item(group_id, members)
    return out
