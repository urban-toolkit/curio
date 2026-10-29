"""A package template whose starter is a node's whole content (``starterIsContent``)
keeps it when the Dataflow Builder's plan creates the node: the node starts
with the template's spec and the plan's widgets, and Solve leaves it as it is.
A Node Builder ``node.create`` of such a template starts it the same way, at
mint, so its card shows what landed.

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
from utk_curio.backend.tests.test_agents import test_source_grounding_routes as grounding_routes
from utk_curio.backend.tests.test_agents.test_routes_proposals import (
    TestDataflowPlanMint,
    TestNodeCreate,
    _changes,
    _landed_plan,
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
OPERATION = (
    "from scout_rasters.raster_algebra import raster_calculate\n"
    "\n"
    'return raster_calculate("subtract", [input_0, input_1], output_file=curio_output_file)'
)


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


def _landed(client, user, token, project_id, monkeypatch, nodes, edges, installs, written=WRITTEN):
    """The Dataflow Builder's plan of *nodes* and *edges*, landed in a project
    that holds the packages *installs* write: its attachment and the plan's
    change card, with ``canvas``. Every later model call, each Solve child's,
    writes *written*."""
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
    return att_id, _landed_plan(body)


def _session(client, token, project_id, att_id) -> dict:
    """The planner's builder session, as the attachment listing has it."""
    cards = client.get(f"/api/agents/projects/{project_id}/attachments", headers=_auth(token)).get_json()
    return next(c for c in cards["attachments"] if c["attachmentId"] == att_id)["builderSession"]


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
    def test_the_plan_lands_it_with_its_starter_and_solve_leaves_it(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, card = _landed(
            client, user, token, alice_project, monkeypatch,
            [LOAD, CHART], [{"from": "load", "to": "chart"}], [_install_charts],
        )
        created = _by_type(card["canvas"]["nodes"])
        chart, load = created["test.charts/lines"], created["curio.builtin/computation-analysis"]
        _assert_starts_with_the_starter_and_the_plans_widgets(chart)
        _assert_starts_with_the_starter_and_the_plans_widgets(_saved_nodes(user, alice_project)[chart["id"]])
        assert load["content"] == ""
        session = _session(client, token, alice_project, att_id)
        # Nothing is left for Solve to write in it, nor for Build & validate to
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


class TestEveryOtherTemplateKeepsItsPath:
    def test_the_raster_calculator_and_rasterize_buildings_are_created_empty_for_solve_to_write(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        heights = {"ref": "heights", "nodeType": "curio.scout/rasterize-buildings",
                   "title": "Heights", "intent": "rasterize the buildings"}
        calc = {"ref": "calc", "nodeType": "curio.scout/raster-calculator",
                "title": "Change", "intent": "subtract the two rasters"}
        att_id, card = _landed(
            client, user, token, alice_project, monkeypatch,
            [heights, calc], [], [_install_scout_rasters], written=OPERATION,
        )
        created = _by_type(card["canvas"]["nodes"])
        session = _session(client, token, alice_project, att_id)
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


def _scout_bars() -> tuple[str, list[dict]]:
    """Scout's Bars chart, as the package Curio ships holds it: its starter, the
    node's whole content, and its widgets."""
    package = REPO / "packages" / "curio.scout@1"
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    (template,) = [t for t in manifest["templates"] if t["id"] == "bars"]
    assert template.get("starterIsContent") is True
    return (package / template["source"]).read_text(encoding="utf-8"), template["widgets"]


class TestACreatedTemplateStartsFromItsStarter:
    """The Node Builder's ``node.create`` of Scout's Bars, a template whose
    starter is its whole content, as a plan creates one: with no content of
    its own, the node starts from the template's spec and widgets, the widgets
    the request gives set over the ones of their names."""

    def _run(self, client, user, token, project_id, monkeypatch, *replies):
        helper = TestNodeCreate()
        att_id, calls = helper._setup(client, user=user, token=token, project_id=project_id,
                                      monkeypatch=monkeypatch, replies=[*replies, "Added it."])
        key = TestDataflowPlanMint()._ukey(user)
        _enlist(key, project_id, [_install_scout_rasters(key)])
        r = helper._run(client, token, project_id, att_id)
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert not [p for p in body["content"] if p["type"] == "proposal"]
        card = next((p for p in _changes(body) if p["kind"] == "node"), None)
        created = helper._created(body) if card is not None else None
        # Each node.create result is read by its prefix, never by its index.
        return helper, card, created, grounding_routes._tool_results(calls[-1], "node.create")

    def test_with_no_content_it_starts_from_its_template_and_the_asked_value_is_set(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        starter, widgets = _scout_bars()
        create = TestNodeCreate()._create_tail_json
        calculator = create(nodeType="curio.scout/raster-calculator", content="")
        bars = create(nodeType="curio.scout/bars", title="Mean shadow", content="",
                      widgets=[{"name": "y", "type": "text", "value": "shadow_minutes"}])
        helper, card, created, results = self._run(
            client, user, token, alice_project, monkeypatch, calculator, bars,
        )
        refused, landed = results
        # A template whose starter is not its content keeps today's rule: its
        # code is the agent's to write.
        assert "params.content must be a non-empty string" in refused, refused
        assert landed.startswith("[tool result] node.create: applied"), landed
        # The card shows what landed: the template's spec, as its package holds it.
        assert card is not None
        assert card["preview"] == starter
        assert card["summary"] == "Created a new Bars node · Mean shadow · widgets y, combine, y_title"
        assert created["content"] == starter
        got = created["metadata"]["widgets"]
        # The template's widgets, in its order, the asked value set over its own.
        assert [w["name"] for w in got] == [w["name"] for w in widgets] == ["y", "combine", "y_title"]
        assert got[0]["value"] == "shadow_minutes"
        assert got[0]["label"] == "Y column"
        assert got[1] == widgets[1] and got[2] == widgets[2]
        stored = next(n for n in helper._spec_nodes(user, alice_project) if n["id"] == created["id"])
        assert stored["content"] == starter
        assert stored["metadata"]["widgets"] == got

    def test_content_of_its_own_is_refused_in_words_that_name_its_widgets(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        starter, _widgets = _scout_bars()
        retyped = starter.replace('"type": "bar"', '"type": "line"')
        assert retyped != starter
        reply = TestNodeCreate()._create_tail_json(nodeType="curio.scout/bars", content=retyped)
        helper, card, _, [refused] = self._run(client, user, token, alice_project, monkeypatch, reply)
        assert card is None, "a retyped Scout chart landed"
        assert "params.content: a Bars node starts from its template's own content" in refused, refused
        assert "y, combine, y_title" in refused, refused
        assert [n["id"] for n in helper._spec_nodes(user, alice_project)] == ["n1"]
