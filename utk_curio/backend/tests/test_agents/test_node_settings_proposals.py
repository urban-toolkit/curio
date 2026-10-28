"""A Data Pool's conflict modes and a Simple View's image column, set by an
agent: a Dataflow Builder plan and a Node Builder node.create, through the real
mint, the review card and both applies. A mode the pool has not, an empty
image column, or a setting on a node of another template comes back to the
model as an error naming it.

The helpers are the proposal route tests' own, reached through their module so
this one collects none of their tests.
"""
from __future__ import annotations

import json

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_routes_proposals as routes
from utk_curio.backend.tests.test_agents import test_source_grounding_routes as grounding_routes

DL = "curio.builtin/data-loading"
POOL = "curio.builtin/data-pool"
VIEW = "curio.builtin/vis-simple"
CA = "curio.builtin/computation-analysis"

#: A loader, the Data Pool and the Simple View as curio.builtin@1 declares
#: them, each with its behavior, and a code node.
TEMPLATES = [
    {"id": "data-loading", "label": "Data Loading", "category": "data", "engine": "python", "editor": "code",
     "description": "Load data into the flow.",
     "inputPorts": [], "outputPorts": [{"types": ["GEODATAFRAME"], "cardinality": "1"}]},
    {"id": "data-pool", "label": "Data Pool", "category": "data", "engine": "python", "editor": "none",
     "hasCode": False, "hasGrammar": False, "behavior": "data-pool",
     "description": "Shows its input as a table and marks the rows selected in the views linked to it.",
     "inputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "[1,n]"}],
     "outputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "1"}]},
    {"id": "vis-simple", "label": "Simple View", "category": "vis_simple", "engine": "python", "editor": "none",
     "hasCode": False, "hasGrammar": False, "behavior": "simple-vis",
     "description": "Displays incoming data: a table, or a card per row when the frame carries images.",
     "inputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "1"}],
     "outputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "1"}]},
    {"id": "computation-analysis", "label": "Computation Analysis", "category": "computation",
     "engine": "python", "editor": "code", "description": "Run python analysis code.",
     "inputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "[1,n]"}],
     "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
]

MERGED = {"betweenCharts": "MERGE_AND"}
OVERLAYS = {"imageColumn": "overlay_url"}
#: The card's words for them: the pool's and the view's own.
MERGED_WORDS = "Conflict between visualizations: Merge (AND)"
OVERLAYS_WORDS = "Image column: overlay_url"


def _plan(pool: dict | None = None, view: dict | None = None) -> dict:
    pool_node = {"ref": "pool", "nodeType": POOL, "title": "Picked photos",
                 "intent": "the photos picked in both charts"}
    if pool is not None:
        pool_node["dataPool"] = pool
    view_node = {"ref": "view", "nodeType": VIEW, "title": "Overlays",
                 "intent": "the overlay of each picked photo"}
    if view is not None:
        view_node["simpleVis"] = view
    return {
        "goal": "show the overlays of the photos picked in both charts",
        "nodes": [
            {"ref": "photos", "nodeType": DL, "title": "Photos", "intent": "street photos with their overlays"},
            pool_node,
            view_node,
        ],
        "edges": [{"from": "photos", "to": "pool"}, {"from": "pool", "to": "view"}],
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


def _spec_nodes(user, project_id) -> dict[str, dict]:
    nodes = routes.TestDataflowPlanApply()._spec(user, project_id)["dataflow"]["nodes"]
    return {str(n["type"]).split("@", 1)[0]: n for n in nodes if n["id"] != "n1"}


class TestAPlannedPoolAndView:
    def test_their_settings_reach_the_card_the_spec_and_the_canvas(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, proposal, _ = _mint(
            client, user, token, alice_project, monkeypatch, [_reply(_plan(MERGED, OVERLAYS))],
        )
        assert proposal is not None and proposal["status"] == "pending"
        rows = {n["ref"]: n for n in proposal["plan"]["nodes"]}
        # The card shows what each node will do, and nothing for the loader.
        assert rows["pool"]["dataPool"] == MERGED
        assert rows["view"]["simpleVis"] == OVERLAYS
        assert not {"dataPool", "simpleVis"} & set(rows["photos"])
        assert "simpleVis" not in rows["pool"] and "dataPool" not in rows["view"]
        # And the card's text preview, each in the node's own words, once.
        assert proposal["preview"].count(MERGED_WORDS) == 1
        assert proposal["preview"].count(OVERLAYS_WORDS) == 1
        r = routes.TestDataflowPlanApply()._apply(client, token, alice_project, att_id, proposal["proposalId"])
        assert r.status_code == 200, r.get_json()
        nodes = _spec_nodes(user, alice_project)
        # Where each node keeps it, so the pool merges and the view shows the overlays.
        assert nodes[POOL]["metadata"]["dataPool"] == MERGED
        assert nodes[VIEW]["metadata"]["simpleVis"] == OVERLAYS
        assert not {"dataPool", "simpleVis"} & set(nodes[DL].get("metadata") or {})
        # The bridge carries them to the live canvas.
        created = {n["id"]: n for n in r.get_json()["appliedGraph"]["nodes"]}
        assert created[nodes[POOL]["id"]]["metadata"]["dataPool"] == MERGED
        assert created[nodes[VIEW]["id"]]["metadata"]["simpleVis"] == OVERLAYS

    def test_the_node_by_node_apply_writes_them_too(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        both = {"insideChart": "MERGE_OR", "betweenCharts": "MERGE_AND"}
        att_id, proposal, _ = _mint(
            client, user, token, alice_project, monkeypatch, [_reply(_plan(both, OVERLAYS))],
        )
        apply_node = routes.TestPerNodePlanApply()._apply_node
        pool = apply_node(client, token, alice_project, att_id, proposal["proposalId"], "pool").get_json()
        # Beside the header the plan names it with.
        assert pool["createdNode"]["metadata"] == {"dataPool": both, "packageTemplateLabel": "Picked photos"}
        view = apply_node(client, token, alice_project, att_id, proposal["proposalId"], "view").get_json()
        assert view["createdNode"]["metadata"] == {"simpleVis": OVERLAYS, "packageTemplateLabel": "Overlays"}

    def test_an_explicit_overwrite_is_the_pools_default_and_sets_nothing(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        att_id, proposal, calls = _mint(
            client, user, token, alice_project, monkeypatch,
            [_reply(_plan({"insideChart": "OVERWRITE", "betweenCharts": "MERGE_OR"}))],
        )
        assert len(calls) == 1, "a plan the pool takes was sent back"
        assert {n["ref"]: n for n in proposal["plan"]["nodes"]}["pool"]["dataPool"] == {"betweenCharts": "MERGE_OR"}
        assert "Conflict inside visualization" not in proposal["preview"]

    def test_a_mode_the_pool_has_not_is_refused_in_words_that_name_its_modes(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        _, proposal, calls = _mint(
            client, user, token, alice_project, monkeypatch,
            [_reply(_plan({"betweenCharts": "MERGE_(AND)"})), _reply(_plan(MERGED))],
        )
        assert len(calls) == 2, "the plan with a mode the pool has not was minted"
        assert (
            "nodes[1].dataPool.betweenCharts must be one of OVERWRITE, MERGE_AND, MERGE_OR; got 'MERGE_(AND)', "
            "which a Data Pool reads as OVERWRITE"
        ) in calls[1][-1]["content"]
        # The corrected plan minted.
        assert {n["ref"]: n for n in proposal["plan"]["nodes"]}["pool"]["dataPool"] == MERGED

    def test_an_empty_image_column_is_refused(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        _, proposal, calls = _mint(
            client, user, token, alice_project, monkeypatch,
            [_reply(_plan(view={"imageColumn": "  "})), _reply(_plan(view=OVERLAYS))],
        )
        assert len(calls) == 2, "the plan with an empty image column was minted"
        assert "nodes[2].simpleVis.imageColumn must name a column, such as" in calls[1][-1]["content"]
        assert {n["ref"]: n for n in proposal["plan"]["nodes"]}["view"]["simpleVis"] == OVERLAYS

    def test_a_setting_on_a_node_of_another_template_is_refused(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        wrong = _plan(MERGED, OVERLAYS)
        wrong["nodes"][0]["dataPool"] = MERGED
        wrong["nodes"][1]["simpleVis"] = OVERLAYS
        _, proposal, calls = _mint(
            client, user, token, alice_project, monkeypatch, [_reply(wrong), _reply(_plan(MERGED, OVERLAYS))],
        )
        assert len(calls) == 2, "a loader with a pool's modes was minted"
        said = calls[1][-1]["content"]
        assert (
            "plan node 'photos': a Data Loading node has no conflict modes; only a Data Pool node takes dataPool"
        ) in said
        assert (
            "plan node 'pool': a Data Pool node has no image column; only a Simple View node takes simpleVis"
        ) in said
        assert proposal is not None


class _SettingsNodeBuilder(routes.TestNodeCreate):
    """The node.create helper, with the templates above."""

    def _write_builtin_package(self, user_key, templates=None):
        super()._write_builtin_package(user_key, templates or TEMPLATES)


class TestAProposedPoolAndView:
    def _run(self, client, user, token, project_id, monkeypatch, *replies):
        helper = _SettingsNodeBuilder()
        att_id, calls = helper._setup(client, user=user, token=token, project_id=project_id,
                                      monkeypatch=monkeypatch, replies=[*replies, "Proposed: review it above."])
        r = helper._run(client, token, project_id, att_id)
        assert r.status_code == 200, r.get_json()
        proposal = next((p for p in r.get_json()["content"] if p["type"] == "proposal"), None)
        # Every recorded call is the one message list the loop appends to, so
        # each node.create result is read by its prefix, never by its index.
        return helper, att_id, proposal, grounding_routes._tool_results(calls[-1], "node.create")

    def _apply(self, client, token, project_id, att_id, proposal) -> dict:
        resp = client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.get_json()
        return resp.get_json()["createdNode"]

    def test_a_pools_modes_reach_the_card_and_the_node(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        reply = _SettingsNodeBuilder()._create_tail_json(nodeType=POOL, title="Picked photos", content="",
                                                           dataPool=MERGED)
        helper, att_id, proposal, [proposed] = self._run(client, user, token, alice_project, monkeypatch, reply)
        assert proposed.startswith("[tool result] node.create: proposed"), proposed
        assert proposal["summary"] == f"Create a new Data Pool node · Picked photos · {MERGED_WORDS}"
        created = self._apply(client, token, alice_project, att_id, proposal)
        assert created["content"] == ""  # a Data Pool holds no content
        assert created["metadata"] == {"dataPool": MERGED}
        stored = next(n for n in helper._spec_nodes(user, alice_project) if n["id"] == created["id"])
        assert stored["metadata"]["dataPool"] == MERGED

    def test_a_views_image_column_reaches_the_card_and_the_node(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        reply = _SettingsNodeBuilder()._create_tail_json(nodeType=VIEW, title="Overlays", content="",
                                                           simpleVis={"imageColumn": " overlay_url "})
        helper, att_id, proposal, [proposed] = self._run(client, user, token, alice_project, monkeypatch, reply)
        assert proposed.startswith("[tool result] node.create: proposed"), proposed
        assert proposal["summary"] == f"Create a new Simple View node · Overlays · {OVERLAYS_WORDS}"
        created = self._apply(client, token, alice_project, att_id, proposal)
        assert created["metadata"] == {"simpleVis": OVERLAYS}
        stored = next(n for n in helper._spec_nodes(user, alice_project) if n["id"] == created["id"])
        assert stored["metadata"]["simpleVis"] == OVERLAYS

    def test_a_mode_the_pool_has_not_is_refused_to_the_model(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        reply = _SettingsNodeBuilder()._create_tail_json(nodeType=POOL, content="", dataPool={"insideChart": "AND"})
        _, _, proposal, [refused] = self._run(client, user, token, alice_project, monkeypatch, reply)
        assert proposal is None
        assert (
            "params.dataPool.insideChart must be one of OVERWRITE, MERGE_AND, MERGE_OR; got 'AND', "
            "which a Data Pool reads as OVERWRITE"
        ) in refused, refused

    def test_an_empty_image_column_is_refused_to_the_model(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        reply = _SettingsNodeBuilder()._create_tail_json(nodeType=VIEW, content="", simpleVis={"imageColumn": ""})
        _, _, proposal, [refused] = self._run(client, user, token, alice_project, monkeypatch, reply)
        assert proposal is None
        assert "params.simpleVis.imageColumn must name a column, such as" in refused, refused

    def test_a_setting_on_a_node_of_another_template_is_refused(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        user, token = user_and_token
        reply = _SettingsNodeBuilder()._create_tail_json(
            nodeType=CA, content="return input_0", simpleVis=OVERLAYS,
        )
        _, _, proposal, [refused] = self._run(client, user, token, alice_project, monkeypatch, reply)
        assert proposal is None, "a code node with a view's image column was proposed"
        assert (
            "params.simpleVis: a Computation Analysis node has no image column; "
            "only a Simple View node takes simpleVis"
        ) in refused, refused
