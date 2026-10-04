"""The Scenario Catalog (#662): every scenario in the account's projects.

Scenarios live in projects, so the catalog has no storage of its own. A
listing reads the project summaries, which carry each project's scenarios; a
scenario's details read its project's spec for its fixed context, levers and
outcomes, and the Data Catalog for the outputs the project saved. Editing a
project changes its scenarios here; deleting it takes them away.
"""
from __future__ import annotations

from typing import Any

from utk_curio.backend.app.execution.code_references import effective_value, normalize_shared
from utk_curio.backend.app.projects.scenarios import scenario_summaries
from utk_curio.backend.app.scenario_catalog.domain.parts import (
    is_parameter_node,
    saved_sources,
    scenario_parts,
    spec_nodes_and_edges,
)
from utk_curio.backend.app.scenario_catalog.infrastructure import projects


class ScenarioCatalogError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def scenario_key(project_id: str, scenario_id: str) -> str:
    """A scenario's id is unique in its project only: a copy of a project
    keeps its scenarios' ids, so the catalog keys each by both."""
    return f"{project_id}/{scenario_id}"


def scenario_row(scenario: dict, project: dict, preview: dict | None) -> dict[str, Any]:
    """What a client is told about one scenario in a listing."""
    return {
        "key": scenario_key(project["id"], scenario["id"]),
        "id": scenario["id"],
        "name": scenario["name"],
        "color": scenario["color"],
        "description": scenario.get("description", ""),
        "nodeCount": len(scenario.get("nodes") or []),
        "project": project,
        "preview": preview,
    }


def _node_entry(node: dict, results: list[dict]) -> dict[str, Any]:
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    label = node.get("title") or metadata.get("packageTemplateLabel")
    entry: dict[str, Any] = {"id": node["id"], "type": str(node.get("type") or "")}
    if isinstance(label, str) and label:
        entry["label"] = label
    if is_parameter_node(node):
        widgets = normalize_shared(metadata.get("widgets"))
        if widgets:
            entry["parameter"] = {"name": widgets[0]["name"], "value": effective_value(widgets[0])}
    entry["results"] = results
    return entry


def _result_row(item: dict, node_id: str) -> dict[str, Any]:
    """A saved output, as a client is told of it. Never a path on this machine."""
    return {
        "datasetId": item["id"],
        "nodeId": node_id,
        "title": item.get("title") or item["id"],
        "format": item.get("format"),
        "rowCount": item.get("rowCount"),
        "featureCount": item.get("featureCount"),
        "updatedAt": item.get("updatedAt"),
    }


class ScenarioCatalogService:
    def __init__(self, user) -> None:
        self.user = user

    def list_catalog(self, *, q: str | None = None) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for summary in projects.project_summaries(self.user):
            if not summary.scenarios:
                continue
            project = {
                "id": summary.id,
                "name": summary.name,
                "isExample": summary.is_example,
                "updatedAt": summary.updated_at,
            }
            for scenario in summary.scenarios:
                items.append(scenario_row(scenario, project, summary.graph_preview))
        if q:
            needle = q.strip().lower()
            items = [
                item for item in items
                if needle in " ".join([item["name"], item["description"], item["project"]["name"]]).lower()
            ]
        return {"items": items}

    def get_scenario(self, project_id: str, scenario_id: str) -> dict[str, Any]:
        """One scenario: its fixed context, levers and outcomes, each with the
        outputs its project saved for it."""
        try:
            row, spec, is_example = projects.owned_project(self.user, project_id)
        except projects.ProjectNotFound:
            raise ScenarioCatalogError(f"Project {project_id} not found", 404) from None
        scenario = next((s for s in scenario_summaries(spec) if s["id"] == scenario_id), None)
        if scenario is None:
            raise ScenarioCatalogError(f"{row.name} has no scenario {scenario_id}", 404)

        nodes, edges = spec_nodes_and_edges(spec)
        by_id = {n["id"]: n for n in nodes}
        parts = scenario_parts(scenario, nodes, edges)
        outputs = projects.saved_outputs(self.user, project_id)

        def entry(node_id: str) -> dict[str, Any]:
            results = []
            for source_id in saved_sources(node_id, nodes, edges):
                item = outputs.get(projects.computed_dataset_id(source_id, project_id))
                if item is not None:
                    results.append(_result_row(item, source_id))
            return _node_entry(by_id[node_id], results)

        project = {
            "id": row.id,
            "name": row.name,
            "isExample": is_example,
            "updatedAt": row.updated_at.isoformat() if row.updated_at else "",
        }
        return {
            **scenario_row(scenario, project, projects.graph_preview(spec)),
            "context": [entry(i) for i in parts["context"]],
            "levers": [entry(i) for i in parts["levers"]],
            "outcomes": [entry(i) for i in parts["outcomes"]],
        }
