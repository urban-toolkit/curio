"""Tests for tool contracts + grant resolution + read execution
(memos dev/39/dev/41, DEC-017/DEC-045)."""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents import tools
from utk_curio.backend.app.agents.manifest import ToolRequirement
from utk_curio.backend.app.agents.tools import ToolContract


def _req(tool_id: str, required: bool = False) -> ToolRequirement:
    return ToolRequirement(id=tool_id, required=required)


class TestRegistry:
    def test_registry_holds_exactly_the_named_contracts(self):
        # Each contract has a named consumer in the built-in roster (dev/41
        # §4.3; node.create → agent.node-builder, dev/48) — nothing
        # speculative lives here.
        assert set(tools.REGISTRY) == {
            "dataflow.read", "node.read", "node.content.write", "node.create",
            "node.template.create", "catalog.search", "dataset.install",
            "dataflow.plan.write", "node.runtime.read",
        }
        assert tools.REGISTRY["dataflow.read"].effect == "read"
        assert tools.REGISTRY["node.read"].effect == "read"
        assert tools.REGISTRY["node.content.write"].effect == "mutate"
        assert tools.REGISTRY["node.create"].effect == "mutate"
        assert tools.REGISTRY["node.template.create"].effect == "mutate"
        assert tools.REGISTRY["catalog.search"].effect == "read"
        assert tools.REGISTRY["dataset.install"].effect == "mutate"
        assert tools.REGISTRY["dataflow.plan.write"].effect == "mutate"
        assert tools.REGISTRY["node.runtime.read"].effect == "read"

    def test_contract_validates_effect(self):
        with pytest.raises(ValueError):
            ToolContract(id="x.y", contract_version="1", effect="write", description="")


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
                "agents": ["agent.chat-agent@1.0.0"] if with_agents else [],
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

        spec = {"dataflow": {"nodes": [
            {"id": "a", "type": "t", "content": ""},
            {"id": "m", "type": "curio.builtin/merge-flow", "content": ""},
        ], "edges": [
            {"id": "e1", "source": "a", "target": "m",
             "sourceHandle": "out", "targetHandle": "in_0"},
        ]}}
        projects_storage.write_spec(self.UKEY, self.PID, spec)
        _, text = tools.execute_read_tool(
            "dataflow.read", user_key=self.UKEY, project_id=self.PID, target=None, params={}
        )
        assert json.loads(text)["edges"][0]["targetHandle"] == "in_0"


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
