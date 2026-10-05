"""A Dataflow Builder plan's widgets and scenarios (#662) through the real
mint, the review card and both applies: the whole plan at once, and node by
node, where a scenario is saved with the last of its nodes. The node.create
lane's widgets too.

The plan grammar is in ``test_plan_scenarios.py``. The helpers are the plan
route tests' own, reached through their module so this one collects none of
their tests.
"""
from __future__ import annotations

import json

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_routes_proposals as routes

CA = "curio.builtin/computation-analysis"
POOL = "curio.builtin/data-pool"
PARAMETER = "curio.builtin/parameter"

#: The test builtin package of the plan route tests, plus a Parameter template.
TEMPLATES = [
    {"id": "computation-analysis", "label": "Computation Analysis", "category": "computation",
     "engine": "python", "editor": "code", "description": "Run python analysis code.",
     "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,n]"}],
     "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
    {"id": "data-pool", "label": "Data Pool", "category": "data", "engine": "python", "editor": "none",
     "hasCode": False, "description": "Holds data.",
     "inputPorts": [{"types": ["JSON"], "cardinality": "1"}],
     "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
    {"id": "parameter", "label": "Parameter", "category": "flow", "engine": "python", "editor": "none",
     "hasCode": False, "hasGrammar": False, "hasWidgets": True, "description": "One value any node can use.",
     "inputPorts": [], "outputPorts": []},
]

FACTOR = {"name": "height_factor", "type": "number", "label": "Height factor", "default": 1,
          "options": {"min": 0.5, "max": 4, "step": 0.5}}


def _plan(**extra) -> dict:
    plan = {
        "goal": "compare real and doubled building heights",
        "nodes": [
            {"ref": "buildings", "nodeType": CA, "title": "Buildings", "intent": "a frame of building heights"},
            {"ref": "shadows", "nodeType": CA, "title": "Shadows", "intent": "shadow length per building",
             "widgets": [dict(FACTOR)]},
            {"ref": "compare", "nodeType": CA, "title": "Compare", "intent": "mean shadow per scenario"},
        ],
        "edges": [
            {"from": "buildings", "to": "shadows"},
            {"from": "shadows", "to": "compare"},
            {"from": "shadows_tall", "to": "compare"},
        ],
        "scenarios": [
            {"name": "Real heights", "nodes": ["shadows"], "description": "the heights as mapped"},
            {"name": "Twice as tall", "duplicateOf": "Real heights", "copies": {"shadows": "shadows_tall"},
             "values": {"shadows_tall": {"height_factor": 2}}},
        ],
    }
    plan.update(extra)
    if plan.get("scenarios") is None:
        # No duplicate, so no copy for the comparison to read.
        plan.pop("scenarios", None)
        plan["edges"] = [e for e in plan["edges"] if e["from"] != "shadows_tall"]
    return plan


def _reply(plan: dict) -> str:
    return "Here is the plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"


def _mint(client, user, token, project_id, monkeypatch, plan=None, *, replies=None, before_run=None):
    helper = routes.TestDataflowPlanMint()
    att_id, calls = helper._setup(
        client, user, token, project_id, monkeypatch,
        replies=replies or [_reply(plan or _plan())], templates=TEMPLATES,
    )
    if before_run is not None:
        before_run()
    r = helper._run(client, token, project_id, att_id)
    assert r.status_code == 200, r.get_json()
    proposal = next((p for p in r.get_json()["content"] if p["type"] == "proposal"), None)
    return att_id, proposal, calls


def _spec(user, project_id) -> dict:
    return routes.TestDataflowPlanApply()._spec(user, project_id)


def _write_spec(user, project_id, spec) -> None:
    from utk_curio.backend.app.projects import storage as projects_storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    projects_storage.write_spec(_user_dir_key(user), project_id, spec)


def _apply(client, token, project_id, att_id, proposal_id):
    return routes.TestDataflowPlanApply()._apply(client, token, project_id, att_id, proposal_id)


def _apply_node(client, token, project_id, att_id, proposal_id, ref):
    return routes.TestPerNodePlanApply()._apply_node(client, token, project_id, att_id, proposal_id, ref)


def _by_goal(spec) -> dict:
    return {n["goal"]: n for n in spec["dataflow"]["nodes"] if n.get("id") != "n1"}


class TestTheReview:
    def test_the_card_names_each_scenario_its_nodes_the_copy_and_the_lever(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        _, proposal, _ = _mint(client, user, token, alice_project, monkeypatch)
        assert proposal["status"] == "pending"
        assert proposal["summary"] == "Apply plan · 4 nodes, 4 edges, 2 scenarios"
        plan = proposal["plan"]
        # The two scenarios take the canvas's first two colors, in turn.
        assert plan["scenarios"] == [
            {"name": "Real heights", "color": "#3567c7", "description": "the heights as mapped",
             "nodes": [{"ref": "shadows", "label": "Shadows"}]},
            {"name": "Twice as tall", "color": "#e86a3c", "duplicateOf": "Real heights",
             "values": {"shadows_tall": {"height_factor": 2}},
             "nodes": [{"ref": "shadows_tall", "label": "Shadows"}]},
        ]
        rows = {n["ref"]: n for n in plan["nodes"]}
        assert rows["shadows"]["scenario"] == "Real heights"
        assert rows["shadows_tall"]["scenario"] == "Twice as tall"
        assert rows["shadows_tall"]["copyOf"] == "shadows"
        assert rows["shadows_tall"]["widgets"] == [{**{k: FACTOR[k] for k in ("name", "type", "label", "default")}, "value": 2}]
        assert "scenario" not in rows["buildings"] and "widgets" not in rows["buildings"]
        # A copy's connections read apart from its original's.
        labels = {(e["fromLabel"], e["toLabel"]) for e in plan["edges"]}
        assert ("Buildings", "Shadows (Twice as tall)") in labels
        assert ("Shadows (Real heights)", "Compare") in labels
        assert "Scenario Twice as tall (a copy of Real heights): Shadows" in proposal["preview"]

    def test_a_node_another_scenario_holds_is_refused_and_the_model_told_why(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token

        def held():
            spec = _spec(user, alice_project)
            spec["dataflow"]["scenarios"] = [{"id": "s0", "name": "Baseline", "color": "#3567c7", "nodes": ["n1"]}]
            _write_spec(user, alice_project, spec)

        bad = _plan(scenarios=None)
        bad["scenarios"] = [{"name": "Mine", "nodes": ["n1", "shadows"]}]
        fixed = _plan(scenarios=None)
        fixed["scenarios"] = [{"name": "Mine", "nodes": ["shadows"]}]
        _, proposal, calls = _mint(
            client, user, token, alice_project, monkeypatch,
            replies=[_reply(bad), _reply(fixed)], before_run=held,
        )
        feedback = calls[1][-1]["content"]
        assert "'n1' is already in the scenario 'Baseline': a node belongs to one scenario" in feedback
        # The corrected plan minted, and takes the color the dataflow's own scenario does not wear.
        assert proposal["plan"]["scenarios"][0]["color"] == "#e86a3c"

    def test_widgets_on_a_node_that_holds_no_code_are_refused(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        pooled = _plan(scenarios=None)
        pooled["nodes"].append({"ref": "pool", "nodeType": POOL, "title": "Pool", "intent": "hold it",
                                "widgets": [dict(FACTOR)]})
        _, _, calls = _mint(
            client, user, token, alice_project, monkeypatch,
            replies=[_reply(pooled), _reply(_plan(scenarios=None))],
        )
        assert "plan node 'pool' (Data Pool) cannot hold widgets" in calls[1][-1]["content"]

    def test_a_parameter_named_like_another_is_refused(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token

        def season():
            spec = _spec(user, alice_project)
            spec["dataflow"]["nodes"].append({
                "id": "p0", "type": PARAMETER, "x": 0, "y": 400, "content": "",
                "metadata": {"widgets": [{"name": "season", "type": "text", "default": "winter"}]},
            })
            _write_spec(user, alice_project, spec)

        parameter = {"ref": "p", "nodeType": PARAMETER, "title": "Season", "intent": "the season",
                     "widgets": [{"name": "season", "type": "text", "default": "summer"}]}
        _, _, calls = _mint(
            client, user, token, alice_project, monkeypatch,
            replies=[_reply({"goal": "g", "nodes": [parameter]}), _reply(_plan(scenarios=None))],
            before_run=season,
        )
        assert "plan node 'p': Another Parameter node is named season." in calls[1][-1]["content"]


class TestThePlanApply:
    def test_the_apply_writes_the_widgets_the_lineage_and_both_scenarios(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        from utk_curio.backend.app.projects.scenarios import scenario_problems

        user, token = user_and_token
        att_id, proposal, _ = _mint(client, user, token, alice_project, monkeypatch)
        r = _apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        spec = _spec(user, alice_project)
        nodes = [n for n in spec["dataflow"]["nodes"] if n["id"] != "n1"]
        shadows = next(n for n in nodes if n["goal"].startswith("Shadows") and "copiedFrom" not in n.get("metadata", {}))
        copy = next(n for n in nodes if "copiedFrom" in n.get("metadata", {}))
        assert shadows["metadata"]["widgets"] == [FACTOR]
        assert copy["metadata"] == {"widgets": [{**FACTOR, "value": 2}], "copiedFrom": [shadows["id"]]}
        assert copy["goal"] == shadows["goal"]
        assert spec["dataflow"]["scenarios"] == [
            {"id": body["appliedGraph"]["scenarios"][0]["id"], "name": "Real heights", "color": "#3567c7",
             "description": "the heights as mapped", "nodes": [shadows["id"]]},
            {"id": body["appliedGraph"]["scenarios"][1]["id"], "name": "Twice as tall", "color": "#e86a3c",
             "nodes": [copy["id"]]},
        ]
        assert body["appliedGraph"]["scenarios"] == spec["dataflow"]["scenarios"]
        assert scenario_problems(spec) == []
        # The copy reads the same context, and the comparison reads both on circles of its own.
        buildings = next(n for n in nodes if n["goal"].startswith("Buildings"))
        compare = next(n for n in nodes if n["goal"].startswith("Compare"))
        into = {(e["source"], e["target"]): e.get("targetHandle") for e in spec["dataflow"]["edges"]}
        assert (buildings["id"], copy["id"]) in into
        assert {into[(shadows["id"], compare["id"])], into[(copy["id"], compare["id"])]} == {"in", "in_1"}
        # The bridge carries the widgets and the lineage to the live canvas.
        created = {n["id"]: n for n in body["appliedGraph"]["nodes"]}
        assert created[copy["id"]]["metadata"]["copiedFrom"] == [shadows["id"]]
        # And the agent reads the scenarios back with their parts.
        from utk_curio.backend.app.agents.application import tools
        from utk_curio.backend.app.projects.services import _user_dir_key

        _, text = tools.execute_read_tool(
            "dataflow.read", user_key=_user_dir_key(user), project_id=alice_project, target=None, params={}
        )
        read = {s["name"]: s for s in json.loads(text)["scenarios"]}
        assert read["Twice as tall"]["context"] == [buildings["id"]]
        assert read["Twice as tall"]["levers"] == read["Twice as tall"]["outcomes"] == [copy["id"]]

    def test_a_scenario_whose_node_was_taken_since_the_mint_is_not_saved(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """The shape digest covers ids only: a scenario edit between mint and
        apply is caught by the apply's own check, and the scenario is refused,
        never written over the user's."""
        user, token = user_and_token
        mine = _plan(scenarios=None)
        mine["scenarios"] = [{"name": "Mine", "nodes": ["n1", "shadows"]}]
        att_id, proposal, _ = _mint(client, user, token, alice_project, monkeypatch, mine)
        spec = _spec(user, alice_project)
        spec["dataflow"]["scenarios"] = [{"id": "s0", "name": "Theirs", "color": "#3567c7", "nodes": ["n1"]}]
        _write_spec(user, alice_project, spec)
        body = _apply(client, token, alice_project, att_id, proposal["proposalId"]).get_json()
        assert "scenarios" not in body["appliedGraph"]
        assert [s["name"] for s in _spec(user, alice_project)["dataflow"]["scenarios"]] == ["Theirs"]


class TestTheNodeByNodeApply:
    def test_a_copy_waits_for_its_original_and_each_scenario_is_saved_with_its_last_node(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, proposal, _ = _mint(client, user, token, alice_project, monkeypatch)
        pid = proposal["proposalId"]
        early = _apply_node(client, token, alice_project, att_id, pid, "shadows_tall")
        assert early.status_code == 409
        assert "create 'Shadows' first" in early.get_json()["error"]

        assert "createdScenarios" not in _apply_node(client, token, alice_project, att_id, pid, "buildings").get_json()
        first = _apply_node(client, token, alice_project, att_id, pid, "shadows").get_json()
        assert [s["name"] for s in first["createdScenarios"]] == ["Real heights"]
        assert first["scenarioStates"] == {"0": "applied"}
        original = first["createdNode"]
        assert original["metadata"] == {"widgets": [FACTOR]}

        second = _apply_node(client, token, alice_project, att_id, pid, "shadows_tall").get_json()
        assert second["createdNode"]["metadata"] == {"widgets": [{**FACTOR, "value": 2}], "copiedFrom": [original["id"]]}
        assert [s["name"] for s in second["createdScenarios"]] == ["Twice as tall"]
        assert second["status"] == "pending"  # compare and its edges are still to come
        spec = _spec(user, alice_project)
        assert [s["nodes"] for s in spec["dataflow"]["scenarios"]] == [[original["id"]], [second["createdNode"]["id"]]]

        last = _apply_node(client, token, alice_project, att_id, pid, "compare").get_json()
        assert last["status"] == "applied"  # every node, edge and scenario of the plan exists
        # The review mirror carries which scenarios are saved, across reloads.
        from utk_curio.backend.app.agents.application import attachments
        from utk_curio.backend.app.agents.application.proposals import store

        stored = attachments.get_active_proposal(_spec(user, alice_project), att_id)
        assert stored["proposalId"] == pid
        assert store._proposal_summary(stored)["scenarioStates"] == {"0": "applied", "1": "applied"}


class TestNodeCreateWidgets:
    def test_a_created_node_keeps_the_widgets_its_code_reads(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        helper = routes.TestNodeCreate()
        reply = helper._create_tail_json(
            content="return arg * [!! factor !!]", widgets=[{"name": "factor", "type": "number", "default": 2}],
        )
        att_id, _ = helper._setup(client, user=user, token=token, project_id=alice_project, monkeypatch=monkeypatch,
                                  replies=[reply, "Proposed: review it above."])
        proposal = helper._proposal_from_run(helper._run(client, token, alice_project, att_id))
        assert proposal["summary"].endswith("· widgets factor")
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        created = resp.get_json()["createdNode"]
        assert created["metadata"] == {"widgets": [{"name": "factor", "type": "number", "default": 2}]}
        stored = next(n for n in helper._spec_nodes(user, alice_project) if n["id"] == created["id"])
        assert stored["metadata"]["widgets"] == [{"name": "factor", "type": "number", "default": 2}]

    def test_a_wrong_widget_is_refused_to_the_model(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        helper = routes.TestNodeCreate()
        reply = helper._create_tail_json(content="return 1", widgets=[{"name": "f", "type": "slider"}])
        att_id, calls = helper._setup(client, user=user, token=token, project_id=alice_project,
                                      monkeypatch=monkeypatch, replies=[reply, "done"])
        r = helper._run(client, token, alice_project, att_id)
        assert all(p["type"] != "proposal" for p in r.get_json()["content"])
        assert "params.widgets[0] ('f'): A slider needs a minimum and a maximum." in calls[1][-1]["content"]
