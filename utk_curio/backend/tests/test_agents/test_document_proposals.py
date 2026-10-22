"""A chart or a map an agent proposes is checked as Solve checks one, before
its review card appears: a Node Builder ``node.create`` and a content
replacement (``node.content.write``, which delegated content and a proposing
Solve mint too), through the gate every agent-authored content passes. A
Solve that writes without running holds a document to the same check, and a
document that does not validate fails the node as one, not as an ungrounded
source.

A document is checked with its references resolved as far as the dataflow
knows them: the node's widgets (a created node's, the ones it declares), the
shared tags, and its wired inputs with their boxes. A reference nothing can
resolve yet, such as an input chip of a node with no edge, is read as Solve
reads one for a node it does not hold. The documents are
``test_document_validation``'s.
"""
from __future__ import annotations

import json

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_routes_proposals as routes_proposals
from utk_curio.backend.tests.test_agents import test_routes_solve as routes_solve
from utk_curio.backend.tests.test_agents import test_source_grounding_routes as grounding_routes
from utk_curio.backend.tests.test_agents.test_document_validation import OWNERS_AUTK, OWNERS_VEGA

NB = "agent.curio.node-builder@1"
DFB = "agent.curio.dataflow-builder@1"
CA = "curio.builtin/computation-analysis"
VEGA = "curio.builtin/vis-vega"
AUTK = "curio.builtin/autk-grammar"

#: A code node, and the chart and the map as curio.builtin@1 declares them.
TEMPLATES = [
    {"id": "computation-analysis", "label": "Computation Analysis", "category": "computation",
     "engine": "python", "editor": "code", "description": "Run python analysis code.",
     "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,n]"}],
     "outputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}]},
    {"id": "vis-vega", "label": "Vega-Lite", "category": "vis_grammar", "engine": "python", "editor": "grammar",
     "hasCode": False, "hasGrammar": True, "grammarId": "vega-lite", "hasWidgets": True, "behavior": "vega",
     "description": "A Vega-Lite chart of its inputs.",
     "inputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "[1,n]"}],
     "outputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "1"}]},
    {"id": "autk-grammar", "label": "Autark", "category": "vis_grammar", "engine": "python", "editor": "grammar",
     "hasCode": False, "hasGrammar": True, "grammarId": "autk-grammar", "hasWidgets": True,
     "behavior": "autk-grammar", "description": "An Autark map of its inputs.",
     "inputPorts": [{"types": ["GEODATAFRAME", "DATAFRAME"], "cardinality": "[0,n]"}],
     "outputPorts": [{"types": ["GEODATAFRAME"], "cardinality": "[0,1]"}]},
]

#: A Scout-style chart: its dataset and its scenario chips, a field and a
#: title through its widgets (inside quotes), and a widget written bare.
SCOUT_STYLE = (
    '{"$schema": "https://vega.github.io/schema/vega-lite/v6.json", "data": {"name": "[!! inputs !!]"}, '
    '"mark": {"type": "bar", "opacity": [!! opacity !!]}, '
    '"title": "[!! title !!]", '
    '"encoding": {'
    '"x": {"field": "scenario_name", "type": "nominal", "sort": [!! scenario order !!]}, '
    '"y": {"field": "[!! y !!]", "type": "quantitative", "aggregate": "mean"}, '
    '"color": {"field": "scenario_name", "type": "nominal", "scale": [!! scenario colors !!]}}}'
)
SCOUT_WIDGETS = [
    {"name": "opacity", "type": "slider", "default": 0.8, "options": {"min": 0, "max": 1}},
    {"name": "title", "type": "text", "default": "Mean daily trips"},
    {"name": "y", "type": "text", "default": "daily_trips"},
]
#: The owner's map, its layer read from the node's first input by its chip.
MAP_OF_INPUT_0 = OWNERS_AUTK.replace('"population_density"', '"[!! input_0 !!]"')
#: Each scenario's mean trips, in its box's color and order.
WITH_SCENARIO_CHIPS = (
    '{"$schema": "https://vega.github.io/schema/vega-lite/v6.json", "data": {"name": "inputs"}, '
    '"mark": "bar", "encoding": {'
    '"x": {"field": "scenario_name", "type": "nominal", "sort": [!! scenario order !!]}, '
    '"y": {"field": "daily_trips", "type": "quantitative", "aggregate": "mean"}, '
    '"color": {"field": "scenario_name", "type": "nominal", "scale": [!! scenario colors !!]}}}'
)


@pytest.fixture()
def charts(client, user_and_token):
    """A dataflow whose chart reads two scenarios' trips, one per circle."""
    user, token = user_and_token
    from utk_curio.backend.app.projects.services import _user_dir_key

    routes_proposals.TestNodeCreate()._write_builtin_package(_user_dir_key(user), templates=TEMPLATES)
    body = {
        "name": "p",
        "spec": {"dataflow": {
            "nodes": [
                {"id": "today", "type": CA, "title": "Today", "content": "return input_0", "x": 0, "y": 0},
                {"id": "bus", "type": CA, "title": "Bus lanes", "content": "return input_0", "x": 0, "y": 200},
                {"id": "chart", "type": VEGA, "goal": "trips per scenario", "content": "", "x": 400, "y": 100},
            ],
            "edges": [
                {"id": "e1", "source": "today", "target": "chart", "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e2", "source": "bus", "target": "chart", "sourceHandle": "out", "targetHandle": "in_1"},
            ],
            "scenarios": [
                {"id": "s-today", "name": "Today", "color": "#2a9d8f", "nodes": ["today"]},
                {"id": "s-bus", "name": "Bus lanes", "color": "#e76f51", "nodes": ["bus"]},
            ],
            "packages": [],
        }},
        "outputs": [],
    }
    resp = client.post("/api/projects", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _create(node_type, content, **params) -> str:
    request = {"tool": "node.create", "params": {"nodeType": node_type, "content": content, **params}}
    return "```curio.v1\n" + json.dumps({"toolRequest": request}) + "\n```"


def _write(node_id, content) -> str:
    request = {"tool": "node.content.write", "params": {"nodeId": node_id, "content": content}}
    return "```curio.v1\n" + json.dumps({"toolRequest": request}) + "\n```"


def _results(calls: list, tool: str) -> list[str]:
    """Each result the model was handed for *tool*, in order. Every recorded
    call is the one message list the loop appends to, so a result is read by
    its prefix, never by its index."""
    return grounding_routes._tool_results(calls[-1], tool)


def _proposals(body) -> list[dict]:
    return [p for p in body["content"] if p["type"] == "proposal"]


def _node(user, project, node_id) -> dict:
    spec = routes_proposals.TestDataflowPlanApply()._spec(user, project)
    return next(n for n in spec["dataflow"]["nodes"] if n["id"] == node_id)


class TestACreatedNode:
    def test_a_chart_that_does_not_validate_is_refused_and_one_with_its_chips_and_widgets_is_proposed(
        self, client, user_and_token, tmp_curio, charts, monkeypatch
    ):
        _, token = user_and_token
        grounding_routes._install(client, token, charts, NB)
        att = grounding_routes._attach(client, token, charts, NB)
        calls = grounding_routes._script(monkeypatch, [
            _create(VEGA, OWNERS_VEGA),
            _create(VEGA, SCOUT_STYLE, widgets=SCOUT_WIDGETS),
            "Proposed: review it above.",
        ])
        body = grounding_routes._run(client, token, charts, att, "chart the mean trips per scenario")
        refused, proposed = _results(calls, "node.create")
        assert "document refused" in refused, refused
        assert "'else' was unexpected" in refused
        assert proposed.startswith("[tool result] node.create: proposed"), proposed
        # The chart that resolves through its own widgets and the scenario chips is proposed as written.
        [proposal] = _proposals(body)
        assert proposal["preview"] == SCOUT_STYLE

    def test_a_map_that_draws_nothing_is_refused_and_one_reading_an_input_not_yet_wired_is_proposed(
        self, client, user_and_token, tmp_curio, charts, monkeypatch
    ):
        _, token = user_and_token
        grounding_routes._install(client, token, charts, NB)
        att = grounding_routes._attach(client, token, charts, NB)
        calls = grounding_routes._script(monkeypatch, [
            _create(AUTK, '{"map": {"layerRefs": []}}'),
            _create(AUTK, MAP_OF_INPUT_0),
            "Proposed: review it above.",
        ])
        body = grounding_routes._run(client, token, charts, att, "map the population density")
        refused, proposed = _results(calls, "node.create")
        assert "document refused" in refused, refused
        assert "a map with no layers renders nothing" in refused
        assert proposed.startswith("[tool result] node.create: proposed"), proposed
        [proposal] = _proposals(body)
        assert proposal["preview"] == MAP_OF_INPUT_0


class TestAReplacedContent:
    def test_a_chart_that_does_not_validate_is_refused_and_one_with_its_boxes_chips_is_proposed(
        self, client, user_and_token, tmp_curio, charts, monkeypatch
    ):
        """What a verified Solve accepts for this node, the review mint accepts too."""
        user, token = user_and_token
        grounding_routes._install(client, token, charts, NB)
        att = grounding_routes._attach(client, token, charts, NB, target={"kind": "node", "targetId": "chart"})
        calls = grounding_routes._script(monkeypatch, [
            _write("chart", OWNERS_VEGA),
            _write("chart", WITH_SCENARIO_CHIPS),
            "Proposed: review it above.",
        ])
        body = grounding_routes._run(client, token, charts, att, "chart the trips per scenario")
        refused, proposed = _results(calls, "node.content.write")
        assert "document refused" in refused, refused
        assert "'else' was unexpected" in refused
        assert proposed.startswith("[tool result] node.content.write: proposed"), proposed
        [proposal] = _proposals(body)
        assert proposal["preview"] == WITH_SCENARIO_CHIPS
        assert _node(user, charts, "chart")["content"] == ""  # proposed, not written


class TestASolveThatDoesNotRun:
    """A Solve without verification writes, or proposes, without running; a
    document still has to validate, and the node's error says it did not."""

    def _applied_chart(self, client, user, token, project, monkeypatch, document):
        plan = {
            "goal": "trips per scenario",
            "nodes": [{"ref": "trips", "nodeType": VEGA, "title": "Trips", "intent": "a bar chart of mean trips"}],
            "edges": [],
        }
        plan_tail = "Plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"
        grounding_routes._install(client, token, project, DFB, NB)
        att = grounding_routes._attach(client, token, project, DFB)
        grounding_routes._script(monkeypatch, [
            lambda calls: document if "[delegated task" in calls[-1][-1]["content"] else plan_tail,
        ])
        [proposal] = _proposals(grounding_routes._run(client, token, project, att, "plan the chart"))
        applied = client.post(
            f"/api/agents/projects/{project}/attachments/{att}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        ).get_json()
        chart = next(n["id"] for n in applied["appliedGraph"]["nodes"] if str(n.get("type", "")).startswith(VEGA))
        return att, chart

    def test_a_document_that_does_not_validate_fails_the_node_and_one_that_does_is_written(
        self, client, user_and_token, tmp_curio, charts, monkeypatch
    ):
        from utk_curio.backend.tests.test_agents.test_document_validation import FIXED_VEGA

        user, token = user_and_token
        att, chart = self._applied_chart(client, user, token, charts, monkeypatch, OWNERS_VEGA)
        body = client.post(
            f"/api/agents/projects/{charts}/attachments/{att}/solve",
            json={"verify": False}, headers=_auth(token),
        ).get_json()
        result = body["results"][chart]
        assert result["status"] == "failed", result
        assert result["error"].startswith("document-invalid: "), result["error"]
        assert "'else' was unexpected" in result["error"]
        assert "ungrounded source" not in result["error"]
        assert _node(user, charts, chart)["content"] == ""
        # Retried with a document that validates, it is written, as before.
        grounding_routes._script(monkeypatch, [FIXED_VEGA])
        body = client.post(
            f"/api/agents/projects/{charts}/attachments/{att}/solve",
            json={"verify": False, "nodeIds": [chart]}, headers=_auth(token),
        ).get_json()
        assert body["results"][chart]["status"] == "solved", body["results"][chart]
        assert _node(user, charts, chart)["content"] == FIXED_VEGA

    def test_a_proposing_solve_proposes_no_document_that_does_not_validate(
        self, client, user_and_token, tmp_curio, charts, monkeypatch
    ):
        user, token = user_and_token
        att, chart = self._applied_chart(client, user, token, charts, monkeypatch, OWNERS_VEGA)
        r = client.post(
            f"/api/agents/projects/{charts}/attachments/{att}/solve/stream",
            json={"mode": "propose", "verify": False}, headers=_auth(token),
        )
        events = routes_solve.TestStreamedSolve()._sse_events(r)
        results = [p for k, p in events if k == "node_result" and p.get("nodeId") == chart]
        assert results and all(p["status"] == "failed" for p in results), results
        assert results[-1]["error"].startswith("document-invalid: "), results[-1]["error"]
        assert not any(p.get("proposalId") for p in results)
        assert _node(user, charts, chart)["content"] == ""
