"""The order a run on the server follows, decided as Run All decides it.

- :func:`is_interaction_edge`: a two-way link between charts carries a
  selection, not data, so a run never orders nodes by it. The canvas knows one
  by its ``in/out`` handles; a saved dataflow also types it ``Interaction``.
- :func:`topological_levels` is the twin of ``computeTopologicalLevels`` in
  ``providers/flow/runLevels.ts``: nodes with no edge at all first, then the
  roots that feed something, then each level whose inputs are all done.
  ``runLevels.cases.json`` beside the TypeScript holds the cases both run.
- :func:`ancestors` is the slice ``playNodesUpTo`` runs for one node.
- :func:`node_role`: what a run does with a node. ``run`` executes it in the
  sandbox; ``forward`` passes its input on, as a chart, a pool or a download
  does on the canvas, or has nothing to run, as a Parameter node, whose value
  reaches the nodes that name it through their code; ``browser`` makes data only the browser can
  (an Autark data or compute node, a Spatial Join), so nothing below it can run
  until a tab does.
"""
from __future__ import annotations

from typing import Iterable

INTERACTION_HANDLE = "in/out"

#: Node kinds a run forwards besides the pass-through kinds of a dashboard walk:
#: a Data Export only offers a download, and a Parameter node only holds a
#: value; neither has anything to run.
_FORWARD_KINDS = frozenset({"data-export", "parameter"})


def is_interaction_edge(edge: dict) -> bool:
    if edge.get("type") == "Interaction":
        return True
    return (
        edge.get("sourceHandle") == INTERACTION_HANDLE
        and edge.get("targetHandle") == INTERACTION_HANDLE
    )


def directed_edges(edges: Iterable[dict]) -> list[dict]:
    """The edges a run orders nodes by: every edge but an interaction link."""
    return [e for e in edges if isinstance(e, dict) and not is_interaction_edge(e)]


def topological_levels(node_ids: list[str], edges: Iterable[dict]) -> list[list[str]]:
    """The levels a run executes, one after another (``computeTopologicalLevels``).

    A node inside a cycle is in no level. Edges with an end outside *node_ids*
    are ignored.
    """
    known = set(node_ids)
    in_degree = {node_id: 0 for node_id in node_ids}
    successors: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in directed_edges(edges):
        source, target = edge.get("source"), edge.get("target")
        if source not in known or target not in known:
            continue
        in_degree[target] += 1
        successors[source].append(target)

    roots = [node_id for node_id in node_ids if in_degree[node_id] == 0]
    isolated = [node_id for node_id in roots if not successors[node_id]]
    sources = [node_id for node_id in roots if successors[node_id]]
    if not isolated and not sources:
        return []

    levels: list[list[str]] = []
    if isolated:
        levels.append(isolated)
    if sources:
        levels.append(sources)
    remaining = dict(in_degree)
    visited = set(isolated) | set(sources)
    queue = sources
    while queue:
        following: list[str] = []
        for node_id in queue:
            for successor in successors[node_id]:
                remaining[successor] -= 1
                if remaining[successor] == 0 and successor not in visited:
                    following.append(successor)
                    visited.add(successor)
        if following:
            levels.append(following)
        queue = following
    return levels


def ancestors(target_id: str, edges: Iterable[dict]) -> set[str]:
    """*target_id* and every node it reads from, through data edges."""
    predecessors: dict[str, list[str]] = {}
    for edge in directed_edges(edges):
        predecessors.setdefault(edge.get("target"), []).append(edge.get("source"))
    wanted = {target_id}
    frontier = [target_id]
    while frontier:
        node_id = frontier.pop()
        for source in predecessors.get(node_id, []):
            if source not in wanted:
                wanted.add(source)
                frontier.append(source)
    return wanted


def node_role(node: dict, templates: dict | None = None) -> str:
    """``run``, ``forward`` or ``browser`` for a node as a saved dataflow holds it."""
    from utk_curio.backend.app.execution.workflow_spec import is_executable_kind
    from utk_curio.backend.app.projects.dashboard_payload import _is_pass_through, _node_kind

    if is_executable_kind(node.get("type"), templates):
        return "run"
    if _is_pass_through(node) or _node_kind(node) in _FORWARD_KINDS:
        return "forward"
    return "browser"
