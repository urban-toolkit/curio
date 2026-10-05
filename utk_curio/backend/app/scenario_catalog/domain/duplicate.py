"""Duplicate selection (#662), on the saved shape of a dataflow.

The twin of ``duplicateSelection`` in ``src/utils/scenarios/duplicateSelection.ts``,
which the canvas's Duplicate selection runs. A Dataflow Builder plan's
duplicate copies a selection of its nodes through this one, so both copy the
same way:

* the selected nodes are copied with fresh ids, in dataflow order;
* the edges between them are copied, and every edge that enters the selection
  from outside is wired into the copy too, so the copy reads the same context;
* an edge that leaves the selection is not copied: what reads the original
  keeps reading it, and a link from a view outside the selection is not data
  the copy reads;
* each copy names where it came from at ``metadata.copiedFrom``: the
  original's own lineage, then the original.

Both sides read one table of cases, ``duplicateSelection.cases.json`` beside
the TypeScript module.
"""
from __future__ import annotations

import copy as _copy
from typing import Callable, Iterable

#: What a copy no longer carries: a copy is not a dashboard tile until someone
#: pins it.
_DASHBOARD_KEYS = ("dashboardPinned", "dashboardX", "dashboardY")


def lineage_of(node: dict) -> list[str]:
    """The ids *node* descends from, oldest first; anything else is dropped."""
    raw = (node.get("metadata") or {}).get("copiedFrom") if isinstance(node.get("metadata"), dict) else None
    return [i for i in raw if isinstance(i, str) and i] if isinstance(raw, list) else []


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_interaction(edge: dict) -> bool:
    return edge.get("type") == "Interaction"


def duplicate_selection(
    nodes: Iterable[dict],
    edges: Iterable[dict],
    selected: Iterable[str],
    *,
    new_id: Callable[[], str],
    offset: dict | None = None,
) -> dict:
    """``{"nodes", "edges", "ids"}``: the copies, their edges, and each
    original id to its copy's (in dataflow order). *new_id* is asked for the
    copied nodes first, then for each copied edge."""
    wanted = set(selected)
    shift = offset or {"x": 0, "y": 0}
    originals = [n for n in nodes if isinstance(n, dict) and n.get("id") in wanted]
    ids = {node["id"]: new_id() for node in originals}

    copies: list[dict] = []
    for node in originals:
        twin = _copy.deepcopy(node)
        twin["id"] = ids[node["id"]]
        if _is_number(node.get("x")):
            twin["x"] = node["x"] + shift["x"]
        if _is_number(node.get("y")):
            twin["y"] = node["y"] + shift["y"]
        metadata = twin.get("metadata") if isinstance(twin.get("metadata"), dict) else {}
        twin["metadata"] = {**metadata, "copiedFrom": [*lineage_of(node), node["id"]]}
        for key in _DASHBOARD_KEYS:
            twin.pop(key, None)
        copies.append(twin)

    copied_edges: list[dict] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = ids.get(edge.get("source"))
        target = ids.get(edge.get("target"))
        if target is None:
            continue
        # A link between a view outside the selection and one in it is not
        # data the copy reads; one between two copied views is copied with them.
        if source is None and _is_interaction(edge):
            continue
        twin = _copy.deepcopy(edge)
        twin["id"] = new_id()
        twin["source"] = source if source is not None else edge.get("source")
        twin["target"] = target
        # Always explicit: without one, a load reads the circle from the edge id.
        handle = edge.get("targetHandle")
        twin["targetHandle"] = handle if handle is not None else ("in/out" if _is_interaction(edge) else "in")
        copied_edges.append(twin)
    return {"nodes": copies, "edges": copied_edges, "ids": ids}
