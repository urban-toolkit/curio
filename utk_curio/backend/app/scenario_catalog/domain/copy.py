"""What dragging a scenario into another dataflow copies, read from its
project's spec (#662).

* Its levers, with the edges between them and the edges entering them.
* Its fixed context. A Parameter node is copied with its value; any other
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


def copy_plan(scenario: dict, nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    """The nodes, edges and outputs a drop of *scenario* copies, as node ids
    of its own project. ``context`` lists each context node with the one node
    whose saved output stands for it (``source``), or ``sources`` when that is
    not one node."""
    by_id = {n["id"]: n for n in nodes}
    parts = scenario_parts(scenario, nodes, edges)
    levers = parts["levers"]
    inside = set(levers)

    context: list[dict[str, Any]] = []
    for node_id in parts["context"]:
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
    copied = [by_id[i] for i in levers] + [by_id[c["nodeId"]] for c in context if c.get("parameter")]
    return {
        "levers": levers,
        "context": context,
        "outcomes": outcomes,
        "dataflow": {
            "nodes": copied,
            "edges": [e for e in edges if e["target"] in inside],
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
