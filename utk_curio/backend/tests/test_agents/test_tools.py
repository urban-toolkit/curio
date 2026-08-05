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
            "dataflow.plan.write",
        }
        assert tools.REGISTRY["dataflow.read"].effect == "read"
        assert tools.REGISTRY["node.read"].effect == "read"
        assert tools.REGISTRY["node.content.write"].effect == "mutate"
        assert tools.REGISTRY["node.create"].effect == "mutate"
        assert tools.REGISTRY["node.template.create"].effect == "mutate"
        assert tools.REGISTRY["catalog.search"].effect == "read"
        assert tools.REGISTRY["dataset.install"].effect == "mutate"
        assert tools.REGISTRY["dataflow.plan.write"].effect == "mutate"

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
        payload = json.loads(text)
        # Rule-9 posture: agent sections never enter model context.
        assert "agents" not in payload["dataflow"]
        assert "agentAttachments" not in payload["dataflow"]
        assert payload["dataflow"]["nodes"][0]["id"] == "n1"

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
