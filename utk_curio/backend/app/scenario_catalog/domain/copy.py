"""What dragging a scenario into another dataflow copies, read from its
project's spec (#662).

* Its levers, with the edges between them and the edges entering them.
* Its upstream and downstream nodes, as its last save stored them
  (``scenario_neighbors``), copied as they are, with the edges among them and
  the levers. Their saved outputs arrive with them (``saved``).
* The rest of its fixed context. A Parameter node is copied with its value; any other
  context node stands for the output it passes on, so it is the one node whose
  saved output (``saved_sources``) arrives as data. A context node that
  passes on several outputs, or none, cannot.
* The outputs its outcomes show, which are the saved outputs of levers.
* What the levers need: their packages, datasets and models.
"""
from __future__ import annotations

from typing import Any

from utk_curio.backend.app.scenario_catalog.domain.duplicate import lineage_of
from utk_curio.backend.app.scenario_catalog.domain.parts import (
    _template,
    is_parameter_node,
    saved_sources,
    scenario_neighbors,
    scenario_parts,
)


def node_label(node: dict) -> str:
    """What a message calls *node*: its title, else its template's name, as a
    saved output's title names it."""
    from utk_curio.backend.app.projects.services import _humanize_node_type

    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    label = node.get("title") or metadata.get("packageTemplateLabel")
    if isinstance(label, str) and label:
        return label
    return _humanize_node_type(_template(node)) or str(node.get("id"))


def neighbors_of(scenario: dict, scenarios: list, nodes: list[dict], edges: list[dict]) -> dict[str, list[str]]:
    """*scenario*'s upstream and downstream nodes as its last save stored them
    (a missing one stored none), else as its graph has them now: a spec saved
    before they were stored, or with neither."""
    if isinstance(scenario.get("upstream"), list) or isinstance(scenario.get("downstream"), list):
        ids = {n["id"] for n in nodes}
        return {
            key: [i for i in scenario.get(key) or [] if isinstance(i, str) and i in ids]
            for key in ("upstream", "downstream")
        }
    return scenario_neighbors(scenario, scenarios, nodes, edges)


def copy_plan(scenario: dict, nodes: list[dict], edges: list[dict], scenarios: list | None = None) -> dict[str, Any]:
    """The nodes, edges and outputs a drop of *scenario* copies, as node ids
    of its own project. ``context`` lists each context node that is not
    upstream with the one node whose saved output stands for it (``source``),
    or ``sources`` when that is not one node. ``saved`` lists the upstream and
    downstream nodes whose saved outputs stand for theirs."""
    by_id = {n["id"]: n for n in nodes}
    parts = scenario_parts(scenario, nodes, edges)
    near = neighbors_of(scenario, scenarios if scenarios is not None else [scenario], nodes, edges)
    levers = parts["levers"]
    inside = set(levers)
    around = [i for i in [*near["upstream"], *near["downstream"]] if i not in inside]
    carried = inside | set(around)

    context: list[dict[str, Any]] = []
    for node_id in parts["context"]:
        if node_id in carried:
            continue
        node = by_id[node_id]
        entry: dict[str, Any] = {"nodeId": node_id, "label": node_label(node)}
        if is_parameter_node(node):
            entry["parameter"] = True
        else:
            sources = saved_sources(node_id, nodes, edges)
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
            "sources": [s for s in saved_sources(node_id, nodes, edges) if s in inside],
        }
        for node_id in parts["outcomes"]
    ]
    saved: list[str] = []
    for node_id in around:
        for source in saved_sources(node_id, nodes, edges):
            if source in carried and source not in inside and source not in saved:
                saved.append(source)
    copied = (
        [by_id[i] for i in levers]
        + [by_id[i] for i in around]
        + [by_id[c["nodeId"]] for c in context if c.get("parameter")]
    )
    return {
        "levers": levers,
        "upstream": [i for i in near["upstream"] if i not in inside],
        "downstream": [i for i in near["downstream"] if i not in inside],
        "context": context,
        "outcomes": outcomes,
        "saved": saved,
        "dataflow": {
            "nodes": copied,
            "edges": [e for e in edges if e["target"] in carried],
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
