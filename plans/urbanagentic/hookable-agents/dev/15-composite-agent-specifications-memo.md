# Implementation Memo: Composite Agent Specifications (Dataflow Builder, Dataset Finder, Node Builder)

Status update (2026-08-24): **implemented**. Node Builder shipped in dev/48, Dataset Finder in dev/50, and Dataflow Builder in dev/52, with later orchestration refinements through dev/67 and dev/95. The current product roster is 21 built-ins; this memo's future-tense and 18-agent inventory describe its July specification baseline.

This memo closes hardening item **H-5** (`14-plan-hardening-and-open-decisions-memo.md`). It specifies
the three net-new **composite** agents that Phase 5 ships but that have no prompt-migration source and no
manifest: `agent.dataflow-builder`, `agent.dataset-finder`, and `agent.node-builder`. It uses the
canonical manifest schema (`docs/11-agent-manifest-and-product-model.md`), the current lifecycle
(`12-agent-template-installation-attachment-sharing-lifecycle-memo.md`, `DEC-029`–`DEC-033`), the
capability model (`08-semantic-agent-capabilities-memo.md`), and the sharing scope of memo `14`
(D-0 = B). Where this memo and an image differ, this specification is authoritative.

## 1. Problem Statement

At this memo's baseline the planned product roster was **eighteen agents**: fourteen prompt-backed
identities (`dev/06`), the three composites specified here, and `agent.package-recommendation`
(`dev/16`). Thirteen prompt-backed identities are migrated one-to-one from source files; the evaluator
was later authored under `DEC-055`. The current roster is 21 after Node Researcher, Package Builder,
and Researcher were added. At the baseline, the three composites were **net-new orchestrations over
migrated capabilities** and were under-specified:

- `docs/11` profile-family tables and the concept screens (`png-concepts/01`, `10`, `03`, `05`) show the
  three composites, but **no manifest, capability contract, `delegatesTo` composition, or prompt
  provenance exists** for any of them (`dev/06:51-57`; `dev/14:110-120`).
- Phase 5 (`dev/05` Step 5) leads with "Implement Dataset Finder, Node Explainer, and Dataflow Builder
  manifests/delegates/tools" and "Add Node Builder handoff" — it cannot start without these specs.
- A reader could wrongly assume a migrated prompt backs a composite, or that a composite may auto-install
  or auto-run the specialists it delegates to.

**Expected behavior.** Each composite has a complete camelCase `manifest.json`, a declared semantic
capability set distinct from the capabilities it delegates to, an explicit `delegatesTo` list of
already-specified agents, net-new prompt provenance, a compatible-target/hook definition, a reviewed
settings-default profile family, and orchestration invariants that forbid silent import/install/attach/
run and any new sharing surface.

## 2. Scope

**Included.** Manifest specifications and capability contracts for `agent.dataflow-builder`,
`agent.dataset-finder`, and `agent.node-builder`; their `delegatesTo` composition over the fourteen
migrated capabilities and each other; net-new prompt provenance; compatible targets/hooks; settings
profile-family assignment; provider/tool requirements; orchestration/handoff invariants (no auto-install,
reviewed `Install in project`, two-lane Dataset Finder handoff, review-before-apply mutations); tests,
acceptance criteria, and traceability.

**Out of scope.** Runtime package creation and application code; the fourteen prompt-migration packages
(`dev/06`); the provider-credential migration (`dev/14` H-4); authoring the missing evaluator prompt
(`OQ-007`); final retention durations (`OQ-008`); any new sharing mechanic (D-0 = B). **Also flagged:** the concept
screens reference three further product agents — Package Recommendation, Validation, and Optimization —
that are neither in the fourteen-agent migration roster nor among these three composites (tracked as
OQ-011). **Package Recommendation is now specified in `16-agent-node-package-capabilities-memo.md`**
(identify/suggest/reviewed-install of node packages); Validation and Optimization ~~remain unspecified and
must be specified later or descoped~~ *(since resolved by `DEC-056`, dev/85: Validation = a category
view over the shipped family, Optimization = descoped demand-driven)*. This memo does not define them.

## 3. Recommended Implementation Approach

Each composite ships as a built-in `AgentDefinitionArtifact` under the `agents/` artifact root with its
own `manifest.json` and `prompts/` directory, exactly like the migrated packages. The difference is
provenance: a composite's coordinating prompt is **net-new** (no migrated source), and its behavior is
realized primarily through `delegatesTo` capability resolution rather than a single prompt.

Two invariants govern all three:

1. **Capabilities a composite *declares* are distinct from the capabilities it *delegates to*.** The
   declared capability is what the composite is discovered/attached/substituted by; `delegatesTo`
   expresses preferred implementations it may call, and grants nothing (`08`, `docs/11:173`). Resolution
   is restricted to `ProjectAgentTemplate` records installed in the **current project**; a visible global
   definition is never executable merely because it matches (`08:13`, `dev/03:347`).
2. **No lifecycle command auto-chains.** Attaching or running a composite grants no context/provider/
   tool/target/mutation permission; each delegated execution independently re-authorizes every boundary.
   A missing specialist yields a **reviewed `Install in project` proposal**, never a silent import/
   install/attach/run/publish (`dev/03:347`, `REQ-ORCH-001`).

### 3.1 Capability IDs introduced by this memo

These are net-new semantic capability IDs (contract version `1`). Per `08`/`docs/11:334`, capability IDs
contain no `_prompt`, `.txt`, path separators, or prompt filenames, and are independent of prompt assets.

| Capability ID | Declared by | Contract summary (inputs → outputs) |
| --- | --- | --- |
| `dataflow.orchestrate` | `agent.dataflow-builder` | mission + canvas/graph context → a reviewed plan, delegated child-execution requests, and an assembled executable dataflow proposal |
| `dataset.discover` | `agent.dataset-finder` | mission + node/catalog/geography/lineage context → ranked external + catalog dataset candidates (two lanes) |
| `dataset.select` | `agent.dataset-finder` | a confirmed candidate → an external Node Builder handoff request **or** a catalog dataset-only install request |
| `node.build` | `agent.node-builder` | node intent + canvas/connection context → a reviewable computation/transform/visualization/HTML node proposal |
| `dataset.fetch.author` | `agent.node-builder` | an external dataset selection → a reviewable executable fetch-node proposal (request code, params, credential-profile requirement, parsing, error handling, output format) |

The five capabilities each need an `inputSchema`/`outputSchema` pair under the agent's `schemas/`
directory; the summaries above are the contract intent. `dataset.discover`/`dataset.select` reuse the
IDs already shown in the `docs/11:290-323` Dataset Finder manifest.

### 3.2 Delegation graph (composition over already-specified agents)

Every `delegatesTo` entry below is an agent specified elsewhere in the plan (one of the fourteen migrated
identities, another composite, or `agent.package-recommendation` specified in `dev/16`). Grounding:
`docs/10:76-82`, `docs/02:64-83`, `docs/09:86-127`, `docs/06:26-33`, `docs/11:290-323`.

```text
agent.dataflow-builder  (declares dataflow.orchestrate)
  delegatesTo →
    agent.dataset-finder          (dataset.discover / dataset.select)
    agent.node-builder            (node.build / dataset.fetch.author)
    agent.connection-builder      (connection.propose)
    agent.dataflow-task-planner   (workflow.plan.create)
    agent.execution-subtask-planner (execution.followup.plan)
    agent.task-refresh-agent      (workflow.plan.refresh)
    agent.workflow-suggester      (workflow.suggest)
    agent.plan-coherence-validator (workflow.coherence.validate)
    agent.dataflow-explainer      (dataflow.explain)
    agent.package-recommendation  (package.recommend)   # the "Recommend packages" plan step — see dev/16
    # DEC-056 resolution: Validation is a category view over the shipped family,
    # not a separate agent; Optimization is descoped demand-driven. Neither is
    # assumed as an installed delegate.

agent.dataset-finder  (declares dataset.discover, dataset.select)
  delegatesTo →
    agent.node-builder            (dataset.fetch.author)   # external-source handoff
    agent.workflow-suggester      (workflow.suggest)        # discovery support
    agent.keyword-binding-agent   (workflow.keyword.bind)   # discovery support

agent.node-builder  (declares node.build, dataset.fetch.author)
  delegatesTo →
    agent.node-content-builder    (node.content.generate)
    agent.execution-subtask-planner (execution.followup.plan)
    agent.package-recommendation  (package.identify)   # a built node's required packages — see dev/16
```

### 3.3 Prompt provenance (all net-new)

None of the three has a migrated prompt. Each links a validated system preamble plus a net-new
instruction asset authored specifically for the composite, stored inside the composite's own artifact
directory and digest-referenced by the manifest.

| Agent | Provenance | Prompt assets |
| --- | --- | --- |
| `agent.dataflow-builder` | net-new orchestration prompt | `prompts/default_preamble.txt`, `prompts/orchestration_instruction.txt` |
| `agent.dataset-finder` | net-new discovery/selection prompt | `prompts/default_preamble.txt`, `prompts/discovery_instruction.txt` |
| `agent.node-builder` | net-new node-authoring prompt | `prompts/default_preamble.txt`, `prompts/node_build_instruction.txt` |

Because these are built-in-trust seeds, the net-new prompt bytes are authored as part of building the
built-in package (not through a user `PromptAuthoringWorkspace`), but they are subject to the same
manifest validation, variable/schema checks, and pre-release evaluation/audit as any package.

### 3.4 Manifests

#### `agent.dataflow-builder`

```json
{
  "$schema": "../../docs/schemas/agent-package.v1.json",
  "id": "agent.dataflow-builder",
  "name": "Dataflow Builder",
  "category": "canvas",
  "version": "1.0.0",
  "purpose": "Master orchestrator: interpret intent, decompose into subtasks, coordinate specialized agents, evaluate progress, and assemble a complete executable dataflow.",
  "roles": ["orchestration"],
  "capabilities": [{ "id": "dataflow.orchestrate", "contractVersion": "1" }],
  "delegatesTo": [
    "agent.dataset-finder",
    "agent.node-builder",
    "agent.connection-builder",
    "agent.dataflow-task-planner",
    "agent.execution-subtask-planner",
    "agent.task-refresh-agent",
    "agent.workflow-suggester",
    "agent.plan-coherence-validator",
    "agent.dataflow-explainer",
    "agent.package-recommendation"
  ],
  "prompts": {
    "system": { "path": "prompts/default_preamble.txt", "sha256": "<sha256>", "variables": [] },
    "instruction": { "path": "prompts/orchestration_instruction.txt", "sha256": "<sha256>", "variables": ["mission", "graphContext"] }
  },
  "contracts": {
    "inputSchema": "schemas/input.schema.json",
    "outputSchema": "schemas/output.schema.json"
  },
  "compatibleTargets": [{ "kind": "canvas", "requires": [] }],
  "inputs": { "reads": ["mission", "graphContext", "installedTemplates"], "requiredConfig": [] },
  "outputs": ["dataflowPlan", "delegatedExecutionRequests", "installProposals"],
  "configuration": {
    "options": ["maxParallelChildren", "tokenBudget", "autoEvaluate"],
    "defaults": { "maxParallelChildren": 3, "autoEvaluate": true }
  },
  "runtime": { "execution": "foreground", "reviewPolicy": "review-before-apply" },
  "providerRequirements": { "capabilities": ["structured-output"] },
  "tools": [],
  "settingsDefaults": {
    "profileId": "orchestration-mutation",
    "profileVersion": "1",
    "suggestions": {
      "quota": { "maxConcurrentExecutions": 1 },
      "resource": { "resourceClass": "standard", "network": "provider-and-authorized-tools-only" },
      "promptQuality": { "staticChecksAfterEdit": true, "requiredBeforeRelease": true }
    }
  },
  "provenance": { "publisher": "curio", "license": "MIT", "trust": "built-in" }
}
```

Orchestration invariants: the orchestrator may plan and evaluate without confirmation, but **project
install and every graph/dataset mutation are reviewed proposals** (`dev/03:347`). Child executions are
linked by `parentExecutionId`; parent/child work shares one aggregate reservation while each delegated
agent keeps its own tighter policy (`dev/03:277`). It resolves only active-project templates and never
uses another project's template (`REQ-ORCH-001`).

#### `agent.dataset-finder`

```json
{
  "$schema": "../../docs/schemas/agent-package.v1.json",
  "id": "agent.dataset-finder",
  "name": "Dataset Finder",
  "category": "data",
  "version": "1.0.0",
  "purpose": "Discover and select relevant datasets across external sources and the Data Catalog; hand external picks to Node Builder and route catalog picks to the dataset-only install flow. Never authors fetch code.",
  "roles": ["discovery", "selection"],
  "capabilities": [
    { "id": "dataset.discover", "contractVersion": "1" },
    { "id": "dataset.select", "contractVersion": "1" }
  ],
  "delegatesTo": ["agent.node-builder", "agent.workflow-suggester", "agent.keyword-binding-agent"],
  "prompts": {
    "system": { "path": "prompts/default_preamble.txt", "sha256": "<sha256>", "variables": [] },
    "instruction": { "path": "prompts/discovery_instruction.txt", "sha256": "<sha256>", "variables": ["mission", "nodeContext", "catalog", "geography", "lineage"] }
  },
  "contracts": {
    "inputSchema": "schemas/input.schema.json",
    "outputSchema": "schemas/output.schema.json"
  },
  "compatibleTargets": [{ "kind": "node", "requires": ["data-loading"] }],
  "inputs": {
    "reads": ["mission", "nodeContext", "catalog", "geography", "lineage"],
    "requiredConfig": ["sourceScope"]
  },
  "outputs": ["externalDatasetSelections", "catalogDatasetInstallRequests"],
  "configuration": {
    "options": ["sourceScope", "maxSources", "tokenBudget"],
    "defaults": { "sourceScope": "all" }
  },
  "runtime": { "execution": "background", "reviewPolicy": "review-before-apply" },
  "providerRequirements": { "capabilities": ["structured-output"] },
  "tools": [{ "id": "catalog.search", "required": false }],
  "settingsDefaults": {
    "profileId": "planning-analysis",
    "profileVersion": "1",
    "suggestions": {
      "quota": { "maxConcurrentExecutions": 1 },
      "resource": { "resourceClass": "standard", "network": "provider-and-authorized-tools-only" },
      "promptQuality": { "staticChecksAfterEdit": true, "requiredBeforeRelease": true }
    }
  },
  "provenance": { "publisher": "curio", "license": "MIT", "trust": "built-in" }
}
```

**Two-lane contract** (`docs/06:26-33`): `dataset.discover` returns candidates in two lanes and
`dataset.select` produces the confirmed handoff per lane:

| Lane | Candidate type | Confirmed handoff (`dataset.select` output) |
| --- | --- | --- |
| **External sources** | APIs, endpoints, portals, documents, or databases not represented by a reusable catalog dataset | A reviewed `dataset.fetch.author` request to **Node Builder** (`externalDatasetSelections`), which owns fetch code/params/credential-profile requirement/parsing/errors/output. |
| **From your Data Catalog** | Reusable datasets already visible through the existing Data Catalog | The existing dataset-only install/select flow (`catalogDatasetInstallRequests`); the catalog dataset may auto-install when required and authorized. **This never imports or installs an agent.** |

Finder rows are informational and multi-selectable with no bespoke per-row buttons; a candidate may show
a permission/provider-profile/credential-profile requirement without exposing a secret; agent/tool
content is untrusted and unsafe schemes/active HTML/scripts are rejected (`docs/06:35-61`).

#### `agent.node-builder`

```json
{
  "$schema": "../../docs/schemas/agent-package.v1.json",
  "id": "agent.node-builder",
  "name": "Node Builder",
  "category": "node",
  "version": "1.0.0",
  "purpose": "Create computation, transform, visualization, or HTML nodes — including the executable dataset-fetch node for an external source selected in Dataset Finder — as reviewable proposals.",
  "roles": ["authoring"],
  "capabilities": [
    { "id": "node.build", "contractVersion": "1" },
    { "id": "dataset.fetch.author", "contractVersion": "1" }
  ],
  "delegatesTo": ["agent.node-content-builder", "agent.execution-subtask-planner", "agent.package-recommendation"],
  "prompts": {
    "system": { "path": "prompts/default_preamble.txt", "sha256": "<sha256>", "variables": [] },
    "instruction": { "path": "prompts/node_build_instruction.txt", "sha256": "<sha256>", "variables": ["nodeIntent", "targetContext", "externalSelection"] }
  },
  "contracts": {
    "inputSchema": "schemas/input.schema.json",
    "outputSchema": "schemas/output.schema.json"
  },
  "compatibleTargets": [
    { "kind": "canvas", "requires": [] },
    { "kind": "connection", "requires": [] }
  ],
  "inputs": { "reads": ["nodeIntent", "targetContext", "externalSelection"], "requiredConfig": [] },
  "outputs": ["nodeProposal", "fetchNodeProposal"],
  "configuration": {
    "options": ["nodeKinds", "tokenBudget"],
    "defaults": { "nodeKinds": ["computation", "transform", "visualization", "html", "data-fetch"] }
  },
  "runtime": { "execution": "foreground", "reviewPolicy": "review-before-apply" },
  "providerRequirements": { "capabilities": ["structured-output", "code-generation"] },
  "tools": [],
  "settingsDefaults": {
    "profileId": "mutation-proposal",
    "profileVersion": "1",
    "suggestions": {
      "quota": { "maxConcurrentExecutions": 1 },
      "resource": { "resourceClass": "standard", "network": "provider-and-authorized-tools-only" },
      "promptQuality": { "staticChecksAfterEdit": true, "requiredBeforeRelease": true }
    }
  },
  "provenance": { "publisher": "curio", "license": "MIT", "trust": "built-in" }
}
```

Node Builder returns a **reviewable node/fetch-node preview before any graph mutation** (`docs/06:65-74`).
Its authored external node is provenance-labeled `EXTERNAL · Node Builder` in the DATA palette, distinct
from an `IMPORTED · Data Catalog` auto-installed dataset (`docs/05-png-concepts.md:47`).

## 4. Data and State Handling

- **Source of truth.** Each composite is an immutable `AgentDefinitionArtifact`
  `{publisherNamespace, agentId, exactVersion, artifactDigest}`. Import → `AccountImportedAgent`; Install →
  `ProjectAgentTemplate` + project-only defaults; Attach → project-private `AttachedAgentInstance`
  (`attachmentId` + concurrency `revision`, no SemVer/publication). Executions pin resolved definition/
  prompt/settings/attachment/provider/effective-policy revisions (`dev/06:63`).
- **Delegated executions.** A composite run spawns child executions linked by `parentExecutionId`. Each
  child resolves and pins its own definition and settings independently; the parent never mutates or
  overrides a child's policy. Capability resolution reads only current-project templates.
- **Missing specialist.** If a required delegate is not an installed project template, the composite
  emits a reviewed `Install in project` proposal for a definition already visible to the actor; it never
  auto-imports/installs/attaches/runs (`dev/03:347`, `REQ-ORCH-001`).
- **Loading/empty/error/success.** The attached-agent chat shows per-delegate status (queued / running /
  interrupted / done); a partial orchestrator failure preserves successful child results, identifies
  failed children, and offers targeted retry (`dev/03:652`). `Interrupted` never resumes side effects in
  place; retry creates a new linked execution (`dev/05:375`).
- **No stale/duplicated state.** Project switching clears delegated child state, proposals, and selection
  before another project renders. Composite output surfaced through Curio's existing flow-sharing carries
  **no agent-private data** (definitions, prompts, provider/tool detail, private IDs) — D-0 = B.

## 5. UI and UX Requirements

- **Hooks/targets.** Dataflow Builder attaches at the **canvas** level (orange canvas hook boundary,
  `docs/02:64-83`); Dataset Finder attaches to a compatible **Data Load node** (green node hook,
  `docs/02:27-41`); Node Builder attaches to the **canvas or a selected connection**.
- **Palette.** All three appear in the Global Catalog / My Imports with readable metadata and, once
  installed, as fully draggable action-free rows in the active project's AGENTS palette.
- **Orchestration UI.** Dataflow Builder's chat lists each delegated specialist with live status and
  surfaces `Install in project` and graph-mutation actions as **reviewed proposals** naming the selected
  project and requested context/tool/provider needs — approval installs only that project template and
  does not import/attach/run/publish/grant (`dev/03:601-602`).
- **Two-lane Finder UI.** Dataset Finder shows External sources and From your Data Catalog lanes with
  per-row badges and install-state chips; rows are multi-selectable with no per-row buttons; confirmation
  routes external picks to a Node Builder handoff card and catalog picks to the existing install flow.
- **Node Builder review.** Node/fetch-node proposals render as a reviewable preview (code, provider/
  credential-profile requirement, request params, parsing/error/output checklist, data sample; secrets
  never shown) added by sending a suggested prompt — no bespoke card button (`docs/05-png-concepts.md:46`).
- **No new sharing UI, no version/publish/share action** on templates/instances (D-0 = B).
- **Accessibility.** Delegate-status lists, proposal dialogs, and lane selection expose semantic labels,
  focus management, non-color state, and screen-reader-friendly announcements per WCAG 2.2 AA.

## 6. Edge Cases

- A composite is attached but a delegated specialist is uninstalled mid-run → reviewed `Install in
  project` proposal, not silent install; the in-flight plan pauses that branch.
- Capability resolves to multiple installed templates → deterministic selection by contract/target/
  provider/trust/source policy; ambiguity surfaces for review, never a silent pick (`08` §6).
- `delegatesTo` names an agent not installed in the project → treated as missing specialist, not an error.
- A composite delegates to a composite (Dataflow Builder → Dataset Finder → Node Builder) → each level
  re-authorizes independently; no transitive permission inheritance; cycle detection prevents a delegation
  loop.
- Dataset Finder external pick with no reusable catalog equivalent → single Node Builder handoff, never a
  catalog install request; catalog pick → dataset-only install, never an agent install.
- Node Builder produces code embedding a secret/private URL/hostile payload → rejected by review-before-
  apply output validation; secrets never rendered.
- Provider lacks `code-generation` (Node Builder) or `structured-output` → admission fails closed with an
  actionable diagnostic; no partial node is written.
- Orchestrator token/quota budget exhausted mid-plan → stable `429`/`retryAfter`; completed children are
  preserved and the plan is resumable as new linked executions.
- Two tabs edit the same attachment → optimistic `revision` conflict preserves intent without creating an
  attachment "version."
- A composite tries to Publish/Share a template/instance, or surface agent-private data in a share →
  rejected (imported-only Publish; D-0 = B no-leak guard).

## 7. Testing Strategy

- **Manifest fixtures.** Validate all three manifests against `agent-package.v1.json`: camelCase fields,
  contained/digest-verified prompt paths, declared variables, `capabilities` with `contractVersion`,
  `compatibleTargets`, `settingsDefaults` profile-family ID/version, and `provenance.trust = built-in`.
- **Capability-contract tests.** For each of `dataflow.orchestrate`, `dataset.discover`, `dataset.select`,
  `node.build`, `dataset.fetch.author`: input/output schema validity and that IDs contain no prompt/path
  tokens.
- **Delegation resolution.** `delegatesTo` resolves only current-project templates; a missing delegate
  produces a reviewed `Install in project` proposal and never auto-installs/attaches/runs; cross-project
  templates are never used; delegation cycles are detected.
- **Orchestration.** Dataflow Builder plans/evaluates without confirmation but gates install/graph/dataset
  mutations behind review; child executions link by `parentExecutionId`; partial failure preserves
  successful children; aggregate reservation is shared while child policies stay tighter.
- **Dataset Finder two-lane.** External picks emit exactly one Node Builder `dataset.fetch.author` handoff;
  catalog picks emit a dataset-only install request and never an agent install; untrusted candidate content
  is sanitized.
- **Node Builder.** `node.build` and `dataset.fetch.author` return reviewable previews before any mutation;
  authored external node is provenance-labeled; secrets never rendered.
- **Lifecycle + privacy.** Import/Install/Attach separation, imported-only Publish, unversioned attachment,
  project isolation, and a **D-0 = B regression guard** proving no composite adds agent-private data as a
  new shared surface.
- **Accessibility.** Delegate-status list, proposal dialog, and lane selection meet WCAG 2.2 AA.

## 8. Acceptance Criteria

- Three manifests (`agent.dataflow-builder`, `agent.dataset-finder`, `agent.node-builder`) are specified,
  schema-valid, built-in-trust, and link net-new prompt assets by contained digest-verified path.
- Each composite declares its own capability set (`dataflow.orchestrate`; `dataset.discover` +
  `dataset.select`; `node.build` + `dataset.fetch.author`) distinct from the capabilities it delegates to.
- `delegatesTo` for each composite lists only already-specified agents and matches §3.2; resolution is
  current-project-only and grants nothing.
- A missing delegated specialist yields a reviewed `Install in project` proposal; no composite auto-
  imports/installs/attaches/runs/publishes.
- Dataflow Builder gates all install/graph/dataset mutations behind review while planning/evaluation may
  proceed unconfirmed; child executions link by `parentExecutionId`.
- Dataset Finder produces external Node Builder handoffs and catalog dataset-only install requests across
  two lanes and never authors fetch code or installs an agent.
- Node Builder returns reviewable node/fetch-node previews before mutation and owns the executable fetch
  node for external selections.
- No composite exposes Publish/Share/version actions on templates/instances or adds agent-private data to
  the existing flow-sharing (D-0 = B).
- Each composite maps to its reviewed settings profile family (orchestration-mutation / planning-analysis /
  mutation-proposal) with immutable seed suggestions only.

## 9. Recommended Commit Breakdown

1. `feat(agents-manifest): add composite capability contracts (dataflow.orchestrate, dataset.discover/select, node.build, dataset.fetch.author)` with schema + ID-format tests.
2. `feat(agents-manifest): add agent.dataset-finder manifest + net-new discovery prompt assets` with two-lane fixture tests.
3. `feat(agents-manifest): add agent.node-builder manifest + net-new node-build prompt assets` with review-before-apply preview tests.
4. `feat(agents-manifest): add agent.dataflow-builder manifest + net-new orchestration prompt assets` with delegation-resolution and missing-specialist proposal tests.
5. `test(agents-composite): lifecycle/privacy/D-0 regression coverage for all three composites`.

## 10. Engineering Quality Checklist

- [ ] Each composite has one stable `agent.`-prefixed ID and a schema-valid camelCase manifest.
- [ ] Declared capabilities are distinct from `delegatesTo`; capability IDs contain no prompt/path tokens.
- [ ] Every `delegatesTo` entry references an already-specified agent (fourteen migrated, another composite, or `agent.package-recommendation` from dev/16).
- [ ] Net-new prompt assets are contained, digest-verified, and variable-checked; no migrated prompt is assumed.
- [ ] Capability resolution is current-project-only; a missing delegate produces a reviewed `Install in project` proposal and no auto-chaining.
- [ ] Dataflow Builder gates install/graph/dataset mutations behind review; child executions pin their own revisions and link by `parentExecutionId`.
- [ ] Dataset Finder two-lane output routes external → Node Builder handoff, catalog → dataset-only install, and never installs an agent.
- [ ] Node Builder previews are reviewable before mutation; secrets are never rendered; external nodes are provenance-labeled.
- [ ] Templates/instances expose no Publish/Share/version action; no composite adds agent-private data to existing flow-sharing (D-0 = B).
- [ ] Each composite binds its reviewed settings profile family with immutable seed suggestions only.
- [x] Package Recommendation resolves only when installed and ships under `DEC-035`; `DEC-056` closes OQ-011 by making Validation a category view and Optimization demand-gated.
