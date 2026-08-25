"""The one node-context composer (memo dev/67-6).

Every content generation for a node — Solve children, the Node Builder's
Node Content Builder delegation, and the 67-9 sequence — receives the SAME
structured neighborhood: the node's intent and current content, its nearest
upstream/downstream nodes (goals, content lengths, runtime status from the
dev/67-2 journal), the graph summary, and the dataset references. One
composer, so no per-caller context drift; bounded, so it can never crowd a
child prompt.

Honesty rules: a neighbor that never executed says ``never-executed`` —
nothing here fabricates schemas or results; ``outputSchema`` joins when the
runtime journal starts capturing column metadata (recorded 67-2 follow-up).
"""

from __future__ import annotations

from utk_curio.backend.app.execution import runtime_journal

_MAX_NEIGHBORS = 8
_GOAL_MAX_CHARS = 200
_INTENT_MAX_CHARS = 300
_CONTENT_MAX_CHARS = 6000
_MAX_DATASETS = 12
_CONTENT_TRUNCATION_MARKER = "\n…[truncated: content exceeds the context bound]"


def _neighbors(adjacency: dict[str, list[str]], start: str) -> list[str]:
    """Nearest-first BFS from *start*, capped at ``_MAX_NEIGHBORS``."""
    out: list[str] = []
    seen = {start}
    frontier = [start]
    while frontier and len(out) < _MAX_NEIGHBORS:
        next_frontier: list[str] = []
        for node_id in frontier:
            for neighbor in adjacency.get(node_id, []):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                out.append(neighbor)
                next_frontier.append(neighbor)
                if len(out) >= _MAX_NEIGHBORS:
                    return out
        frontier = next_frontier
    return out


def compose_node_context(
    user_key: str, project_id: str, spec: dict | None, node_id: str
) -> dict | None:
    """The structured context for generating/modifying one node's content,
    or ``None`` when the node is not in the spec (the caller reports that
    honestly rather than composing against a ghost)."""
    dataflow = (spec or {}).get("dataflow") or {}
    nodes = {
        n.get("id"): n for n in dataflow.get("nodes") or [] if isinstance(n, dict)
    }
    node = nodes.get(node_id)
    if node is None:
        return None
    edges = [e for e in dataflow.get("edges") or [] if isinstance(e, dict)]
    forward: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = {}
    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        if source in nodes and target in nodes:
            forward.setdefault(source, []).append(target)
            reverse.setdefault(target, []).append(source)
    runtime = runtime_journal.status_map(user_key, project_id)

    def _status(nid: str) -> str:
        return (runtime.get(nid) or {}).get("status") or "never-executed"

    def _row(nid: str) -> dict:
        neighbor = nodes[nid]
        content_text = str(neighbor.get("content") or "")
        return {
            "id": nid,
            "type": neighbor.get("type"),
            "goal": str(neighbor.get("goal") or "")[:_GOAL_MAX_CHARS],
            "hasContent": bool(content_text.strip()),
            "contentChars": len(content_text),
            "runtimeStatus": _status(nid),
        }

    current = str(node.get("content") or "")
    if len(current) > _CONTENT_MAX_CHARS:
        current = current[:_CONTENT_MAX_CHARS] + _CONTENT_TRUNCATION_MARKER
    datasets = []
    for entry in (dataflow.get("datasets") or [])[:_MAX_DATASETS]:
        if isinstance(entry, dict):
            datasets.append(
                {
                    "id": entry.get("id"),
                    "name": (entry.get("name") or entry.get("title") or "")[:_GOAL_MAX_CHARS],
                }
            )
    return {
        "nodeId": node_id,
        "nodeType": node.get("type"),
        "intent": str(node.get("goal") or "")[:_INTENT_MAX_CHARS],
        "currentContent": current,
        "runtimeStatus": _status(node_id),
        "upstream": [_row(nid) for nid in _neighbors(reverse, node_id)],
        "downstream": [_row(nid) for nid in _neighbors(forward, node_id)],
        "graphSummary": {
            "name": dataflow.get("name"),
            "goal": dataflow.get("task"),
            "nodes": len(nodes),
            "edges": len(edges),
        },
        "datasetRefs": datasets,
    }
