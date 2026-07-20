"""Tests for the built-in agent roster (the 13 prompt-agent migrations)."""

from __future__ import annotations

from utk_curio.backend.app.agents import builtin
from utk_curio.backend.app.agents.manifest import AgentManifest


# The dev/06 canonical map: agent id -> its prompt file and capabilities.
_EXPECTED = {
    "agent.chat-agent": ("chat_prompt.txt", ["conversation.respond", "attachment.refine"]),
    "agent.debug-agent": ("debug_prompt.txt", ["code.debug.diagnose", "code.fix.propose"]),
    "agent.dataflow-explainer": ("explanation_prompt.txt", ["dataflow.explain"]),
    "agent.node-explainer": ("single_box_explanation_prompt.txt", ["node.explain", "node.output.interpret"]),
    "agent.node-content-builder": ("new_content_prompt.txt", ["node.content.generate"]),
    "agent.execution-subtask-planner": ("new_subtask_from_exec_prompt.txt", ["execution.followup.plan"]),
    "agent.dataflow-task-planner": ("new_subtasks_prompt.txt", ["workflow.plan.create"]),
    "agent.connection-builder": ("new_connection_prompt.txt", ["connection.propose"]),
    "agent.workflow-suggester": ("workflow_suggestions_prompt.txt", ["workflow.suggest"]),
    "agent.plan-coherence-validator": ("evaluate_coherence_subtasks_prompt.txt", ["workflow.coherence.validate"]),
    "agent.syntax-analysis-agent": ("syntax_analysis_prompt.txt", ["code.syntax.analyze"]),
    "agent.task-refresh-agent": ("task_refresh_prompt.txt", ["workflow.plan.refresh"]),
    "agent.keyword-binding-agent": ("keywords_binding_prompt.txt", ["workflow.keyword.bind"]),
}


class TestRoster:
    def test_thirteen_agents(self):
        assert len(builtin.BUILTIN_AGENTS) == 13

    def test_evaluator_excluded(self):
        ids = {s.agent_id for s in builtin.BUILTIN_AGENTS}
        assert "agent.generated-content-evaluator" not in ids  # blocked by OQ-007

    def test_matches_dev06_map(self):
        got = {s.agent_id: (s.prompt_file, list(s.capabilities)) for s in builtin.BUILTIN_AGENTS}
        assert got == _EXPECTED

    def test_every_prompt_file_exists(self):
        for spec in builtin.BUILTIN_AGENTS:
            assert (builtin.PROMPT_SOURCE_DIR / spec.prompt_file).is_file(), spec.prompt_file


class TestManifests:
    def test_all_validate(self):
        manifests = builtin.list_builtin_manifests()
        assert len(manifests) == 13
        assert all(isinstance(m, AgentManifest) for m in manifests)

    def test_coords_and_capabilities(self):
        by_id = {m.agent_id: m for m in builtin.list_builtin_manifests()}
        for agent_id, (_, caps) in _EXPECTED.items():
            m = by_id[agent_id]
            assert m.dir_name == f"{agent_id}@1.0.0"
            assert m.capability_ids == caps
            assert m.provenance.trust == "built-in"

    def test_get_by_coord(self):
        m = builtin.get_builtin_manifest("agent.node-explainer@1.0.0")
        assert m is not None and m.agent_id == "agent.node-explainer"
        assert builtin.get_builtin_manifest("agent.node-explainer@9.9.9") is None
        assert builtin.get_builtin_manifest("curio.builtin@1") is None
