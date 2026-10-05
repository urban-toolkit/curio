"""Present the per-layer datasets of one multi-layer import as a single grouped,
bundle-shaped catalog entry.

Two importers produce these: OSM PBF extracts and GeoPackages; and the
Discovery Catalog does, for an OpenStreetMap download of several layers and for
a GTFS feed. In every case the layers are stored as independent datasets
sharing a ``groupId``, and
this module folds them into one synthetic catalog item whose id IS the group id,
so the existing bundle card and tabbed preview UI render it and install/uninstall
expand to the members.

What the card *says* comes from the group id's prefix rather than being assumed:
a GeoPackage labelled "OpenStreetMap import" with an ``osm`` format badge would
be wrong on screen, which is the whole reason the kind is carried in the id.
A group whose layers were all downloaded from the Discovery Catalog says what
its layers say, as a single download's card does, and so does a group whose
layers all ship in the catalog every account shares.

NetCDF variables stored a file each form a group too (``netcdf.``): their
manifests carry the group id and each variable's name as its ``layerName``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from utk_curio.backend.app.datasets.domain.catalog_item import (
    KEPT_IN_CODE,
    LOADED_VARIABLES,
    base_item,
    is_safe_dataset_id,
    loader_snippet,
)
from utk_curio.backend.app.datasets.domain.constants import OSM_LAYER_ORDER, layer_group_kind
from utk_curio.backend.app.datasets.infrastructure.catalog_utils import iso_from_timestamp

# Strips a trailing " (points)" / " (multipolygons)" layer suffix from a member
# title to recover the import's base name.
_LAYER_SUFFIX_RE = re.compile(r"\s*\([^)]*\)\s*$")


#: How each kind of layer group describes itself on its card.
_GROUP_KINDS = {
    "osm": {
        "format": "osm",
        "scheme": "osm",
        "source_label": "OSM Import",
        "tags": ["osm", "pbf"],
        "noun": "OpenStreetMap import",
    },
    "gpkg": {
        "format": "gpkg",
        "scheme": "gpkg",
        "source_label": "GeoPackage Import",
        "tags": ["gpkg", "geopackage"],
        "noun": "GeoPackage import",
    },
    # The tables of a GTFS feed the Discovery Catalog downloaded. Its layers are
    # Parquet like a GeoPackage's, so the feed is what the group says it is.
    "gtfs": {
        "format": "gtfs",
        "scheme": "gtfs",
        "source_label": "GTFS Download",
        "tags": ["gtfs", "transit"],
        "noun": "GTFS feed",
        "always_its_own_format": True,
    },
    # NetCDF variables, a file each, as a WRF run writes them.
    "netcdf": {
        "format": "netcdf",
        "scheme": "netcdf",
        "source_label": "NetCDF Import",
        "tags": ["netcdf"],
        "noun": "NetCDF dataset",
        "parts": "variable(s)",
    },
}


def _shared_catalog_member(member: dict[str, Any]) -> bool:
    """A layer that ships in the catalog every account on this Curio shares:
    its hub row, or the copy of it a project installed, whose folder is a
    ``data.*`` one. Mirrors ``isSharedCatalogDataset`` in
    ``datasetCatalogTypes.ts``."""
    return member.get("origin") == "hub" or str(member.get("dirName") or "").startswith("data.")


def _members_loader_snippet(fmt: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    """Every member read by its own id into one ``layers`` dict, keyed by its
    layer name, as the canvas palette's group drag reads them
    (``osmGroupLoaderSnippet`` in ``datasetLoaderSnippets.ts``). Returned
    unless *fmt* is kept in the node's code."""
    lines = ["layers = {}"]
    for index, member in enumerate(members):
        member_id = member.get("id")
        if not is_safe_dataset_id(member_id):
            continue
        key = member.get("layerName") or member.get("title") or f"layer_{index}"
        lines.append(f"layers[{json.dumps(key)}] = curio_load_data({json.dumps(member_id)})")
    return {
        "language": "python",
        "imports": [],
        "pathVariable": "layers",
        "code": "\n".join(lines),
        "returnVariable": None if fmt in KEPT_IN_CODE else "layers",
    }


def sort_group_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order members for stable tabs.

    OSM layer names are a closed, meaningful set, so they keep their canonical
    order. Anything else, GeoPackage layers included, sorts by name: the map
    returns 99 for an unlisted name, so the secondary key decides.
    """
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


def build_layer_group_item(group_id: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the synthetic bundle-shaped catalog item for a layer group.

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
    kind = _GROUP_KINDS.get(layer_group_kind(group_id) or "osm", _GROUP_KINDS["osm"])
    # Displayed as its own type (not a generic bundle); the tabbed preview is
    # driven by the preview response's ``bundle`` flag, not this format. Layers
    # downloaded from the Discovery Catalog: the group says what each of them
    # says (format, source label, tags, where they came from), as a single
    # download's card does. Layers that ship in the shared catalog give the
    # group their source label and tags, and it keeps its kind's format, as
    # the canvas palette shows it (``layerGroupFormat``). An upload says what
    # its file was.
    downloaded = bool(members) and all(m.get("discoverySource") for m in members)
    shipped = bool(members) and all(_shared_catalog_member(m) for m in members)
    labels = (
        {
            "format": members[0].get("format"),
            "sourceLabel": members[0].get("sourceLabel"),
            "tags": list(members[0].get("tags") or []),
            "discoverySource": members[0].get("discoverySource"),
        }
        if downloaded or shipped
        else {
            "format": kind["format"],
            "sourceLabel": kind["source_label"],
            "tags": list(kind["tags"]),
        }
    )
    if kind.get("always_its_own_format") or (shipped and not downloaded):
        # A GTFS feed is always a download, and its tables' Parquet says
        # nothing about it; the group says GTFS.
        labels["format"] = kind["format"]
    # The group's loader is its kind's, whatever format it shows. A kind that
    # is itself a format ``curio_load_data`` reads (NetCDF) reads each member by
    # its own id instead, since the group id names no file.
    loader = (
        _members_loader_snippet(kind["format"], members)
        if kind["format"] in LOADED_VARIABLES
        else loader_snippet(kind["format"], None, dataset_id=group_id)
    )
    return base_item(
        id=group_id,
        title=group_base_title(members, group_id),
        description=f"{kind['noun']} - {len(members)} {kind.get('parts', 'layer(s)')}.",
        origin="hub" if shipped else "imported",
        uri=f"curio://{kind['scheme']}/{group_id}",
        loaderSnippet=loader,
        sizeBytes=total_size,
        featureCount=total_features,
        updatedAt=updated,
        **labels,
        schema={"bundleParts": bundle_parts},
        installed=installed,
        # Real per-layer dataset ids, so the client can install/uninstall each
        # member (keeping its dataflow refs accurate) rather than the synthetic
        # group id.
        groupLayerIds=[m.get("id") for m in members if m.get("id")],
    )


def collapse_layer_groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        out[slot_by_group[group_id]] = build_layer_group_item(group_id, members)
    return out
