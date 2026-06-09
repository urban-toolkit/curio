"""Merge and facet helpers for catalog listing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.constants import SUPPORTED_SUFFIXES
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
    if winner.get("origin") == "hub" or loser.get("origin") == "hub":
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
        bad_sl = frozenset(
            {"data catalog", "data hub", "current dataflow", "current workflow"},
        )
        for cand in (winner, loser):
            if cand.get("origin") == "computed" or cand.get("producerNodeId"):
                lab = (cand.get("sourceLabel") or "").strip()
                if lab and lab.lower() not in bad_sl:
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


def catalog_facets(items: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    facets = {
        "origin": {"source_node": 0, "computed": 0, "imported": 0, "hub": 0},
        "format": {fmt: 0 for fmt in sorted(set(SUPPORTED_SUFFIXES.values()))},
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
