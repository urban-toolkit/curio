"""The Scenario Catalog (#662): every scenario in the account's projects.

Scenarios live in projects, so the catalog has no storage of its own. A
listing reads the project summaries, which carry each project's scenarios; a
scenario's details read its project's spec for its fixed context, levers and
outcomes, and the Data Catalog for the outputs the project saved. Editing a
project changes its scenarios here; deleting it takes them away.
"""
from __future__ import annotations

import re
from typing import Any

from utk_curio.backend.app.execution.code_references import effective_value, normalize_shared
from utk_curio.backend.app.projects.scenarios import scenario_summaries
from utk_curio.backend.app.scenario_catalog.domain.copy import copy_plan, node_label, requirements
from utk_curio.backend.app.scenario_catalog.domain.parts import (
    is_parameter_node,
    saved_sources,
    scenario_parts,
    spec_nodes_and_edges,
)
from utk_curio.backend.app.scenario_catalog.infrastructure import projects
from utk_curio.backend.app.scenario_catalog.infrastructure import requirements as needs
from utk_curio.backend.app.scenario_catalog.infrastructure import runs as server_runs

#: A node id a drop may give a copy: what the canvas makes (a uuid), and the
#: ids hand-written dataflows use.
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


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

    def _project(self, project_id: str) -> tuple[Any, dict, bool]:
        try:
            return projects.owned_project(self.user, project_id)
        except projects.ProjectNotFound:
            raise ScenarioCatalogError(f"Project {project_id} not found", 404) from None

    def _scenario(self, project_id: str, scenario_id: str) -> tuple[Any, dict, bool, dict]:
        row, spec, is_example = self._project(project_id)
        scenario = next((s for s in scenario_summaries(spec) if s["id"] == scenario_id), None)
        if scenario is None:
            raise ScenarioCatalogError(f"{row.name} has no scenario {scenario_id}", 404)
        return row, spec, is_example, scenario

    def get_scenario(self, project_id: str, scenario_id: str) -> dict[str, Any]:
        """One scenario: its fixed context, levers and outcomes, each with the
        outputs its project saved for it."""
        row, spec, is_example, scenario = self._scenario(project_id, scenario_id)

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

    # -- Dragging a scenario into another dataflow --------------------------

    def copy_plan(self, project_id: str, scenario_id: str, target_id: str) -> dict[str, Any]:
        """What dragging the scenario into *target_id* copies, the context
        nodes a run on the server makes first in the scenario's project
        (``toRun``), and why it cannot be, if it cannot (``problems``).
        Changes nothing."""
        return self._plan(project_id, scenario_id, target_id)[0]

    def _plan(self, project_id: str, scenario_id: str, target_id: str) -> tuple[dict[str, Any], Any, dict, Any]:
        row, spec, _is_example, scenario = self._scenario(project_id, scenario_id)
        target_row, target_spec, _ = self._project(target_id)
        nodes, edges = spec_nodes_and_edges(spec)
        by_id = {n["id"]: n for n in nodes}
        plan = copy_plan(scenario, nodes, edges)
        # What the scenario's project saved, read at once under its spec lock,
        # before anything else, so a save of it is waited for (#941).
        saved = projects.saved_outputs_of(self.user, project_id, spec, [
            entry["source"]["nodeId"]
            for entry in plan["context"]
            if not entry.get("parameter") and entry.get("source") is not None
        ] + [source for outcome in plan["outcomes"] for source in outcome["sources"]])
        name = scenario["name"]
        problems: list[str] = []
        to_run: list[dict[str, str]] = []
        runs_refused = server_runs.refusal(self.user)

        for entry in plan["context"]:
            if entry.get("parameter"):
                continue
            source = entry.get("source")
            if source is None:
                count = len(entry["sources"])
                problems.append(
                    f'"{name}" reads {entry["label"]}, which passes on '
                    f'{"nothing" if count == 0 else f"{count} outputs"}; only a node that passes on one '
                    "can arrive as data."
                )
                continue
            found = saved.get(source["nodeId"])
            if found is not None:
                source["datasetId"] = found["datasetId"]
                continue
            # A run on the server makes the output in the scenario's project,
            # where the account's runs go to the server and the server can run
            # the node and every node it reads from.
            unsaved = f'"{name}" reads {entry["label"]}, which has no saved output in {row.name}'
            if runs_refused is not None:
                problems.append(f"{unsaved}: run the scenario there and save the project, then drag it again.")
                continue
            blocker = server_runs.browser_node(self.user, project_id, nodes, edges, source["nodeId"])
            if blocker is not None:
                problems.append(
                    f"{unsaved}, and {node_label(blocker)} runs only in the browser: "
                    "run the scenario there and save the project, then drag it again."
                )
                continue
            if all(item["nodeId"] != source["nodeId"] for item in to_run):
                to_run.append({"nodeId": source["nodeId"], "label": node_label(by_id[source["nodeId"]])})

        # An outcome without a saved output shows once the scenario runs.
        for outcome in plan["outcomes"]:
            outcome["sources"] = [s for s in outcome["sources"] if (saved.get(s) or {}).get("computed")]

        ukey = projects.user_key(self.user)
        needed = requirements(plan["dataflow"]["nodes"])
        present = needs.project_packages(ukey, target_id)
        packages: list[str] = []

        def add(dir_name: str) -> None:
            """The package *dir_name* the levers need: added to the target the
            way the Node Catalog adds one, unless it is there already."""
            if needs.is_builtin(dir_name) or dir_name in present or dir_name in packages:
                return
            problem = needs.package_problem(self.user, ukey, dir_name)
            if problem:
                problems.append(f'"{name}" needs {problem}.')
            else:
                packages.append(dir_name)

        for node_type, dir_name in needs.package_dirs(ukey, project_id, needed["types"]).items():
            if dir_name is None:
                problems.append(f'"{name}" needs the package of {node_type}, which is not in your Node Catalog.')
            else:
                add(dir_name)
        for dataset_id in needed["datasets"]:
            problem = needs.dataset_problem(self.user, dataset_id)
            if problem:
                problems.append(f'"{name}" needs {problem}.')
        # A model is a model package: added as a node's package is.
        for model_id in needed["models"]:
            dir_name = needs.model_package_dir(ukey, model_id)
            if dir_name is None:
                problems.append(f'"{name}" needs the model {model_id}, which is not in your Model Catalog.')
            else:
                add(dir_name)

        return {
            "scenario": {
                "id": scenario["id"],
                "name": name,
                "color": scenario["color"],
                "description": scenario.get("description", ""),
            },
            "project": {"id": row.id, "name": row.name},
            **plan,
            "packages": packages,
            "toRun": to_run,
            "problems": problems,
        }, row, spec, (target_row, target_spec)

    def copy_into(self, project_id: str, scenario_id: str, target_id: str, outputs: object) -> dict[str, Any]:
        """Do what :meth:`copy_plan` says, for a drop into *target_id* whose
        copies have the node ids *outputs* names (``[{source, node}]``): add
        the packages it needs, copy each saved output to its copy, and restore
        those for the canvas. Each project is read or written under its own
        spec lock, one at a time (``projects.copy_outputs``). Refused, changing
        nothing, while the plan has a problem or a context node still to run;
        a saved output that is gone, or that cannot be copied, is a 409, the
        second saying to try again."""
        plan, row, spec, (target_row, target_spec) = self._plan(project_id, scenario_id, target_id)
        unsaved = [
            f'"{plan["scenario"]["name"]}" reads {item["label"]}, which has no saved output in {row.name}: '
            "run it there first."
            for item in plan["toRun"]
        ]
        if plan["problems"] or unsaved:
            raise ScenarioCatalogError(" ".join(plan["problems"] + unsaved), 409)
        context = {
            entry["source"]["nodeId"]: entry["source"]["datasetId"]
            for entry in plan["context"]
            if entry.get("source") and entry["source"].get("datasetId")
        }
        outcomes = {source for outcome in plan["outcomes"] for source in outcome["sources"]}
        taken = {node["id"] for node in spec_nodes_and_edges(target_spec)[0]}
        copies = self._copies(outputs, set(context) | outcomes, taken)

        ukey = projects.user_key(self.user)
        added: list[str] = []
        for dir_name in plan["packages"]:
            problem = needs.add_package(ukey, target_id, dir_name)
            if problem:
                raise ScenarioCatalogError(
                    f'"{plan["scenario"]["name"]}" needs the package {dir_name}, which could not be added: {problem}', 409,
                )
            added.append(dir_name)

        try:
            copied = projects.copy_outputs(
                self.user, project_id, spec, copies, target_id=target_id, target_name=target_row.name,
            )
        except projects.OutputGone as gone:
            raise ScenarioCatalogError(f"The saved output of {gone.node_id} in {row.name} is gone.", 409) from None
        except projects.CopyFailed as failed:
            raise ScenarioCatalogError(
                f"The saved output of {failed.node_id} in {row.name} could not be copied. Try again in a moment.", 409,
            ) from None
        loaders = {node: copied.dataset_ids[node] for source, node in copies if source in context}

        items = projects.dataset_items(self.user, target_id, set(loaders.values()))
        return {
            "packages": sorted(needs.project_packages(ukey, target_id)),
            "added": added,
            "datasets": {node: items[d] for node, d in loaders.items() if d in items},
            "outputs": [
                {"node_id": ref.node_id, "filename": ref.filename, **({"data_type": ref.data_type} if ref.data_type else {})}
                for ref in copied.restored
            ],
        }

    @staticmethod
    def _copies(outputs: object, allowed: set[str], taken: set[str]) -> list[tuple[str, str]]:
        """``(source, node)`` pairs from a request: each source one of the
        scenario's saved outputs, each node a fresh id named once, which the
        target does not already hold."""
        if not isinstance(outputs, list):
            raise ScenarioCatalogError("outputs must be a list of {source, node}")
        pairs: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in outputs:
            source = item.get("source") if isinstance(item, dict) else None
            node = item.get("node") if isinstance(item, dict) else None
            if not isinstance(source, str) or source not in allowed:
                raise ScenarioCatalogError(f"{source!r} is not a saved output this scenario brings")
            if not isinstance(node, str) or not _NODE_ID_RE.match(node) or node in seen or node in taken:
                raise ScenarioCatalogError(f"{node!r} is not a fresh node id")
            seen.add(node)
            pairs.append((source, node))
        return pairs
