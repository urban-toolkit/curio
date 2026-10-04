"""What a scenario is made of, read from a saved spec (#662).

The twin of ``scenarioParts`` in ``src/utils/scenarios/scenarioParts.ts``,
which reads the live canvas:

* its levers, the nodes in it, in the scenario's order;
* its fixed context, the nodes outside it that it reads, through an edge into
  it or through a shared tag (``[!! @name !!]``) its code names;
* its outcomes, the levers whose output nothing in it reads, or that something
  outside it reads. A Parameter node has no output, so it is never one.

A pass-through (a chart, a Data Pool, a drawing Autark node) saves nothing
itself; :func:`saved_sources` resolves it to the nodes feeding it, the walk
pinned dashboard tiles use (``producersFeeding`` in ``utils/dashboardLayout.ts``).

Both sides read one table of cases, ``scenarioParts.cases.json`` beside the
TypeScript module.
"""
from __future__ import annotations

from collections import deque

from utk_curio.backend.app.datasets.domain.code_refs import node_code
from utk_curio.backend.app.execution.code_references import normalize_shared, shared_names_in
from utk_curio.backend.app.execution.workflow_spec import PARAMETER_TYPE
from utk_curio.backend.app.projects.dashboard_payload import (
    _AUTK_GRAMMAR_KIND,
    _PASS_THROUGH_KINDS,
    _classify_autk_spec,
    _unversioned,
)


def _template(node: dict) -> str:
    """``curio.builtin/parameter@1`` -> ``curio.builtin/parameter``."""
    return str(node.get("type") or "").split("@", 1)[0]


def is_parameter_node(node: dict) -> bool:
    return _template(node) == PARAMETER_TYPE


def is_pass_through(node: dict) -> bool:
    """Whether a saved spec's *node* shows data it is handed rather than
    making its own: a chart, a Data Pool, or an Autark spec that draws."""
    kind = _unversioned(node.get("type"))
    if kind in _PASS_THROUGH_KINDS:
        return True
    if kind == _AUTK_GRAMMAR_KIND:
        return _classify_autk_spec(node_code(node)) == "render"
    return False


def _is_interaction(edge: dict) -> bool:
    """A two-way link between views, which a run does not follow."""
    return edge.get("type") == "Interaction" or (
        edge.get("sourceHandle") == "in/out" and edge.get("targetHandle") == "in/out"
    )


def spec_nodes_and_edges(spec: object) -> tuple[list[dict], list[dict]]:
    """A saved spec's nodes and edges, the malformed ones left out."""
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict):
        return [], []
    nodes = [n for n in dataflow.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("id"), str)]
    edges = [
        e for e in dataflow.get("edges") or []
        if isinstance(e, dict) and isinstance(e.get("source"), str) and isinstance(e.get("target"), str)
    ]
    return nodes, edges


def scenario_parts(scenario: dict, nodes: list[dict], edges: list[dict]) -> dict:
    """``{"levers", "context", "outcomes"}`` for *scenario*, as node ids.

    Members that are not among *nodes* are left out.
    """
    by_id = {n["id"]: n for n in nodes}
    levers: list[str] = []
    for node_id in scenario.get("nodes") or []:
        if node_id in by_id and node_id not in levers:
            levers.append(node_id)
    members = set(levers)

    context: set[str] = set()
    read_inside: set[str] = set()
    read_outside: set[str] = set()
    for edge in edges:
        if _is_interaction(edge) or edge["source"] not in by_id or edge["target"] not in by_id:
            continue
        from_inside = edge["source"] in members
        to_inside = edge["target"] in members
        if not from_inside and to_inside:
            context.add(edge["source"])
        elif from_inside and to_inside:
            read_inside.add(edge["source"])
        elif from_inside and not to_inside:
            read_outside.add(edge["source"])

    named = {name for node_id in levers for name in shared_names_in(node_code(by_id[node_id]))}
    if named:
        for node in nodes:
            if node["id"] in members or not is_parameter_node(node):
                continue
            widgets = normalize_shared((node.get("metadata") or {}).get("widgets"))
            if any(widget["name"] in named for widget in widgets):
                context.add(node["id"])

    outcomes = [
        node_id for node_id in levers
        if not is_parameter_node(by_id[node_id])
        and (node_id not in read_inside or node_id in read_outside)
    ]
    return {
        "levers": levers,
        "context": [n["id"] for n in nodes if n["id"] in context],
        "outcomes": outcomes,
    }


def producers_feeding(ids: list[str], nodes: list[dict], edges: list[dict]) -> set[str]:
    """The nodes that make the data reaching *ids*: walking up from each, the
    first node on every path that is not a pass-through. *ids* themselves are
    not in the set. Breadth-first with a visited set, so a cycle ends."""
    by_id = {n["id"]: n for n in nodes}
    incoming: dict[str, list[str]] = {}
    for edge in edges:
        incoming.setdefault(edge["target"], []).append(edge["source"])
    sources: set[str] = set()
    queue = deque(ids)
    visited: set[str] = set()
    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        for source_id in incoming.get(node_id, []):
            node = by_id.get(source_id)
            if node is None:
                continue
            if is_pass_through(node):
                queue.append(source_id)
            else:
                sources.add(source_id)
    return sources


def saved_sources(node_id: str, nodes: list[dict], edges: list[dict]) -> list[str]:
    """The nodes whose saved output stands for *node_id*'s, in dataflow order:
    itself, or for a pass-through the nodes feeding it. A Parameter node's
    value is in the spec, so it has none."""
    by_id = {n["id"]: n for n in nodes}
    node = by_id.get(node_id)
    if node is None or is_parameter_node(node):
        return []
    if not is_pass_through(node):
        return [node_id]
    feeding = producers_feeding([node_id], nodes, edges)
    return [n["id"] for n in nodes if n["id"] in feeding]
