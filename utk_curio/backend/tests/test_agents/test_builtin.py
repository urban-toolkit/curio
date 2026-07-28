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


class TestPreambleAndInputs:
    """The dev/05 roster's System-file column + grounded inputs (dev/06 parity):
    every built-in manifest carries its preamble asset and non-empty reads."""

    def test_every_builtin_declares_system_asset_and_reads(self):
        from utk_curio.backend.app.agents import builtin

        for m in builtin.list_builtin_manifests():
            assert "system" in m.prompts, m.agent_id
            assert m.prompts["system"].path.startswith("prompts/"), m.agent_id
            assert m.inputs_reads, f"{m.agent_id} has no inputs.reads"

    def test_syntax_agent_uses_its_own_preamble(self):
        from utk_curio.backend.app.agents import builtin

        m = builtin.get_builtin_manifest("agent.syntax-analysis-agent@1.0.0")
        assert m.prompts["system"].path == "prompts/syntax_analysis_preamble.txt"
        others = builtin.get_builtin_manifest("agent.chat-agent@1.0.0")
        assert others.prompts["system"].path == "prompts/default_preamble.txt"

    def test_preamble_text_readable_for_all_builtins(self):
        from utk_curio.backend.app.agents import builtin

        for spec in builtin.BUILTIN_AGENTS:
            coord = f"{spec.agent_id}@1.0.0"
            assert builtin.read_prompt_text(coord, "system"), coord
            assert builtin.read_prompt_text(coord, "instruction"), coord
