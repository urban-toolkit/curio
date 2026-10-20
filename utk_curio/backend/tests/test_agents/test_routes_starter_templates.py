"""A package template whose starter is a node's whole content (``starterIsContent``)
keeps it when the Dataflow Builder's plan creates the node, whole or node by
node: the node starts with the template's spec and the plan's widgets, and Solve
leaves it as it is.

Every other template keeps its path, in which a planned node is created empty
and Solve writes its content: Scout's Raster Calculator, whose operation
the agent writes for each use, and Rasterize Buildings, whose starter is a
starting point."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from utk_curio.backend.tests._support.agent_routes import _auth

# Imported for their helpers. conftest.py runs each class only in the file
# that defines it, never again here.
from utk_curio.backend.tests.test_agents.test_routes_proposals import (
    TestDataflowPlanMint,
    TestPerNodePlanApply,
)
from utk_curio.backend.tests.test_agents.test_routes_solve import TestSolve

REPO = Path(__file__).resolve().parents[4]

#: The test-only package: one Vega-Lite chart whose spec is its starter.
CHARTS = "test.charts@1"
SPEC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "data": {"name": "input_0"},
    "mark": "line",
    "encoding": {
        "x": {"field": "[!! x !!]", "type": "quantitative"},
        "y": {"field": "[!! y !!]", "type": "quantitative"},
        "color": {"field": "scenario_name", "type": "nominal"},
    },
}, indent=2) + "\n"
WIDGETS = [
    {"name": "x", "type": "text", "label": "X column", "default": "x"},
    {"name": "y", "type": "text", "label": "Y column", "default": "y"},
]

LOAD = {"ref": "load", "nodeType": "curio.builtin/computation-analysis",
        "title": "Load", "intent": "load the counts"}
CHART = {"ref": "chart", "nodeType": "test.charts/lines", "title": "Counts by hour",
         "intent": "draw the counts", "widgets": [{"name": "y", "type": "text", "value": "pedestrians"}]}

#: What every Solve child writes in these tests.
WRITTEN = "return input_0"
OPERATION = 'return curio_raster_calculate("subtract", [input_0, input_1])'


def _charts_manifest() -> dict:
    return {
        "id": "test.charts", "version": "1.0.0", "name": "Test charts", "publisher": "Test",
        "description": "A chart whose spec is its starter.", "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "permissions": [], "dependencies": {"packages": {}, "python": {}, "js": {}},
        "templates": [{
            "id": "lines", "label": "Lines", "category": "vis_grammar", "engine": "python",
            "editor": "grammar", "behavior": "vega", "grammarId": "vega-lite", "badge": "VEGA",
            "hasCode": False, "hasGrammar": True, "hasWidgets": True,
            "description": "One line per scenario over x.",
            "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
            "outputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
            "source": "sources/lines.vl.json",
            "starterIsContent": True,
            "widgets": WIDGETS,
        }],
        "createdAt": "2026-10-18T00:00:00Z",
    }


def _install_charts(user_key: str) -> str:
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    d = user_packages_dir(user_key) / CHARTS
    (d / "sources").mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(_charts_manifest()), encoding="utf-8")
    (d / "sources" / "lines.vl.json").write_text(SPEC, encoding="utf-8")
    return CHARTS


def _install_scout_rasters(user_key: str) -> str:
    """The package Curio ships, as the repository holds it."""
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    shutil.copytree(REPO / "packages" / "curio.scout@1",
                    user_packages_dir(user_key) / "curio.scout@1", dirs_exist_ok=True)
    return "curio.scout@1"


def _enlist(user_key: str, project_id: str, dirs: list[str]) -> None:
    from utk_curio.backend.app.packages.domain.spec_packages import set_project_packages
    from utk_curio.backend.app.projects import storage as projects_storage

    spec = projects_storage.read_spec(user_key, project_id)
    set_project_packages(spec, set(spec["dataflow"].get("packages") or []) | set(dirs))
    projects_storage.write_spec(user_key, project_id, spec)


def _minted(client, user, token, project_id, monkeypatch, nodes, edges, installs, written=WRITTEN):
    """The Dataflow Builder's plan of *nodes* and *edges*, minted in a project
    that holds the packages *installs* write, and its proposal part. Every
    later model call, each Solve child's, writes *written*."""
    helper = TestDataflowPlanMint()
    reply = "Here is the plan.\n" + helper._plan_tail(nodes=nodes, edges=edges)
    att_id, _ = helper._setup(client, user, token, project_id, monkeypatch, replies=[reply, written])
    key = helper._ukey(user)
    _enlist(key, project_id, [install(key) for install in installs])
    # Solve runs every executable node it writes; a sandbox that passes keeps
    # these tests about which nodes it writes.
    monkeypatch.setattr(
        "utk_curio.backend.app.execution.runner._http_exec",
        lambda endpoint, payload: {"stdout": [], "stderr": "",
                                   "output": {"path": "art-1", "dataType": "dataframe"}},
    )
    client.post(f"/api/agents/projects/{project_id}/install", json={"coord": TestSolve.WRITER},
                headers=_auth(token))
    body = helper._run(client, token, project_id, att_id).get_json()
    proposal = next(p for p in body["content"] if p["type"] == "proposal")
    return att_id, proposal


def _apply(client, token, project_id, att_id, proposal_id) -> dict:
    r = client.post(
        f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply",
        headers=_auth(token),
    )
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def _by_type(nodes: list[dict]) -> dict[str, dict]:
    return {n["type"].split("@", 1)[0]: n for n in nodes}


def _saved_nodes(user, project_id) -> dict[str, dict]:
    return {n["id"]: n for n in TestSolve()._spec_nodes(user, project_id)}


def _assert_starts_with_the_starter_and_the_plans_widgets(node: dict) -> None:
    assert node["content"] == SPEC
    widgets = node["metadata"]["widgets"]
    # The template's widgets, in its order, with the plan's set over them.
    assert [w["name"] for w in widgets] == ["x", "y"]
    assert widgets[0] == {"name": "x", "type": "text", "label": "X column", "default": "x"}
    assert widgets[1]["value"] == "pedestrians"
    assert widgets[1]["label"] == "Y column"


class TestAPlannedTemplateKeepsItsStarter:
    def test_the_whole_plan_creates_it_with_its_starter_and_solve_leaves_it(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, proposal = _minted(
            client, user, token, alice_project, monkeypatch,
            [LOAD, CHART], [{"from": "load", "to": "chart"}], [_install_charts],
        )
        body = _apply(client, token, alice_project, att_id, proposal["proposalId"])
        created = _by_type(body["appliedGraph"]["nodes"])
        chart, load = created["test.charts/lines"], created["curio.builtin/computation-analysis"]
        _assert_starts_with_the_starter_and_the_plans_widgets(chart)
        assert load["content"] == ""
        session = body["builderSession"]
        # Nothing is left for Solve to write in it, nor for Simulation Mode to
        # validate: its content is the template's.
        assert session["nodeRuns"] == {load["id"]: "pending"}
        assert session["nodeStates"] == {"load": "created", "chart": "approved"}

        resp = TestSolve()._solve(client, token, alice_project, att_id)
        assert resp.status_code == 200, resp.get_json()
        result = resp.get_json()
        assert set(result["results"]) == {load["id"]}
        assert result["results"][load["id"]]["status"] == "solved"
        assert result["builderSession"]["phase"] == "ready"
        saved = _saved_nodes(user, alice_project)
        _assert_starts_with_the_starter_and_the_plans_widgets(saved[chart["id"]])
        assert saved[load["id"]]["content"] == WRITTEN

    def test_node_by_node_it_is_created_with_its_starter(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, proposal = _minted(
            client, user, token, alice_project, monkeypatch,
            [LOAD, CHART], [{"from": "load", "to": "chart"}], [_install_charts],
        )
        apply_node = TestPerNodePlanApply()._apply_node
        body = apply_node(client, token, alice_project, att_id, proposal["proposalId"], "chart").get_json()
        chart = body["createdNode"]
        _assert_starts_with_the_starter_and_the_plans_widgets(chart)
        session = body["builderSession"]
        assert chart["id"] not in session["nodeRuns"]
        assert session["nodeStates"]["chart"] == "approved"

        body = apply_node(client, token, alice_project, att_id, proposal["proposalId"], "load").get_json()
        load = body["createdNode"]
        assert load["content"] == ""
        session = body["builderSession"]
        assert session["nodeRuns"] == {load["id"]: "pending"}
        assert session["nodeStates"] == {"chart": "approved", "load": "created"}
        assert _saved_nodes(user, alice_project)[chart["id"]]["content"] == SPEC


class TestEveryOtherTemplateKeepsItsPath:
    def test_the_raster_calculator_and_rasterize_buildings_are_created_empty_for_solve_to_write(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        heights = {"ref": "heights", "nodeType": "curio.scout/rasterize-buildings",
                   "title": "Heights", "intent": "rasterize the buildings"}
        calc = {"ref": "calc", "nodeType": "curio.scout/raster-calculator",
                "title": "Change", "intent": "subtract the two rasters"}
        att_id, proposal = _minted(
            client, user, token, alice_project, monkeypatch,
            [heights, calc], [], [_install_scout_rasters], written=OPERATION,
        )
        body = _apply(client, token, alice_project, att_id, proposal["proposalId"])
        created = _by_type(body["appliedGraph"]["nodes"])
        session = body["builderSession"]
        assert set(created) == {"curio.scout/rasterize-buildings", "curio.scout/raster-calculator"}
        for node in created.values():
            assert node["content"] == ""
        assert session["nodeRuns"] == {n["id"]: "pending" for n in created.values()}
        assert session["nodeStates"] == {"heights": "created", "calc": "created"}

        resp = TestSolve()._solve(client, token, alice_project, att_id)
        assert resp.status_code == 200, resp.get_json()
        assert {r["status"] for r in resp.get_json()["results"].values()} == {"solved"}
        saved = _saved_nodes(user, alice_project)
        # The agent wrote each one's code: the calculator's, its operation.
        for node in created.values():
            assert saved[node["id"]]["content"] == OPERATION
