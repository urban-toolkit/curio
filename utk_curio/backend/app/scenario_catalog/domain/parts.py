"""What a scenario is made of, read from a saved spec (#662), by role.

The twin of ``scenarioParts`` in ``src/utils/scenarios/scenarioParts.ts``,
which reads the live canvas. For one scenario of a dataflow:

* ``nodes``, its Scenario-specific nodes, in the scenario's order;
* ``last``, its own last nodes: those of its nodes whose output nothing in it
  reads, or that something outside it reads, the results it shows;
* ``context``, its Shared context: the nodes upstream of it, outside every
  scenario's box, that it keeps (``projects/scenario_sets.py``);
* ``outcomes``, its Shared outcomes: the nodes downstream of it, outside every
  box, that it keeps;
* ``boundary``, the nodes whose output crosses into it, or into one of its
  shared outcomes from outside every box and every shared outcome: the
  context a drop brings as data.

The canvas and the Scenario Catalog's details show the whole shared context
and shared outcomes. What saves its output because of a scenario is what
stands for its boundary, its own last nodes and its shared outcomes, and
nothing else (:func:`scenario_source_node_ids`): a pass-through (a chart, a
Data Pool, a drawing Autark node) saves nothing itself, and
:func:`saved_sources` resolves it to the nodes feeding it, the walk pinned
dashboard tiles use (``producersFeeding`` in ``utils/dashboardLayout.ts``).

Both sides read one table of cases, ``scenarioParts.cases.json`` beside the
TypeScript module.
"""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Optional

from utk_curio.backend.app.projects.dashboard_payload import passes_through
from utk_curio.backend.app.projects.scenario_sets import infer_context_outcomes

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


def scenario_parts(scenario: dict, nodes: list[dict], edges: list[dict], scenarios: list[dict]) -> dict:
    """``{"nodes", "last", "context", "outcomes", "boundary"}`` for
    *scenario*, one of the dataflow's *scenarios*, as ids of *nodes*: its own
    nodes and its last nodes in its order, the rest in the dataflow's.

    A node that is not among *nodes* is left out, and so is a node of a box
    from its context and outcomes. A context or outcomes list the scenario does
    not keep is the one Curio infers for it (``infer_context_outcomes``), as a
    save fills it in.
    """
    by_id = {n["id"]: n for n in nodes}
    order = [n["id"] for n in nodes]
    own: list[str] = []
    for node_id in scenario.get("nodes") or []:
        if node_id in by_id and node_id not in own:
            own.append(node_id)
    members = set(own)
    boxed = members | {i for s in scenarios for i in s.get("nodes") or []}
    links = [
        e for e in edges
        if not _is_interaction(e) and e["source"] in by_id and e["target"] in by_id
    ]

    kept: dict[str, list[str]] = {}
    inferred = None
    for key in ("context", "outcomes"):
        given = scenario.get(key)
        if not isinstance(given, list):
            inferred = inferred or infer_context_outcomes(own, order, links, boxed)
            given = inferred[key]
        listed = {i for i in given if isinstance(i, str)}
        kept[key] = [i for i in order if i in listed and i not in boxed]

    outcomes = set(kept["outcomes"])
    every_outcome = outcomes | {
        i for s in scenarios for i in s.get("outcomes") or [] if isinstance(i, str)
    }
    boundary: set[str] = set()
    read_inside: set[str] = set()
    read_outside: set[str] = set()
    for edge in links:
        source, target = edge["source"], edge["target"]
        if source in members:
            (read_inside if target in members else read_outside).add(source)
        if target in members and source not in members:
            boundary.add(source)
        elif target in outcomes and source not in boxed and source not in every_outcome:
            boundary.add(source)
    return {
        "nodes": own,
        "last": [i for i in own if i not in read_inside or i in read_outside],
        "context": kept["context"],
        "outcomes": kept["outcomes"],
        "boundary": [i for i in order if i in boundary],
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
    sources of each scenario's boundary, its own last nodes and its shared
    outcomes, so a drop into another project brings them and the Scenario
    Catalog shows them. The twin
    of ``scenarioSourceNodeIds``; a run on the server adds them to the pinned
    tiles' sources, as ``savedSourceNodeIds`` does. The scenarios are read as
    a save keeps them (``kept_scenarios``). *packages* reads the manifests
    (``TemplateGrammars.for_account()`` when None)."""
    from utk_curio.backend.app.projects.scenarios import kept_scenarios

    packages = _catalog_templates(packages)
    nodes, edges = spec_nodes_and_edges(spec)
    scenarios, _sets = kept_scenarios(spec)
    sources: set[str] = set()
    for scenario in scenarios:
        parts = scenario_parts(scenario, nodes, edges, scenarios)
        for node_id in [*parts["boundary"], *parts["last"], *parts["outcomes"]]:
            sources.update(saved_sources(node_id, nodes, edges, packages))
    return sources
