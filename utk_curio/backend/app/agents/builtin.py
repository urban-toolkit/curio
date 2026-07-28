"""Built-in agent definitions — the 13 prompt-agent migrations.

Data-driven roster generated from the canonical prompt→agent map (plan memo
``dev/06``) over the existing prompt files in ``utk_curio/llm-prompts/*.txt``.
Each roster entry is turned into a manifest dict and validated through
``parse_agent_manifest``, so the built-ins can never drift from the manifest
contract. This roster is the **Global Catalog** source (real content the drawer
browses) and the resolution source for importing/installing a built-in.

``agent.generated-content-evaluator`` is intentionally absent: it has no prompt
file and is blocked by ``OQ-007`` — it must not be fabricated.

Prompt-byte materialization (copying ``llm-prompts/`` into a user store on
install) is a later step; the manifest ``prompts.instruction.path`` here is the
package-relative name the asset takes once materialized.

User-facing overview: ``docs/AGENTS.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from utk_curio.backend.app.agents.manifest import AgentManifest, parse_agent_manifest

BUILTIN_VERSION = "1.0.0"

# Where the legacy prompt files currently live. This module is
# utk_curio/backend/app/agents/builtin.py, so parents[3] is utk_curio/.
PROMPT_SOURCE_DIR = (Path(__file__).resolve().parents[3] / "llm-prompts")

# category -> the single compatible attachment target kind.
_TARGET_BY_CATEGORY = {
    "data": "node",
    "node": "node",
    "canvas": "canvas",
    "package": "node",
    "evaluate": "node",
}


@dataclass(frozen=True)
class BuiltinAgentSpec:
    agent_id: str
    name: str
    category: str
    purpose: str
    prompt_file: str  # instruction filename in llm-prompts/
    capabilities: tuple[str, ...]
    roles: tuple[str, ...] = field(default_factory=tuple)
    # System preamble filename in llm-prompts/ — the dev/05 roster's "System
    # file" column: default_preamble.txt for all but the syntax agent. Every
    # legacy call site composed preamble + prompt, so migration parity
    # (dev/06) requires the asset and its runtime composition.
    preamble_file: str = "default_preamble.txt"
    # inputs.reads — the context the agent consumes, grounded in what each
    # legacy call site actually passed (dev/06 migration map).
    reads: tuple[str, ...] = field(default_factory=tuple)
    # Compatible attachment target kinds. Empty → derive the single kind from
    # the category (_TARGET_BY_CATEGORY). Set explicitly for dual-compatible
    # agents (e.g. Chat attaches to a node OR the canvas).
    targets: tuple[str, ...] = field(default_factory=tuple)
    # Typed tool requirements (memo dev/41) — declarations, never grants
    # (DEC-017); grounded in the agent's declared reads / legacy behavior.
    # All optional: a missing grant degrades to the pre-tool blind behavior.
    tools: tuple[str, ...] = field(default_factory=tuple)

    def target_kinds(self) -> tuple[str, ...]:
        return self.targets or (_TARGET_BY_CATEGORY[self.category],)


# The 13 releasable prompt-agent migrations (dev/06 canonical map). The blocked
# generated-content evaluator is deliberately omitted.
BUILTIN_AGENTS: tuple[BuiltinAgentSpec, ...] = (
    BuiltinAgentSpec("agent.chat-agent", "Chat", "node",
                     "Conversational assistant for a node or the canvas.",
                     "chat_prompt.txt", ("conversation.respond", "attachment.refine"), ("chat",),
                     targets=("node", "canvas"), reads=("userMessage",)),
    BuiltinAgentSpec("agent.debug-agent", "Debug", "node",
                     "Diagnose errors and propose fixes for a node or the canvas.",
                     "debug_prompt.txt", ("code.debug.diagnose", "code.fix.propose"), ("debug",),
                     targets=("node", "canvas"), reads=("dataflowContext",),
                     tools=("dataflow.read",)),
    BuiltinAgentSpec("agent.dataflow-explainer", "Dataflow Explainer", "canvas",
                     "Explain what the whole dataflow does.",
                     "explanation_prompt.txt", ("dataflow.explain",), ("explanation",),
                     reads=("dataflowContext",), tools=("dataflow.read",)),
    BuiltinAgentSpec("agent.node-explainer", "Node Explainer", "node",
                     "Explain what a node or its output does.",
                     "single_box_explanation_prompt.txt",
                     ("node.explain", "node.output.interpret"), ("explanation",),
                     reads=("nodeContext",), tools=("node.read",)),
    BuiltinAgentSpec("agent.node-content-builder", "Node Content Builder", "node",
                     "Generate node content for a target.",
                     "new_content_prompt.txt", ("node.content.generate",), ("authoring",),
                     reads=("dataflowContext", "nodeId", "subtask", "workflowGoal"),
                     tools=("dataflow.read", "node.read", "node.content.write")),
    BuiltinAgentSpec("agent.execution-subtask-planner", "Execution Subtask Planner", "canvas",
                     "Plan follow-up subtasks from an execution.",
                     "new_subtask_from_exec_prompt.txt", ("execution.followup.plan",), ("planning",),
                     reads=("nodeContent", "nodeType", "currentTask")),
    BuiltinAgentSpec("agent.dataflow-task-planner", "Dataflow Task Planner", "canvas",
                     "Create a workflow plan from a goal.",
                     "new_subtasks_prompt.txt", ("workflow.plan.create",), ("planning",),
                     reads=("currentTask", "dataflowContext")),
    BuiltinAgentSpec("agent.connection-builder", "Connection Builder", "node",
                     "Suggest and create valid node connections.",
                     "new_connection_prompt.txt", ("connection.propose",), ("authoring",),
                     reads=("workflowGoal", "nodeId", "subtask", "connectionSide", "dataflowContext")),
    BuiltinAgentSpec("agent.workflow-suggester", "Workflow Suggester", "canvas",
                     "Suggest workflow next steps.",
                     "workflow_suggestions_prompt.txt", ("workflow.suggest",), ("planning",),
                     reads=("dataflowContext", "workflowGoal"), tools=("dataflow.read",)),
    BuiltinAgentSpec("agent.plan-coherence-validator", "Plan Coherence Validator", "evaluate",
                     "Validate that a plan's subtasks are coherent.",
                     "evaluate_coherence_subtasks_prompt.txt", ("workflow.coherence.validate",), ("validation",),
                     reads=("workflowGoal", "dataflowContext")),
    BuiltinAgentSpec("agent.syntax-analysis-agent", "Syntax Analysis", "evaluate",
                     "Analyze code syntax.",
                     "syntax_analysis_prompt.txt", ("code.syntax.analyze",), ("validation",),
                     preamble_file="syntax_analysis_preamble.txt", reads=("codeContext",)),
    BuiltinAgentSpec("agent.task-refresh-agent", "Task Refresh", "canvas",
                     "Refresh a workflow plan.",
                     "task_refresh_prompt.txt", ("workflow.plan.refresh",), ("planning",),
                     reads=("currentTask", "keywords", "dataflowContext")),
    BuiltinAgentSpec("agent.keyword-binding-agent", "Keyword Binding", "canvas",
                     "Bind keywords for a workflow.",
                     "keywords_binding_prompt.txt", ("workflow.keyword.bind",), ("planning",),
                     reads=("keywords", "dataflowContext")),
)


def build_builtin_manifest(spec: BuiltinAgentSpec) -> dict:
    """Turn a roster entry into a manifest dict (camelCase)."""
    return {
        "id": spec.agent_id,
        "name": spec.name,
        "category": spec.category,
        "version": BUILTIN_VERSION,
        "purpose": spec.purpose,
        "roles": list(spec.roles),
        "capabilities": [{"id": c, "contractVersion": "1"} for c in spec.capabilities],
        "prompts": {
            "system": {"path": f"prompts/{spec.preamble_file}", "variables": []},
            "instruction": {"path": f"prompts/{spec.prompt_file}", "variables": []},
        },
        "compatibleTargets": [{"kind": k, "requires": []} for k in spec.target_kinds()],
        "inputs": {"reads": list(spec.reads), "requiredConfig": []},
        # Typed tool requirements (dev/41) — all optional declarations.
        "tools": [{"id": t} for t in spec.tools],
        "runtime": {"execution": "foreground", "reviewPolicy": "report-only"},
        "providerRequirements": {"capabilities": ["structured-output"]},
        "provenance": {"publisher": "curio", "license": "MIT", "trust": "built-in"},
    }


def list_builtin_manifests() -> list[AgentManifest]:
    """Validated manifests for every built-in, in roster order."""
    return [parse_agent_manifest(build_builtin_manifest(s), where=s.agent_id) for s in BUILTIN_AGENTS]


def _by_coord() -> dict[str, BuiltinAgentSpec]:
    return {f"{s.agent_id}@{BUILTIN_VERSION}": s for s in BUILTIN_AGENTS}


def get_builtin_spec(coord: str) -> BuiltinAgentSpec | None:
    """Resolve a ``<agentId>@<version>`` coordinate to its roster spec, or None."""
    return _by_coord().get(coord)


def get_builtin_manifest(coord: str) -> AgentManifest | None:
    """Resolve a ``<agentId>@<version>`` coordinate to a built-in manifest, or None."""
    spec = _by_coord().get(coord)
    if spec is None:
        return None
    return parse_agent_manifest(build_builtin_manifest(spec), where=spec.agent_id)


def read_prompt_text(coord: str, name: str) -> str | None:
    """Read a built-in's prompt asset text from ``llm-prompts/``, or None.

    ``name`` is the manifest prompt key: ``"instruction"`` (the agent's task
    prompt) or ``"system"`` (its preamble).
    """
    spec = _by_coord().get(coord)
    if spec is None:
        return None
    filename = spec.prompt_file if name == "instruction" else spec.preamble_file
    path = PROMPT_SOURCE_DIR / filename
    return path.read_text(encoding="utf-8") if path.is_file() else None


def read_instruction_text(coord: str) -> str | None:
    """Read a built-in's instruction prompt text from ``llm-prompts/``, or None."""
    return read_prompt_text(coord, "instruction")
