"""Built-in agent definitions: every agent Curio ships with; those marked ``in_catalog`` are the catalog cards.

Data-driven roster generated from the canonical prompt→agent map (plan memo
``dev/06``) over the existing prompt files in ``utk_curio/llm-prompts/*.md``,
plus the P5 composites (memo ``dev/48``: ``agent.node-builder``), whose
instruction assets are net-new but live in the same directory so resolution
and materialization work unchanged.
Each roster entry is turned into a manifest dict and validated through
``parse_agent_manifest``, so the built-ins can never drift from the manifest
contract. This roster is what the catalog browses and the resolution source for
importing or installing a built-in.

``agent.generated-content-evaluator`` shipped as a net-new AUTHORED built-in
under ``DEC-055`` (memo dev/85 resolved ``OQ-007``: authored, not migrated —
the advisory semantic-validation layer; report-only, never feeds the DEC-054
empirical auto-approve).

Prompt-byte materialization (copying ``llm-prompts/`` into a user store on
install) is a later step; the manifest ``prompts.instruction.path`` here is the
package-relative name the asset takes once materialized.

User-facing overview: ``docs/AGENT-CATALOG.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from utk_curio.backend.app.agents.domain.manifest import (
    AgentManifest,
    parse_agent_manifest,
)
from utk_curio.backend.app.agents.domain.contracts import AUTK_PROMPT_KEY, PACKAGE_CONTRACT

log = logging.getLogger(__name__)

BUILTIN_VERSION = "1.0.0"

# Where the legacy prompt files currently live. This module is
# utk_curio/backend/app/agents/builtin.py, so parents[3] is utk_curio/.
# domain/builtin.py -> domain -> agents -> app -> backend -> utk_curio/llm-prompts (one deeper since B1)
PROMPT_SOURCE_DIR = (Path(__file__).resolve().parents[4] / "llm-prompts")
# The one preamble every built-in composes before its instruction. It is
# generated, as are the instructions with a ``.template.md`` beside them
# (``contracts.render_prompt``).
PREAMBLE_FILE = "default_preamble.md"
# The package backend contract: the Node Builder's package-writing prompt
# includes the text, and a delegated call of that mode receives this file as
# an input.
PACKAGE_CONTRACT_FILE = f"{PACKAGE_CONTRACT}.md"
# The Node Builder's package-writing capabilities, in the order its manifest
# lists them (``content.PACKAGE_AUTHORING_CAPABILITIES`` holds the same set).
# All three are one mode prompt, ``package_build_instruction.md``.
_PACKAGE_WRITING = ("package.build", "package.extend", "node.kind.author")

# category -> the single compatible attachment target kind.
_TARGET_BY_CATEGORY = {
    "data": "node",
    "node": "node",
    "canvas": "canvas",
    "package": "node",
    "evaluate": "node",
}


@dataclass(frozen=True)
class BuiltinMode:
    """One capability of a merged agent: its own instruction file, the context
    it reads, and the catalog settings it needs. A delegated run of that
    capability runs this mode."""

    capability: str
    prompt_file: str
    reads: tuple[str, ...]
    required_config: tuple[str, ...] = ()
    # Whether a run of this mode gets worked examples, the shipped dataflows
    # closest to its task, in its runtime slot (``turns/examples``).
    worked_examples: bool = False


#: A ``delegates_to`` entry: an agent id, or ``(agent id, capabilities)`` to
#: delegate only those capabilities of it.
Delegate = "str | tuple[str, tuple[str, ...]]"


@dataclass(frozen=True)
class BuiltinAgentSpec:
    agent_id: str
    name: str
    category: str
    purpose: str
    prompt_file: str  # instruction filename in llm-prompts/
    capabilities: tuple[str, ...]
    roles: tuple[str, ...] = field(default_factory=tuple)
    # inputs.reads — the context the agent consumes, grounded in what each
    # legacy call site actually passed (dev/06 migration map).
    reads: tuple[str, ...] = field(default_factory=tuple)
    # Compatible attachment target kinds. Empty → derive the single kind from
    # the category (_TARGET_BY_CATEGORY). Set explicitly for dual-compatible
    # agents (e.g. the Researcher attaches to a node OR the canvas).
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
    # current-project-only at run time. An entry may name the capabilities it
    # delegates, so a merged agent is not offered whole to every parent.
    delegates_to: tuple = field(default_factory=tuple)
    # Hard dependencies (memo dev/106): the subset of delegates_to a SERVER
    # code path of this agent invokes without model choice. Installing the
    # agent installs the closure at the user's explicit click; uninstalling a
    # required one while a dependent is installed is refused.
    requires_agents: tuple[str, ...] = field(default_factory=tuple)
    # runtime.reviewPolicy. The default keeps the thirteen migrated manifests
    # byte-identical; composites that mint mutation proposals declare
    # "review-before-apply".
    review_policy: str = "report-only"
    # runtime.execution (dev/115, DEC-073): "background" declares that a SERVER
    # path of this agent outlives the HTTP request — the Dataflow Builder's
    # Solve runs as a detached, re-attachable job. The dock projects a running
    # indicator from the live job (docs/11:178). Every other built-in stays
    # "foreground" byte-identically.
    execution: str = "foreground"
    # Whether the agent is a catalog card. A card can change the user's
    # project, is one whose input or output the runtime treats as structure,
    # or is the only agent for a canvas target. Every other built-in is
    # internal: it runs only as a delegate, resolves from this roster without
    # being installed, and is never listed, installed or attached.
    in_catalog: bool = True
    # A merged agent's modes, one per capability. Empty for an agent with one
    # instruction for everything it does.
    modes: tuple[BuiltinMode, ...] = field(default_factory=tuple)
    # Instructions a run selects in place of its instruction or a mode's in
    # one situation, as (prompts key, file): the Autark document under its
    # reply schema (``reply_schemas.AUTK_PROMPT_KEY``).
    variant_prompts: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    # Whether a run of this agent, under its instruction or a variant, gets
    # worked examples (``turns/examples``). A mode decides for itself.
    worked_examples: bool = False

    def target_kinds(self) -> tuple[str, ...]:
        return self.targets or (_TARGET_BY_CATEGORY[self.category],)

    def delegate_ids(self) -> tuple[str, ...]:
        return tuple(d if isinstance(d, str) else d[0] for d in self.delegates_to)

    def prompt_files(self) -> dict[str, str]:
        """Every prompt key this agent declares and the file behind it."""
        files = {"system": PREAMBLE_FILE, "instruction": self.prompt_file}
        files.update({mode.capability: mode.prompt_file for mode in self.modes})
        files.update(dict(self.variant_prompts))
        return files


def _merged(agent_id: str, name: str, category: str, purpose: str,
            modes: tuple[BuiltinMode, ...], **kwargs) -> BuiltinAgentSpec:
    """An internal agent made of *modes*: its capabilities are the modes',
    its default instruction the first mode's, and its reads their union."""
    reads = tuple(dict.fromkeys(r for mode in modes for r in mode.reads))
    return BuiltinAgentSpec(
        agent_id, name, category, purpose, modes[0].prompt_file,
        tuple(mode.capability for mode in modes), reads=reads, modes=modes,
        in_catalog=False, **kwargs,
    )


# The prompt-agent migrations (dev/06 canonical map) plus the P5 composites
# (dev/48) and the package-authoring agents. The catalog cards are the ones
# marked ``in_catalog``, which is what docs/AGENT-CATALOG.md quotes and
# test_prompt_assets parametrizes over; the catalog lists them in this order.
BUILTIN_AGENTS: tuple[BuiltinAgentSpec, ...] = (
    # The twenty-first built-in (memo dev/90): the agent you talk to about a
    # node or the whole dataflow, which took over the chat agent. Its chat
    # explains, debugs and helps define a task from the dataflow as it is on
    # screen, unsaved edits included, with the read tools to look further;
    # answers a question the dataflow cannot answer from the web, as post-it
    # style note nodes; and checks facts (dev/67-4 web VERIFICATION) with
    # labeled findings and no notes. The model picks which, following its
    # chat prompt's rules. Other agents ask for its two modes, each a
    # delegated call with no tools: research.notes.compose (dev/95) composes
    # notes from the search results the runtime gathered, and research.verify
    # synthesizes over the verification the runtime ran. Its chat and its
    # checking mode carry the same checking rules ({{research.verify_rules}}),
    # and its chat and its notes mode the same notes format
    # ({{research.notes_rules}}).
    # Reuse-first (node.create on an installed notes template, per-note
    # appearance color); when no template fits it delegates the
    # package.create-or-extend intent to the Node Builder's package-writing
    # mode with the post-it recipe's REQUIREMENTS as inputs: it never composes
    # manifests or behavior source itself. package.draft.apply is declared
    # for the dev/90 delegate-draft mint authorization only (DEC-017:
    # proposal purposes; the draft content always comes from the delegate).
    BuiltinAgentSpec("agent.researcher", "Researcher", "node",
                     "Talk about a node or the whole dataflow: it explains them, diagnoses "
                     "errors and helps you define what to build. It also answers questions "
                     "from the web as notes on the canvas, and checks facts such as dataset "
                     "ids and endpoints.",
                     "researcher_instruction.md",
                     ("research.notes.compose", "research.verify"), ("authoring",),
                     targets=("node", "canvas"),
                     # The dataflow on screen, unsaved edits included
                     # (dataflowContext), beside what it is attached to
                     # (targetContext: on a node, that node and its last run).
                     reads=("mission", "targetContext", "installedTemplates", "dataflowContext"),
                     # The read tools answer about the dataflow and a node's
                     # last run. dev/90 A1: the reference recording's loop,
                     # question, web search, post-it reply. The dev/67-4 web
                     # contracts ride as-is (egress policy, at most 4 calls a
                     # run, honest not-configured error).
                     # dev/93 D4: package.install is the MIDDLE rung of the
                     # reuse ladder. Without it the Researcher could only
                     # reuse a template this project already enlisted or
                     # author a brand-new package, so a notes package the
                     # user already owned was unreachable, and one weather
                     # question produced two near-duplicate packages. The
                     # reviewed install lane (dev/84) keeps the user in
                     # control; nothing installs without their approval.
                     tools=("dataflow.read", "node.read", "node.runtime.read", "web.search",
                            "web.fetch", "node.create", "package.install",
                            "package.draft.apply"),
                     # Package writing only: it checks facts and composes
                     # notes itself.
                     delegates_to=(("agent.node-builder", _PACKAGE_WRITING),),
                     review_policy="review-before-apply",
                     modes=(BuiltinMode("research.notes.compose", "researcher_notes_instruction.md",
                                        ("question", "searchResults", "notesTemplates")),
                            BuiltinMode("research.verify", "research_instruction.md",
                                        ("mission", "nodeContext")))),
    # The planning and keyword agents, merged: six capabilities that shared
    # their tools (none), delegates (none), review and execution, each still
    # running its own instruction as a mode. Internal: a delegate only.
    _merged("agent.dataflow-planner", "Dataflow Planner", "canvas",
            "Plan, refresh and check a dataflow's tasks, and extract and bind "
            "the keywords that describe it.",
            (BuiltinMode("workflow.plan.create", "new_subtasks_prompt.md",
                         ("currentTask", "dataflowContext")),
             BuiltinMode("execution.followup.plan", "new_subtask_from_exec_prompt.md",
                         ("nodeContent", "nodeType", "currentTask")),
             BuiltinMode("workflow.plan.refresh", "task_refresh_prompt.md",
                         ("currentTask", "keywords", "dataflowContext"), ("keywordTypes",)),
             BuiltinMode("workflow.coherence.validate", "evaluate_coherence_subtasks_prompt.md",
                         ("workflowGoal", "dataflowContext")),
             BuiltinMode("workflow.keyword.bind", "keywords_binding_prompt.md",
                         ("keywords", "dataflowContext"), ("keywordTypes",)),
             BuiltinMode("workflow.keywords.extract", "syntax_analysis_prompt.md",
                         ("workflowGoal",), ("keywordTypes",))),
            roles=("planning", "validation"), targets=("canvas",)),
    # The two dataflow readers, merged the same way.
    _merged("agent.dataflow-reader", "Dataflow Reader", "canvas",
            "Explain what the whole dataflow does, and suggest its next steps.",
            (BuiltinMode("dataflow.explain", "explanation_prompt.md", ("dataflowContext",)),
             BuiltinMode("workflow.suggest", "workflow_suggestions_prompt.md",
                         ("dataflowContext", "workflowGoal"), worked_examples=True)),
            roles=("explanation", "planning"), targets=("canvas",), tools=("dataflow.read",)),
    # The first P5 composite (memo dev/48; spec dev/15 §3.4). Its chat runs
    # its own instruction; content for a node runs as its
    # node.content.generate mode, which its chat asks for through the entry
    # naming itself, and Solve and validate ask for by capability. The mode
    # is a delegated call with no tools, under the Autark prompt for an
    # Autark document. On a connection, or asked what could come before or
    # after a node, its chat suggests up to three nodes in prose and creates
    # the one the user picks (the connection builder's work, which it took
    # over); the user wires it.
    # It also took over the package agents (dev/84, dev/89). Its chat installs
    # a catalog package that already fits (the reviewed package.install
    # lane), grounded in packages.catalog and packages.resolve, and climbs the
    # node type ladder: an existing template, a package to install,
    # node.template.create, then a package written by its writing mode. The
    # writing mode (package.build, package.extend and node.kind.author, one
    # prompt) is a delegated call with no tools that its own chat, the
    # Researcher and the Dataflow Builder ask for. package.draft.apply is the
    # ONE package-writing mutate contract (dev/89 commit 8): the runtime mints
    # the reviewed draft from the mode's JSON at the asking agent's
    # attachment, and Apply promotes the exact reviewed artifact digest. The
    # recommendation mode (package.recommend) answers the Dataflow Builder
    # from the existingPackages the runtime passes, and is listed before the
    # writing capabilities so reuse stays ahead of writing.
    BuiltinAgentSpec("agent.node-builder", "Node Builder", "node",
                     "Create a node, or rewrite a node's content, as a proposal you review. "
                     "On a connection it suggests what could go there. It installs or "
                     "writes the node packages your nodes need.",
                     "node_build_instruction.md",
                     ("node.build", "dataset.fetch.author", "node.content.generate",
                      "package.recommend", *_PACKAGE_WRITING),
                     ("authoring",),
                     # dev/67-6: node targets lift the dev/48 canvas-only
                     # limitation: the modify-existing posture attaches to
                     # the node it modifies. The connection target is why it
                     # reads ``connectionSide``: bound to one edge it knows
                     # which end is which, and the read composes only there.
                     targets=("canvas", "node", "connection"),
                     reads=("nodeIntent", "targetContext", "externalSelection", "connectionSide"),
                     # dev/114 (DEC-072): catalog.search — the ONLY way a
                     # data-loading node learns a real local path (rows carry
                     # the resolved path); the grounding gate refuses any
                     # other file the code opens. models.search does the same
                     # for a node that runs a model. dev/84: packages.catalog
                     # and packages.resolve ground the packages its chat
                     # names, and package.install proposes one for review.
                     # dev/89: package.draft.apply authorizes the mint of the
                     # draft its writing mode returns.
                     tools=("dataflow.read", "node.read", "node.create", "node.template.create",
                            "node.runtime.read", "node.content.write", "catalog.search",
                            "models.search", "packages.catalog", "packages.resolve",
                            "package.install", "package.draft.apply"),
                     # Its own content and package-writing modes, asked for by
                     # its chat: dev/89, no suitable template anywhere, so the
                     # package.create-or-extend intent goes to the writing
                     # capabilities. It recommends packages in its own chat.
                     delegates_to=(("agent.node-builder", ("node.content.generate", *_PACKAGE_WRITING)),
                                   ("agent.dataflow-planner", ("execution.followup.plan",)),
                                   # dev/67-4: checking a fact the node needs.
                                   ("agent.researcher", ("research.verify",)),
                                   # dev/86 (DEC-055): optional post-generation
                                   # semantic check — advisory, never approval.
                                   "agent.generated-content-evaluator",
                                   # dev/114 (DEC-072): source resolution for a
                                   # data-loading node — the tool-less child gets
                                   # the catalog as INPUT and its candidates are
                                   # runtime-minted onto the two-lane card.
                                   "agent.dataset-finder"),
                     # dev/126: a data-loading node's source resolution
                     # delegates dataset.discover from a SERVER path, with no
                     # model choice — the Dataset Finder is a hard dependency,
                     # not a preference.
                     requires_agents=("agent.dataset-finder",),
                     review_policy="review-before-apply",
                     modes=(BuiltinMode("node.content.generate", "new_content_prompt.md",
                                        ("dataflowContext", "nodeId", "subtask", "workflowGoal"),
                                        worked_examples=True),
                            BuiltinMode("package.recommend", "package_recommendation_instruction.md",
                                        ("mission", "targetContext", "existingPackages")),
                            *(BuiltinMode(capability, "package_build_instruction.md",
                                          ("packageIntent", "targetContext", "existingPackages"))
                              for capability in _PACKAGE_WRITING)),
                     variant_prompts=((AUTK_PROMPT_KEY, "new_content_autk_prompt.md"),),
                     worked_examples=True),
    # The second P5 composite (memo dev/50; spec dev/15 §3.4 + docs/06). Two-
    # lane discovery: catalog picks → reviewed dataset.install; external picks
    # → the DEC-047 user-mediated Node Builder handoff. Never authors fetch
    # code. Deviations recorded in the memo (canvas target added for mission-
    # first discovery; foreground-only; no auto-install).
    BuiltinAgentSpec("agent.dataset-finder", "Dataset Finder", "data",
                     "Discover and select datasets across connected data portals and the "
                     "Data Catalog; download portal picks into the Data Catalog as a "
                     "reviewed proposal. Never authors fetch code.",
                     "discovery_instruction.md",
                     ("dataset.discover", "dataset.select"), ("discovery", "selection"),
                     targets=("node", "canvas"),
                     reads=("mission", "nodeContext", "catalog"),
                     # The external lane used to dead-end: it could NAME a
                     # portal dataset and nothing could act on it, so the only
                     # move was the Node Builder handoff. The three discovery
                     # contracts make it actionable - roster, live search, and
                     # a reviewed download. node-builder stays in delegates_to
                     # because a source no provider covers is still real; it
                     # just stops being the only answer.
                     tools=("catalog.search", "discovery.sources", "discovery.search",
                            "discovery.acquire", "dataset.install", "dataflow.read"),
                     delegates_to=(("agent.node-builder", ("node.build", "dataset.fetch.author")),
                                   ("agent.dataflow-reader", ("workflow.suggest",)),
                                   ("agent.dataflow-planner", ("workflow.keyword.bind",)),
                                   ("agent.researcher", ("research.verify",))),
                     review_policy="review-before-apply",
                     node_requires=("data-loading",)),
    # The third P5 composite (memo dev/52; spec dev/15 §3.4 + dev/49 DR-1…5).
    # Plan → Revise → Solve → Run: additive graph-level plan proposals, the
    # persisted builder session, and the authenticated Solve batch (DEC-048).
    # Deviation recorded: the package recommendation step deferred (dev/16).
    BuiltinAgentSpec("agent.dataflow-builder", "Dataflow Builder", "canvas",
                     "Plan a connected dataflow from a goal as one reviewable proposal; "
                     "solve unresolved nodes through delegated specialists. Never mutates "
                     "without review.",
                     "orchestration_instruction.md",
                     ("dataflow.orchestrate",), ("orchestration",),
                     reads=("mission", "graphContext", "installedTemplates"),
                     # dev/95: node.create is the reviewed lane the delegated
                     # Researcher's note proposals mint on (grant-gated —
                     # nothing lands without the user's Apply). examples.read:
                     # any worked example, beside the ones a run is given.
                     tools=("dataflow.read", "dataflow.plan.write",
                            "node.runtime.read", "node.create", "examples.read"),
                     # dev/73: the Node Builder's node.content.generate is
                     # OFFERED in the delegation paragraph, the chat path for
                     # "change this node's content" (the runtime mints the review
                     # at that node's own agent; plans stay content-free).
                     # dev/84: the "Recommend packages" plan step is the Node
                     # Builder's package.recommend mode; dev/89: package-scale
                     # plan steps, one coherent new or extended multi-template
                     # package instead of repeated single-template rewrites,
                     # are its package-writing mode.
                     delegates_to=("agent.dataset-finder", "agent.node-builder",
                                   ("agent.dataflow-planner", (
                                       "workflow.plan.create", "execution.followup.plan",
                                       "workflow.plan.refresh", "workflow.coherence.validate")),
                                   ("agent.dataflow-reader", ("workflow.suggest", "dataflow.explain")),
                                   # dev/86 (DEC-055): optional post-generation
                                   # semantic check — advisory, never approval.
                                   "agent.generated-content-evaluator",
                                   # dev/95 (Follow-up D): research questions in
                                   # the DFB chat delegate research.notes.compose,
                                   # the Researcher's notes mode: runtime-gathered
                                   # search inputs, schema reply, reviewed note
                                   # sequence. A fact to check is its
                                   # research.verify mode. Never its chat.
                                   ("agent.researcher", ("research.notes.compose", "research.verify"))),
                     # dev/106: Solve/Validate hard-invoke node.content.generate,
                     # the Node Builder's content mode.
                     # dev/126: and resolution hard-invokes dataset.discover for
                     # a data-loading node, while every plan-created node is
                     # given a Node Builder at the user's Apply: server
                     # paths, none a model choice, so both are required
                     # (DEC-068's own criterion) instead of merely preferred.
                     # The install proposal for a required agent that the owner
                     # hit mid-conversation (memo dev/126 §0) cannot recur.
                     requires_agents=("agent.dataset-finder", "agent.node-builder"),
                     review_policy="review-before-apply",
                     # dev/115 (DEC-073): Solve is a detached background job.
                     execution="background",
                     worked_examples=True),
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
                     "evaluate_generated_content_prompt.md",
                     ("content.quality.evaluate",), ("validation",),
                     targets=("node", "canvas"),
                     reads=("nodeContext", "targetContext"),
                     tools=("node.read", "node.runtime.read", "dataflow.read"),
                     in_catalog=False),
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
        "capabilities": [_capability_entry(spec, c) for c in spec.capabilities],
        "prompts": {
            key: {"path": f"prompts/{filename}", "variables": []}
            for key, filename in spec.prompt_files().items()
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
        "runtime": {"execution": spec.execution, "reviewPolicy": spec.review_policy},
        "providerRequirements": {"capabilities": ["structured-output"]},
        "provenance": {"publisher": "curio", "license": "MIT", "trust": "built-in"},
    }
    # Only composites carry the key — the thirteen migrated manifests stay
    # byte-identical (memo dev/48 regression requirement).
    if spec.delegates_to:
        manifest["delegatesTo"] = [
            d if isinstance(d, str) else {"id": d[0], "capabilities": list(d[1])}
            for d in spec.delegates_to
        ]
    if spec.requires_agents:
        manifest["requiresAgents"] = list(spec.requires_agents)
    return manifest


def _capability_entry(spec: BuiltinAgentSpec, capability: str) -> dict:
    """A capability, with its mode's instruction, reads and settings when it has one."""
    entry: dict = {"id": capability, "contractVersion": "1"}
    mode = next((m for m in spec.modes if m.capability == capability), None)
    if mode is not None:
        entry["instruction"] = mode.capability
        entry["reads"] = list(mode.reads)
        entry["requiredConfig"] = list(mode.required_config)
    return entry


def list_builtin_manifests() -> list[AgentManifest]:
    """Validated manifests for every built-in, in roster order."""
    return [parse_agent_manifest(build_builtin_manifest(s), where=s.agent_id) for s in BUILTIN_AGENTS]


def _by_coord() -> dict[str, BuiltinAgentSpec]:
    return {f"{s.agent_id}@{BUILTIN_VERSION}": s for s in BUILTIN_AGENTS}


def get_builtin_spec(coord: str) -> BuiltinAgentSpec | None:
    """Resolve a ``<agentId>@<version>`` coordinate to its roster spec, or None."""
    return _by_coord().get(coord)


def gets_worked_examples(coord: str, capability: str | None = None) -> bool:
    """Whether a run of the built-in *coord* gets worked examples: in the mode
    of *capability* when it has one, else as the agent says. Any other
    definition gets none."""
    spec = _by_coord().get(coord)
    if spec is None:
        return False
    mode = next((m for m in spec.modes if m.capability == capability), None)
    return mode.worked_examples if mode is not None else spec.worked_examples


def internal_agent_ids() -> frozenset[str]:
    """The built-ins that run only as delegates (``in_catalog`` false)."""
    return frozenset(spec.agent_id for spec in BUILTIN_AGENTS if not spec.in_catalog)


def is_internal(coord: object) -> bool:
    """Whether *coord* (or a bare agent id) is an internal built-in. A
    definition of the same id at another version is the owner's own, and is not."""
    agent_id, _, version = str(coord or "").partition("@")
    return agent_id in internal_agent_ids() and version in ("", BUILTIN_VERSION)


def get_builtin_manifest(coord: str) -> AgentManifest | None:
    """Resolve a ``<agentId>@<version>`` coordinate to a built-in manifest, or None."""
    spec = _by_coord().get(coord)
    if spec is None:
        return None
    return parse_agent_manifest(build_builtin_manifest(spec), where=spec.agent_id)


def read_prompt_text(coord: str, name: str) -> str | None:
    """Read a built-in's prompt asset text from ``llm-prompts/``, or None.

    ``name`` is the manifest prompt key: ``"instruction"`` (the agent's task
    prompt), ``"system"`` (its preamble), or a mode's capability id.
    """
    spec = _by_coord().get(coord)
    if spec is None:
        return None
    filename = spec.prompt_files().get(name)
    if filename is None:
        return None
    return read_prompt_file(filename, wanted_by=f"built-in agent {coord}, prompt {name!r},")


def read_prompt_file(filename: str, *, wanted_by: str) -> str | None:
    """Read one file from ``llm-prompts/``, or None when it is missing.

    A missing file is logged: returning None silently would ship an agent
    with no system or task prompt and no symptom beyond worse answers, which
    is precisely what an sdist without ``utk_curio/llm-prompts/`` used to do.
    """
    path = PROMPT_SOURCE_DIR / filename
    if path.is_file():
        return path.read_text(encoding="utf-8")
    log.error(
        "%s reads %s but %s is missing, so it runs without it. If this is an "
        "installed Curio, the package is missing utk_curio/llm-prompts/ (see "
        "MANIFEST.in).",
        wanted_by, filename, path,
    )
    return None


def read_instruction_text(coord: str) -> str | None:
    """Read a built-in's instruction prompt text from ``llm-prompts/``, or None."""
    return read_prompt_text(coord, "instruction")
