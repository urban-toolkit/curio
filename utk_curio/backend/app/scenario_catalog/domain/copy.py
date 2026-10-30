"""What dragging scenarios of one set into another dataflow copies, read
from their project's spec (#662).

* Their levers, with the edges between them and the edges entering them.
* Their fixed context, once. A context node stands for the output it passes
  on, so it is the one node whose saved output (``saved_sources``) arrives as
  data. A context node that passes on several outputs, or none, cannot.
* The set's shared outcome nodes that still work: those whose every input
  comes too (a dragged scenario's node, a context node arriving as data, or
  another outcome that comes).
* The outputs their results show, which are the saved outputs of levers.
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


def copy_plan(scenario: dict, nodes: list[dict], edges: list[dict], packages=None) -> dict[str, Any]:
    """The nodes, edges and outputs a drop of *scenario* copies, as node ids
    of its own project. ``context`` lists each context node with the one node
    whose saved output stands for it (``source``), or ``sources`` when that is
    not one node. *packages* (a ``TemplateGrammars``, the account's) reads what
    each node's template declares, ``TemplateGrammars.for_account()`` when
    None."""
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

    by_id = {n["id"]: n for n in nodes}
    parts = scenario_parts(scenario, nodes, edges)
    levers = parts["levers"]
    inside = set(levers)
    packages = packages or TemplateGrammars.for_account()

    context: list[dict[str, Any]] = []
    for node_id in parts["context"]:
        node = by_id[node_id]
        entry: dict[str, Any] = {"nodeId": node_id, "label": node_label(node)}
        sources = saved_sources(node_id, nodes, edges, packages)
        if len(sources) == 1:
            source = by_id[sources[0]]
            entry["source"] = {"nodeId": source["id"], "copiedFrom": lineage_of(source)}
        else:
            entry["sources"] = sources
        context.append(entry)

    outcomes = [
        {
            "nodeId": node_id,
            "label": node_label(by_id[node_id]),
            "sources": [s for s in saved_sources(node_id, nodes, edges, packages) if s in inside],
        }
        for node_id in parts["outcomes"]
    ]
    return {
        "levers": levers,
        "context": context,
        "outcomes": outcomes,
        "dataflow": {
            "nodes": [by_id[i] for i in levers],
            "edges": [e for e in edges if e["target"] in inside],
        },
    }


def copy_set_plan(scenarios: list[dict], nodes: list[dict], edges: list[dict], packages=None) -> dict[str, Any]:
    """What a drop of *scenarios*, all of one set and each with the
    ``context`` and ``outcomes`` it keeps, copies, as node ids of their
    project. A context node read by several of them is listed once.

    ``context`` lists each context node with the one node whose saved output
    stands for it (``source``), or ``sources`` when that is not one node, and
    the scenarios that use it (``scenarios``). ``outcomes`` lists each
    scenario's own results, as :func:`copy_plan` does. ``shared`` lists the
    set's outcome nodes that come, each with the scenarios that list it and
    the copied nodes whose saved outputs stand for it. ``scenarios`` gives
    each scenario's levers, and the context and shared outcomes of its that
    come."""
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

    by_id = {n["id"]: n for n in nodes}
    packages = packages or TemplateGrammars.for_account()
    order = {n["id"]: i for i, n in enumerate(nodes)}
    in_order = lambda ids: sorted(ids, key=lambda i: order[i])  # noqa: E731

    parts = {s["id"]: scenario_parts(s, nodes, edges) for s in scenarios}
    levers = [node_id for s in scenarios for node_id in parts[s["id"]]["levers"]]
    inside = set(levers)
    # Each scenario's context: what it reads directly, and what it keeps.
    reads: dict[str, set[str]] = {
        s["id"]: {i for i in [*parts[s["id"]]["context"], *(s.get("context") or [])] if i in by_id and i not in inside}
        for s in scenarios
    }
    single: dict[str, str | None] = {}

    def source_of(node_id: str) -> str | None:
        if node_id not in single:
            found = saved_sources(node_id, nodes, edges, packages)
            single[node_id] = found[0] if len(found) == 1 else None
        return single[node_id]

    known_context = set().union(*reads.values()) if reads else set()
    incoming: dict[str, list[str]] = {}
    for edge in edges:
        if _is_interaction(edge) or edge["source"] not in by_id or edge["target"] not in by_id:
            continue
        incoming.setdefault(edge["target"], []).append(edge["source"])

    # The shared outcomes that come: every input of theirs comes too. Read to
    # a fixpoint, so an outcome reading another outcome comes with it.
    candidates = in_order({
        i for s in scenarios for i in (s.get("outcomes") or []) if i in by_id and i not in inside
    })
    shared: list[str] = []
    brought_context: set[str] = set()
    grew = True
    while grew:
        grew = False
        for node_id in candidates:
            if node_id in shared:
                continue
            inputs = incoming.get(node_id, [])
            ok = bool(inputs) and all(
                source in inside or source in shared
                or (source in known_context and source_of(source) is not None)
                for source in inputs
            )
            if ok:
                shared.append(node_id)
                brought_context.update(i for i in inputs if i in known_context)
                grew = True
    shared = in_order(shared)
    copied = inside | set(shared)

    # The context: what the levers read, and what a shared outcome reads.
    direct = {i for s in scenarios for i in parts[s["id"]]["context"]}
    context: list[dict[str, Any]] = []
    for node_id in in_order(direct | brought_context):
        node = by_id[node_id]
        entry: dict[str, Any] = {
            "nodeId": node_id,
            "label": node_label(node),
            "scenarios": [s["id"] for s in scenarios if node_id in reads[s["id"]]],
        }
        sources = saved_sources(node_id, nodes, edges, packages)
        if len(sources) == 1:
            source = by_id[sources[0]]
            entry["source"] = {"nodeId": source["id"], "copiedFrom": lineage_of(source)}
        else:
            entry["sources"] = sources
        context.append(entry)
    context_ids = {entry["nodeId"] for entry in context}

    results = [
        {
            "nodeId": node_id,
            "label": node_label(by_id[node_id]),
            "sources": [x for x in saved_sources(node_id, nodes, edges, packages) if x in inside],
        }
        for s in scenarios
        for node_id in parts[s["id"]]["outcomes"]
    ]
    return {
        "levers": levers,
        "context": context,
        "outcomes": results,
        "shared": [
            {
                "nodeId": node_id,
                "label": node_label(by_id[node_id]),
                "scenarios": [s["id"] for s in scenarios if node_id in (s.get("outcomes") or [])],
                "sources": [x for x in saved_sources(node_id, nodes, edges, packages) if x in copied],
            }
            for node_id in shared
        ],
        "scenarios": [
            {
                "id": s["id"],
                "levers": parts[s["id"]]["levers"],
                "context": in_order(reads[s["id"]] & context_ids),
                "outcomes": [i for i in shared if i in (s.get("outcomes") or [])],
            }
            for s in scenarios
        ],
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
