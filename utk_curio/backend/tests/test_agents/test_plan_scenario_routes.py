"""A Dataflow Builder plan's widgets and scenarios (#662) through the real
mint and the plan as it lands, whole, with its scenarios checked again after
it waited for a person. The node.create lane's widgets too.

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

#: The test builtin package of the plan route tests.
TEMPLATES = [
    {"id": "computation-analysis", "label": "Computation Analysis", "category": "computation",
     "engine": "python", "editor": "code", "description": "Run python analysis code.",
     "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,n]"}],
     "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
    {"id": "data-pool", "label": "Data Pool", "category": "data", "engine": "python", "editor": "none",
     "hasCode": False, "description": "Holds data.",
     "inputPorts": [{"types": ["JSON"], "cardinality": "1"}],
     "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
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


def _land(client, user, token, project_id, monkeypatch, plan=None, *, replies=None, before_run=None):
    """The plan the turn landed (its change card, with ``canvas``), or None."""
    helper = routes.TestDataflowPlanMint()
    att_id, calls = helper._setup(
        client, user, token, project_id, monkeypatch,
        replies=replies or [_reply(plan or _plan())], templates=TEMPLATES,
    )
    if before_run is not None:
        before_run()
    r = helper._run(client, token, project_id, att_id)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert not [p for p in body["content"] if p["type"] == "proposal"], "a plan waited for review"
    landed = any(p.get("kind") == "plan" for p in routes._changes(body))
    return att_id, (routes._landed_plan(body) if landed else None), calls


def _spec(user, project_id) -> dict:
    return routes.TestDataflowPlanApply()._spec(user, project_id)


def _write_spec(user, project_id, spec) -> None:
    from utk_curio.backend.app.projects import storage as projects_storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    projects_storage.write_spec(_user_dir_key(user), project_id, spec)


class TestThePlanCard:
    def test_the_card_names_each_scenario_its_nodes_the_copy_and_the_lever(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        _, card, _ = _land(client, user, token, alice_project, monkeypatch)
        assert card["status"] == "applied"
        assert card["summary"] == "Plan · 4 nodes, 4 edges, 2 scenarios"
        plan = card["plan"]
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
        assert "Scenario Twice as tall (a copy of Real heights): Shadows" in card["preview"]

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
        _, card, calls = _land(
            client, user, token, alice_project, monkeypatch,
            replies=[_reply(bad), _reply(fixed)], before_run=held,
        )
        feedback = calls[1][-1]["content"]
        assert "'n1' is already in the scenario 'Baseline': a node belongs to one scenario" in feedback
        # The corrected plan landed, and takes the color the dataflow's own scenario does not wear.
        assert card["plan"]["scenarios"][0]["color"] == "#e86a3c"

    def test_a_scenario_named_like_one_the_dataflow_has_is_refused_and_the_model_told_why(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """Scenario chips color and order a dataflow's scenarios by name, so a
        plan saves no second scenario under a name the dataflow gives one."""
        user, token = user_and_token

        def named():
            spec = _spec(user, alice_project)
            spec["dataflow"]["scenarios"] = [{"id": "s0", "name": "Real heights", "color": "#3567c7", "nodes": ["n1"]}]
            _write_spec(user, alice_project, spec)

        renamed = _plan()
        renamed["scenarios"][0]["name"] = "Mapped heights"
        renamed["scenarios"][1]["duplicateOf"] = "Mapped heights"
        _, card, calls = _land(
            client, user, token, alice_project, monkeypatch,
            replies=[_reply(_plan()), _reply(renamed)], before_run=named,
        )
        assert len(calls) == 2, "a plan naming a scenario as the dataflow already does landed"
        assert "the dataflow already has a scenario named 'Real heights'" in calls[1][-1]["content"]
        assert [s["name"] for s in card["plan"]["scenarios"]] == ["Mapped heights", "Twice as tall"]

    def test_widgets_on_a_node_that_holds_no_code_are_refused(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        pooled = _plan(scenarios=None)
        pooled["nodes"].append({"ref": "pool", "nodeType": POOL, "title": "Pool", "intent": "hold it",
                                "widgets": [dict(FACTOR)]})
        _, card, calls = _land(
            client, user, token, alice_project, monkeypatch,
            replies=[_reply(pooled), _reply(_plan(scenarios=None))],
        )
        assert "plan node 'pool' (Data Pool) cannot hold widgets" in calls[1][-1]["content"]
        assert "pool" not in {n["ref"] for n in card["plan"]["nodes"]}


class TestThePlanLands:
    def test_the_plan_writes_the_widgets_the_lineage_and_both_scenarios(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        from utk_curio.backend.app.projects.scenarios import scenario_problems

        user, token = user_and_token
        _att_id, card, _ = _land(client, user, token, alice_project, monkeypatch)
        canvas = card["canvas"]
        spec = _spec(user, alice_project)
        nodes = [n for n in spec["dataflow"]["nodes"] if n["id"] != "n1"]
        shadows = next(n for n in nodes if n["goal"].startswith("Shadows") and "copiedFrom" not in n.get("metadata", {}))
        copy = next(n for n in nodes if "copiedFrom" in n.get("metadata", {}))
        assert shadows["metadata"]["widgets"] == [FACTOR]
        assert copy["metadata"] == {"widgets": [{**FACTOR, "value": 2}], "copiedFrom": [shadows["id"]]}
        assert copy["goal"] == shadows["goal"]
        assert spec["dataflow"]["scenarios"] == [
            {"id": canvas["scenarios"][0]["id"], "name": "Real heights", "color": "#3567c7",
             "description": "the heights as mapped", "nodes": [shadows["id"]]},
            {"id": canvas["scenarios"][1]["id"], "name": "Twice as tall", "color": "#e86a3c",
             "nodes": [copy["id"]]},
        ]
        assert canvas["scenarios"] == spec["dataflow"]["scenarios"]
        assert scenario_problems(spec) == []
        # The copy reads the same context, and the comparison reads both on circles of its own.
        buildings = next(n for n in nodes if n["goal"].startswith("Buildings"))
        compare = next(n for n in nodes if n["goal"].startswith("Compare"))
        into = {(e["source"], e["target"]): e.get("targetHandle") for e in spec["dataflow"]["edges"]}
        assert (buildings["id"], copy["id"]) in into
        assert {into[(shadows["id"], compare["id"])], into[(copy["id"], compare["id"])]} == {"in", "in_1"}
        # The bridge carries the widgets and the lineage to the live canvas.
        created = {n["id"]: n for n in canvas["nodes"]}
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
        # The planner's ledger says which scenarios are saved, across reloads.
        cards = client.get(f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)).get_json()
        planner = next(c for c in cards["attachments"] if c["attachmentId"] == _att_id)
        assert planner["planProposal"]["scenarioStates"] == {"0": "applied", "1": "applied"}

    def _wait_for_ana_in_n2(self, user, project_id, monkeypatch, scenario):
        """The canvas gets a second node, n2, the plan removes; Ana holds it and,
        while the plan waits for her, saves *scenario*, then leaves."""
        import time as real_time
        from types import SimpleNamespace

        from utk_curio.backend.app.agents.application.proposals import changes
        from utk_curio.backend.app.collaboration import dataflow_docs
        from utk_curio.backend.app.collaboration import room_state
        from utk_curio.backend.app.projects.services import _user_dir_key

        held = {"by": "Ana"}
        real_snapshot = room_state.snapshot

        def _snapshot(room):
            out = dict(real_snapshot(room) or {})
            if held["by"]:
                out["locks"] = {"n2": {"user_id": "someone-else", "name": held["by"]}}
            return out

        def _sleep(seconds):
            if held["by"]:
                spec = dataflow_docs.live(_user_dir_key(user), project_id)
                spec["dataflow"]["scenarios"] = [dict(scenario)]
                dataflow_docs.write(_user_dir_key(user), project_id, spec, dataflow_docs.person("someone-else", "edit"))
                held["by"] = None

        def second_node():
            spec = _spec(user, project_id)
            spec["dataflow"]["nodes"].append({"id": "n2", "content": "print(2)", "x": 10, "y": 400})
            _write_spec(user, project_id, spec)

        monkeypatch.setattr(room_state, "snapshot", _snapshot)
        monkeypatch.setattr(changes, "time", SimpleNamespace(monotonic=real_time.monotonic, sleep=_sleep))
        return held, second_node

    def test_a_scenario_whose_node_was_taken_while_the_plan_waited_refuses_it(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """A scenario a person saved while the plan waited for them, holding a
        node the plan's scenario names: the plan lands nothing, never a
        scenario written over the person's."""
        user, token = user_and_token
        mine = _plan(scenarios=None, removeNodes=["n2"])
        mine["scenarios"] = [{"name": "Mine", "nodes": ["n1", "shadows"]}]
        held, second_node = self._wait_for_ana_in_n2(
            user, alice_project, monkeypatch, {"id": "s0", "name": "Theirs", "color": "#3567c7", "nodes": ["n1"]},
        )
        _, card, calls = _land(client, user, token, alice_project, monkeypatch,
                               replies=[_reply(mine), "Ana saved one."], before_run=second_node)
        assert held["by"] is None, "the plan never waited for Ana"
        assert card is None
        assert "the scenario Mine the plan saves" in calls[-1][-1]["content"]
        spec = _spec(user, alice_project)
        assert [s["name"] for s in spec["dataflow"]["scenarios"]] == ["Theirs"]
        assert {n["id"] for n in spec["dataflow"]["nodes"]} == {"n1", "n2"}

    def test_a_scenario_whose_name_was_taken_while_the_plan_waited_refuses_it(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """The person named a scenario as the plan does while it waited for
        them: the plan's is never saved beside theirs under one name."""
        user, token = user_and_token
        mine = _plan(scenarios=None, removeNodes=["n2"])
        mine["scenarios"] = [{"name": "Mine", "nodes": ["shadows"]}]
        held, second_node = self._wait_for_ana_in_n2(
            user, alice_project, monkeypatch, {"id": "s0", "name": "Mine", "color": "#3567c7", "nodes": ["n1"]},
        )
        _, card, calls = _land(client, user, token, alice_project, monkeypatch,
                               replies=[_reply(mine), "Ana saved one."], before_run=second_node)
        assert held["by"] is None, "the plan never waited for Ana"
        assert card is None
        assert [s["id"] for s in _spec(user, alice_project)["dataflow"]["scenarios"]] == ["s0"]


class TestNodeCreateWidgets:
    def test_a_created_node_keeps_the_widgets_its_code_reads(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        helper = routes.TestNodeCreate()
        reply = helper._create_tail_json(
            content="return input_0 * [!! factor !!]", widgets=[{"name": "factor", "type": "number", "default": 2}],
        )
        att_id, _ = helper._setup(client, user=user, token=token, project_id=alice_project, monkeypatch=monkeypatch,
                                  replies=[reply, "Added it."])
        body = helper._run(client, token, alice_project, att_id).get_json()
        [card] = routes._changes(body)
        assert card["summary"].endswith("· widgets factor")
        created = helper._created(body)
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
        assert all(p["type"] not in ("proposal", "change") for p in r.get_json()["content"])
        assert "params.widgets[0] ('f'): A slider needs a minimum and a maximum." in calls[1][-1]["content"]
