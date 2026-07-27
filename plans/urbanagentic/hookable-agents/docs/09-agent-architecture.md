# Agent Architecture: Definition, Assignment & Orchestration

Two **independent** concerns. Changing one must not require changing the other.

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ (2) AGENT ASSIGNMENT  — application UI & interaction (framework-agnostic)  │
│     Catalog · palette attach · dock · chat · shared settings modal          │
│     configure · enable/disable · status · background execution             │
└───────────────▲────────────────────────────────────────────────────────────┘
                │ stable interface (run / stream / status / cancel)
┌───────────────┴──────────────────────────────────────────────────────────┐
│ (1) AGENT DEFINITION — how agents are implemented                          │
│     Framework abstraction  →  LangChain adapter (initial)                  │
│     tools · manifest-linked prompts · memory · execution lifecycle          │
└────────────────────────────────────────────────────────────────────────────┘
```

The UI talks to agents only through the stable interface, so the LangChain layer can
be replaced with another framework without touching any screen.

## (1) Agent Definition — LangChain (initial implementation)

Every agent — the master **Dataflow Builder** orchestrator and each specialized agent —
is instantiated through **LangChain** and exposes the same interface:

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

- **Framework behind an abstraction.** A thin `AgentRuntime` interface wraps LangChain
  (chains, tools, memory, agent executors). Only the adapter imports LangChain.
- **Independently executable.** Each agent runs on its own given a context; it does not
  depend on the orchestrator being present.
- **Composable.** Agents expose the same interface so the orchestrator can treat them
  uniformly and future multi-agent workflows can nest them.
- **Swappable.** Replacing LangChain means writing a new adapter to the same interface.
- **Exact artifact resolution.** Runtime construction receives a validated immutable
  coordinate `(publisher namespace, agent ID, exact version, digest)`, never a mutable
  catalog name or browser-supplied path.
- **Provider privacy boundary.** Runtime receives an authorized provider-profile reference,
  not a secret. Local-to-remote fallback is never implicit, and minimum context is checked
  against data-egress policy before invocation.
- **Recoverable, not replayed.** Executions persist ordered events and a lease/heartbeat.
  Expired nonterminal work becomes `interrupted`; Retry creates a linked new execution and
  never automatically repeats provider or tool side effects.
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
   ├─ spawn:  instantiate LangChain agents
   ├─ delegate ──► Dataset Finder ─┐
   │             ► Node Builder     │  run / stream / status
   │             ► Connection Builder
   │             ► Package Recommendation
   │             ► Validation
   │             ► Optimization
   │             ► Node Explainer ──┘
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
4. Instantiate the required LangChain agents.
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
- **Background execution** — long-running agents keep running; status persists in the
  dock and the orchestrator's chat.

This layer never references LangChain; it only uses the stable agent interface.

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
and any approved evaluator. It does not silently substitute `agent.generated-content-evaluator`
while that package is blocked, and an evaluation cannot auto-release, activate, install, migrate,
or publish. Prompt Editor is writable only for an owned imported definition; release creates a new
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

Node UI has no built-in `Explanation` tab, explanation cache/state, or direct raw prompt/provider
path. `agent.node-explainer` must be explicitly installed in the project and attached; its dock tile
opens unified chat for requests, responses, history, policy, and provenance. A discoverability
affordance may enter this standard flow but cannot recreate a node panel. The separate
`agent.dataflow-explainer` remains a canvas/full-flow behavior.

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
- **Framework adapters** — LangChain today; a different runtime later via a new adapter
  to the same interface.
