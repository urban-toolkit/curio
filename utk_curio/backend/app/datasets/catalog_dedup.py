"""Merge and facet helpers for catalog listing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.constants import JUNK_SOURCE_LABELS, SUPPORTED_SUFFIXES
from utk_curio.backend.app.datasets.provenance import catalog_item_is_computed_provenance

def catalog_item_rank(item: dict[str, Any]) -> int:
    """Higher rank = richer catalog record (prefer when deduping by id)."""
    score = 0
    if item.get("dirName"):
        score += 8
    path_val = item.get("path") or ""
    if path_val and Path(path_val).is_absolute() and Path(path_val).is_file():
        score += 4
    if item.get("installed"):
        score += 2
    uri = item.get("uri") or ""
    if not uri.startswith("curio://outputs/"):
        score += 1
    return score

def merge_catalog_items(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge two catalog rows that share the same id."""
    winner = existing if catalog_item_rank(existing) >= catalog_item_rank(incoming) else incoming
    loser = incoming if winner is existing else existing
    merged = dict(winner)
    if loser.get("installed"):
        merged["installed"] = True
    if loser.get("needsReinstall"):
        merged["needsReinstall"] = True
    if not merged.get("dirName") and loser.get("dirName"):
        merged["dirName"] = loser["dirName"]
    if not merged.get("producerNodeId") and loser.get("producerNodeId"):
        merged["producerNodeId"] = loser["producerNodeId"]
    if not merged.get("publishedToHub") and loser.get("publishedToHub"):
        merged["publishedToHub"] = loser["publishedToHub"]
    # Hub registry rows do not carry ``publishedToHub``; merge must still reflect
    # that the dataset is listed in the committed Data Catalog when the same id
    # appears as a project ``computed`` / live row (or publish ran without ref sync).
    # But never resurrect it over an explicit ``publishedToHub == False`` (a
    # just-unpublished ref): a lingering hub row would otherwise keep a stale
    # "Published" badge until the next full refresh.
    explicitly_unpublished = (
        winner.get("publishedToHub") is False or loser.get("publishedToHub") is False
    )
    if not explicitly_unpublished and (
        winner.get("origin") == "hub" or loser.get("origin") == "hub"
    ):
        merged["publishedToHub"] = True
    # Prefer project provenance when the same id appears as hub (registry) + installed copy.
    win_o, los_o = winner.get("origin"), loser.get("origin")
    if merged.get("installed") and win_o == "hub" and los_o in ("imported", "computed", "source_node"):
        merged["origin"] = los_o
    elif merged.get("installed") and los_o == "hub" and win_o in ("imported", "computed", "source_node"):
        merged["origin"] = win_o
    # Node-produced rows must never pick up the global catalog listing subtitle.
    if (
        winner.get("origin") == "computed"
        or loser.get("origin") == "computed"
        or winner.get("producerNodeId")
        or loser.get("producerNodeId")
    ):
        merged["origin"] = "computed"
        pid = merged.get("producerNodeId") or winner.get("producerNodeId") or loser.get("producerNodeId")
        if pid:
            merged["producerNodeId"] = pid
        chosen_sl = None
        for cand in (winner, loser):
            if cand.get("origin") == "computed" or cand.get("producerNodeId"):
                lab = (cand.get("sourceLabel") or "").strip()
                if lab and lab.lower() not in JUNK_SOURCE_LABELS:
                    chosen_sl = cand.get("sourceLabel")
                    break
        merged["sourceLabel"] = chosen_sl or "Computed"
    return merged

def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for item in items:
        item_id = item.get("id")
        if not item_id:
            anonymous.append(item)
            continue
        prev = by_id.get(item_id)
        by_id[item_id] = item if prev is None else merge_catalog_items(prev, item)
    return [*by_id.values(), *anonymous]


def collapse_computed_by_file(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse computed datasets that resolve to the SAME data file.

    Two different producer nodes can end up installing the same underlying
    output (e.g. both auto-installing one shared artifact, or the same output
    installed under two node ids). Each is a distinct ``computed.<node>`` id, so
    ``dedupe_items`` keeps both — and since the title is derived from the file
    name they render as duplicate, identically-named palette entries. Keep only
    the richest record per data file (by ``catalog_item_rank``).

    Only ``computed`` rows are collapsed, and only when a concrete file path is
    known; everything else passes through untouched and order is preserved.
    """
    result: list[dict[str, Any]] = []
    index_by_file: dict[str, int] = {}
    for item in items:
        path_val = item.get("path") or ""
        key = Path(path_val).name if (item.get("origin") == "computed" and path_val) else None
        if key is None:
            result.append(item)
            continue
        existing_idx = index_by_file.get(key)
        if existing_idx is None:
            index_by_file[key] = len(result)
            result.append(item)
        elif catalog_item_rank(item) > catalog_item_rank(result[existing_idx]):
            # Prefer the richer record (installed/published/absolute path) but
            # keep the original position so ordering stays stable.
            result[existing_idx] = item
    return result


def catalog_facets(items: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    facets = {
        "origin": {"source_node": 0, "computed": 0, "imported": 0, "hub": 0},
        # ``bundle`` is a synthetic multi-output format with no file suffix, so it
        # isn't in ``SUPPORTED_SUFFIXES``; seed it explicitly so bundles are counted.
        "format": {fmt: 0 for fmt in sorted(set(SUPPORTED_SUFFIXES.values()) | {"bundle"})},
    }
    for item in items:
        fmt = item.get("format")
        if fmt in facets["format"]:
            facets["format"][fmt] += 1
        if catalog_item_is_computed_provenance(item):
            facets["origin"]["computed"] += 1
        else:
            raw_origin = item.get("origin")
            if raw_origin in facets["origin"]:
                facets["origin"][raw_origin] += 1
    return facets
