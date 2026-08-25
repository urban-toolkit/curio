# Agent Architecture: Definition, Assignment & Orchestration

Two **independent** concerns. Changing one must not require changing the other.

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ (2) AGENT ASSIGNMENT  — application UI & interaction (framework-agnostic)  │
│     Catalog · palette attach · dock · chat · shared settings modal          │
│     configure · enable/disable · status · streamed execution                │
└───────────────▲────────────────────────────────────────────────────────────┘
                │ stable interface (run / stream / status / cancel)
┌───────────────┴──────────────────────────────────────────────────────────┐
│ (1) AGENT DEFINITION — how agents are implemented                          │
│     AgentRuntime/provider ports  →  direct-code orchestration               │
│     tools · manifest-linked prompts · memory · execution lifecycle          │
└────────────────────────────────────────────────────────────────────────────┘
```

The UI talks to agents only through the stable interface. The current implementation uses a direct
provider port and direct-code orchestration; a future framework adapter can be added behind the same
boundary without changing screens.

## (1) Agent Definition — provider-port runtime

Every agent — the master **Dataflow Builder** orchestrator and each specialized agent —
runs through the agent-owned runtime/provider boundary and exposes the same interface:

```text
Agent
  id, type, version
  interface:
    run(context) -> result          # one-shot
    stream(context) -> events        # incremental progress
    status() -> queued|running|review_required|interrupted|done|error
    cancel()
  definition:
    requestedTools[]   # typed tool requirements; execution policy grants access
    capabilities[]     # semantic behavior contracts implemented by this agent
    delegatesTo[]      # explicit preferred/required agent IDs it may invoke
    memory             # session / conversation memory
    policyRequirements # immutable supported/default requirements, not user policy
    lifecycle          # instantiate -> plan -> act -> observe -> finish
```

Design rules:

- **Runtime behind an abstraction.** The agent-owned runtime resolves providers, prompts, typed
  content, tool grants, reviews, and delegation behind stable ports. No UI/domain module imports a
  provider SDK or orchestration framework.
- **Independently executable.** Each agent runs on its own given a context; it does not
  depend on the orchestrator being present.
- **Composable.** Agents expose the same interface so the orchestrator can treat them
  uniformly and future multi-agent workflows can nest them.
- **Swappable.** A future framework integration belongs behind the existing provider/delegation
  seams. `DEC-048` retired the planned LangChain adapter; `DEC-021` background execution is its
  explicit re-open condition.
- **Exact artifact resolution.** Runtime construction receives a validated immutable
  coordinate `(publisher namespace, agent ID, exact version, digest)`, never a mutable
  catalog name or browser-supplied path.
- **Provider privacy boundary.** Runtime receives an authorized provider-profile reference,
  not a secret. Local-to-remote fallback is never implicit, and minimum context is checked
  against data-egress policy before invocation.
- **Recoverable, not replayed.** Current streamed foreground runs persist execution records and
  cancellation state and never silently replay provider/tool work. Durable leases, startup
  reconciliation, and multi-instance scheduling remain gated by `DEC-021`/`OQ-009`.
- **Server-authoritative effective policy.** Runtime receives one authorized snapshot derived
  from deployment/account limits, project-template defaults, attachment overrides, and an atomic
  execution reservation. Manifest requirements and browser fields cannot relax inherited cost,
  quota, resource, egress, context, or tool boundaries.
- **Immutable prompt release.** Runtime loads only prompt assets from one exact validated artifact.
  Prompt editing happens in a separate draft and becomes runnable only after validation,
  evaluation as required, audit, and release of a new immutable coordinate.

The definition's `id`/version/digest does not make an attachment versioned. Lifecycle aggregates
remain distinct:

```text
immutable AgentDefinitionArtifact
  ├─ explicit Import ─► private AccountImportedAgent ─► explicit user Publish ─► Global Catalog
  └─ Global Catalog or My Imports ─► explicit Install in project ─► ProjectAgentTemplate
                                                               └─ explicit Attach ─► AttachedAgentInstance
```

Only an owned validated `AccountImportedAgent` is user-publishable. Import never installs;
Publish never installs; project templates and attached instances never expose Publish/Share.
`AttachedAgentInstance` uses `attachmentId` plus a concurrency `revision`, references its project
template/target, and has no SemVer or release/catalog lifecycle. An execution privately pins the
resolved definition, settings, prompt, provider, and policy revisions required for reproducibility.

## Master orchestration — the Dataflow Builder

The Dataflow Builder is the **master orchestration agent**. It does not directly
recommend isolated datasets/nodes/packages; it coordinates specialized agents that do.

```text
User intent
   │
   ▼
Dataflow Builder (orchestrator)
   ├─ plan: decompose intent into subtasks
   ├─ select: which specialized agents are needed
   ├─ spawn:  resolve installed specialist definitions
   ├─ delegate ──► Dataset Finder ─┐
   │             ► Node Builder     │  run / stream / status
   │             ► Connection Builder
   │             ► Package Recommendation
   │             ► Generated Content Evaluator   (DEC-055/056: the Validation
   │             ► Node Explainer ──┘             family; Optimization descoped)
   ├─ merge: combine intermediate outputs
   ├─ evaluate: coherence & completeness
   ├─ refine: re-plan / re-delegate if needed
   ▼
Complete, executable dataflow  +  recommendations & explanations
```

### Orchestration flow

1. Analyze the user's objective.
2. Generate an execution plan.
3. Determine which specialized agents are required.
4. Resolve the required installed specialist definitions and runtime grants.
5. Delegate work to each specialized agent.
6. Merge intermediate outputs.
7. Evaluate completeness and coherence.
8. Refine the workflow if necessary.
9. Produce the final executable dataflow.
10. Present recommendations and explanations to the user.

Steps 5–8 loop until evaluation passes or the user stops. Graph-mutating steps are
gated by explicit confirmation (review-before-apply).

## (2) Agent Assignment — the UI

Assignment is purely the application's interaction model and reuses the existing
concepts (see `03-ui-decisions`, `04-interaction-states`, `08-unified-agent-chat`):

- **Discover/import/install** — use distinct Global Catalog, My Imports, and Installed in this
  project drawer scopes. Import creates only a private definition; explicit Install in project
  creates the active project's template/palette row.
- **Assign / attach** — drag a project-installed AGENTS palette row to a compatible node or canvas;
  it creates a private instance and floating dock tile. Switching project replaces the palette.
- **Conversationally refine** — use the unified chat drawer for intent, quick replies,
  suggestions, reviews, and execution.
- **Configure policy and prompts** — use one shared settings modal with Cost, Quotas, Resource
  policies, Prompt quality, Prompt editor, and Prompt audit screens. Account scope sets policy;
  owned imported definitions own prompt governance; project templates own project policy defaults;
  chat `Attachment settings` only tightens them and shows prompt evidence read-only.
- **Enable / disable** — toggle an attached agent without detaching it.
- **Visualize active agents** — dock tiles; the orchestrator lists spawned agents.
- **Execution status** — per-agent status (queued / running / review required /
  interrupted / done / cancelled / error) via dock running dots and status chips.
- **Streamed foreground execution** — progress and cancellation stay visible in the dock/chat.
  Durable background/multi-instance execution is not claimed until `DEC-021`/`OQ-009` is resolved.

This layer never references provider SDKs or orchestration frameworks; it only uses the stable agent interface.

## Policy And Prompt Governance Boundary

```text
drawer Agent settings ───────► account policy/defaults ──────────┐
definition settingsDefaults ─► project-template profile ─────────┤ server computes effective policy
chat Attachment settings ───► tightening instance override ──────┤
deployment hard limits ──────────────────────────────────────────┘
                                                       │
                                                       ▼
                                            atomic execution reservation

owned imported artifact ─► private prompt draft ─► validate/evaluate/audit ─► new private release
```

Cost policy governs monetary budgets and alerts; quota policy governs count/token/tool/
concurrency windows; resource policy governs authorized provider/model/locality, time/context/
output bounds, egress, network/tools, and supported local resources. The backend owns policy
precedence, usage reservations, conflict detection, and enforcement. The UI receives effective
values, inherited sources, current usage, server capabilities, and revision tokens; it never
receives provider secrets.

Each exact definition's immutable, schema-valid `settingsDefaults` only seeds project installation.
Every project install materializes an independent project-private revisioned profile after clamping
current account/deployment ceilings; the same definition in two projects has two profiles. `Reset
to agent default` changes only the selected project template and reuses the reviewed seed under
ceilings current at reset time. Attached-instance overrides may only tighten it.

Prompt Quality pins the artifact or draft revision, suite version, thresholds, provider profile,
and any approved evaluator. The DEC-055 `agent.generated-content-evaluator` is shipped but remains
an advisory report-only agent, not a silently substituted platform release judge; an evaluation
cannot auto-release, activate, install, migrate, or publish. Prompt Editor is writable only for an owned imported definition; release creates a new
private definition version/digest and does not retarget project templates or attachments. Project
and attachment prompt screens are read-only provenance/evidence. Prompt Audit pins versioned privacy/security/compliance
rules, records audit findings, and appends a governance stream distinct from the session transcript
and redacted according to actor authorization.

The modal is one generic agent-owned UI, not a LangChain surface and not six per-agent
implementations. The shared result has no entry point. Server-returned capabilities decide
edit/evaluate/audit access, and dialog focus, keyboard navigation, dirty-state guards, announcements,
zoom/reflow, and focus restoration meet the same WCAG 2.2 AA requirements as the chat.

## Sharing Privacy Boundary

When a flow/Trill is shared, agent-private data is not exposed in the shared result. Datasets, node
packages/code, definitions/imports/templates/attachments, agent flows, settings, prompts,
evaluation/audit/history, providers/tools, usage/cost, private IDs, and executable controls never
appear in the public result view.

## Node Explanation Ownership

Per `DEC-041`, Node UI permanently retains the built-in `Explanation` tab, its cache/state, and its
direct caller. `agent.node-explainer` is a separate coexisting path: it must be explicitly installed
in the project and attached, and its dock tile opens unified chat for requests, responses, history,
policy, and provenance. Neither surface implicitly falls back to or double-runs the other. The
separate `agent.dataflow-explainer` remains a canvas/full-flow behavior.

## Extensibility

- **Capability registry** — semantic behaviors such as `node.explain` and
  `workflow.plan.create` have typed/versioned contracts. Prompt filenames are never
  capability IDs.
- **Agent registry** — specialized and prompt-backed agents are registered by manifest;
  the orchestrator discovers implementations by required capability, contract version,
  target, provider/tools, trust, project installation, and version policy.
  New agents plug in without UI changes.
- **Authorization registry** — manifest capabilities and requested tools are untrusted
  declarations, not grants. Server context/tool policy and explicit user grants remain
  authoritative for every execution.
- **Prompt asset registry** — backend infrastructure validates and loads package-local prompt
  links for installed agent versions. Prompt filenames are never invoked directly by UI or
  orchestration code; see `10-prompt-architecture`.
- **Policy registry/services** — typed cost, quota, and resource policies are composed and
  enforced outside the manifest and model, with immutable execution snapshots and atomic usage
  accounting.
- **Prompt governance services** — drafts, versioned quality evaluations, versioned compliance
  audits/findings, releases, and append-only audit events use stable contracts independent of the
  runtime framework.
- **Runtime adapters** — direct provider/delegation ports today; a future framework adapter may be
  added at the `DEC-021` background-execution revisit without changing the UI contract.
