"""Tests for tool contracts + grant resolution + read execution
(memos dev/39/dev/41, DEC-017/DEC-045)."""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents.application import tools
from utk_curio.backend.app.agents.application.turns import examples
from utk_curio.backend.app.agents.domain.manifest import ToolRequirement
from utk_curio.backend.app.agents.application.tools import ToolContract
from utk_curio.backend.tests._support.agent_routes import _auth


def _req(tool_id: str, required: bool = False) -> ToolRequirement:
    return ToolRequirement(id=tool_id, required=required)


class TestRegistry:
    def test_registry_holds_exactly_the_named_contracts(self):
        # Each contract has a named consumer in the built-in roster (dev/41
        # §4.3; node.create → agent.curio.node-builder, dev/48) — nothing
        # speculative lives here.
        assert set(tools.REGISTRY) == {
            "dataflow.read", "node.read", "node.content.write", "node.create",
            "catalog.search", "dataset.install",
            "dataflow.plan.write", "node.runtime.read",
            "node.history.read",  # a node's runs and edits, as its Provenance drawer lists them
            "web.fetch", "web.search",
            "packages.catalog", "packages.resolve", "package.install",  # dev/84
            "package.draft.apply",  # dev/89
            # The Discovery Catalog: roster, live search, reviewed download.
            "discovery.sources", "discovery.search", "discovery.acquire",
            "models.search",  # the Model Catalog
            "examples.read",  # the worked examples
            "node.settings.write",  # an existing node's settings and widget values
            "scenarios.search",  # the Scenario Catalog
            "skill.read",  # a skill a chat lists, loaded when a task needs it
        }
        assert tools.REGISTRY["dataflow.read"].effect == "read"
        assert tools.REGISTRY["node.read"].effect == "read"
        assert tools.REGISTRY["node.content.write"].effect == "mutate"
        # A settings change is applied only on review, as a content change is.
        assert tools.REGISTRY["node.settings.write"].effect == "mutate"
        assert tools.REGISTRY["node.create"].effect == "mutate"
        assert tools.REGISTRY["catalog.search"].effect == "read"
        assert tools.REGISTRY["dataset.install"].effect == "mutate"
        assert tools.REGISTRY["dataflow.plan.write"].effect == "mutate"
        assert tools.REGISTRY["node.runtime.read"].effect == "read"
        assert tools.REGISTRY["node.history.read"].effect == "read"
        assert tools.REGISTRY["web.fetch"].effect == "read"
        assert tools.REGISTRY["web.search"].effect == "read"
        assert tools.REGISTRY["discovery.sources"].effect == "read"
        assert tools.REGISTRY["discovery.search"].effect == "read"
        # A download writes bytes into the user's store and mints a catalog
        # row, so it goes through review and never executes in the model loop.
        assert tools.REGISTRY["discovery.acquire"].effect == "mutate"
        assert tools.REGISTRY["packages.catalog"].effect == "read"
        assert tools.REGISTRY["packages.resolve"].effect == "read"
        assert tools.REGISTRY["package.install"].effect == "mutate"
        assert tools.REGISTRY["package.draft.apply"].effect == "mutate"  # dev/89
        assert tools.REGISTRY["models.search"].effect == "read"
        assert tools.REGISTRY["examples.read"].effect == "read"
        assert tools.REGISTRY["scenarios.search"].effect == "read"
        assert tools.REGISTRY["skill.read"].effect == "read"

    def test_contract_validates_effect(self):
        with pytest.raises(ValueError):
            ToolContract(id="x.y", contract_version="1", effect="write")

    def test_a_package_draft_carries_the_justification_of_its_new_node_types(self):
        # A package draft is the one way an agent makes a node type. Its
        # justification is a param, required only of a draft that adds a
        # template (an extend may only revise), so the schema does not require it.
        draft = tools.REGISTRY["package.draft.apply"]
        assert "justification" in draft.parameters["properties"]
        assert "justification" not in draft.parameters["required"]
        assert '"justification"' in draft.description
        assert "a label no existing template has" in draft.description


class TestGrantResolution:
    def test_unregistered_requests_grant_nothing(self):
        assert tools.resolve_grants([_req("ghost.tool"), _req("other.ghost")]) == []

    def test_read_effect_contract_is_grantable(self):
        assert tools.resolve_grants([_req("dataflow.read")]) == ["dataflow.read"]

    def test_mutate_is_grantable_for_proposal_purposes(self):
        # dev/41: a mutate grant lets the model PROPOSE; execution authority
        # is the apply endpoint alone (DEC-006 — structural, not a flag). The
        # loop-level refusal is asserted in the route tests.
        assert tools.resolve_grants([_req("node.content.write")]) == ["node.content.write"]

    def test_unregistered_requests_resolve_silently(self):
        granted = tools.resolve_grants([_req("dataflow.read"), _req("ghost.tool")])
        assert granted == ["dataflow.read"]

    def test_grant_descriptions_pair_ids_with_registry_text(self):
        pairs = tools.grant_descriptions(["node.read", "ghost.tool"])
        assert len(pairs) == 1
        assert pairs[0][0] == "node.read"
        assert "node" in pairs[0][1]


class TestMissingRequired:
    def test_optional_ungranted_is_not_missing(self):
        assert tools.missing_required([_req("ghost.tool", required=False)]) == []

    def test_required_ungranted_is_missing(self):
        assert tools.missing_required([_req("ghost.tool", required=True)]) == ["ghost.tool"]

    def test_required_registered_is_satisfied(self):
        assert tools.missing_required([_req("dataflow.read", required=True)]) == []
        assert tools.missing_required([_req("node.content.write", required=True)]) == []


class TestExecuteReadTool:
    """Read executors (dev/41 §4.3): domain-owned reads, bounded output,
    agent-private data stripped, failures as data — never raises."""

    UKEY = "42"
    PID = "p1"

    def _write_spec(self, tmp_curio, nodes=None, with_agents=True):
        from utk_curio.backend.app.projects import storage as projects_storage

        spec = {
            "dataflow": {
                "nodes": nodes if nodes is not None else [{"id": "n1", "type": "CODE", "content": "print(1)"}],
                "edges": [],
                "agents": ["agent.curio.researcher@1"] if with_agents else [],
                "agentAttachments": [{"attachmentId": "a1", "sessionId": "s1"}] if with_agents else [],
            }
        }
        projects_storage.write_spec(self.UKEY, self.PID, spec)

    def test_dataflow_read_strips_agent_private_sections(self, tmp_curio):
        self._write_spec(tmp_curio)
        status, text = tools.execute_read_tool(
            "dataflow.read", user_key=self.UKEY, project_id=self.PID, target=None, params={}
        )
        assert status == "ok"
        # Rule-9 posture: agent sections never enter model context — in the
        # dev/67-2 projection AND the include=content full dump.
        assert "agentAttachments" not in text and '"agents"' not in text
        payload = json.loads(text)
        assert payload["nodes"][0]["id"] == "n1"
        status, text = tools.execute_read_tool(
            "dataflow.read", user_key=self.UKEY, project_id=self.PID, target=None,
            params={"include": ["content"]},
        )
        full = json.loads(text)
        assert "agents" not in full["dataflow"]
        assert "agentAttachments" not in full["dataflow"]
        assert full["dataflow"]["nodes"][0]["content"] == "print(1)"

    def test_dataflow_read_without_spec_is_an_error_result(self, tmp_curio):
        status, text = tools.execute_read_tool(
            "dataflow.read", user_key=self.UKEY, project_id="ghost", target=None, params={}
        )
        assert status == "error"
        assert "no saved project spec" in text

    def test_node_read_defaults_to_the_attached_node(self, tmp_curio):
        self._write_spec(tmp_curio)
        status, text = tools.execute_read_tool(
            "node.read",
            user_key=self.UKEY,
            project_id=self.PID,
            target={"kind": "node", "targetId": "n1"},
            params={},
        )
        assert status == "ok"
        assert json.loads(text)["content"] == "print(1)"

    def test_node_read_explicit_node_id_wins(self, tmp_curio):
        self._write_spec(
            tmp_curio,
            nodes=[{"id": "n1", "content": "one"}, {"id": "n2", "content": "two"}],
        )
        status, text = tools.execute_read_tool(
            "node.read",
            user_key=self.UKEY,
            project_id=self.PID,
            target={"kind": "node", "targetId": "n1"},
            params={"nodeId": "n2"},
        )
        assert status == "ok"
        assert json.loads(text)["content"] == "two"

    def test_node_read_canvas_attachment_without_node_id_errors(self, tmp_curio):
        self._write_spec(tmp_curio)
        status, text = tools.execute_read_tool(
            "node.read",
            user_key=self.UKEY,
            project_id=self.PID,
            target={"kind": "canvas"},
            params={},
        )
        assert status == "error"
        assert "nodeId" in text

    def test_node_read_missing_node_errors(self, tmp_curio):
        self._write_spec(tmp_curio)
        status, text = tools.execute_read_tool(
            "node.read", user_key=self.UKEY, project_id=self.PID, target=None,
            params={"nodeId": "ghost"},
        )
        assert status == "error"
        assert "ghost" in text

    def test_results_are_truncated_at_the_bound(self, tmp_curio):
        self._write_spec(tmp_curio, nodes=[{"id": "n1", "content": "x" * 50_000}])
        status, text = tools.execute_read_tool(
            "node.read", user_key=self.UKEY, project_id=self.PID, target=None,
            params={"nodeId": "n1"},
        )
        assert status == "ok"
        assert len(text) <= tools.TOOL_RESULT_MAX_CHARS + 100
        assert "truncated" in text


class TestDataflowReadProjection:
    """dev/67-2 — structure-first dataflow.read: ALL edges survive specs whose
    node contents previously pushed the edge list past the truncation bound."""

    UKEY = "42"
    PID = "p-projection"

    def _write_big_spec(self, n_nodes=40, content_chars=2000):
        from utk_curio.backend.app.projects import storage as projects_storage

        nodes = [
            {"id": f"n{i}", "type": "curio.builtin/computation-analysis",
             "goal": f"step {i}", "content": "x" * content_chars}
            for i in range(n_nodes)
        ]
        edges = [
            {"id": f"e{i}", "source": f"n{i}", "target": f"n{i+1}"}
            for i in range(n_nodes - 1)
        ]
        spec = {"dataflow": {"nodes": nodes, "edges": edges, "name": "wf", "task": "goal"}}
        projects_storage.write_spec(self.UKEY, self.PID, spec)
        return nodes, edges

    def test_all_edges_survive_a_spec_that_used_to_truncate_them(self, tmp_curio):
        nodes, edges = self._write_big_spec()
        # The pre-dev/67-2 dump of this spec exceeds the bound — edges died.
        status, text = tools.execute_read_tool(
            "dataflow.read", user_key=self.UKEY, project_id=self.PID, target=None, params={}
        )
        assert status == "ok"
        payload = json.loads(text)
        assert len(payload["edges"]) == len(edges)  # every edge, always
        row = payload["nodes"][0]
        assert row["hasContent"] is True and row["contentChars"] == 2000
        assert "x" * 50 not in text  # content elided — node.read serves it

    def test_runtime_status_rides_the_projection(self, tmp_curio):
        from utk_curio.backend.app.execution import runtime_journal

        self._write_big_spec(n_nodes=3, content_chars=10)
        runtime_journal.record_execution(
            self.UKEY, self.PID, "n1",
            code="x", stdout=[], stderr="boom",
            output={"path": "", "dataType": "str"},
            started_at="2026-08-05T00:00:00Z", duration_ms=1,
        )
        _, text = tools.execute_read_tool(
            "dataflow.read", user_key=self.UKEY, project_id=self.PID, target=None, params={}
        )
        assert json.loads(text)["runtime"]["n1"]["status"] == "error"

    def test_edge_handles_survive_when_present(self, tmp_curio):
        from utk_curio.backend.app.projects import storage as projects_storage

        # Two inputs on one node's circles, "in" and "in_1" (#662).
        spec = {"dataflow": {"nodes": [
            {"id": "a", "type": "t", "content": ""},
            {"id": "b", "type": "t", "content": ""},
            {"id": "m", "type": "curio.builtin/computation-analysis", "content": ""},
        ], "edges": [
            {"id": "e1", "source": "a", "target": "m",
             "sourceHandle": "out", "targetHandle": "in"},
            {"id": "e2", "source": "b", "target": "m",
             "sourceHandle": "out", "targetHandle": "in_1"},
        ]}}
        projects_storage.write_spec(self.UKEY, self.PID, spec)
        _, text = tools.execute_read_tool(
            "dataflow.read", user_key=self.UKEY, project_id=self.PID, target=None, params={}
        )
        handles = {e["id"]: e["targetHandle"] for e in json.loads(text)["edges"]}
        assert handles == {"e1": "in", "e2": "in_1"}

    def test_interaction_edges_are_named_as_such_data_edges_stay_bare(self, tmp_curio):
        """dev/125 §3.6 — the read-back the instruction demands.

        The builder is told to re-read the graph and confirm the topology
        before claiming a repair. If the projection cannot say which edge is
        the feedback link, the agent that just asked for an interaction edge
        cannot tell whether it got one — so it re-diagnoses and loops, which is
        the failure this whole memo exists to end. `kind` follows the plan
        grammar's own vocabulary and its byte-absent default: present only when
        the edge is an interaction edge.
        """
        from utk_curio.backend.app.projects import storage as projects_storage

        spec = {"dataflow": {"nodes": [
            {"id": "vis", "type": "curio.builtin/vis-vega", "content": ""},
            {"id": "pool", "type": "curio.builtin/data-pool", "content": ""},
        ], "edges": [
            {"id": "e1", "source": "pool", "target": "vis",
             "sourceHandle": "out", "targetHandle": "in"},
            {"id": "e2", "source": "vis", "target": "pool", "type": "Interaction",
             "sourceHandle": "in/out", "targetHandle": "in/out"},
        ]}}
        projects_storage.write_spec(self.UKEY, self.PID, spec)
        _, text = tools.execute_read_tool(
            "dataflow.read", user_key=self.UKEY, project_id=self.PID, target=None, params={}
        )
        by_id = {e["id"]: e for e in json.loads(text)["edges"]}
        assert by_id["e2"]["kind"] == "interaction"
        assert "kind" not in by_id["e1"]  # data stays byte-absent, as in the plan

    def test_scenarios_ride_the_projection_with_their_parts(self, tmp_curio):
        """#662: each scenario with what it is made of, read by the rule the
        canvas reads it by: its levers, its fixed context (each node an edge
        into it comes from, a value node's among them) and its outcomes. Nodes
        show their widgets' values and a copy its lineage."""
        from utk_curio.backend.app.projects import storage as projects_storage

        spec = {"dataflow": {"nodes": [
            {"id": "load", "type": "curio.builtin/data-loading", "content": "return 1"},
            {"id": "a", "type": "curio.builtin/computation-analysis",
             "content": "return input_0 * [!! factor !!] * input_1",
             "metadata": {"widgets": [{"name": "factor", "type": "number", "default": 1, "value": 2}]}},
            {"id": "b", "type": "curio.builtin/vis-vega", "content": "{}"},
            {"id": "p", "type": "curio.builtin/computation-analysis", "content": "return [!! season !!]",
             "metadata": {"widgets": [{"name": "season", "type": "text", "default": "winter"}]}},
            {"id": "a2", "type": "curio.builtin/computation-analysis", "content": "return input_0",
             "metadata": {"copiedFrom": ["a"]}},
        ], "edges": [
            {"id": "e1", "source": "load", "target": "a"},
            {"id": "e2", "source": "a", "target": "b"},
            {"id": "e3", "source": "load", "target": "a2"},
            {"id": "e4", "source": "p", "target": "a", "targetHandle": "in_1"},
        ], "scenarios": [
            {"id": "s1", "name": "Real heights", "color": "#3567c7", "description": "as mapped",
             "nodes": ["a", "b", "ghost"], "collapsed": True, "box": {"x": 1, "y": 2}},
        ]}}
        projects_storage.write_spec(self.UKEY, self.PID, spec)
        _, text = tools.execute_read_tool(
            "dataflow.read", user_key=self.UKEY, project_id=self.PID, target=None, params={}
        )
        payload = json.loads(text)
        assert payload["scenarios"] == [{
            "id": "s1", "name": "Real heights", "color": "#3567c7", "description": "as mapped",
            "levers": ["a", "b"], "context": ["load", "p"], "outcomes": ["b"],
        }]
        rows = {n["id"]: n for n in payload["nodes"]}
        assert rows["a"]["widgets"] == [{"name": "factor", "type": "number", "value": 2}]
        assert rows["a2"]["copiedFrom"] == ["a"]
        assert "widgets" not in rows["load"] and "copiedFrom" not in rows["a"]

    def test_a_dataflow_without_scenarios_projects_as_before(self, tmp_curio):
        self._write_big_spec(n_nodes=3, content_chars=10)
        _, text = tools.execute_read_tool(
            "dataflow.read", user_key=self.UKEY, project_id=self.PID, target=None, params={}
        )
        payload = json.loads(text)
        assert "scenarios" not in payload
        assert all(set(n) == {"id", "type", "goal", "hasContent", "contentChars"} for n in payload["nodes"])


def _project_with_scenarios(client, token, name: str, scenarios: list[dict]) -> str:
    """A project of the signed-in account, saved through its route, with two
    nodes, ``a`` and ``b``, and *scenarios*. Its id."""
    nodes = [
        {"id": node_id, "type": "curio.builtin/computation-analysis@1", "content": "return input_0", "x": 0, "y": 0}
        for node_id in ("a", "b")
    ]
    spec = {"dataflow": {"name": name, "nodes": nodes, "edges": [], "scenarios": scenarios}}
    resp = client.post("/api/projects", json={"name": name, "spec": spec, "outputs": []}, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _signed_in_read(app, user, tool_id: str, project_id: str, params: dict) -> tuple[str, str]:
    """*tool_id* run as a chat turn runs it: in a request whose signed-in
    account is *user* (``g.user``)."""
    from flask import g

    from utk_curio.backend.app.projects.services import _user_dir_key

    with app.test_request_context():
        g.user = user
        return tools.execute_read_tool(
            tool_id, user_key=_user_dir_key(user), project_id=project_id, target=None, params=params,
        )


class TestDataflowReadScenarioSource:
    """A scenario dragged in from another project keeps that project's and
    that scenario's ids (``source``). dataflow.read names them, reading only
    the projects such scenarios name, each once, and says when that project,
    or that scenario in it, is gone. dataflow.read runs on every turn, so a
    dataflow with no dropped scenario reads no other project."""

    @staticmethod
    def _scenarios(app, user, project_id: str) -> dict[str, dict]:
        status, text = _signed_in_read(app, user, "dataflow.read", project_id, {})
        assert status == "ok", text
        return {row["name"]: row for row in json.loads(text)["scenarios"]}

    def test_a_dropped_scenario_names_its_project_and_scenario(self, app, client, user_and_token):
        user, token = user_and_token
        # Renamed in its project since the drop: the source is read as it is now.
        loop = _project_with_scenarios(client, token, "Loop shadow", [
            {"id": "s-towers", "name": "Without towers", "color": "#3567c7", "nodes": ["a"]},
        ])
        mine = _project_with_scenarios(client, token, "My study", [
            {"id": "s1", "name": "Existing", "color": "#e86a3c", "nodes": ["a"]},
            {"id": "s2", "name": "Towers removed", "color": "#3567c7", "nodes": ["b"],
             "source": {"project": loop, "scenario": "s-towers"}},
        ])

        rows = self._scenarios(app, user, mine)

        assert rows["Towers removed"]["source"] == {"project": "Loop shadow", "scenario": "Without towers"}
        # A scenario made here has no source.
        assert "source" not in rows["Existing"]
        # The agent names the source by its names, never by its ids.
        assert loop not in json.dumps(rows)

    def test_a_source_that_is_gone_says_so(self, app, client, user_and_token):
        user, token = user_and_token
        loop = _project_with_scenarios(client, token, "Loop shadow", [
            {"id": "s-towers", "name": "Towers removed", "color": "#3567c7", "nodes": ["a"]},
        ])
        old = _project_with_scenarios(client, token, "Old study", [
            {"id": "s-old", "name": "Old heights", "color": "#3567c7", "nodes": ["a"]},
        ])
        resp = client.delete(f"/api/projects/{old}", headers=_auth(token))
        assert resp.status_code in (200, 204), resp.get_data(as_text=True)
        mine = _project_with_scenarios(client, token, "My study", [
            {"id": "s1", "name": "Old heights", "color": "#3567c7", "nodes": ["a"],
             "source": {"project": old, "scenario": "s-old"}},
            {"id": "s2", "name": "Towers kept", "color": "#e86a3c", "nodes": ["b"],
             "source": {"project": loop, "scenario": "s-kept"}},
            {"id": "s3", "name": "Not ours", "color": "#2f8f4a", "nodes": [],
             "source": {"project": "no-such-project", "scenario": "s1"}},
        ])

        rows = self._scenarios(app, user, mine)

        # Its project was deleted, or is none of this account's.
        assert rows["Old heights"]["source"] == {"status": "project-gone"}
        assert rows["Not ours"]["source"] == {"status": "project-gone"}
        # Its project is still here, and no longer holds it.
        assert rows["Towers kept"]["source"] == {"project": "Loop shadow", "status": "scenario-gone"}

    def test_a_dataflow_without_a_dropped_scenario_reads_no_other_project(
        self, app, client, user_and_token, monkeypatch
    ):
        from utk_curio.backend.app.scenario_catalog.infrastructure import projects as scenario_projects

        user, token = user_and_token
        loop = _project_with_scenarios(client, token, "Loop shadow", [
            {"id": "s-towers", "name": "Towers removed", "color": "#3567c7", "nodes": ["a"]},
        ])
        mine = _project_with_scenarios(client, token, "My study", [
            {"id": "s1", "name": "Existing", "color": "#e86a3c", "nodes": ["a"]},
        ])
        twice = _project_with_scenarios(client, token, "Two drops", [
            {"id": "s1", "name": "Towers removed", "color": "#3567c7", "nodes": ["a"],
             "source": {"project": loop, "scenario": "s-towers"}},
            {"id": "s2", "name": "Towers removed again", "color": "#e86a3c", "nodes": ["b"],
             "source": {"project": loop, "scenario": "s-towers"}},
        ])
        read, listed = [], []
        owned = scenario_projects.owned_project

        def owned_project(account, project_id):
            read.append(project_id)
            return owned(account, project_id)

        def project_summaries(account):
            listed.append(account)
            return []

        monkeypatch.setattr(scenario_projects, "owned_project", owned_project)
        monkeypatch.setattr(scenario_projects, "project_summaries", project_summaries)

        assert "source" not in self._scenarios(app, user, mine)["Existing"]
        assert (read, listed) == ([], [])

        # Two scenarios dropped from one project read that project, once.
        rows = self._scenarios(app, user, twice)
        assert (read, listed) == ([loop], [])
        assert rows["Towers removed again"]["source"] == {"project": "Loop shadow", "scenario": "Towers removed"}


class TestNodeRuntimeRead:
    """dev/67-2 — the journal's read tool: honest never-executed, traceback
    evidence, and the best-effort content-changed signal."""

    UKEY = "42"
    PID = "p-runtime"

    def _write_spec(self, content="print(1)"):
        from utk_curio.backend.app.projects import storage as projects_storage

        spec = {"dataflow": {"nodes": [
            {"id": "n1", "type": "curio.builtin/computation-analysis", "content": content},
        ], "edges": []}}
        projects_storage.write_spec(self.UKEY, self.PID, spec)

    def _read(self, params=None, target=None):
        return tools.execute_read_tool(
            "node.runtime.read", user_key=self.UKEY, project_id=self.PID,
            target=target, params=params or {},
        )

    def test_never_executed_is_honest(self, tmp_curio):
        self._write_spec()
        status, text = self._read({"nodeId": "n1"})
        assert status == "ok"
        assert json.loads(text) == {"nodeId": "n1", "status": "never-executed"}

    def test_failure_record_with_content_change_signal(self, tmp_curio):
        from utk_curio.backend.app.execution import runtime_journal

        self._write_spec(content="print(1)")
        runtime_journal.record_execution(
            self.UKEY, self.PID, "n1",
            code="    print(1)",  # transport indentation — normalized away
            stdout=[], stderr="Traceback: KeyError",
            output={"path": "", "dataType": "str"},
            started_at="2026-08-05T00:00:00Z", duration_ms=5,
        )
        _, text = self._read({"nodeId": "n1"})
        payload = json.loads(text)
        assert payload["status"] == "error"
        assert "KeyError" in payload["stderrTail"]
        assert payload["contentChangedSinceRun"] is False
        # The user edits the node: the record is flagged as predating it.
        self._write_spec(content="print(2)")
        _, text = self._read({"nodeId": "n1"})
        assert json.loads(text)["contentChangedSinceRun"] is True

    def test_defaults_to_the_attached_node_and_missing_node_errors(self, tmp_curio):
        self._write_spec()
        status, text = self._read(target={"kind": "node", "targetId": "n1"})
        assert status == "ok" and json.loads(text)["nodeId"] == "n1"
        status, text = self._read({"nodeId": "ghost"})
        assert status == "error" and "not found" in text
        status, text = self._read()
        assert status == "error" and "not attached" in text


class TestCatalogSearchRows:
    """dev/114 (DEC-072): installed rows carry the resolved ``path`` and the
    domain's ONE loader recipe — the only local paths generated node content
    may open. Rows without a resolved path carry neither."""

    def _listing(self, monkeypatch, items):
        class _Svc:
            def __init__(self, user):
                pass

            def list_catalog(self, **kwargs):
                return {"items": items}

        monkeypatch.setattr(
            "utk_curio.backend.app.datasets.application.catalog_service.DatasetCatalogService", _Svc
        )

    def test_path_and_loader_ride_resolved_rows_only(self, app, monkeypatch):
        self._listing(monkeypatch, [
            {"id": "ds-acs", "title": "Census ACS", "format": "csv", "origin": "hub",
             "installed": True, "path": "/store/census-acs@1/acs.csv",
             "loaderSnippet": {"code": 'dataset_path = "/store/census-acs@1/acs.csv"\ndf = pd.read_csv(dataset_path)'}},
            {"id": "ds-hub", "title": "Hub only", "format": "csv", "origin": "hub",
             "installed": False, "path": None},
            {"id": "ds-geo", "title": "Tracts", "format": "geojson", "origin": "local",
             "installed": True, "path": "/store/tracts@1/tracts.geojson"},  # no snippet → recipe
        ])
        with app.test_request_context():
            rows = tools._catalog_search_rows("42", "p1", {})
        assert rows[0]["path"] == "/store/census-acs@1/acs.csv"
        assert "pd.read_csv(dataset_path)" in rows[0]["loader"]
        assert "path" not in rows[1] and "loader" not in rows[1]
        assert rows[2]["path"] == "/store/tracts@1/tracts.geojson"
        assert 'gpd.read_file(dataset_path)' in rows[2]["loader"]
        assert "path" in tools.REGISTRY["catalog.search"].description


class TestModelsSearch:
    """models.search: the model packages this account's store holds, the only
    models its node code runs (models behave like nodes): one that ships with
    Curio and was added, or seeded for the examples, and one of its own, each
    with the loader line node code copies. A model it never added is not a
    row."""

    DDRNET = "model.curio.ddrnet23-slim"
    DOWNLOAD = "imported.xa1b2c3d4e5f6"
    ROW_KEYS = {"id", "name", "task", "runtime", "origin", "description", "labels", "loader"}

    @staticmethod
    def _key(user) -> str:
        from utk_curio.backend.app.projects.services import _user_dir_key

        return _user_dir_key(user)

    @pytest.fixture()
    def shipped(self, monkeypatch):
        """The package catalog Curio ships: DDRNet23-Slim, Deep Umbra and the
        weather GNN are its model packages."""
        from pathlib import Path

        packages = Path(__file__).resolve().parents[4] / "packages"
        monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(packages))
        return packages

    @pytest.fixture()
    def catalog(self, app, user_and_token, tmp_path, shipped):
        """DDRNet23-Slim added to the user's store, and a model package of the
        user's own with 60 labels, as the Discovery Catalog writes one."""
        from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
        from utk_curio.backend.app.packages.service import install_downloaded_model, model_template

        user, _ = user_and_token
        key = self._key(user)
        install_package_from_directory(key, shipped / f"{self.DDRNET}@1")
        files = tmp_path / "incoming"
        files.mkdir()
        (files / "m.onnx").write_bytes(b"onnx")
        install_downloaded_model(key, files, {
            "id": self.DOWNLOAD, "kind": "model", "name": "Tiny facades", "version": "1.0.0",
            "compatibility": {"major": 1}, "publisher": "org", "license": "MIT",
            "templates": [model_template("semantic-segmentation")],
            "model": {
                "type": "semantic-segmentation", "runtime": "onnx", "entry": "models/m.onnx",
                "labels": [f"class {i}" for i in range(60)],
                "input": {"width": 64, "height": 32, "dtype": "float32", "scale": 0.00392},
                "license": "MIT", "sizeBytes": 4,
            },
        })
        return key

    def test_rows_carry_both_origins_and_the_loader_line(self, catalog):
        from utk_curio.backend.app.datasets.domain.code_refs import model_ids_in_code

        by_id = {row["id"]: row for row in tools._models_search_rows(catalog, {})}
        # Deep Umbra and the weather GNN ship too, but this account added neither.
        assert set(by_id) == {self.DDRNET, self.DOWNLOAD}
        for row in by_id.values():
            # The model whose 60 labels are cut also says how many were.
            assert set(row) == self.ROW_KEYS | ({"labelsElided"} if row["id"] == self.DOWNLOAD else set())
            assert row["loader"] == f'model = curio_load_model("{row["id"]}")'
            # The line resolves through the runtime's own reading of node code.
            assert model_ids_in_code(row["loader"]) == [row["id"]]
        shipped, mine = by_id[self.DDRNET], by_id[self.DOWNLOAD]
        assert (shipped["origin"], shipped["runtime"], shipped["task"]) == ("shipped", "onnx", "semantic-segmentation")
        assert "vegetation" in shipped["labels"] and len(shipped["labels"]) == 19
        assert (mine["origin"], mine["name"]) == ("downloaded", "Tiny facades")
        # Labels are bounded; a checkpoint may name hundreds of classes.
        assert mine["labels"] == [f"class {i}" for i in range(tools._MODEL_LABELS_MAX)]

    def test_a_model_the_account_never_added_is_not_a_row(self, app, user_and_token, shipped):
        """Each shipped model package is in the catalog, and none is a model this
        account's code runs until it is added; nor does an account-less run
        see one."""
        from utk_curio.backend.app.packages.service import list_model_packages

        user, _ = user_and_token
        assert {"model.scout.deep-umbra", self.DDRNET} <= {
            listed.manifest.package_id for listed in list_model_packages(self._key(user))
        }
        assert tools._models_search_rows(self._key(user), {}) == []
        assert tools._models_search_rows(None, {}) == []

    def test_q_filters_and_limit_bounds(self, catalog):
        def rows(params):
            return tools._models_search_rows(catalog, params)

        assert [r["id"] for r in rows({"q": "  tiny  "})] == [self.DOWNLOAD]
        assert [r["id"] for r in rows({"q": "cityscapes"})] == [self.DDRNET]
        assert rows({"q": "no-such-model-zzz"}) == []
        assert len(rows({"limit": 1})) == 1
        assert len(rows({"limit": "1"})) == 1
        # A native call may carry every number as a float.
        assert len(rows({"limit": 1.0})) == 1
        everything = rows({})
        # A limit that is not a whole number, or is out of range, never hides a row.
        assert rows({"limit": "many"}) == everything
        assert rows({"limit": 1.5}) == everything
        assert rows({"limit": 10_000}) == everything
        assert len(rows({"limit": 0})) == 1

    def test_the_executor_returns_the_rows_and_needs_no_project_spec(self, catalog):
        status, text = tools.execute_read_tool(
            "models.search", user_key=catalog, project_id="no-such-project", target=None, params={"q": "tiny"},
        )
        assert status == "ok"
        assert [row["id"] for row in json.loads(text)["models"]] == [self.DOWNLOAD]

    def test_lists_that_stop_short_say_how_many_they_left_out(self, catalog):
        """The rows a search returns, and the labels of each, stop at a
        number; a model shown fewer is told how many it was not shown."""
        status, text = tools.execute_read_tool(
            "models.search", user_key=catalog, project_id="no-such-project", target=None, params={"limit": 1},
        )
        assert status == "ok"
        payload = json.loads(text)
        assert len(payload["models"]) == 1
        assert payload.get("modelsElided") == 1
        mine = next(row for row in tools._models_search_rows(catalog, {}) if row["id"] == self.DOWNLOAD)
        assert mine.get("labelsElided") == 60 - tools._MODEL_LABELS_MAX

    def test_the_contract_states_its_params_and_rows(self):
        contract = tools.REGISTRY["models.search"]
        assert contract.parameters["properties"]["q"]["type"] == "string"
        assert contract.parameters["properties"]["limit"]["type"] == "integer"
        assert "required" not in contract.parameters
        for word in ("id", "name", "task", "origin", "labels", "loader", 'curio_load_model("<id>")', "added"):
            assert word in contract.description, word


class TestScenariosSearch:
    """scenarios.search: the Scenario Catalog's own listing
    (``ScenarioCatalogService.list_catalog``), read as the signed-in account,
    one row per scenario: its key, name, description, project, node count and
    whether it is one of this dataflow's own, never its project's preview. A
    search that stops short says how many rows it left out, and a run with no
    signed-in account is told so."""

    ROW_KEYS = {"key", "name", "description", "project", "nodeCount", "inThisDataflow"}

    @staticmethod
    def _listing(user, q=None) -> list[dict]:
        """The Scenario Catalog's own listing, in its order."""
        from utk_curio.backend.app.scenario_catalog.service import ScenarioCatalogService

        return ScenarioCatalogService(user).list_catalog(q=q)["items"]

    def test_rows_are_the_catalogs_own_filtered_by_q_without_a_preview(self, app, client, user_and_token):
        user, token = user_and_token
        loop = _project_with_scenarios(client, token, "Loop shadow", [
            {"id": "s1", "name": "Towers removed", "color": "#3567c7", "description": "no zebra tower stands",
             "nodes": ["a"]},
            {"id": "s2", "name": "Towers kept", "color": "#e86a3c", "nodes": ["b"]},
        ])
        mine = _project_with_scenarios(client, token, "My study", [
            {"id": "s1", "name": "Zebra crossings", "color": "#2f8f4a", "nodes": ["a", "b"]},
        ])

        status, text = _signed_in_read(app, user, "scenarios.search", mine, {"q": "  Zebra "})

        assert status == "ok", text
        rows = json.loads(text)["scenarios"]
        # The rows the Scenario Catalog lists for that search, in its order.
        assert [row["key"] for row in rows] == [item["key"] for item in self._listing(user, q="zebra")]
        assert {row["key"]: row for row in rows} == {
            f"{loop}/s1": {"key": f"{loop}/s1", "name": "Towers removed", "description": "no zebra tower stands",
                           "project": "Loop shadow", "nodeCount": 1, "inThisDataflow": False},
            f"{mine}/s1": {"key": f"{mine}/s1", "name": "Zebra crossings", "description": "",
                           "project": "My study", "nodeCount": 2, "inThisDataflow": True},
        }

        # No search: the whole listing, in its order, each row without the
        # graph a card draws.
        status, text = _signed_in_read(app, user, "scenarios.search", mine, {})
        assert status == "ok", text
        rows = json.loads(text)["scenarios"]
        keys = [item["key"] for item in self._listing(user)]
        assert f"{loop}/s2" in keys
        assert [row["key"] for row in rows] == keys[:tools._SCENARIOS_SEARCH_MAX_ROWS]
        assert all(set(row) == self.ROW_KEYS for row in rows)
        assert "preview" not in text

    def test_a_search_that_stops_short_says_how_many_scenarios_it_left_out(
        self, app, client, user_and_token, monkeypatch
    ):
        user, token = user_and_token
        mine = _project_with_scenarios(client, token, "My study", [
            {"id": "s1", "name": "Baseline", "color": "#3567c7", "nodes": ["a"]},
            {"id": "s2", "name": "Twice as tall", "color": "#e86a3c", "nodes": ["b"]},
        ])
        monkeypatch.setattr(tools, "_SCENARIOS_SEARCH_MAX_ROWS", 1)

        status, text = _signed_in_read(app, user, "scenarios.search", mine, {})

        assert status == "ok", text
        payload = json.loads(text)
        everything = self._listing(user)
        assert len(everything) >= 2
        assert [row["key"] for row in payload["scenarios"]] == [everything[0]["key"]]
        # The count comes first, so a result cut at the tool output bound still carries it.
        assert list(payload) == ["scenariosElided", "scenarios"]
        assert payload["scenariosElided"] == len(everything) - 1

    def test_a_run_with_no_signed_in_account_is_told_so(self, app):
        from utk_curio.backend.app.agents.domain import agent_text

        with app.test_request_context():
            status, text = tools.execute_read_tool(
                "scenarios.search", user_key="42", project_id="p1", target=None, params={},
            )

        assert (status, text) == ("error", agent_text.message("tools.scenarios-no-account"))

    def test_the_contract_states_its_param_and_rows(self):
        contract = tools.REGISTRY["scenarios.search"]
        assert (contract.effect, contract.label) == ("read", "Search the Scenario Catalog")
        assert contract.parameters["properties"]["q"]["type"] == "string"
        assert "required" not in contract.parameters
        # Where the user brings a scenario of another project in from.
        for words in (*sorted(self.ROW_KEYS), "scenariosElided", "Scenario, Browse all"):
            assert words in contract.description, words


class TestExamplesRead:
    """examples.read: the worked examples' list, one of them by key, and the
    example an evaluation is scored against left out by the per-run block's rule."""

    UKEY = "42"
    PID = "p-examples"
    NINE = "09-heterogeneous-data-linked-views"

    def _read(self, params=None):
        return tools.execute_read_tool(
            "examples.read", user_key=self.UKEY, project_id=self.PID, target=None, params=params or {},
        )

    def _used(self) -> dict:
        return {example.key: example for example in examples.used_examples()}

    def _mark(self, fixture_id):
        from utk_curio.backend.app.agents.evaluation import authorization
        from utk_curio.backend.app.projects import storage as projects_storage

        spec = {"dataflow": {"nodes": [], "edges": []}}
        marker = authorization.new_marker("run-1", fixture_id)
        projects_storage.write_spec(self.UKEY, self.PID, authorization.mark_spec(spec, marker))

    def test_no_key_lists_every_used_example(self, tmp_curio):
        # No saved spec: nothing is left out, and that is no error.
        status, text = self._read()
        assert status == "ok"
        rows = json.loads(text)["examples"]
        used = self._used()
        assert rows and [row["key"] for row in rows] == list(used)
        for row in rows:
            entry = used[row["key"]].entry
            assert row == {"key": row["key"], "title": entry.title, "line": entry.text}
        # A "Not used" dataflow is no worked example.
        assert "dataflows/widget" not in used
        assert self._read({"key": "  "}) == (status, text)

    def test_a_key_returns_that_examples_line_and_trill(self, tmp_curio):
        nine = self._used()[self.NINE]
        status, text = self._read({"key": self.NINE})
        assert status == "ok"
        # The view the per-run block shows: the line, then the Trill.
        assert text == examples.shown(nine)
        assert text.startswith(f"{nine.entry.line}\n```json\n")
        trill = json.loads(text.split("```json\n", 1)[1].rsplit("\n```", 1)[0])["dataflow"]
        assert len(trill["nodes"]) == len(nine.spec["dataflow"]["nodes"])
        assert len(trill["edges"]) == len(nine.spec["dataflow"]["edges"])
        # Its file name names it too, as in the block's exclusion.
        assert self._read({"key": f"{self.NINE}.json"}) == (status, text)
        assert self._read({"key": "dataflows/regression"})[0] == "ok"

    def test_an_unknown_key_says_how_to_list_the_keys(self, tmp_curio):
        for key in ("no-such-example", "dataflows/widget"):
            status, text = self._read({"key": key})
            assert status == "error", key
            assert repr(key) in text and "call examples.read with no key to list the keys" in text
        status, text = self._read({"key": 9})
        assert status == "error" and "call examples.read with no key to list the keys" in text

    def test_an_evaluation_never_reads_the_example_it_is_scored_against(self, tmp_curio):
        from utk_curio.backend.app.projects import storage as projects_storage

        self._mark(self.NINE)
        # The rule the per-run block follows: the scored example, and every
        # example that shares a piece of its answer.
        excluded = examples.excluded_by(projects_storage.read_spec(self.UKEY, self.PID))
        assert self.NINE in excluded
        status, text = self._read()
        keys = [row["key"] for row in json.loads(text)["examples"]]
        assert status == "ok" and self.NINE not in keys
        assert keys == [key for key in self._used() if key not in excluded]
        assert keys, "every example is excluded; the readable case below would be vacuous"
        entry = self._used()[self.NINE].entry
        for key in (self.NINE, f"{self.NINE}.json", f"docs/examples/{self.NINE}.json"):
            status, text = self._read({"key": key})
            assert status == "error", key
            assert "call examples.read with no key" in text
            # The refusal never describes the answer.
            assert entry.title not in text and entry.text not in text
        # Every excluded example is refused, and every other one stays readable.
        for key in excluded - {self.NINE}:
            assert self._read({"key": key})[0] == "error", key
        assert self._read({"key": keys[0]})[0] == "ok"

    def test_the_contract_states_its_param_and_results(self):
        contract = tools.REGISTRY["examples.read"]
        assert set(contract.parameters["properties"]) == {"key"}
        assert contract.parameters["properties"]["key"]["type"] == "string"
        assert "required" not in contract.parameters
        for word in ("no key", "key, title and one line", "Trill", "unknown key"):
            assert word in contract.description, word


class TestWebTools:
    """dev/67-4 (DEC-053) — the web read tools: policy-gated, bounded,
    honest when unconfigured; no spec needed."""

    def _fetch(self, params, monkeypatch=None, result=None, error=None):
        from utk_curio.backend.app.agents.infrastructure import egress

        if monkeypatch is not None:
            if error is not None:
                def _boom(url, **kw):
                    raise error
                monkeypatch.setattr(egress, "fetch", _boom)
            elif result is not None:
                monkeypatch.setattr(egress, "fetch", lambda url, **kw: result)
        return tools.execute_read_tool(
            "web.fetch", user_key="42", project_id="none", target=None, params=params,
        )

    def test_web_fetch_returns_bounded_preview(self, monkeypatch):
        from utk_curio.backend.app.agents.infrastructure.egress import EgressResult

        status, text = self._fetch(
            {"url": "https://api.example.org/x"},
            monkeypatch,
            result=EgressResult(
                url="https://api.example.org/x", final_url="https://api.example.org/x",
                status=200, content_type="application/json", body='{"a": 1}',
            ),
        )
        assert status == "ok"
        payload = json.loads(text)
        assert payload["status"] == 200 and payload["bodyPreview"] == '{"a": 1}'

    def test_web_fetch_policy_refusal_is_data(self, monkeypatch):
        from utk_curio.backend.app.agents.infrastructure.egress import EgressRefused

        status, text = self._fetch(
            {"url": "https://metadata.internal/x"},
            monkeypatch, error=EgressRefused("non-public address"),
        )
        assert status == "error" and "egress policy" in text
        status, text = self._fetch({})
        assert status == "error" and "params.url" in text

    def test_web_search_falls_back_to_the_default_provider(self, monkeypatch):
        """Unset is no longer unconfigured: search works out of the box."""
        from utk_curio.backend.app.agents.infrastructure import egress
        from utk_curio.backend.app.agents.infrastructure.egress import EgressResult

        monkeypatch.delenv("CURIO_SEARCH_URL", raising=False)
        seen: dict = {}

        def _fake_fetch(url, **kwargs):
            seen["url"] = url
            seen["trusted_host"] = kwargs.get("trusted_host")
            return EgressResult(url=url, final_url=url, status=200,
                                content_type="application/json",
                                body='{"RelatedTopics": []}')

        monkeypatch.setattr(egress, "fetch", _fake_fetch)
        status, _ = tools.execute_read_tool(
            "web.search", user_key="42", project_id="none", target=None,
            params={"q": "chicago heat dataset"},
        )
        assert status == "ok"
        assert seen["url"].startswith("https://api.duckduckgo.com/")
        assert "q=chicago%20heat%20dataset" in seen["url"]
        # The default names the host, so it is operator-trusted the same way a
        # configured one is - not because the model asked for it.
        assert seen["trusted_host"] == ("api.duckduckgo.com", None)

    def test_a_template_without_the_placeholder_errors_honestly(self, monkeypatch):
        # The remaining misconfiguration: a template that cannot carry a query.
        monkeypatch.setenv("CURIO_SEARCH_URL", "https://api.provider.test/v1?key=K")
        status, text = tools.execute_read_tool(
            "web.search", user_key="42", project_id="none", target=None,
            params={"q": "chicago heat dataset"},
        )
        assert status == "error"
        assert "not configured" in text and "web.fetch" in text
        # It names the actual fault, the missing placeholder.
        assert "CURIO_SEARCH_URL" in text and "{q}" in text


class TestPackageTools:
    """dev/84: packages.catalog / packages.resolve — thin wrappers over the
    packages domain, asserted against the real committed catalog."""

    UKEY = "42"
    PID = "proj-pkg"

    def _write_spec(self, packages: list[str]) -> None:
        from utk_curio.backend.app.projects import storage as projects_storage

        projects_storage.write_spec(self.UKEY, self.PID, {
            "dataflow": {"name": "wf", "nodes": [], "edges": [], "packages": packages},
        })

    def test_catalog_rows_carry_project_install_state_and_builtin_flag(self, tmp_curio):
        self._write_spec(["curio.builtin@1", "ai.utk.uhvi@1"])
        status, text = tools.execute_read_tool(
            "packages.catalog", user_key=self.UKEY, project_id=self.PID,
            target=None, params={},
        )
        assert status == "ok"
        rows = {r["dirName"]: r for r in json.loads(text)["packages"]}
        assert rows["curio.builtin@1"]["builtin"] is True
        assert rows["curio.builtin@1"]["installed"] is True  # always present
        assert rows["ai.utk.uhvi@1"]["installed"] is True  # in the lockfile
        assert rows["ai.utk.uhvi@1"]["builtin"] is False
        assert rows["curio.weather@1"]["installed"] is False  # not in the lockfile

    def test_catalog_q_filter_bounds_the_rows(self, tmp_curio):
        self._write_spec([])
        status, text = tools.execute_read_tool(
            "packages.catalog", user_key=self.UKEY, project_id=self.PID,
            target=None, params={"q": "uhvi"},
        )
        assert status == "ok"
        rows = json.loads(text)["packages"]
        assert [r["dirName"] for r in rows] == ["ai.utk.uhvi@1"]

    def test_a_catalog_that_stops_short_says_how_many_packages_it_left_out(self, tmp_curio, monkeypatch):
        from utk_curio.backend.app.packages import service as packages_services

        self._write_spec([])
        monkeypatch.setattr(tools, "_PACKAGES_CATALOG_MAX_ROWS", 1)
        status, text = tools.execute_read_tool(
            "packages.catalog", user_key=self.UKEY, project_id=self.PID,
            target=None, params={},
        )
        assert status == "ok"
        payload = json.loads(text)
        everything = packages_services.agent_catalog_overview(self.UKEY, self.PID)
        assert len(everything) > 1
        assert len(payload["packages"]) == 1
        assert payload.get("packagesElided") == len(everything) - 1

    def test_resolve_reports_real_permissions_and_deps(self, tmp_curio):
        status, text = tools.execute_read_tool(
            "packages.resolve", user_key=self.UKEY, project_id=self.PID,
            target=None, params={"dirNames": ["ai.utk.uhvi@1"]},
        )
        assert status == "ok"
        report = json.loads(text)
        pkg = next(p for p in report["packages"] if p["dirName"] == "ai.utk.uhvi@1")
        # Grounded in the committed manifest — never invented.
        assert pkg["permissions"] == ["filesystem.read", "network.fetch"]
        assert "geopandas" in pkg["pythonDeps"]
        assert report["conflicts"] == []

    def test_resolve_rejects_bad_params_and_unknown_packages(self, tmp_curio):
        status, text = tools.execute_read_tool(
            "packages.resolve", user_key=self.UKEY, project_id=self.PID,
            target=None, params={},
        )
        assert status == "error" and "dirNames" in text
        status, text = tools.execute_read_tool(
            "packages.resolve", user_key=self.UKEY, project_id=self.PID,
            target=None, params={"dirNames": ["no.such.package@9"]},
        )
        assert status == "error" and "no.such.package@9" in text


class TestWebSearchTrustedProvider:
    """dev/90 A2 — web.search derives the trusted host from CURIO_SEARCH_URL;
    web.fetch (model-supplied URLs) never passes one."""

    def test_search_passes_the_operator_host(self, monkeypatch):
        from utk_curio.backend.app.agents.infrastructure import egress
        from utk_curio.backend.app.agents.infrastructure.egress import EgressResult

        monkeypatch.setenv(
            "CURIO_SEARCH_URL", "http://localhost:8888/search?q={q}&format=json")
        seen: dict = {}

        def _fake_fetch(url, **kwargs):
            seen["url"] = url
            seen["trusted_host"] = kwargs.get("trusted_host")
            return EgressResult(url=url, final_url=url, status=200,
                                content_type="application/json",
                                body='{"results": [{"title": "Chicago cool roofs", '
                                     '"url": "https://w.test", "content": "18C"}]}')

        monkeypatch.setattr(egress, "fetch", _fake_fetch)
        status, text = tools.execute_read_tool(
            "web.search", user_key="42", project_id="none", target=None,
            params={"q": "cool roofs in Chicago"},
        )
        assert status == "ok" and "18C" in text
        assert seen["trusted_host"] == ("localhost", 8888)
        assert "q=cool%20roofs%20in%20Chicago" in seen["url"]

    def test_web_fetch_never_passes_a_trusted_host(self, monkeypatch):
        from utk_curio.backend.app.agents.infrastructure import egress
        from utk_curio.backend.app.agents.infrastructure.egress import EgressResult

        monkeypatch.setenv(
            "CURIO_SEARCH_URL", "http://localhost:8888/search?q={q}&format=json")
        seen: dict = {}

        def _fake_fetch(url, **kwargs):
            seen["kwargs"] = kwargs
            return EgressResult(url=url, final_url=url, status=200,
                                content_type="text/plain", body="ok")

        monkeypatch.setattr(egress, "fetch", _fake_fetch)
        status, _ = tools.execute_read_tool(
            "web.fetch", user_key="42", project_id="none", target=None,
            params={"url": "https://api.example.org/x"},
        )
        assert status == "ok"
        assert "trusted_host" not in seen["kwargs"]


class TestDuckDuckGoShape:
    """The default provider answers in its own format, so the parser has to
    read it or an unconfigured install would search and find nothing."""

    def _search(self, monkeypatch, body: str):
        from utk_curio.backend.app.agents.infrastructure import egress
        from utk_curio.backend.app.agents.infrastructure.egress import EgressResult

        monkeypatch.delenv("CURIO_SEARCH_URL", raising=False)
        monkeypatch.setattr(egress, "fetch", lambda url, **kw: EgressResult(
            url=url, final_url=url, status=200,
            content_type="application/json", body=body))
        status, text = tools.execute_read_tool(
            "web.search", user_key="42", project_id="none", target=None,
            params={"q": "chicago"},
        )
        assert status == "ok", text
        return json.loads(text)["results"]

    def test_flat_related_topics(self, monkeypatch):
        rows = self._search(monkeypatch, json.dumps({"RelatedTopics": [
            {"FirstURL": "https://w.test/a", "Text": "Chicago - a city in Illinois"},
        ]}))
        assert rows == [{
            "title": "Chicago",
            "url": "https://w.test/a",
            "snippet": "Chicago - a city in Illinois",
        }]

    def test_grouped_topics_are_flattened_one_level(self, monkeypatch):
        rows = self._search(monkeypatch, json.dumps({"RelatedTopics": [
            {"Name": "Places", "Topics": [
                {"FirstURL": "https://w.test/b", "Text": "Loop - downtown"},
            ]},
            {"FirstURL": "https://w.test/c", "Text": "Chicago River"},
        ]}))
        assert [r["url"] for r in rows] == ["https://w.test/b", "https://w.test/c"]

    def test_entries_without_a_url_are_dropped(self, monkeypatch):
        rows = self._search(monkeypatch, json.dumps({"RelatedTopics": [
            {"Result": "<a>no FirstURL here</a>"},
            {"FirstURL": "https://w.test/d", "Text": "Kept"},
        ]}))
        assert [r["url"] for r in rows] == ["https://w.test/d"]


class TestWebSearchProviderShapes:
    """dev/90 A3 — the public keyed-GET search APIs work through the one
    CURIO_SEARCH_URL template with no provider server and no new deps."""

    def _search(self, monkeypatch, body: str):
        from utk_curio.backend.app.agents.infrastructure import egress
        from utk_curio.backend.app.agents.infrastructure.egress import EgressResult

        monkeypatch.setenv("CURIO_SEARCH_URL", "https://api.provider.test/v1?key=K&q={q}")
        monkeypatch.setattr(egress, "fetch", lambda url, **kw: EgressResult(
            url=url, final_url=url, status=200,
            content_type="application/json", body=body))
        status, text = tools.execute_read_tool(
            "web.search", user_key="42", project_id="none", target=None,
            params={"q": "cool roofs in Chicago"},
        )
        assert status == "ok"
        return json.loads(text)["results"]

    def test_google_programmable_search_items(self, monkeypatch):
        rows = self._search(monkeypatch, json.dumps({"items": [{
            "title": "Chicago cool roofs", "link": "https://heat.test/cool-roofs",
            "snippet": "white roofs ran 18°C cooler"}]}))
        assert rows == [{"title": "Chicago cool roofs", "url": "https://heat.test/cool-roofs",
                         "snippet": "white roofs ran 18°C cooler"}]

    def test_serpapi_organic_results(self, monkeypatch):
        rows = self._search(monkeypatch, json.dumps({"organic_results": [{
            "title": "Chicago cool roofs", "link": "https://w.test/p", "snippet": "cooler"}]}))
        assert rows[0]["url"] == "https://w.test/p"

    def test_brave_shaped_web_results_with_description(self, monkeypatch):
        rows = self._search(monkeypatch, json.dumps({"web": {"results": [{
            "title": "Chicago cool roofs", "url": "https://w.test/p",
            "description": "reflective coating"}]}}))
        assert rows[0]["snippet"] == "reflective coating"

    def test_href_alias_and_top_level_list(self, monkeypatch):
        rows = self._search(monkeypatch, json.dumps([{
            "title": "Chicago cool roofs", "href": "https://w.test/p", "content": "18C"}]))
        assert rows[0]["url"] == "https://w.test/p" and rows[0]["snippet"] == "18C"

    def test_unrecognized_shape_yields_empty_rows_not_an_error(self, monkeypatch):
        rows = self._search(monkeypatch, json.dumps({"answers": ["42"]}))
        assert rows == []
