"""Built-in agent definitions — the 13 prompt-agent migrations + composites.

Data-driven roster generated from the canonical prompt→agent map (plan memo
``dev/06``) over the existing prompt files in ``utk_curio/llm-prompts/*.txt``,
plus the P5 composites (memo ``dev/48``: ``agent.node-builder``), whose
instruction assets are net-new but live in the same directory so resolution
and materialization work unchanged.
Each roster entry is turned into a manifest dict and validated through
``parse_agent_manifest``, so the built-ins can never drift from the manifest
contract. This roster is the **Global Catalog** source (real content the drawer
browses) and the resolution source for importing/installing a built-in.

``agent.generated-content-evaluator`` shipped as a net-new AUTHORED built-in
under ``DEC-055`` (memo dev/85 resolved ``OQ-007``: authored, not migrated —
the advisory semantic-validation layer; report-only, never feeds the DEC-054
empirical auto-approve).

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
    # compatibleTargets[].requires for the "node" kind (memo dev/50): template
    # id suffixes the target node's canonical type must match (e.g.
    # "data-loading"). Empty = any node — every prior agent byte-identical.
    node_requires: tuple[str, ...] = field(default_factory=tuple)
    # Preferred delegate agents, in preference order (memo dev/48 / dev/15
    # §3.2). Expresses composition only — grants nothing; resolution is
    # current-project-only at run time.
    delegates_to: tuple[str, ...] = field(default_factory=tuple)
    # Hard dependencies (memo dev/106): the subset of delegates_to a SERVER
    # code path of this agent invokes without model choice. Installing the
    # agent installs the closure at the user's explicit click; uninstalling a
    # required one while a dependent is installed is refused.
    requires_agents: tuple[str, ...] = field(default_factory=tuple)
    # runtime.reviewPolicy. The default keeps the thirteen migrated manifests
    # byte-identical; composites that mint mutation proposals declare
    # "review-before-apply".
    review_policy: str = "report-only"

    def target_kinds(self) -> tuple[str, ...]:
        return self.targets or (_TARGET_BY_CATEGORY[self.category],)


# The 13 releasable prompt-agent migrations (dev/06 canonical map) + the P5
# composites (dev/48). The blocked generated-content evaluator is deliberately
# omitted.
BUILTIN_AGENTS: tuple[BuiltinAgentSpec, ...] = (
    BuiltinAgentSpec("agent.chat-agent", "Chat", "node",
                     "Conversational assistant for a node or the canvas.",
                     "chat_prompt.txt", ("conversation.respond", "attachment.refine"), ("chat",),
                     targets=("node", "canvas"), reads=("userMessage",)),
    BuiltinAgentSpec("agent.debug-agent", "Debug", "node",
                     "Diagnose errors and propose fixes for a node or the canvas.",
                     "debug_prompt.txt", ("code.debug.diagnose", "code.fix.propose"), ("debug",),
                     targets=("node", "canvas"), reads=("dataflowContext",),
                     tools=("dataflow.read", "node.runtime.read")),
    BuiltinAgentSpec("agent.dataflow-explainer", "Dataflow Explainer", "canvas",
                     "Explain what the whole dataflow does.",
                     "explanation_prompt.txt", ("dataflow.explain",), ("explanation",),
                     reads=("dataflowContext",), tools=("dataflow.read",)),
    BuiltinAgentSpec("agent.node-explainer", "Node Explainer", "node",
                     "Explain what a node or its output does.",
                     "single_box_explanation_prompt.txt",
                     ("node.explain", "node.output.interpret"), ("explanation",),
                     reads=("nodeContext",), tools=("node.read", "node.runtime.read")),
    BuiltinAgentSpec("agent.node-content-builder", "Node Content Builder", "node",
                     "Generate node content for a target.",
                     "new_content_prompt.txt", ("node.content.generate",), ("authoring",),
                     reads=("dataflowContext", "nodeId", "subtask", "workflowGoal"),
                     tools=("dataflow.read", "node.read", "node.content.write",
                            "node.runtime.read")),
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
                     reads=("workflowGoal", "nodeId", "subtask", "connectionSide", "dataflowContext"),
                     # dev/16 §3.3 addendum via dev/84 (deviation D4): the one
                     # migrated manifest that gains delegatesTo — a proposed
                     # connection's required packages surface as reviewed
                     # proposals. Its connection.propose capability is unchanged.
                     delegates_to=("agent.package-recommendation",)),
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
    # dev/67-4 (DEC-053): the research agent — concise factual verification
    # of external sources (dataset ids, endpoints, schemas) other agents
    # chain to via research.verify; policy-gated web tools; never mutates.
    BuiltinAgentSpec("agent.node-researcher", "Node Researcher", "evaluate",
                     "Verify external facts — dataset ids, API endpoints, schemas, "
                     "parameter names — with policy-gated web access; reusable and "
                     "chainable; reports failure to verify as a finding.",
                     "research_instruction.txt",
                     ("research.verify", "research.summarize"), ("validation",),
                     targets=("node", "canvas"),
                     reads=("mission", "nodeContext"),
                     tools=("web.search", "web.fetch", "node.read")),
    # The first P5 composite (memo dev/48; spec dev/15 §3.4). Net-new
    # instruction — no migrated prompt source. dev/15 deviations recorded in
    # the memo: "connection" target and agent.package-recommendation deferred.
    BuiltinAgentSpec("agent.node-builder", "Node Builder", "node",
                     "Create computation, transform, visualization, or data-fetch nodes as "
                     "reviewable proposals — or modify an existing node through a reviewed "
                     "content replacement; delegates content generation to Node Content Builder.",
                     "node_build_instruction.txt",
                     ("node.build", "dataset.fetch.author"), ("authoring",),
                     # dev/67-6: node targets lift the dev/48 canvas-only
                     # limitation — the modify-existing posture attaches to
                     # the node it modifies.
                     targets=("canvas", "node"),
                     reads=("nodeIntent", "targetContext", "externalSelection"),
                     tools=("dataflow.read", "node.create", "node.template.create",
                            "node.runtime.read", "node.content.write"),
                     delegates_to=("agent.node-content-builder", "agent.execution-subtask-planner",
                                   "agent.node-researcher",
                                   # dev/84: a built node's required packages.
                                   "agent.package-recommendation",
                                   # dev/89: no suitable template anywhere →
                                   # the package.create-or-extend intent goes
                                   # to the authoring specialist (reuse/catalog
                                   # discovery stays ahead in preference order).
                                   "agent.package-builder",
                                   # dev/86 (DEC-055): optional post-generation
                                   # semantic check — advisory, never approval.
                                   "agent.generated-content-evaluator"),
                     review_policy="review-before-apply"),
    # The second P5 composite (memo dev/50; spec dev/15 §3.4 + docs/06). Two-
    # lane discovery: catalog picks → reviewed dataset.install; external picks
    # → the DEC-047 user-mediated Node Builder handoff. Never authors fetch
    # code. Deviations recorded in the memo (canvas target added for mission-
    # first discovery; foreground-only; no auto-install).
    BuiltinAgentSpec("agent.dataset-finder", "Dataset Finder", "data",
                     "Discover and select datasets across external sources and the Data "
                     "Catalog; hand external picks to Node Builder. Never authors fetch code.",
                     "discovery_instruction.txt",
                     ("dataset.discover", "dataset.select"), ("discovery", "selection"),
                     targets=("node", "canvas"),
                     reads=("mission", "nodeContext", "catalog"),
                     tools=("catalog.search", "dataset.install", "dataflow.read"),
                     delegates_to=("agent.node-builder", "agent.workflow-suggester",
                                   "agent.keyword-binding-agent", "agent.node-researcher"),
                     review_policy="review-before-apply",
                     node_requires=("data-loading",)),
    # The third P5 composite (memo dev/52; spec dev/15 §3.4 + dev/49 DR-1…5).
    # Plan → Revise → Solve → Run: additive graph-level plan proposals, the
    # persisted builder session, and the authenticated Solve batch (DEC-048).
    # Deviation recorded: agent.package-recommendation deferred (dev/16).
    BuiltinAgentSpec("agent.dataflow-builder", "Dataflow Builder", "canvas",
                     "Plan a connected dataflow from a goal as one reviewable proposal; "
                     "solve unresolved nodes through delegated specialists. Never mutates "
                     "without review.",
                     "orchestration_instruction.txt",
                     ("dataflow.orchestrate",), ("orchestration",),
                     reads=("mission", "graphContext", "installedTemplates"),
                     # dev/95: node.create is the reviewed lane the delegated
                     # Researcher's note proposals mint on (grant-gated —
                     # nothing lands without the user's Apply).
                     tools=("dataflow.read", "dataflow.plan.write",
                            "node.runtime.read", "node.create"),
                     # dev/73: node-content-builder listed so node.content.generate
                     # is OFFERED in the delegation paragraph — the chat path for
                     # "change this node's content" (the runtime mints the review
                     # at that node's own agent; plans stay content-free).
                     delegates_to=("agent.dataset-finder", "agent.node-builder",
                                   "agent.node-content-builder",
                                   "agent.connection-builder", "agent.dataflow-task-planner",
                                   "agent.execution-subtask-planner", "agent.task-refresh-agent",
                                   "agent.workflow-suggester", "agent.plan-coherence-validator",
                                   "agent.dataflow-explainer", "agent.node-researcher",
                                   # dev/84: the "Recommend packages" plan step.
                                   "agent.package-recommendation",
                                   # dev/89: package-scale plan steps — one
                                   # coherent new or extended multi-template
                                   # package, instead of repeated single-
                                   # template rewrites.
                                   "agent.package-builder",
                                   # dev/86 (DEC-055): optional post-generation
                                   # semantic check — advisory, never approval.
                                   "agent.generated-content-evaluator",
                                   # dev/95 (Follow-up D): research questions in
                                   # the DFB chat delegate research.notes.compose
                                   # — runtime-gathered search inputs, schema
                                   # reply, reviewed note sequence.
                                   "agent.researcher"),
                     # dev/106: Solve/Validate hard-invoke node.content.generate.
                     requires_agents=("agent.node-content-builder",),
                     review_policy="review-before-apply"),
    # The fourteenth releasable built-in (memo dev/84; spec dev/16 / DEC-035).
    # Net-new instruction. Deviations recorded in the memo: roster-generated
    # manifest (foreground, no settingsDefaults); the dev/16 installedPackages
    # read is served by packages.catalog's installed flags, not a new fragment.
    # Identify/suggest/reviewed-install only — never installs, never authors.
    BuiltinAgentSpec("agent.package-recommendation", "Package Recommendation", "package",
                     "Identify and recommend the node packages a task, node, or dataflow "
                     "needs; surface each required-but-uninstalled package as a reviewed "
                     "install proposal against the existing Nodes Catalog. Never installs "
                     "anything itself and never authors a package.",
                     "package_recommendation_instruction.txt",
                     ("package.recommend", "package.identify"), ("recommendation",),
                     targets=("node", "canvas"),
                     reads=("mission", "targetContext", "installedTemplates"),
                     tools=("packages.catalog", "packages.resolve", "package.install",
                            "dataflow.read"),
                     delegates_to=("agent.syntax-analysis-agent",),
                     review_policy="review-before-apply"),
    # The DEC-055 authored built-in (memo dev/85 resolved OQ-007; impl dev/86).
    # The advisory semantic-validation layer over the empirical stack: judges
    # generated content against its goal/assumptions/journal evidence and
    # reports findings + a derived verdict. Report-only, delegates-free —
    # it can never approve, propose, or mutate; DEC-054's simulation
    # auto-approve stays exclusively empirical.
    BuiltinAgentSpec("agent.generated-content-evaluator", "Generated Content Evaluator",
                     "evaluate",
                     "Judge whether generated node content does what its goal and "
                     "assumptions say — findings with quoted evidence and an advisory "
                     "verdict. Never approves, never mutates, never replaces "
                     "execution-based validation.",
                     "evaluate_generated_content_prompt.txt",
                     ("content.quality.evaluate",), ("validation",),
                     targets=("node", "canvas"),
                     reads=("nodeContext", "targetContext"),
                     tools=("node.read", "node.runtime.read", "dataflow.read")),
    # The twentieth built-in (memo dev/89). Net-new instruction. The package
    # AUTHORING specialist, deliberately separate from Package Recommendation
    # (dev/89 §3): recommendation stays catalog-grounded discovery + reviewed
    # install; authoring owns the package artifact — new or extended packages,
    # template definitions, behavior source, dependencies, assets, integrity —
    # always as a reviewed draft. Node Builder's template fallback and Dataflow
    # Builder's package-scale plan steps delegate the package.create-or-extend
    # intent here, which resolves to these capabilities. package.draft.apply
    # is the ONE authoring mutate contract (dev/89 commit 8): requesting it
    # runs the isolated build service and mints the reviewed draft proposal;
    # Apply promotes the exact reviewed artifact digest.
    BuiltinAgentSpec("agent.package-builder", "Package Builder", "package",
                     "Author a new node package or extend an installed editable one — "
                     "templates, custom JS behavior, dependencies, assets, integrity — "
                     "as one reviewed, installable draft. Never installs, never "
                     "publishes, never touches read-only packages.",
                     "package_build_instruction.txt",
                     ("package.build", "package.extend", "node.kind.author"),
                     ("authoring",),
                     targets=("node", "canvas"),
                     reads=("packageIntent", "targetContext", "installedTemplates"),
                     tools=("packages.catalog", "packages.resolve", "dataflow.read",
                            "package.draft.apply"),
                     review_policy="review-before-apply"),
    # The twenty-first built-in (memo dev/90). Net-new instruction. The NOTES
    # scenario owner: turns findings into post-it style note nodes. Distinct
    # from agent.node-researcher (dev/67-4 web VERIFICATION) — the two
    # cooperate: Researcher may chain research.verify before composing.
    # Reuse-first (node.create on an installed notes template, per-note
    # appearance color); when no template fits it delegates the
    # package.create-or-extend intent to the Package Builder with the
    # post-it recipe's REQUIREMENTS as inputs — it never composes manifests
    # or behavior source itself. package.draft.apply is declared for the
    # dev/90 delegate-draft mint authorization only (DEC-017: proposal
    # purposes; the draft content always comes from the delegate).
    # Dataflow Builder wiring is deliberately deferred (dev/90 Follow-up D).
    BuiltinAgentSpec("agent.researcher", "Researcher", "node",
                     "Answer questions by searching the web and compose the "
                     "findings into post-it style note nodes — reuse an "
                     "installed notes template, or delegate package authoring to "
                     "the Package Builder with the post-it look requirements. "
                     "Never authors packages itself; distinct from Node "
                     "Researcher (verification).",
                     "researcher_notes_instruction.txt",
                     ("research.notes.compose",), ("authoring",),
                     targets=("node", "canvas"),
                     reads=("mission", "targetContext", "installedTemplates"),
                     # dev/90 A1: the reference recording's loop — question →
                     # web search → post-it reply. The dev/67-4 web contracts
                     # ride as-is (egress policy, ≤4 calls/run, honest
                     # not-configured error).
                     # dev/93 D4: package.install is the MIDDLE rung of the
                     # reuse ladder. Without it the Researcher could only
                     # reuse a template this project already enlisted or
                     # author a brand-new package — so a notes package the
                     # user already owned was unreachable, and one weather
                     # question produced two near-duplicate packages. The
                     # reviewed install lane (dev/84) keeps the user in
                     # control; nothing installs without their approval.
                     tools=("dataflow.read", "web.search", "web.fetch",
                            "node.create", "package.install",
                            "package.draft.apply"),
                     delegates_to=("agent.package-builder", "agent.node-researcher"),
                     review_policy="review-before-apply"),
)


def build_builtin_manifest(spec: BuiltinAgentSpec) -> dict:
    """Turn a roster entry into a manifest dict (camelCase)."""
    manifest = {
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
        "compatibleTargets": [
            {
                "kind": k,
                "requires": list(spec.node_requires) if k == "node" else [],
            }
            for k in spec.target_kinds()
        ],
        "inputs": {"reads": list(spec.reads), "requiredConfig": []},
        # Typed tool requirements (dev/41) — all optional declarations.
        "tools": [{"id": t} for t in spec.tools],
        "runtime": {"execution": "foreground", "reviewPolicy": spec.review_policy},
        "providerRequirements": {"capabilities": ["structured-output"]},
        "provenance": {"publisher": "curio", "license": "MIT", "trust": "built-in"},
    }
    # Only composites carry the key — the thirteen migrated manifests stay
    # byte-identical (memo dev/48 regression requirement).
    if spec.delegates_to:
        manifest["delegatesTo"] = list(spec.delegates_to)
    if spec.requires_agents:
        manifest["requiresAgents"] = list(spec.requires_agents)
    return manifest


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
