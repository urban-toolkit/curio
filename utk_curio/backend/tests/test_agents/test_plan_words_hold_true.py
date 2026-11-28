"""What a plan's ledger, its words and a Dataset Finder's chat say holds true
(fix round 3 of #1654, from a review of 61c6203c4b).

- A check holds only on the code it ran on: a batch's end, a row's Solve and
  Solve this node keep the digest of the code they checked, never of code a
  person typed meanwhile.
- A check of a node outranks an earlier batch's run of it.
- What comes of a pick says nothing that stops being true when a build ends.
- A batch's clock keeps the batch's start through its waves.
- When no card shows a Finder's candidates, its chat says plainly what it
  found and why none is offered.
- The closing sentence and the checks line say what boards S06 and S02 say.

Each check here fails at its own assertion on 61c6203c4b.
"""

from __future__ import annotations

import json
import time

from utk_curio.backend.app.agents.application import dataset_selection
from utk_curio.backend.app.agents.application.proposals import plans
from utk_curio.backend.app.agents.application.solve import node_solve
from utk_curio.backend.app.agents.application.solve import rounds as agents_rounds
from utk_curio.backend.app.agents.application.solve import session as solve_session
from utk_curio.backend.app.agents.application.solve import simulation
from utk_curio.backend.app.agents.application.solve import validate
from utk_curio.backend.app.agents.application.turns import titles
from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_dataset_discovery_routes import _Harness
from utk_curio.backend.tests.test_agents.test_routes_proposals import TestDataflowPlanMint
from utk_curio.backend.tests.test_agents.test_routes_solve import (
    TestSolve,
    TestStreamedSolve,
    TestValidateNode,
    _landed_plan,
    _node_agent,
    _saved_nodes,
)

#: The code the Node Builder writes for each node, and the code a person types.
WRITTEN, TYPED = "print('generated')", "print('mine')"


def _a_person_types(user_key: str, project_id: str, node_id: str, code: str) -> None:
    """A person's edit of the node *node_id*'s code, through the dataflow's one
    writer, as a tab's typing reaches it."""
    with projects_storage.spec_write_lock(user_key, project_id):
        live = dataflow_docs.live(user_key, project_id)
        next(n for n in live["dataflow"]["nodes"] if n["id"] == node_id)["content"] = code
        dataflow_docs.write(user_key, project_id, live, dataflow_docs.person(user_key, "edit"))


def _listed_session(client, token, project_id, attachment_id) -> dict:
    """The plan's ledger as the listing hands it every tab."""
    cards = client.get(f"/api/agents/projects/{project_id}/attachments", headers=_auth(token)).get_json()["attachments"]
    return next(c for c in cards if c["attachmentId"] == attachment_id)["builderSession"]


def _scripted(monkeypatch, on_call=None):
    """Every child of a Solve writes :data:`WRITTEN`; *on_call* runs at each
    call, with how many came before it."""
    asked: list = []

    def _fake_run(config, messages, **kwargs):
        if messages and messages[0].get("content") == titles.title_prompt():
            return "Title"
        asked.append(1)
        if on_call is not None:
            on_call(len(asked))
        return WRITTEN

    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", _fake_run)
    return asked


class TestACheckHoldsOnTheCodeItRan:
    def test_a_batch_keeps_no_check_of_a_node_typed_into_after_its_wave(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        """Wave 1 solves the first node; while wave 2 works on the second, a
        person types into the first. The batch ran the code it wrote, so its
        end keeps that check on that code, which the node holds no more.
        Before, the batch's end kept the check on the code the person typed."""
        user, token = user_and_token
        key = _user_dir_key(user)
        solve = TestSolve()
        att_id, _canvas, _calls = solve._applied_plan(client, user, token, alice_project, monkeypatch)
        ids = _listed_session(client, token, alice_project, att_id)["nodeIds"]
        asked = _scripted(monkeypatch, on_call=lambda n: n == 2 and _a_person_types(key, alice_project, ids["a"], TYPED))
        body = solve._solve(client, token, alice_project, att_id).get_json()
        assert len(asked) == 2 and body["results"][ids["a"]]["status"] == "solved", body["results"]
        assert _saved_nodes(user, alice_project)[ids["a"]]["content"] == TYPED
        assert _listed_session(client, token, alice_project, att_id).get("nodeChecks") == {"b": "ran"}

    def test_a_rows_solve_keeps_no_check_of_code_typed_after_it_landed(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        """The row's Solve landed the code that passed; a person typed into the
        node before its row was settled. Before, the check was kept on the
        person's code."""
        user, token = user_and_token
        key = _user_dir_key(user)
        rows = TestValidateNode()
        rows._fake_exec(monkeypatch)
        att_id, ref, node_id, _ = rows._setup_plan_node(
            client, user, token, alice_project, monkeypatch,
            replies=["Plan.\n" + TestDataflowPlanMint()._plan_tail(), WRITTEN],
        )
        landing = validate._land_validated

        def _then_a_person_types(*args, **kwargs):
            landed = yield from landing(*args, **kwargs)
            _a_person_types(key, alice_project, node_id, TYPED)
            return landed

        monkeypatch.setattr(validate, "_land_validated", _then_a_person_types)
        done = rows._validate(client, token, alice_project, att_id, {"ref": ref})[-1][1]
        assert done["verdict"] == "pass", done
        assert ref not in (_listed_session(client, token, alice_project, att_id).get("nodeChecks") or {})

    def test_solve_this_node_keeps_no_check_of_code_typed_after_it_wrote(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        """Solve this node wrote the code that passed into the empty node; a
        person typed into it before the plan's row was settled. Before, the
        plan kept the check on the person's code."""
        user, token = user_and_token
        key = _user_dir_key(user)
        TestValidateNode()._fake_exec(monkeypatch)
        att_id, card, ids, _ = _landed_plan(
            client, user, token, alice_project, monkeypatch,
            replies=["Plan.\n" + TestDataflowPlanMint()._plan_tail(), WRITTEN], install_nb=True,
        )
        ref = card["plan"]["nodes"][0]["ref"]
        node_id = ids[ref]
        concluding = node_solve._conclude

        def _then_a_person_types(*args, **kwargs):
            said = concluding(*args, **kwargs)
            _a_person_types(key, alice_project, node_id, TYPED)
            return said

        monkeypatch.setattr(node_solve, "_conclude", _then_a_person_types)
        builder = _node_agent(client, token, alice_project, node_id)["attachmentId"]
        r = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{builder}/solve-node",
            json={"nodeId": node_id}, headers=_auth(token),
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        done = TestStreamedSolve()._sse_events(r)[-1][1]
        assert done["verdict"] == "pass", done
        assert ref not in (_listed_session(client, token, alice_project, att_id).get("nodeChecks") or {})


class TestACheckOutranksAnEarlierBatch:
    def test_a_rows_failed_check_after_a_batch_leaves_no_word_of_the_batch_on_its_node(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        """A batch solved both nodes; then the first node's row Solve checked
        it again, and it failed. Its row reads failed, and the line pauses on
        it: the batch's word on the node is older. Before, the batch's
        "solved" stayed on the node, so the line read it built."""
        user, token = user_and_token
        solve = TestSolve()
        att_id, _canvas, _calls = solve._applied_plan(client, user, token, alice_project, monkeypatch)
        _scripted(monkeypatch)
        ids = _listed_session(client, token, alice_project, att_id)["nodeIds"]
        body = solve._solve(client, token, alice_project, att_id).get_json()
        assert {r["status"] for r in body["results"].values()} == {"solved"}, body["results"]
        TestValidateNode()._fake_exec(monkeypatch, fail_markers=(WRITTEN,))
        done = TestValidateNode()._validate(client, token, alice_project, att_id, {"ref": "a"})[-1][1]
        assert done["verdict"] == "fail", done
        listed = _listed_session(client, token, alice_project, att_id)
        assert listed["nodeStates"]["a"] == "failed", listed
        assert (listed.get("nodeRuns") or {}).get(ids["a"]) != "solved", listed


class TestWhatComesOfAPickStaysTrue:
    def test_a_pick_while_a_build_runs_names_no_run_that_ends(self, monkeypatch):
        """A pick made while Build & validate or a Step runs said "the Dataflow
        Builder's Build & validate, running now, builds X from it", which every
        tab kept showing after the build ended. It says what the plan does."""
        monkeypatch.setattr(dataset_selection, "_plan_agent_name", lambda user_key, coord: "Dataflow Builder")
        monkeypatch.setattr(dataset_selection, "_node_named", lambda user_key, project_id, node_id: "Load parks")
        said = {
            running: dataset_selection._plan_waiting("u", "p", "n1", {
                "coord": "agent.curio.dataflow-builder@1", "attachmentId": "dfb", "ref": "parks", "running": running,
            })["reason"]
            for running in ("auto", "step")
        }
        assert said == {
            "auto": "the Dataflow Builder builds Load parks from it",
            "step": "the Dataflow Builder builds Load parks from it",
        }


class _Clock:
    """The Solve session's clock, stopped at *at*; anything else of ``time``."""

    def __init__(self, at: float) -> None:
        self.at = at

    def time(self) -> float:
        return self.at

    def __getattr__(self, name):
        return getattr(time, name)


class TestTheBatchClock:
    def test_a_batch_keeps_when_it_began_through_its_waves(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch,
    ):
        """The plan line's clock counts from ``solvingSince``: a chat opened
        during the second wave counts from the batch's start. Before, each
        wave's persist moved it to that wave's end."""
        user, token = user_and_token
        key = _user_dir_key(user)
        solve = TestSolve()
        att_id, _canvas, _calls = solve._applied_plan(client, user, token, alice_project, monkeypatch)
        began = time.time() - 60
        monkeypatch.setattr(solve_session, "_time", _Clock(began))
        seen: list = []

        def _read_the_clock(n: int) -> None:
            if n == 2:
                spec = projects_storage.read_spec(key, alice_project)
                record = next(a for a in spec["dataflow"]["agentAttachments"] if a["attachmentId"] == att_id)
                seen.append(record["builderSession"].get("solvingSince"))

        _scripted(monkeypatch, on_call=_read_the_clock)
        body = solve._solve(client, token, alice_project, att_id).get_json()
        assert {r["status"] for r in body["results"].values()} == {"solved"}, body["results"]
        assert seen == [began], seen


class TestTheFindersChatWithNoCard:
    def test_it_says_what_it_found_and_why_none_is_offered(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """Every row the Finder named was rated under the fit floor: the
        runtime made no card. Its chat says so, in a line of its own, and the
        reply stays. Before, its chat drew nothing after the asked line."""
        rows = [{
            "name": f"Chicago context {i}", "sourceType": "portal",
            "url": f"https://data.example.org/context-{i}.geojson",
            "fit": {"score": score, "rationale": "context of the boundaries"},
        } for i, score in enumerate((20, 30))]
        reply = json.dumps({"datasetCandidates": {"lanes": {"external": rows, "catalog": []}}})
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, discover_replies=[reply])
        h.solve()
        said = [
            t.get("text") for t in h.session_turns(h.finder_attachment_id())
            if t.get("role") == "agent" and not t.get("forAgents")
        ]
        assert "I found 2 candidates for Load boundaries, and none can be offered: 2 were rated under a fit of 50." in said, said


class TestTheBoardsWords:
    def test_the_closing_sentence_says_the_chart_of_a_node_is_valid(self, monkeypatch):
        """Board S06: "…, and the chart of Library branch map is valid." Before,
        "Library branch map is valid against its grammar"."""
        spec = {"dataflow": {"nodes": [
            {"id": "n1", "type": "curio.builtin/python-computation", "content": "print(1)"},
            {"id": "n2", "type": "curio.builtin/vis-vega", "content": "{}"},
        ], "agentAttachments": []}}
        session = {
            "nodeIds": {"a": "n1", "b": "n2"},
            "nodeStates": {"a": "approved", "b": "approved"},
            "nodeChecks": {"a": "ran", "b": "valid"},
            "nodeCheckedCode": {"a": agents_rounds._content_sha("print(1)"), "b": agents_rounds._content_sha("{}")},
        }
        proposal = {"plan": {"nodes": [
            {"ref": "a", "title": "CPL branches", "nodeType": "curio.builtin/python-computation"},
            {"ref": "b", "title": "Library branch map", "nodeType": "curio.builtin/vis-vega"},
        ]}}
        said: list = []
        monkeypatch.setattr(simulation.sessions, "append_turns",
                            lambda user_key, project_id, session_id, attachment_id, turns: said.extend(turns))
        driver = object.__new__(simulation.SimulationDriver)
        driver.user_key, driver.project_id, driver.attachment_id = "u", "p", "dfb"
        driver._say_built(spec, {"attachmentId": "dfb", "sessionId": "s1"}, session, proposal)
        assert [turn["text"] for turn in said] == [
            "Built all 2 nodes. CPL branches ran in the sandbox, and the chart of Library branch map is valid. "
            "Each node's code and checks are in its own agent's chat."
        ]

    def test_the_checks_line_says_none_on_the_kind_of_node_it_does_not_attach_to(self):
        """Board S02-details: "Checks: no cycles. Node Builder on 3 nodes,
        Dataset Finder on CPL branches; none on the Python Computation node,
        where it does not attach." Before, "no Dataset Finder on Branch
        points, where it does not attach"."""
        spec = {"dataflow": {"nodes": [
            {"id": "n1", "type": "curio.builtin/data-loading", "title": "CPL branches"},
            {"id": "n2", "type": "curio.builtin/python-computation", "title": "Branch points"},
            {"id": "n3", "type": "curio.builtin/vis-vega", "title": "Library branch map"},
        ], "edges": []}}
        attached = [{
            "attached": [
                {"agentId": "nb", "name": "Node Builder", "nodeId": "n1"},
                {"agentId": "nb", "name": "Node Builder", "nodeId": "n2"},
                {"agentId": "nb", "name": "Node Builder", "nodeId": "n3"},
                {"agentId": "df", "name": "Dataset Finder", "nodeId": "n1"},
            ],
            "skipped": [{"agentId": "df", "name": "Dataset Finder", "nodeId": "n2", "notItsKind": True}],
        }]
        titles_of = {"n1": "CPL branches", "n2": "Branch points", "n3": "Library branch map"}
        templates = {"curio.builtin/python-computation": "Python Computation", "curio.builtin/data-loading": "Data Loading",
                     "curio.builtin/vis-vega": "Vega-Lite"}
        assert plans._plan_checks(spec, attached, titles_of, templates=templates) == [
            "Checks: no cycles. Node Builder on 3 nodes, Dataset Finder on CPL branches; "
            "none on the Python Computation node, where it does not attach."
        ]
