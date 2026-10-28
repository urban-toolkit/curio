"""A Spatial Join's operation and output, set by an agent: a Dataflow Builder
plan and a Node Builder node.create, through the real mint, the review card
and both applies. A setting the join does not take, or one on a node that is
no Spatial Join, comes back to the model as an error naming it.

The helpers are the proposal route tests' own, reached through their module so
this one collects none of their tests.
"""
from __future__ import annotations

import json

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_routes_proposals as routes
from utk_curio.backend.tests.test_agents import test_source_grounding_routes as grounding_routes

DL = "curio.builtin/data-loading"
JOIN = "curio.builtin/spatial-join"
CA = "curio.builtin/computation-analysis"

#: A loader, the Spatial Join as curio.builtin@1 declares it, and a code node.
TEMPLATES = [
    {"id": "data-loading", "label": "Data Loading", "category": "data", "engine": "python", "editor": "code",
     "description": "Load data into the flow.",
     "inputPorts": [], "outputPorts": [{"types": ["GEODATAFRAME"], "cardinality": "1"}]},
    {"id": "spatial-join", "label": "Spatial Join", "category": "data", "engine": "python", "editor": "none",
     "hasCode": False, "hasGrammar": False, "behavior": "spatial-join",
     "description": "Pairs the rows of two inputs whose shapes meet.",
     "inputPorts": [{"types": ["GEODATAFRAME"], "cardinality": "1"}, {"types": ["GEODATAFRAME"], "cardinality": "1"}],
     "outputPorts": [{"types": ["GEODATAFRAME"], "cardinality": "1"}]},
    {"id": "computation-analysis", "label": "Computation Analysis", "category": "computation",
     "engine": "python", "editor": "code", "description": "Run python analysis code.",
     "inputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "[1,n]"}],
     "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
]

WITHIN_COUNTS = {"predicate": "within", "output": "counts"}


def _plan(join: dict | None = None, **join_node) -> dict:
    node = {"ref": "join", "nodeType": JOIN, "title": "Labels per neighborhood",
            "intent": "count the sidewalk labels within each neighborhood", **join_node}
    if join is not None:
        node["spatialJoin"] = join
    return {
        "goal": "count sidewalk labels per neighborhood",
        "nodes": [
            {"ref": "labels", "nodeType": DL, "title": "Labels", "intent": "sidewalk label points"},
            {"ref": "hoods", "nodeType": DL, "title": "Neighborhoods", "intent": "neighborhood polygons"},
            node,
        ],
        "edges": [
            {"from": "labels", "to": "join", "toHandle": "in"},
            {"from": "hoods", "to": "join", "toHandle": "in_1"},
        ],
    }


def _reply(plan: dict) -> str:
    return "Here is the plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"


def _mint(client, user, token, project_id, monkeypatch, replies):
    helper = routes.TestDataflowPlanMint()
    att_id, calls = helper._setup(client, user, token, project_id, monkeypatch, replies=replies, templates=TEMPLATES)
    r = helper._run(client, token, project_id, att_id)
    assert r.status_code == 200, r.get_json()
    proposal = next((p for p in r.get_json()["content"] if p["type"] == "proposal"), None)
    return att_id, proposal, calls


def _spec_nodes(user, project_id) -> list[dict]:
    return [n for n in routes.TestDataflowPlanApply()._spec(user, project_id)["dataflow"]["nodes"] if n["id"] != "n1"]


class TestAPlannedJoin:
    def test_its_operation_and_output_reach_the_card_and_the_node(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, proposal, _ = _mint(client, user, token, alice_project, monkeypatch, [_reply(_plan(WITHIN_COUNTS))])
        assert proposal is not None and proposal["status"] == "pending"
        rows = {n["ref"]: n for n in proposal["plan"]["nodes"]}
        # The card shows what the join will do, and nothing for the loaders.
        assert rows["join"]["spatialJoin"] == WITHIN_COUNTS
        assert "spatialJoin" not in rows["labels"]
        # And the card's text preview, the one line that names it.
        assert proposal["preview"].count("operation within, output counts") == 1
        r = routes.TestDataflowPlanApply()._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert r.status_code == 200, r.get_json()
        nodes = _spec_nodes(user, alice_project)
        join = next(n for n in nodes if str(n["type"]).startswith(JOIN))
        # Where the node keeps it, so it draws within and counts, not intersects and pairs.
        assert join["metadata"]["spatialJoin"] == WITHIN_COUNTS
        # A node that sets none keeps none.
        loaders = [n for n in nodes if str(n["type"]).startswith(DL)]
        assert len(loaders) == 2 and all("spatialJoin" not in (n.get("metadata") or {}) for n in loaders)
        # The bridge carries it to the live canvas.
        created = {n["id"]: n for n in r.get_json()["appliedGraph"]["nodes"]}
        assert created[join["id"]]["metadata"]["spatialJoin"] == WITHIN_COUNTS

    def test_the_node_by_node_apply_writes_it_too(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, proposal, _ = _mint(
            client, user, token, alice_project, monkeypatch, [_reply(_plan({"predicate": "nearest"}))],
        )
        body = routes.TestPerNodePlanApply()._apply_node(
            client, token, alice_project, att_id, proposal["proposalId"], "join",
        ).get_json()
        # Beside the header the plan names it with.
        assert body["createdNode"]["metadata"] == {
            "spatialJoin": {"predicate": "nearest"}, "packageTemplateLabel": "Labels per neighborhood",
        }

    def test_an_operation_the_join_has_not_is_refused_in_its_own_words(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        _, proposal, calls = _mint(
            client, user, token, alice_project, monkeypatch,
            [_reply(_plan({"predicate": "near"})), _reply(_plan({"predicate": "nearest"}))],
        )
        assert len(calls) == 2, "the plan with an operation the join has not was minted"
        assert (
            "nodes[2].spatialJoin: The operation must be one of intersects, within, contains, touches, "
            "overlaps, crosses, nearest; got 'near'."
        ) in calls[1][-1]["content"]
        # The corrected plan minted.
        assert {n["ref"]: n for n in proposal["plan"]["nodes"]}["join"]["spatialJoin"] == {"predicate": "nearest"}

    def test_a_setting_on_a_node_that_is_no_join_is_refused(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        wrong = _plan(WITHIN_COUNTS)
        wrong["nodes"][0]["spatialJoin"] = {"predicate": "within"}
        _, proposal, calls = _mint(
            client, user, token, alice_project, monkeypatch, [_reply(wrong), _reply(_plan(WITHIN_COUNTS))],
        )
        assert len(calls) == 2, "a loader with a join's setting was minted"
        assert (
            "plan node 'labels': a Data Loading node has no operation or output; "
            "only a Spatial Join node takes spatialJoin"
        ) in calls[1][-1]["content"]
        assert proposal is not None


class _JoinNodeBuilder(routes.TestNodeCreate):
    """The node.create helper, with the templates above."""

    def _write_builtin_package(self, user_key, templates=None):
        super()._write_builtin_package(user_key, templates or TEMPLATES)


class TestAProposedJoin:
    def _run(self, client, user, token, project_id, monkeypatch, *replies):
        helper = _JoinNodeBuilder()
        att_id, calls = helper._setup(client, user=user, token=token, project_id=project_id,
                                      monkeypatch=monkeypatch, replies=[*replies, "Proposed: review it above."])
        r = helper._run(client, token, project_id, att_id)
        assert r.status_code == 200, r.get_json()
        proposal = next((p for p in r.get_json()["content"] if p["type"] == "proposal"), None)
        # Every recorded call is the one message list the loop appends to, so
        # each node.create result is read by its prefix, never by its index.
        return helper, att_id, proposal, grounding_routes._tool_results(calls[-1], "node.create")

    def test_its_setting_reaches_the_card_and_the_node(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """A Spatial Join holds no content, so it is proposed without one; a
        node that holds code still needs its own."""
        user, token = user_and_token
        helper = _JoinNodeBuilder()
        no_code = helper._create_tail_json(nodeType=CA, content="")
        reply = helper._create_tail_json(nodeType=JOIN, title="Nearest label", spatialJoin={"predicate": "nearest"})
        helper, att_id, proposal, results = self._run(client, user, token, alice_project, monkeypatch, no_code, reply)
        refused, proposed = results
        assert "params.content must be a non-empty string" in refused, refused
        assert proposed.startswith("[tool result] node.create: proposed"), proposed
        assert proposal is not None, "a Spatial Join with no content was not proposed"
        assert proposal["summary"] == "Create a new Spatial Join node · Nearest label · operation nearest"
        resp = client.post(
            f"/api/agents/projects/{alice_project}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        created = resp.get_json()["createdNode"]
        assert created["content"] == ""  # a Spatial Join holds no content
        assert created["metadata"] == {"spatialJoin": {"predicate": "nearest"}}
        stored = next(n for n in helper._spec_nodes(user, alice_project) if n["id"] == created["id"])
        assert stored["metadata"]["spatialJoin"] == {"predicate": "nearest"}

    def test_a_wrong_setting_is_refused_to_the_model(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        reply = _JoinNodeBuilder()._create_tail_json(nodeType=JOIN, spatialJoin={"output": "polygons"})
        _, _, proposal, [refused] = self._run(client, user, token, alice_project, monkeypatch, reply)
        assert proposal is None
        assert "params.spatialJoin: The output must be one of pairs, counts; got 'polygons'." in refused, refused

    def test_a_setting_on_a_node_that_is_no_join_is_refused(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        reply = _JoinNodeBuilder()._create_tail_json(
            nodeType=CA, content="return input_0", spatialJoin={"predicate": "within"},
        )
        _, _, proposal, [refused] = self._run(client, user, token, alice_project, monkeypatch, reply)
        assert proposal is None, "a code node with a join's setting was proposed"
        assert (
            "params.spatialJoin: a Computation Analysis node has no operation or output; "
            "only a Spatial Join node takes spatialJoin"
        ) in refused, refused
