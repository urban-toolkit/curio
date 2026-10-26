"""What a scenario is made of, read from a saved spec (#662).

The twin of ``scenarioParts`` in ``src/utils/scenarios/scenarioParts.ts``,
which reads the live canvas:

* its levers, the nodes in it, in the scenario's order;
* its fixed context, the nodes outside it that it reads, through an edge into
  it;
* its outcomes, the levers whose output nothing in it reads, or that something
  outside it reads.

A pass-through (a chart, a Data Pool, a drawing Autark node) saves nothing
itself; :func:`saved_sources` resolves it to the nodes feeding it, the walk
pinned dashboard tiles use (``producersFeeding`` in ``utils/dashboardLayout.ts``).

Both sides read one table of cases, ``scenarioParts.cases.json`` beside the
TypeScript module.
"""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Optional

from utk_curio.backend.app.projects.dashboard_payload import passes_through

if TYPE_CHECKING:
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars


def _template(node: dict) -> str:
    """``curio.builtin/data-loading@1`` -> ``curio.builtin/data-loading``."""
    return str(node.get("type") or "").split("@", 1)[0]


def _catalog_templates(packages: Optional["TemplateGrammars"]) -> "TemplateGrammars":
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

    return packages or TemplateGrammars.for_account()


def is_pass_through(node: dict, packages: Optional["TemplateGrammars"] = None) -> bool:
    """Whether a saved spec's *node* shows data it is handed rather than
    making its own: a node whose template declares a chart's or a Data Pool's
    behavior (or draws with the Vega-Lite grammar), or an Autark spec that
    draws. The dashboard walk's rule (``dashboard_payload.passes_through``).
    *packages* reads the manifests (``TemplateGrammars.for_account()`` when None)."""
    return passes_through(node, packages)


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

    outcomes = [node_id for node_id in levers if node_id not in read_inside or node_id in read_outside]
    return {
        "levers": levers,
        "context": [n["id"] for n in nodes if n["id"] in context],
        "outcomes": outcomes,
    }


def producers_feeding(
    ids: list[str], nodes: list[dict], edges: list[dict],
    packages: Optional["TemplateGrammars"] = None,
) -> set[str]:
    """The nodes that make the data reaching *ids*: walking up from each, the
    first node on every path that is not a pass-through. *ids* themselves are
    not in the set. Breadth-first with a visited set, so a cycle ends.
    *packages* reads the manifests (``TemplateGrammars.for_account()`` when None)."""
    packages = _catalog_templates(packages)
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
            if is_pass_through(node, packages):
                queue.append(source_id)
            else:
                sources.add(source_id)
    return sources


def saved_sources(
    node_id: str, nodes: list[dict], edges: list[dict],
    packages: Optional["TemplateGrammars"] = None,
) -> list[str]:
    """The nodes whose saved output stands for *node_id*'s, in dataflow order:
    itself, or for a pass-through the nodes feeding it. *packages* reads the
    manifests (``TemplateGrammars.for_account()`` when None)."""
    by_id = {n["id"]: n for n in nodes}
    node = by_id.get(node_id)
    if node is None:
        return []
    packages = _catalog_templates(packages)
    if not is_pass_through(node, packages):
        return [node_id]
    feeding = producers_feeding([node_id], nodes, edges, packages)
    return [n["id"] for n in nodes if n["id"] in feeding]


def scenario_source_node_ids(spec: object, packages: Optional["TemplateGrammars"] = None) -> set[str]:
    """The nodes whose outputs a saved spec's scenarios need saved: the saved
    sources of each scenario's context and outcomes, so another project can
    read them. The twin of ``scenarioSourceNodeIds``; a run on the server adds
    them to the pinned tiles' sources, as ``savedSourceNodeIds`` does.
    *packages* reads the manifests (``TemplateGrammars.for_account()`` when None)."""
    packages = _catalog_templates(packages)
    nodes, edges = spec_nodes_and_edges(spec)
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    scenarios = (dataflow or {}).get("scenarios") if isinstance(dataflow, dict) else None
    sources: set[str] = set()
    for scenario in scenarios or []:
        if not isinstance(scenario, dict):
            continue
        parts = scenario_parts(scenario, nodes, edges)
        for node_id in [*parts["context"], *parts["outcomes"]]:
            sources.update(saved_sources(node_id, nodes, edges, packages))
    return sources
