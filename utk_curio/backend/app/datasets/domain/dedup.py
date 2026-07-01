"""Merge and facet helpers for catalog listing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utk_curio.backend.app.datasets.domain.constants import JUNK_SOURCE_LABELS, SUPPORTED_SUFFIXES
from utk_curio.backend.app.datasets.domain.provenance import catalog_item_is_computed_provenance

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
        # When a computed dataset was published, its hub-registry copy keeps the
        # node id and a STALE file/name captured at publish time. On re-execution
        # the live/local record (origin "computed") carries the CURRENT output —
        # prefer its identity fields (including ``path``) so the palette and drawer
        # show the same, current dataset instead of the stale published name/file.
        live_cand = next(
            (c for c in (winner, loser) if c.get("origin") == "computed"),
            None,
        )
        if live_cand is not None:
            # ``fileName`` travels with ``title`` so the pair stays from the same
            # (live) record — otherwise a live title + stale hub fileName mismatch
            # would defeat the "title is the generated filename" check downstream.
            for field in ("title", "fileName", "updatedAt", "path", "dirName", "uri", "loaderSnippet"):
                if live_cand.get(field):
                    merged[field] = live_cand[field]
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


# NOTE: there is intentionally no "collapse computed datasets by data-file
# basename" step. Distinct saved records (e.g. an Autark map output and its
# baseline-/modified-compute siblings) live in their own ``computed.<node>@1``
# dirs with distinct ids but often share a generated filename; collapsing by
# basename silently hid all but one until the others were deleted. The only
# legitimate duplicates — the same dataset's hub registry row and its
# installed/live copy — share a dataset ``id`` and are merged by ``dedupe_items``.


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
