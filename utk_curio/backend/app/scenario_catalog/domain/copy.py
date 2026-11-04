"""What dragging one scenario into another dataflow copies, read from its
project's spec (#662). The first drop of a set's scenario makes the set's copy
there; a later drop of another scenario of that set joins it.

* Its Scenario-specific nodes, with the edges between them and the edges
  entering them.
* The set's shared outcomes that land with it: those whose every input is in
  once it is (a node of it or of a scenario the copy holds, a context node
  arriving as data, or another outcome landing or landed).
* What crosses into those from outside, its boundary (``scenario_parts``),
  each context node once. A context node stands for the output it passes on,
  so it is the one node whose saved output (``saved_sources``) arrives as
  data. A context node that passes on several outputs, or none, cannot.
* The saved outputs that stand for the shared outcomes landing, so they show
  without a run.
* What the copied nodes need: their packages, datasets and models.
"""
from __future__ import annotations

from typing import Any

from utk_curio.backend.app.scenario_catalog.domain.duplicate import lineage_of
from utk_curio.backend.app.scenario_catalog.domain.parts import (
    _is_interaction,
    _template,
    saved_sources,
    scenario_parts,
)


def node_label(node: dict) -> str:
    """What a message calls *node*: its title, else its template's name."""
    from utk_curio.backend.app.execution.node_names import saved_node_title
    from utk_curio.backend.app.projects.services import _humanize_node_type

    label = saved_node_title(node)
    if label:
        return label
    return _humanize_node_type(_template(node)) or str(node.get("id"))


def copy_plan(
    scenario: dict, present: list[dict], scenarios: list[dict], nodes: list[dict], edges: list[dict], packages=None,
) -> dict[str, Any]:
    """What a drop of *scenario* copies, as node ids of its project, into a
    dataflow whose copy of its set holds *present* already (scenarios of that
    set). *scenarios* are every scenario of the project, as a save keeps them
    (``kept_scenarios``). *packages* (a ``TemplateGrammars``, the account's)
    reads what each node's template declares, ``TemplateGrammars.for_account()``
    when None.

    ``nodes`` are its own; ``shared`` the set's shared outcomes that land with
    it, each with the scenarios dragged or present that list it and the copied
    nodes whose saved outputs stand for it; ``context`` each node whose output
    crosses into what is copied, with the one node whose saved output stands
    for it (``source``), or ``sources`` when that is not one node; ``outcomes``
    the ids of its own shared outcomes."""
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

    by_id = {n["id"]: n for n in nodes}
    packages = packages or TemplateGrammars.for_account()
    order = {n["id"]: i for i, n in enumerate(nodes)}
    in_order = lambda ids: sorted(ids, key=lambda i: order[i])  # noqa: E731

    group = [scenario, *present]
    parts = {s["id"]: scenario_parts(s, nodes, edges, scenarios) for s in group}
    own = parts[scenario["id"]]["nodes"]
    boxed = {i for s in scenarios for i in s.get("nodes") or []}
    every_outcome = {i for s in scenarios for i in s.get("outcomes") or []}
    incoming: dict[str, list[str]] = {}
    for edge in edges:
        if _is_interaction(edge) or edge["source"] not in by_id or edge["target"] not in by_id:
            continue
        incoming.setdefault(edge["target"], []).append(edge["source"])

    single: dict[str, str | None] = {}

    def source_of(node_id: str) -> str | None:
        if node_id not in single:
            found = saved_sources(node_id, nodes, edges, packages)
            single[node_id] = found[0] if len(found) == 1 else None
        return single[node_id]

    def is_context(node_id: str) -> bool:
        return node_id not in boxed and node_id not in every_outcome

    def landed(scenarios_in: list[dict]) -> set[str]:
        """The shared outcomes of *scenarios_in* whose every input is in with
        them. Read to a fixpoint, so an outcome reading another lands with it."""
        inside = {i for s in scenarios_in for i in parts[s["id"]]["nodes"]}
        candidates = in_order({i for s in scenarios_in for i in parts[s["id"]]["outcomes"]})
        done: set[str] = set()
        grew = True
        while grew:
            grew = False
            for node_id in candidates:
                if node_id in done:
                    continue
                inputs = incoming.get(node_id, [])
                if inputs and all(
                    i in inside or i in done or (is_context(i) and source_of(i) is not None) for i in inputs
                ):
                    done.add(node_id)
                    grew = True
        return done

    now = in_order(landed(group) - landed(present))
    copied = set(own) | set(now)

    # The context: what crosses into its own nodes (a node of another box
    # among it, as main's rule reads it), and into the outcomes landing.
    crossing = {i for node_id in own for i in incoming.get(node_id, []) if i not in copied}
    crossing |= {i for node_id in now for i in incoming.get(node_id, []) if is_context(i)}
    context: list[dict[str, Any]] = []
    for node_id in in_order(crossing):
        entry: dict[str, Any] = {"nodeId": node_id, "label": node_label(by_id[node_id])}
        sources = saved_sources(node_id, nodes, edges, packages)
        if len(sources) == 1:
            source = by_id[sources[0]]
            entry["source"] = {"nodeId": source["id"], "copiedFrom": lineage_of(source)}
        else:
            entry["sources"] = sources
        context.append(entry)

    return {
        "nodes": own,
        "context": context,
        "shared": [
            {
                "nodeId": node_id,
                "label": node_label(by_id[node_id]),
                "scenarios": [s["id"] for s in group if node_id in parts[s["id"]]["outcomes"]],
                "sources": [x for x in saved_sources(node_id, nodes, edges, packages) if x in copied],
            }
            for node_id in now
        ],
        "outcomes": parts[scenario["id"]]["outcomes"],
        "dataflow": {
            "nodes": [by_id[i] for i in in_order(copied)],
            "edges": [e for e in edges if e["target"] in copied],
        },
    }


def requirements(nodes: list[dict]) -> dict[str, list[str]]:
    """The node types, datasets and models *nodes* use, each once, in order."""
    types: list[str] = []
    datasets: list[str] = []
    models: list[str] = []

    def add(into: list[str], value: object) -> None:
        if isinstance(value, str) and value and value not in into:
            into.append(value)

    for node in nodes:
        add(types, node.get("type"))
        metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        for dataset_id in metadata.get("datasetRefs") or []:
            add(datasets, dataset_id)
        for model in metadata.get("modelRefs") or []:
            add(models, model.get("id") if isinstance(model, dict) else None)
    return {"types": types, "datasets": datasets, "models": models}
