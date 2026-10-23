"""Dashboards ground the agents.

A node pinned to its dataflow's dashboard is a tile of a page anyone with its
link can open. The page draws from the outputs saved with the dataflow and
refuses a pinned Autark tile whose spec loads its own data
(``projects/dashboard_payload.py``). Agents learn the dashboard from its
knowledge page and read which nodes are tiles in ``dataflow.read``. A spec an
agent writes for a pinned tile is held to the dashboard's own check: the
``node.content.write`` mint sends it back, and Solve, verified or not, ends
the node on it, since the fix is a node upstream that Solve cannot add. A
plan that removes a pinned node says that its tile leaves the dashboard.

Every test imports what it tests inside itself, so a checkout without it
fails test by test rather than at collection.
"""
from __future__ import annotations

import json

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_map_edits_grounding import _project, _seed_builtin, _write_tail
from utk_curio.backend.tests.test_agents.test_source_grounding_routes import (
    _attach,
    _install,
    _proposals,
    _run,
    _script,
    _tool_results,
)

NB = "agent.curio.node-builder@1"
DFB = "agent.curio.dataflow-builder@1"
AUTK = "curio.builtin/autk-grammar"
VEGA = "curio.builtin/vis-vega"
CA = "curio.builtin/computation-analysis"
PAGE = "knowledge/dashboards.md"
MESSAGE = "dashboards.tile-loads-own-data"
#: The account and the dataflow the check is asked about directly.
KEY = "4242"
PID = "p-dashboards"

#: The parks of an area, as an Autark spec loads them itself, from OpenStreetMap:
#: the table ``osm_parks``.
PARKS = {
    "type": "osm", "outputTableName": "osm",
    "queryArea": {"geocodeArea": "Boston", "areas": ["Boston Harbor"]},
    "autoLoadLayers": {"coordinateFormat": "EPSG:3395", "layers": ["parks"]},
}
#: A map of the node's input, which a dashboard carries.
MAP = json.dumps({"map": {"layerRefs": [{"dataRef": "input_0"}]}})
#: The same map with its layer styled: a change a dashboard carries too.
MAP_STYLED = json.dumps({"map": {"layerRefs": [{"dataRef": "input_0", "style": {"opacity": 0.8, "fill": True}}]}})
#: The map with the parks over its input, loaded by a "data" section of its own.
MAP_WITH_PARKS = json.dumps({"data": [PARKS], "map": {"layerRefs": [{"dataRef": "input_0"}, {"dataRef": "osm_parks"}]}})


def _tile(content: str, *, pinned: bool = True, node_type: str = AUTK, node_id: str = "map") -> dict:
    """A node holding *content*, as a dataflow saved from the canvas holds it:
    ``dashboardPinned`` on the node itself when it is a tile."""
    node = {
        "id": node_id, "type": node_type, "goal": "Map the parks of Boston Harbor", "content": content,
        "x": 0, "y": 0,
    }
    if pinned:
        node["dashboardPinned"] = True
    return node


def _message() -> str:
    """What the check tells a model, as the page of messages words it."""
    from utk_curio.backend.app.agents.domain import agent_text

    return agent_text.message(MESSAGE)


class TestTheDashboardsPage:
    """``knowledge/dashboards.md`` in the base entry says what a pin does, what
    the dashboard refuses and who pins, and every agent Curio ships reads it."""

    def _page(self) -> str:
        from utk_curio.backend.app.agents.domain import agent_text

        return agent_text.read(agent_text.page_file(PAGE))

    def test_every_agent_curio_ships_reads_it_in_its_preamble(self):
        from utk_curio.backend.app.agents.domain import builtin

        page = self._page().rstrip("\n")
        assert page.splitlines()[0] == "## Dashboards"
        manifests = builtin.list_builtin_manifests()
        assert len(manifests) >= 7, [m.dir_name for m in manifests]
        for m in manifests:
            assert builtin.read_prompt_text(m.dir_name, "system").count(page) == 1, m.dir_name

    def test_it_names_a_tiles_row_and_the_size_the_dashboard_holds_a_page_to(self):
        """The row ``dataflow.read`` gives a tile, and the dashboard's own
        limit, so neither can drift from the page."""
        from utk_curio.backend.app.projects.dashboard_payload import DEFAULT_PAYLOAD_LIMIT_BYTES

        page = self._page()
        assert '"pinned": true' in page
        assert f"{DEFAULT_PAYLOAD_LIMIT_BYTES // (1024 * 1024)} MB" in page


class TestDataflowReadNamesTheTiles:
    def test_a_pinned_nodes_row_says_so_and_no_other_row_does(self, tmp_curio):
        from utk_curio.backend.app.agents.application import tools
        from utk_curio.backend.app.projects import storage as projects_storage

        spec = {"dataflow": {"nodes": [
            {"id": "load", "type": CA, "content": "return 1"},
            _tile(MAP),
            {"id": "chart", "type": VEGA, "content": "{}", "dashboardPinned": False},
        ], "edges": []}}
        projects_storage.write_spec(KEY, PID, spec)
        status, text = tools.execute_read_tool(
            "dataflow.read", user_key=KEY, project_id=PID, target=None, params={},
        )
        assert status == "ok"
        rows = {row["id"]: row for row in json.loads(text)["nodes"]}
        assert rows["map"]["pinned"] is True
        assert "pinned" not in rows["load"] and "pinned" not in rows["chart"]
        assert "dashboard" in tools.REGISTRY["dataflow.read"].description


class TestTheCheck:
    """``dashboards.refusal``: the dashboard's own check, on the spec an agent
    wrote for a saved node."""

    def test_a_pinned_autark_tile_whose_spec_loads_its_own_data_is_refused_with_the_remedy(self, tmp_curio):
        from utk_curio.backend.app.agents.domain import dashboards

        refusal = dashboards.refusal(KEY, PID, _tile(MAP), MAP_WITH_PARKS)
        assert refusal == _message()
        assert '"data"' in refusal and "upstream" in refusal

    def test_an_unpinned_node_is_not_refused(self, tmp_curio):
        from utk_curio.backend.app.agents.domain import dashboards

        assert dashboards.refusal(KEY, PID, _tile(MAP, pinned=False), MAP_WITH_PARKS) is None

    def test_a_spec_without_data_is_not_refused(self, tmp_curio):
        from utk_curio.backend.app.agents.domain import dashboards

        no_sources = json.dumps({"data": [], "map": {"layerRefs": [{"dataRef": "input_0"}]}})
        for spec in (MAP_STYLED, no_sources):
            assert dashboards.refusal(KEY, PID, _tile(MAP), spec) is None, spec

    def test_a_node_that_is_not_autark_is_not_refused(self, tmp_curio):
        from utk_curio.backend.app.agents.domain import dashboards

        for node_type in (VEGA, CA):
            assert dashboards.refusal(KEY, PID, _tile("", node_type=node_type), MAP_WITH_PARKS) is None, node_type

    def test_the_code_the_node_holds_is_the_users_own_and_is_never_refused(self, tmp_curio):
        """Compared as an agent's code is written into a node: a fence around
        it changes nothing."""
        from utk_curio.backend.app.agents.domain import dashboards

        held = _tile(MAP_WITH_PARKS)
        for written in (MAP_WITH_PARKS, f"```json\n{MAP_WITH_PARKS}\n```"):
            assert dashboards.refusal(KEY, PID, held, written) is None, written


class TestTheMintSendsTheSpecBack:
    def test_node_content_write_refuses_a_pinned_tiles_spec_that_loads_its_own_data(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """The model is told why, with the remedy, and a spec the dashboard
        carries is proposed."""
        user, token = user_and_token
        project = _project(client, user, token, [_tile(MAP)])
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB, target={"kind": "node", "targetId": "map"})
        calls = _script(monkeypatch, [
            _write_tail("map", MAP_WITH_PARKS), _write_tail("map", MAP_STYLED), "Proposed: review it above.",
        ])
        body = _run(client, token, project, att, "add the parks of Boston Harbor to the map")
        refused, proposed = _tool_results(calls[-1], "node.content.write")
        assert "refused" in refused.split("\n", 1)[0] and _message() in refused, refused
        assert proposed.startswith("[tool result] node.content.write: proposed"), proposed
        [proposal] = _proposals(body)
        assert proposal["preview"] == MAP_STYLED


class TestSolveEndsTheNodeOnIt:
    """Solve cannot add the node upstream that the remedy needs, so the
    refusal ends the node with its message instead of a correction round."""

    def test_the_verified_loop_ends_the_node_before_the_sandbox_without_a_correction(self, app, tmp_curio):
        from utk_curio.backend.app.agents.domain import dashboards
        from utk_curio.backend.tests.test_agents.test_verified_rounds import KEY as ROUNDS_KEY, _Exec, _rounds

        _seed_builtin(ROUNDS_KEY)
        sandbox = _Exec()
        _events, outcome, inputs = _rounds(app, _tile(""), replies=[MAP_WITH_PARKS, MAP], exec_fn=sandbox)
        assert [attempt["kind"] for attempt in outcome["attempts"]] == [dashboards.KIND], outcome["attempts"]
        assert outcome["verdict"] == "fail" and outcome["stoppedBy"] == "blocker", outcome
        assert outcome["evidence"]["detail"] == _message()
        assert len(inputs) == 1, "a correction was asked for"
        assert sandbox.calls == [], "the spec ran"

    def test_an_unverified_solve_fails_the_node_and_writes_nothing(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """``verify: false`` writes content without running it, and holds a
        pinned tile's spec to its dashboard as a verified Solve does."""
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        project = _project(client, user, token, [])
        plan = {
            "goal": "a map of the parks of Boston Harbor",
            "nodes": [{"ref": "map", "nodeType": AUTK, "title": "Parks", "intent": "Map the parks of Boston Harbor"}],
            "edges": [],
        }
        plan_tail = "Plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"

        def _reply(calls):
            return MAP_WITH_PARKS if "[delegated task" in calls[-1][-1]["content"] else plan_tail

        _install(client, token, project, DFB, NB)
        att = _attach(client, token, project, DFB)
        _script(monkeypatch, [_reply])
        [proposal] = _proposals(_run(client, token, project, att, "plan a map of the parks of Boston Harbor"))
        applied = client.post(
            f"/api/agents/projects/{project}/attachments/{att}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        ).get_json()
        tile = next(n["id"] for n in applied["appliedGraph"]["nodes"] if str(n.get("type", "")).startswith(AUTK))
        # The user pins the planned map before Solve fills it.
        key = _user_dir_key(user)
        spec = projects_storage.read_spec(key, project)
        next(n for n in spec["dataflow"]["nodes"] if n["id"] == tile)["dashboardPinned"] = True
        projects_storage.write_spec(key, project, spec)
        body = client.post(
            f"/api/agents/projects/{project}/attachments/{att}/solve",
            json={"verify": False}, headers=_auth(token),
        ).get_json()
        result = body["results"][tile]
        assert result["status"] == "failed" and result["error"] == _message(), result
        spec = projects_storage.read_spec(key, project)
        assert next(n for n in spec["dataflow"]["nodes"] if n["id"] == tile)["content"] == ""


class TestAPlanNamesTheTilesItRemoves:
    def test_a_pinned_victim_is_flagged_and_its_preview_line_says_it_leaves_the_dashboard(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        project = _project(client, user, token, [
            {**_tile(MAP), "goal": "Parks map"},
            {"id": "loader", "type": CA, "goal": "Load CSV", "content": "return 1", "x": 0, "y": 300},
        ])
        _install(client, token, project, DFB)
        att = _attach(client, token, project, DFB)
        plan = {"goal": "start the map over", "removeNodes": ["map", "loader"]}
        _script(monkeypatch, ["Revising.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"])
        [proposal] = _proposals(_run(client, token, project, att, "remove the map and the loader"))
        removals = {victim["id"]: victim for victim in proposal["plan"]["removals"]}
        assert removals["map"]["pinned"] is True
        assert "pinned" not in removals["loader"]
        lines = proposal["preview"].splitlines()
        [tile] = [line for line in lines if "Parks map" in line]
        [loader] = [line for line in lines if "Load CSV" in line]
        assert tile.endswith(f" · {AUTK} · a dashboard tile, which leaves the dashboard"), tile
        assert loader.endswith(f" · {CA}"), loader
