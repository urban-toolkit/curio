# Agents Catalog Development Plan

Status: implementation-ready planning baseline  
Date: 2026-07-15  
Source instructions: `02-development-plan-brief.md`  
Traceability companion: `kggraph/Stage-2-Design-Phase/2.1-Agents-Catalog-Design-Traceability.md`  
Build log template: `kggraph/Stage-3-Build-Phase/3.1-Agents-Catalog-Build-Log.md`

Detailed implementation blueprint: `05-agents-catalog-implementation-blueprint.md`

Prompt-agent migration memo: `06-prompt-to-hookable-agent-migration-memo.md`

Decision-closure and privacy-hardening memo: `10-agent-plan-decision-closure-and-hardening-memo.md`

Agent configuration and prompt-governance memo: `11-agent-configuration-modals-and-prompt-governance-memo.md`

Canonical import/install/attachment/share lifecycle memo: `12-agent-template-installation-attachment-sharing-lifecycle-memo.md`

Plan hardening and open decisions: `14-plan-hardening-and-open-decisions-memo.md`

Composite-agent specifications (H-5): `15-composite-agent-specifications-memo.md`

Node-package capabilities (`REQ-PACKAGE-001`): `16-agent-node-package-capabilities-memo.md`

This document is the actionable implementation specification for the Agents Catalog. It does not authorize or contain implementation code. Existing concept documents remain the design source of truth; conflicts are resolved by the decisions and open questions recorded below.

For file-level module contracts, architecture tradeoffs, Mermaid diagrams, pseudocode, persistence/API patterns, and step-by-step source migration, use `05-agents-catalog-implementation-blueprint.md` together with this specification.

## 1. Problem Statement

Curio has mature private account storage, catalog publishing, project/dataflow persistence, and dataset/package patterns, but agents currently exist only as design concepts and scattered LLM behaviors. There is no persisted reusable definition, explicit private account import, project-installed template palette, private attached-instance model, unified attachment session, runtime lifecycle, or provider-neutral execution boundary.

The change affects the Agents drawer, project-only AGENTS palette, canvas/node attachment affordances, attached-agent dock, unified chat drawer, six dedicated governed-settings screens, project/dataflow persistence, backend catalog/runtime/projection services, LLM configuration, prompt authoring/evaluation/audit, and tests. (The built-in node Explanation tab is retained permanently — `DEC-041`, `dev/18` — and is not modified by this change.) Users explicitly import reusable manifest packages into a private account library, explicitly install a visible definition as a project template, attach a private instance to a compatible target, and refine/run it through unified chat. Import, project installation, attachment, Release, and user publication never chain implicitly.

This matters because immutable definition, private account import, global publication, project template, attached instance, policy draft/activation, prompt draft/release, and execution are distinct lifecycles. Treating them as one state would cause cross-project leakage, accidental install/publish, disclosure of private resources, data loss, overspend races, untraceable prompt changes, and framework/provider coupling.

## 2. Scope

### Included

- Agents drawer browse/search/filter/sort/page with distinct Global Catalog, My Imports, and Installed in this project views; explicit import, project install/uninstall, imported-only publish/unpublish, version, and category display.
- Active-project-only `AGENTS` palette sourced from `ProjectAgentTemplate` records and drag-to-attach behavior.
- Node-, connection-, and canvas-level compatibility resolution, with the first release proving Data Load node, any explainable node, and canvas hooks.
- Private `AttachedAgentInstance` configuration, optimistic revision, enablement, session transcript, execution pins, and dock visibility without attachment SemVer/publication/share lifecycle.
- A shared settings dialog shell with dedicated Cost, Quotas, Resource policies, Prompt quality, Prompt editor, and Prompt audit screens opened by clear authorized cog/settings controls.
- Account ceilings, validated per-project-template profiles, downward-only attached-instance overrides, independently typed policy revisions, effective-policy snapshots, and atomic cost/quota/resource admission.
- Private prompt-authoring workspaces, immutable prompt releases, reproducible evaluation suites/runs, and append-only integrity-linked prompt audit history.
- Unified attached-agent chat, review-before-apply actions, previous/next attachment navigation, cancellation, retry, and recovery.
- Versioned definition manifests/artifacts, private account imports, project templates, per-project references, user-authored definitions, and global catalog publications.
- Retention of the built-in node Explanation tab/state/direct path as-is (`DEC-041` — the former removal is cancelled and out of scope); the Node Explainer agent additionally offers the standard project install → attach → unified chat workflow as a coexisting surface.
- Backend agent domain/application/infrastructure/API layers.
- Framework-neutral runtime contracts with a LangChain adapter for the first implementation.
- Provider registry and adapters for cloud APIs, OpenAI-compatible endpoints, local Gemma, Hugging Face, and future providers.
- Manifest-defined prompt-agent packages migrated from `utk_curio/llm-prompts`, loaded through one prompt asset registry.
- Dataflow Builder orchestration and explicit specialized-agent delegation.
- Security, observability, migrations, tests, KGGraph traceability, and incremental build logs.

### Out of scope

- **Any new sharing mechanic, endpoint, viewer, or flow (DECIDED: reuse existing sharing — see `14-plan-hardening-and-open-decisions-memo.md` D-0 = B).** Agents participate only in Curio's existing flow-sharing; the feature builds no `SharedFlowResult` pipeline/projector/endpoint/viewer and does not retire the existing share route. The sole agent requirement is negative: introduce no agent-private data as a new shared surface. `SharedFlowResult` content elsewhere in this plan is superseded by that decision.
- Replacing React Flow, redesigning unrelated catalog pages, or changing existing node/dataset behavior.
- A second agent framework; only the adapter seam is required now.
- Silent graph mutation or autonomous destructive actions.
- A bespoke refinement panel per agent.
- Marketplace billing/payment collection, client-controlled deployment ceilings, or provider-credential editing inside the six agent settings screens.
- In-place mutation of installed/published prompt bytes or silent substitution of the unresolved generated-content evaluator.
- Publishing or sharing project templates/attached instances; attachment SemVer/release history; automatic import/install/publish; editable/executable public projects; cross-account agent execution; or exporting project-local overrides back into a manifest.
- New user/public chips or multiple publish controls that diverge from current Curio UI.
- Full mission-template authoring, marketplace billing, arbitrary third-party executable plugins, or distributed multi-host scheduling.

## 3. Current Design and Concept Review

### Approved product decisions

| ID | Decision | Source |
| --- | --- | --- |
| DEC-001 | Agents are reusable capabilities attached to explicit Curio targets, not isolated chatbots. | `01-consolidated-plan.md`, `02-hook-model-and-flows.md` |
| DEC-004 | Attached agents remain visible as icon-only dock tiles with labels/tooltips and state indicators. | `03-ui-decisions.md`, `04-interaction-states.md` |
| DEC-005 | Every attachment uses one unified chat drawer; its transcript is the run history. | `08-unified-agent-chat.md` |
| DEC-006 | Review-before-apply gates graph and dataset mutations. | `02-hook-model-and-flows.md`, `08-unified-agent-chat.md` |
| DEC-007 | LangChain is the initial runtime, hidden behind a stable application boundary. | `09-agent-architecture.md` |
| DEC-008 | Each current prompt behavior becomes a manifest-defined hookable agent with package-local, typed, digest-verified prompt assets. | `10-prompt-architecture.md`, `06-prompt-to-hookable-agent-migration-memo.md` |
| DEC-009 | Dataflow Builder orchestrates specialized agents; Dataset Finder selects sources and delegates external fetch-node construction to Node Builder. | `01-consolidated-plan.md`, `09-agent-architecture.md`, `11-agent-manifest-and-product-model.md` |
| DEC-010 | Agent manifests drive catalog, palette, compatibility, configuration, runtime, and publishing presentation. | `11-agent-manifest-and-product-model.md` |
| DEC-011 | Agent package IDs use the `agent.` namespace; `curio.` remains reserved for existing non-agent package identities unless separately migrated. | `07-agent-package-prefix-memo.md` |
| DEC-012 | Semantic agent capabilities are stable behavior contracts distinct from roles, delegates, tools, prompt assets, and provider capabilities. Prompt filenames are never capability IDs. | `08-semantic-agent-capabilities-memo.md` |
| DEC-016 | Ollama through the existing OpenAI-compatible adapter is the first local Gemma path. A dedicated local adapter is deferred until a measured capability gap justifies it. | `10-agent-plan-decision-closure-and-hardening-memo.md` |
| DEC-017 | Imported manifests may reference only server-allowlisted typed tool IDs. Package signatures establish provenance, not permission, and manifest-supplied executable code is never run. | `10-agent-plan-decision-closure-and-hardening-memo.md` |
| DEC-020 | Import deletion, project uninstall, unpublish, security quarantine/revocation, attachment detach, and artifact garbage collection are distinct authorized operations. | `12-agent-template-installation-attachment-sharing-lifecycle-memo.md` |
| DEC-021 | Execution uses persisted leases/heartbeats. Expired nonterminal work becomes `interrupted`; provider/tool calls are never replayed automatically, and retry creates a linked execution. | `10-agent-plan-decision-closure-and-hardening-memo.md` |
| DEC-022 | Provider credentials live behind account provider profiles and opaque secret references. Remote egress is explicit, custom endpoints are SSRF-checked, and local failure never falls back to a remote provider. | `10-agent-plan-decision-closure-and-hardening-memo.md` |
| DEC-024 | Server-authoritative rollout flags, kill switches, quotas, baseline telemetry, and recovery instrumentation ship with the first runtime slice rather than as post-launch hardening. | `10-agent-plan-decision-closure-and-hardening-memo.md` |
| DEC-025 | Authorized Account policy, Imported definition, Project agent default, and Attached instance contexts use one accessible six-screen settings shell. Governed changes are not chat commands; applicability is server-defined per lifecycle scope. | `11-agent-configuration-modals-and-prompt-governance-memo.md`, `12-agent-template-installation-attachment-sharing-lifecycle-memo.md` |
| DEC-027 | Prompt editing occurs only for an owned `AccountImportedAgent` created by explicit Import. Release creates a new private immutable imported-definition artifact; built-in/global definitions, project templates, and attachments show prompt provenance/evidence read-only and cannot release or publish it. Any future fork/export must be explicitly packaged and re-imported before it can become publication-eligible and is out of scope. | `11-agent-configuration-modals-and-prompt-governance-memo.md`, `12-agent-template-installation-attachment-sharing-lifecycle-memo.md` |
| DEC-028 | Prompt-quality evidence is reproducible and pinned to exact draft, suite, evaluator, provider-profile, fixture, and policy revisions. Prompt audit combines versioned exact-digest security/compliance/provenance runs and typed findings with a separate mandatory append-only integrity-linked governance history; both are separate from transcripts. Platform quality neither depends on nor silently substitutes the OQ-007 evaluator package. | `11-agent-configuration-modals-and-prompt-governance-memo.md` |
| DEC-029 | Canonical lifecycle is immutable `AgentDefinitionArtifact` → explicit private `AccountImportedAgent` or global visibility → explicit selected-project `ProjectAgentTemplate` with independent defaults → private `AttachedAgentInstance` → private execution. The current project ID/dataflow key scopes installation/palette; every transition is a separate command. | `12-agent-template-installation-attachment-sharing-lifecycle-memo.md` |
| DEC-030 | Only an owned validated manifest-based `AccountImportedAgent` is eligible for user publication. Import, project Install, and Publish are explicit independent commands; global/built-in/project-installed/attached resources cannot be user-republished. | `12-agent-template-installation-attachment-sharing-lifecycle-memo.md` |
| DEC-031 | `AttachedAgentInstance` is a private configured derivation identified by `attachmentId` plus optimistic `revision`, with no SemVer/release/publication/share lifecycle. Each execution pins its resolved definition/settings/attachment/prompt/provider/effective-policy inputs. | `12-agent-template-installation-attachment-sharing-lifecycle-memo.md` |
| DEC-032 | Sharing is out of scope (D-0 = B): agents reuse Curio's existing flow-sharing and add no new sharing mechanic. The only invariant is that the feature introduces no agent-private data as a new shared surface. | `14-plan-hardening-and-open-decisions-memo.md`, `12-agent-template-installation-attachment-sharing-lifecycle-memo.md` |
| DEC-033 | **Superseded by `DEC-041` — do not implement.** (Formerly: remove the built-in node Explanation tab after parity.) | `12-agent-template-installation-attachment-sharing-lifecycle-memo.md`, superseded by `18-node-explainer-tab-retention-memo.md` |
| DEC-041 | The built-in node Explanation tab, its state/cache, and its direct `single_box_explanation_prompt`/provider call are **retained permanently**; the removal planned under `DEC-033` is cancelled and must not be reintroduced. The project-installed, node-attached Node Explainer unified chat coexists as an additional explanation surface. | `18-node-explainer-tab-retention-memo.md` |
| DEC-034 | Specify the three composite agents (`agent.dataflow-builder`, `agent.dataset-finder`, `agent.node-builder`) as net-new compositions over migrated capabilities, each with its own manifest, capability contract (`dataflow.orchestrate`/`dataset.discover`/`dataset.select`/`node.build`/`dataset.fetch.author`), `delegatesTo` composition, and net-new prompt provenance. Closes hardening item H-5. | `15-composite-agent-specifications-memo.md` |
| DEC-035 | Add the `package.*` capability family (`package.recommend`/`package.identify`) and the `agent.package-recommendation` agent; Node Builder, Connection Builder, and Dataflow Builder delegate to it to identify and suggest node packages, and installs go only through Curio's existing reviewed package flow (`InstallPermissionsDialog` → `installToProject`), never silently and never for a `curio.builtin@*` package. | `16-agent-node-package-capabilities-memo.md` |
| DEC-036 | Definition-inspection (prompt bytes/provenance/evaluation/audit) of a template/attachment sourced from an *unpublished* private import is **owner-only**; project collaborators get execution only. Publishing to the Catalog Hub is the single act that widens prompt visibility to installers of the published artifact. | `17-hardening-resolutions-memo.md` |
| DEC-037 | The prompt-evaluation sub-budget is bound to **account** Cost scope; project-template and attachment scopes omit it. A per-import cap may only tighten the account budget. | `17-hardening-resolutions-memo.md` |
| DEC-038 | Ship an explicit **v1 (MVP)** — lifecycle + 13 prompt-agent migrations + three-scope catalog + attachments/chat + Cost/Quotas/Resource policy screens — before **v2** governance (Prompt editor/quality/audit, evaluation, ledgers, crypto-shredding) and the P5 composites + `agent.package-recommendation`. | `17-hardening-resolutions-memo.md` |
| DEC-039 | The LangChain adapter and default `ProviderProfile` derive provider/model/API/runtime defaults from the existing `dev/aiconn/` configuration (OpenAI-compatible sage200 endpoint, `llama4-nim`+`gemma4`, `AICONN_API_KEY`, chat-completions), not separate LangChain defaults; per-agent and per-scope values are explicit overrides of that seed. | `17-hardening-resolutions-memo.md` |
| DEC-040 | Store the agent lifecycle aggregates on the **filesystem**, mirroring the datasets and node-package catalogs — definition artifacts under `.curio/users/<key>/agents/<id>@<version>/`, account imports ("My Imports") in a per-account JSON registry, project-installed templates in the project spec's `dataflow.agents` lockfile, and attachments in the project/dataflow graph spec. The database stays limited to users and the project index; there are **no agent SQL tables and no Alembic migrations**. "Repository" throughout this plan means a filesystem repository (as in `app/datasets/repositories`), not a SQL table. | Implemented in `app/agents/{storage,imports,project_agents}.py`; reuse-first finding (datasets/packages are FS-backed). |
| DEC-043 | Structured agent content rides a validated **terminal `curio.v1` tail block**: the runtime strips it into bounded typed parts (`suggestedPrompts`, `card`) persisted on the agent turn (the transcript stays the single history) and emitted over the additive SSE envelope (`event: content`, enriched `done`); malformed blocks fail **open** to visible text — model content is never silently dropped. Manifest `tools` entries are validated declarations, never grants: the server resolves `granted = requested ∩ registry ∩ policy` (read-effect only until the DEC-006 review-before-apply flow exists), pins grants on the execution record, and refuses a run whose `required` tool resolves no grant. Agent rich content renders only through the centralized safe renderer (`REQ-SEC-002`). | `39-runtime-maturation-tranche2-memo.md` |
| DEC-052 | Per-node runtime state is a **server-owned observational journal** (dev/67-2): every `/process*Code` execution best-effort-persists the node's latest outcome — status by the canonical `output.path == ""` predicate (never stderr-nonempty; warnings land there), traceback/stdout tails, output metadata, normalized content digest — under `<project dir>/runtime/` (`DEC-040` FS posture); writes never delay or fail an execution, reads fail open ("never-executed"). Agents reach it via `node.runtime.read` (with a best-effort `contentChangedSinceRun` signal) and the **structure-first `dataflow.read` v2 projection**: ALL edges always survive (node content elided to lengths — the pre-67-2 dump truncated the edge list away on any non-trivial dataflow), runtime statuses ride along, and `params.include: ["content"]` restores the full dump. The composites' declared reads (`graphContext`/`mission`/`installedTemplates`/`targetContext`/`nodeIntent`) gain frontend producers — before 67-2 they composed `null` and ran context-blind. The saved spec stays the single structural truth; the journal is evidence, never authority. | `67-2-dataflow-awareness-runtime-journal-memo.md` |
| DEC-050 | Solve streams and cancels — the `DEC-021` **user slice**: the batch is ONE generator (`solve_attachment_stream`; the blocking endpoint drains it — one implementation) yielding `solve_started` → `node_started`/`node_result` per target → `done` over the dev/22 SSE envelope; solved content reaches the live canvas per node (the dev/51 bridge) and the strip's pills advance live (transient overlay, cleared on the terminal event); the terminal state comes from ONE re-guarded finally-write that also runs on client disconnect (`GeneratorExit`) — streamed events are transport, never truth. Cancellation is one predicate with two signals: an in-process stop event (registry keyed by the persisted `solveExecutionId`) plus the durable `cancelRequested` session flag (`POST …/solve/cancel`), checked at node-dispatch boundaries — in-flight children finish and persist (`DEC-021`'s no-replay posture), undispatched targets revert to `pending` (no new status vocabulary; `interrupted` stays with lease expiry). `DEC-021` proper (leases/heartbeats, background execution, the LangChain re-open condition) remains open. | `63-streamed-solve-progress-memo.md` |
| DEC-049 | Destructive plan operations are **digest-pinned per victim and reviewed by name**: `dataflowPlan` gains `removeNodes`/`removeEdges` (edges may also reference existing node ids — the dev/52 island restriction lifted); every removal victim is pinned by its content sha256 at mint, so editing a doomed node between mint and apply 409s + `stale` naming it — user work never dies to a stale review; the card lists each victim (label · type · content flag) plus the edge cascade with a blunt bidirectional effect line; attachments on removed nodes are pruned exactly as manual deletion (dev/32); the apply touches ONLY listed elements, so unlisted nodes keep ids/positions/content by construction; the model may remove only on explicit user request (instruction posture superseding dev/52's "removals are theirs to make"). | `59-destructive-replan-reconciliation-memo.md` |
| DEC-048 | The orchestration runtime is **direct code; `DEC-007` is retired**: Plan → Revise → Solve → Run is user-paced (every phase boundary an explicit human action), so orchestration decomposes into bounded synchronous segments — a typed additive `dataflowPlan` proposal (whole-graph shape-digest pinned; the runtime mints, the model never requests), an atomic authenticated apply, and the **Solve authorization model**: ONE explicit authenticated Solve action authorizes a bounded batch (`ThreadPoolExecutor(3)`) of depth-1 children over the applied plan's placeholder nodes, digest-guarded per node so user edits are skipped, never overwritten — mutation authority stays structural. Capability-first resolution lands per dev/03:366 (delegatesTo = preference; any current-project template; visible-roster missing-specialist proposals). LangChain's re-open condition is recorded: background/long-running orchestration (`DEC-021`), through the `delegation.py` seam; until then the architecture of record is the provider port + delegation seam (`DEC-039` unaffected). | `52-dataflow-builder-memo.md` |
| DEC-047 | The Dataset Finder **external handoff is user-mediated, never a child-minted proposal**: under `DEC-046` a depth-1 child is structurally proposal-less, so a confirmed external pick yields a handoff card + a suggested prompt addressed to the user's own Node Builder attachment, whose run produces the reviewed fetch-node `node.create` proposal with the full dev/48 machinery; a missing Node Builder resolves through the existing reviewed `project.install` proposal (the delegation seam is reused exactly where it is sound — resolution + install proposals). Catalog picks route through the reviewed `dataset.install` proposal over the EXISTING dataset-only install flow; no dataset pick ever installs an agent. Batch/orchestrated handoffs are Dataflow Builder territory (dev/49 DR-4). | `50-dataset-finder-memo.md` |
| DEC-046 | Delegation runs as **direct provider-port code**: a `delegateRequest` tail part resolves over the parent manifest's `delegatesTo` ∩ the CURRENT project's installed templates (order = preference, deterministic; never another project) and executes ONE synchronous, depth-1 child run — the child's own prompts with **no tail instruction**, its reply **never parsed** for requests (cycles impossible by construction), its own execution record + ledger reserve→settle under the child's effective policy, linked by `parentExecutionId`, sharing the parent's `MAX_TOOL_ROUNDS` budget. A visible-but-not-installed delegate mints a reviewed `project.install` proposal (`REQ-ORCH-001` — never a silent install); a child failure is framed data the parent recovers from. **LangChain disposition narrowed**: `DEC-007`'s adapter revisit moves from "P5 delegation" to **Dataflow Builder specifically** (parallel children, plan/evaluate cycles); the seam is the one-module boundary `delegation.py`. | `48-node-builder-composite-memo.md` |
| DEC-045 | Tools execute through a **bounded server-side loop** (≤2 rounds per run): granted `read` contracts run domain-owned implementations with results fed back as framed untrusted context and `tool_requested`/`tool_started`/`tool_result` streamed in the dev/03 normalized vocabulary; a granted `mutate` contract never executes in the loop — it mints a **digest-pinned review proposal** (`review_required`), and the authenticated apply endpoint is the ONLY mutation path (drift → 409 + stale; `REQ-REVIEW-001` is structural, not a flag). First contracts, each with a named roster consumer: `dataflow.read`, `node.read`, `node.content.write`. **LangChain disposition**: `DEC-007`'s adapter adoption is deferred to P5 multi-agent delegation — the two-round loop under server-authoritative grants and a mandatory review pause is smaller and safer as direct provider-port code than as a constrained agent executor. | `41-runtime-maturation-t2b-executing-tools-memo.md` |
| DEC-044 | Quota/budget accounting is an **append-only per-account daily ledger** (FS per `DEC-040`; flock-guarded): every run is an atomic reserve→settle pair keyed by its execution id, aggregates are derived never stored, and the budget gate charges settled actuals + settled estimates + in-flight holds + this run's hold — with `REQ-COST-001`'s **fail-closed rule** (a configured budget with neither estimate nor price denies the run). USD prices come from a **deployment-owned table** (`.curio/agents-pricing.json`), **empty by default** — Actual USD exists exactly where the operator states a price, pinned immutably per reservation; nothing ever fabricates a price (memo 11). The advisory counters are retired; the legacy window seeds the ledger once, same-day only. | `40-runtime-maturation-tranche3-memo.md` |

### Repository findings that shape the plan

- Frontend catalog/palette reuse candidates exist under `src/pages/catalog`, `src/components/packages`, `src/components/menus/nodes/datasetPalette`, and `src/services/datasetCatalog`.
- `CatalogPublishPill` and package browse cards provide the publishing and card interaction baseline.
- Dataset services already model pending installs and scoped refresh, useful for flicker-free optimistic project-template installation without reusing dataset ownership semantics.
- `UserDatasetRepository` demonstrates an account-private catalog tier and `InstalledDatasetRepository` demonstrates project/dataflow usage refs. Agents use the former for `AccountImportedAgent` ownership and the latter only as a structural precedent for project-scoped `ProjectAgentTemplate`.
- Backend dataset code already separates domain, application, infrastructure, install, repository, and schema responsibilities.
- Existing LLM calls are centralized through `LLMProvider.tsx` and backend API routes, while provider settings already support OpenAI and OpenAI-compatible endpoints.
- Thirteen requested prompt sources currently live in `utk_curio/llm-prompts`; migrate each into one self-contained versioned agent artifact. The missing generated-content evaluation prompt must be supplied, not inferred.

## 4. Assumptions, Constraints, Dependencies, and Open Questions

### Assumptions

| ID | Assumption |
| --- | --- |
| ASM-001 | Account import needs no open project. Project template installation and attachment require the selected authorized saved project; the current repository uses its dataflow ID as the project scope key. |
| ASM-002 | Authentication and user storage remain the authority for ownership and credentials. |
| ASM-003 | Server-sent events are the preferred first streaming transport; polling is an allowed fallback. |
| ASM-004 | A project template sourced from an imported/global artifact remains reproducible after normal unpublish when retained exact bytes/dependencies remain valid and no quarantine/revocation blocks it. |
| ASM-005 | The initial manifest format is JSON and is validated on import, publish, install, and runtime load. |

### Constraints and dependencies

- Preserve node/dataset catalog behavior and styling.
- Browser code must never receive provider secrets.
- LangChain imports must remain inside infrastructure/runtime adapter modules.
- Attachments must be dataflow-owned, not inferred from transient canvas selection.
- Package dependency selection and LangChain version must be pinned and verified before Phase 2 begins.
- Existing project serialization, authentication, catalog repositories, toast/confirm patterns, React Flow DnD, and LLM settings are required integration points.

### Open questions requiring product or architecture resolution

DEC-029 through DEC-032 (with DEC-033 superseded by DEC-041 — the Explanation tab is retained) close the lifecycle-scope questions. Only the following genuine content, policy, and deployment questions remain open:

| ID | Question | Decision owner | Blocking phase | Fail-closed interim default |
| --- | --- | --- | --- | --- |
| OQ-007 | What is the approved source text and output contract for `evaluate_generated_content_prompt`? | Prompt/product owner | That agent package only | Do not infer or substitute content; do not register, publish, install, or run this package until supplied and reviewed. |
| OQ-008 | What are the approved retention, deletion, backup-expiry, export/reveal, and account-closure rules for transcripts/events, prompt drafts and optional encrypted snapshots/diffs, evaluation suites/fixtures/results, prompt-audit metadata and protected content, publications, secret-remediation redaction/crypto-shredding tombstones, and restored copies? | Product + Security/Privacy | Production release | Do not invent durations or claim irreversible deletion while live/retained backups, public caches, or protected copies exist. Minimize content, keep access/redaction/tombstone state truthful, audit reveal/export/remediation, and block production release until durations, deletion SLA, backup expiry, export scope, and ownership transitions are approved. |
| OQ-009 | Is the first production deployment single-process or multi-instance, and which durable queue/lease owner is authoritative for multi-instance execution? | Platform/Operations | Phase 2 production enablement | Support execution only in the documented single-process topology; disable multi-instance execution until a durable scheduler/queue is selected and tested. |
| OQ-010 | Which data classifications may be sent to each remote provider, and who may approve provider destinations or exceptions? | Security/Data Governance + Product | Phase 2 remote execution | Treat unclassified/restricted context as ineligible for remote egress; require an approved destination and never fall back from local to remote implicitly. |
| OQ-011 | Should the two still-unspecified product agents — `Validation` and `Optimization` (referenced by the concept screens but neither in the fourteen-agent migration roster nor among the three composites) — be specified with their own manifests/capabilities or descoped? (`Package Recommendation`, originally flagged with them, is specified in `16-agent-node-package-capabilities-memo.md` / `DEC-035`.) | Product + architecture | Phase 5 orchestration | Treat both as not-installed; Dataflow Builder resolves them only if installed and never assumes them present. |

### Settings and prompt-governance risks

| ID | Risk | Required control |
| --- | --- | --- |
| RISK-POLICY-001 | One generic blob or incorrect precedence lets a lower scope loosen a ceiling or couples unrelated modal edits. | Independent typed revisions, strict-intersection resolver, provenance UI, schema/contract tests, and server-only activation. |
| RISK-COST-001 | Concurrent or ambiguous provider work overspends budgets or undercounts usage. | Atomic idempotent reservations before queueing, immutable price/effective snapshots, leases, settlement/reconciliation, and fail-closed unknown pricing. |
| RISK-PROMPT-EDIT-001 | Editing mutates released bytes, leaks private content, or overwrites another writer. | Allow editing only through an owned explicitly imported definition's contained workspace; use memory-only client state, optimistic concurrency, new immutable Release, and attachment pin preservation. |
| RISK-EVAL-001 | Stale, self-referential, unapproved, or unbudgeted evaluation falsely certifies a prompt. | Exact input pins, candidate/evaluator separation, independent authorization/budget, stale detection, no automatic activation/release/publish, and OQ-007 unavailable state. |
| RISK-AUDIT-001 | Audit evidence is mutable, leaks prompt/context, or is confused with transcript history. | Append-only integrity-linked metadata, separate protected content, narrow reveal/export authorization, redaction, retention policy, and audited access. |
| RISK-MODAL-001 | Ambiguous cogs, nested dialogs, stale scope, or inaccessible dirty/conflict states cause the wrong policy to change. | Labeled scope-aware triggers, one dialog shell, six screens, server authorization flags, focus/dirty/conflict handling, and WCAG component/E2E coverage. |
| RISK-LIFECYCLE-002 | Import, project install, attach, or publish is implicitly chained or represented by one mutable record. | Separate typed aggregates/commands, idempotency, legal-transition tests, project-keyed caches, and server authorization for every step. |
| RISK-PUBLISH-001 | A global/built-in/project template/attachment is user-republished or Publish accidentally installs it. | Accept user publication only from an owned validated `AccountImportedAgent`; omit/reject Publish elsewhere; no command invokes another lifecycle command. |
| RISK-ATTACH-001 | Attachment revision is mistaken for SemVer/publication, or source/profile changes silently retarget a private instance. | Stable `attachmentId`, concurrency-only revision, no artifact/share endpoints, and immutable execution pins for source/settings/prompt/provider facts. |
| RISK-SHARE-002 | Sharing is out of scope (D-0 = B); agents reuse existing flow-sharing and add no new sharing mechanic. | The only invariant is that the feature introduces no agent-private data as a new shared surface (regression guard). |
| RISK-EXPLAIN-001 | **Retired (`DEC-041`)** — this risk assumed the tab must be removed; it is intentionally retained. Identifier not reused. | — |
| RISK-EXPLAIN-002 | The obsolete Explanation-tab removal (`DEC-033`) is reintroduced from a stale document and the tab or its direct path is deleted. | `DEC-041` supersession notes on every former removal instruction; retired-ID policy (memo `13`); a regression test asserting the Explanation tab renders. |

## 5. Recommended Implementation Approach

Build a vertical, layered feature that mirrors existing catalog domains while extracting only genuinely shared catalog UI and mutation utilities.

```text
React drawer/project palette/canvas/chat/settings
        -> typed agent API + query/mutation hooks + selectors
        -> backend agent application services
        -> domain entities and policies
        -> repositories / catalog storage / event stream
        -> AgentRuntime interface
             -> LangChainRuntimeAdapter
                  -> ProviderRegistry -> provider adapters
             -> CapabilityRegistry -> semantic behavior contracts and agent implementations
             -> PromptAssetRegistry -> installed manifest-linked prompt files
             -> ToolRegistry -> allowlisted application tools
```

Rules:

1. Domain entities never import Flask, LangChain, provider SDKs, or React types.
2. UI receives normalized DTOs and execution events; it never constructs LangChain agents or provider payloads.
3. Immutable definition artifact, account import, publication, project template, attached instance, session, execution, quarantine/revocation, and garbage-collection eligibility are separate records connected only by typed IDs and authorized references.
4. Mutations return authoritative updated entities and revision/ETag data; caches reconcile by entity key rather than full-page reload.
5. Extract shared catalog primitives only after comparing node, dataset, and agent requirements; do not force unlike persistence semantics into one service.
6. **All agent and LLM behavior is module-owned.** Frontend agent UI, hooks, services, state, utilities, execution/provider integration, and compatibility adapters must live under `src/agents/`. Backend orchestration, LangChain integration, LLM provider calls, tool execution, prompt loading, manifests, sessions, and runtime behavior must live under `backend/app/agents/`.
7. Dataset, node, flow, canvas, and generic UI modules may depend only on the public agent interfaces. They must not construct raw LLM requests, import provider SDKs/LangChain, load prompts, execute agent tools, or own agent lifecycle state.
8. Shared abstractions remain outside `agents/` only when they are genuinely feature-neutral and have non-agent consumers; agent-specific wrappers around them belong inside `agents/`.
9. Importing, installing, attaching, or selecting an agent grants no context, provider, tool, target, share, or mutation permission. Each command and execution re-authorizes every boundary independently.
10. Governed settings have independent typed revision streams. Policy changes use Save draft → Validate → Activate; prompt changes apply only to an owned imported definition and use private Save draft → Validate/audit/evaluate/review → Release private definition version. Publish remains a distinct imported-only global-catalog command.
11. The runtime never trusts client estimates or counters. It persists the exact effective-policy sources and atomic cost/quota/resource reservations before provider or tool work begins.
12. Prompt content, evaluation fixtures, audit evidence, every agent lifecycle resource, datasets, and node packages never enter a share (sharing is out of scope — D-0 = B; the feature adds no agent-private data as a new shared surface in existing flow-sharing).
13. The built-in node Explanation tab/direct caller/state/cache is retained as-is (`DEC-041`); Node Explainer *agent* requests use project install, node attach, and unified chat through the `agents/` public API, coexisting with the tab.

## 6. Agent Domain Model and Manifest

### Core entities

| Entity | Identity | Responsibility |
| --- | --- | --- |
| `AgentArtifactCoordinate` | `publisherNamespace + agentId + exactVersion + artifactDigest` | Canonical immutable identity for validated manifest/package bytes; the same publisher/ID/version cannot resolve to a different digest. |
| `AgentDefinitionArtifact` | opaque `artifactId`; unique exact `AgentArtifactCoordinate` | Immutable validated reusable manifest/prompt/contracts/default-suggestion bytes from built-in seed, global catalog, or account import. |
| `AccountImportedAgent` | `accountImportedAgentId` | Private account ownership/provenance/current-artifact/validation/publication-eligibility record created only by explicit Import; it does not mutate a project. |
| `CatalogAgent` / `AgentPublication` | catalog record / `publicationId` | Global discovery/moderation projection referencing an eligible exact artifact; user publication is accepted only from its owning imported-agent record. |
| `ProjectAgentTemplate` | `projectAgentTemplateId + projectId` | Explicit project installation and active-project palette entry referencing a visible exact source definition plus its independent project settings profile. |
| `ProjectAgentSettingsProfile` | `projectAgentSettingsProfileId` | Typed per-project-template default revisions materialized on Install and isolated from other projects/templates using the same profile family. |
| `AttachedAgentInstance` | immutable `attachmentId` plus optimistic `revision` | Private project/target derivation of one project template with non-secret instance config/session; revision is concurrency only and the instance has no SemVer, release, publication, or share identity. |
| `AgentSession` | `sessionId` | Initial intent, ordered transcript, summaries, and current configuration revision. |
| `AgentExecution` | `executionId` | Runtime lifecycle and immutable pins for source definition digest, project settings revision, attachment revision, prompt digest, provider-profile revision, effective policy, events/lease/cancellation/retry/result/usage. |
| `ProviderProfile` | `providerProfileId` | Account-owned non-secret provider/model/destination choices, egress class, capability snapshot, and opaque `secretRef`; secret material stays server-side. |
| `ArtifactRestriction` | restriction/revocation ID | Independent security quarantine/revocation state and reason for one exact artifact coordinate. |
| `AgentSettingsBinding` | `bindingId + scopeType + scopeId + settingKind` | Points Account policy, Imported definition, Project agent default, Attached instance, or private authoring-workspace scope to independent draft/active revisions; applicability is server-defined. |
| `AgentSettingsRevision<T>` | `revisionId` | Immutable revision metadata and schema-validated `CostPolicy`, `QuotaPolicy`, `ResourcePolicy`, `PromptQualityPolicy`, or `PromptAuditPolicy` body. |
| `AgentDefaultProfile` | profile ID/version | Reviewed family seed materialized independently per `ProjectAgentTemplate` and used as that project's Reset target; never exceeds account/deployment ceilings. |
| `EffectiveAgentPolicySnapshot` | `policySnapshotId` | Immutable strict intersection plus all contributing revision IDs used by one execution or evaluation. |
| `BudgetReservation` / `QuotaReservation` | reservation ID | Idempotent admission holds tied to execution/evaluation, expiry/lease, settlement, and reconciliation state. |
| `UsageLedgerEntry` | ledger-entry ID | Append-only estimated/actual/reconciled usage and cost attribution with provider price snapshot. |
| `PromptAuthoringWorkspace` | `workspaceId` | Account-private draft owned through an explicitly imported definition; Release creates another private immutable definition artifact without mutating a project template/attachment. |
| `PromptDraftRevision` / `PromptDraftFile` | draft revision/file ID | Contained package-local prompt assets, variables, schemas, content refs/digests, and optimistic revision. |
| `PromptEvaluationSuite` / `PromptEvaluationRun` | suite/run ID | Versioned fixtures/rubrics and exact-digest evaluation evidence, including evaluator/provider/policy pins, cost, and stale state. |
| `PromptAuditPolicy` / `PromptAuditRun` / `PromptAuditFinding` | policy/run/finding ID | Versioned static security/compliance/provenance rules, exact draft/ruleset/policy pins, typed severity/location/remediation state, and release-gate result. |
| `PromptAuditEvent` | `auditEventId` | Append-only integrity-linked metadata for edits, validations, evaluations, reviews, releases, reveals, exports, and publications. |

### Manifest v1 shape

The canonical manifest shape is `../docs/11-agent-manifest-and-product-model.md`; where this list
differs, docs/11 governs. In particular: camelCase field names, a top-level `$schema` reference
(not a `schemaVersion` string), `provenance` (not `publishing`), and typed
`contracts.{inputSchema, outputSchema}` alongside `inputs.{reads, requiredConfig}` and a named
`outputs[]`. This section is an implementation elaboration that must conform to docs/11.

Required top-level fields:

- `$schema`, `id`, `name`, `version` (SemVer), `category`, `purpose`, `description`.
- `roles[]`: broad human-facing classification such as Planning, Debugging, or Explanation.
- `capabilities[]`: stable semantic behavior IDs and optional contract versions used for discovery, orchestration, compatibility, and authorization.
- `delegatesTo[]`: explicit preferred/required agent IDs used in composition; capability-based discovery remains the default for substitutable implementations.
- `tools[]`: allowlisted tool ID, permissions, optional configuration schema; never executable source.
- `compatibleTargets[]`: target kind and optional node capability predicates.
- `contracts`: `inputSchema` / `outputSchema` references (canonical typing, per docs/11).
- `inputs`: `reads` (context consumed) and `requiredConfig`.
- `outputs`: named output contracts and mutation intent.
- `configuration`: JSON Schema, UI-safe annotations, defaults, secret references.
- `prompts`: package-local system/instruction asset paths, digests, variables, and schema references.
- `providerRequirements`: required/optional capabilities, modality, context window, streaming/tool-call/structured-output needs.
- `runtime`: execution mode, timeout, retry ceiling, review policy, concurrency policy, memory policy, token/cost bounds.
- `settingsDefaults`: schema-valid, non-secret seed suggestions and a reviewed default-profile ID for one exact artifact; these are neither active account policy nor permission grants.
- `provenance`: publisher, license, trust metadata, artifact digest.

For prompt-backed agents, `prompts` is an asset declaration, not a free-form prompt body or global filename. Each entry includes a role, safe package-relative `path`, content digest, required variables, and optional output-schema reference. Exact immutable definitions are stored side-by-side under a logical layout such as `agents/<publisher-namespace>/<agent-id>@<major>/versions/<exact-version>/<artifact-digest>/`. Account imports and project templates reference exact stored artifacts rather than replacing bytes; attached instances remain unversioned derivations while execution snapshots preserve the exact resolved source/prompt facts.

Illustrative shape:

```json
{
  "id": "agent.debug-agent",
  "version": "1.0.0",
  "prompts": {
    "system": {
      "path": "prompts/default_preamble.txt",
      "sha256": "<digest>",
      "variables": []
    },
    "instruction": {
      "path": "prompts/debug_prompt.txt",
      "sha256": "<digest>",
      "variables": ["nodeCode", "runtimeError", "dataflowContext"]
    }
  }
}
```

The runtime resolves paths relative to the validated source-definition artifact pinned by the project template, rejects absolute paths, `..`, symlink escapes, missing assets, and digest mismatches, and never accepts a client-supplied prompt path.

Capabilities describe **what** the agent does; prompts describe **how this package version implements it**. A valid capability resembles `node.explain`, `code.debug.diagnose`, or `workflow.plan.create`. Values such as `single_box_explanation_prompt`, `debug_prompt`, or any `.txt` path are invalid capability IDs.

Reviewed default profiles seed every enabled installation, then account/deployment policy clamps the materialized typed revisions:

| Default profile | Agents | Additional conservative defaults |
| --- | --- | --- |
| `interactive-report` | `agent.chat-agent`, `agent.dataflow-explainer`, `agent.node-explainer` | Foreground, report-only, no mutation tools, one concurrent execution per project template, and evaluation required after prompt changes. |
| `planning-analysis` | `agent.dataset-finder`, `agent.execution-subtask-planner`, `agent.dataflow-task-planner`, `agent.workflow-suggester`, `agent.plan-coherence-validator`, `agent.syntax-analysis-agent`, `agent.task-refresh-agent`, `agent.keyword-binding-agent` | Structured output, bounded background work, no direct mutation, and deterministic regression suite before Release. |
| `mutation-proposal` | `agent.node-builder`, `agent.debug-agent`, `agent.node-content-builder`, `agent.connection-builder`, `agent.package-recommendation` | Review-before-apply, stricter tool/resource ceilings, and quality gate plus authorized human approval before shared release. |
| `orchestration-mutation` | `agent.dataflow-builder` | Parent/child work shares an aggregate reservation, delegated agents keep their tighter policies, concurrency is bounded, and every install or graph mutation remains review-gated. |
| `evaluation-disabled` | `agent.generated-content-evaluator` | Unavailable and unable to run or self-certify until OQ-007 supplies an approved prompt and contract. |

All enabled profiles inherit account budgets, use the deployment `standard` resource class unless a stricter authorized class applies, require an explicit provider profile, allow network only for that provider and authorized tools, and prohibit local-to-remote fallback. The profile registry is versioned/reviewed; manifest suggestions cannot create a new trusted profile implicitly. Every explicit project template materializes its own project-private revisioned profile even when several templates reuse the same family, so Reset or tightening cannot mutate another template, project, imported definition, or attachment.

### Required prompt-backed built-in agents

The following thirteen available prompt behaviors and one planned evaluator become hookable-agent packages rather than raw prompt invocations. Only validated packages are registered; the evaluator row documents the OQ-007 target contract and remains absent/blocked until approved:

| Agent ID | Semantic capabilities | Prompt asset | Primary hook | Responsibility |
| --- | --- | --- | --- | --- |
| `agent.chat-agent` | `conversation.respond`, `attachment.refine` | `prompts/chat_prompt.txt` | Canvas or selected target | Contextual conversation/refinement. |
| `agent.debug-agent` | `code.debug.diagnose`, `code.fix.propose` | `prompts/debug_prompt.txt` | Code/executed node | Diagnose runtime or code failures. |
| `agent.dataflow-explainer` | `dataflow.explain` | `prompts/explanation_prompt.txt` | Canvas/dataflow | Explain the complete dataflow. |
| `agent.node-explainer` | `node.explain`, `node.output.interpret` | `prompts/single_box_explanation_prompt.txt` | Node | Explain one node and its context. |
| `agent.node-content-builder` | `node.content.generate` | `prompts/new_content_prompt.txt` | Node/canvas | Propose node content; review before apply. |
| `agent.execution-subtask-planner` | `execution.followup.plan` | `prompts/new_subtask_from_exec_prompt.txt` | Executed node/canvas | Derive follow-up work from execution. |
| `agent.dataflow-task-planner` | `workflow.plan.create` | `prompts/new_subtasks_prompt.txt` | Canvas | Decompose a mission into subtasks. |
| `agent.connection-builder` | `connection.propose` | `prompts/new_connection_prompt.txt` | Connection/selected nodes | Propose valid connections; review before apply. |
| `agent.workflow-suggester` | `workflow.suggest` | `prompts/workflow_suggestions_prompt.txt` | Canvas | Suggest workflow structure/resources. |
| `agent.plan-coherence-validator` | `workflow.coherence.validate` | `prompts/evaluate_coherence_subtasks_prompt.txt` | Canvas | Validate task/dataflow coherence. |
| `agent.generated-content-evaluator` | `content.quality.evaluate` | `prompts/evaluate_generated_content_prompt.txt` | Node/canvas | Evaluate generated output quality. |
| `agent.syntax-analysis-agent` | `code.syntax.analyze` | `prompts/syntax_analysis_prompt.txt` | Code node | Analyze syntax using `syntax_analysis_preamble.txt`. |
| `agent.task-refresh-agent` | `workflow.plan.refresh` | `prompts/task_refresh_prompt.txt` | Canvas | Re-plan after context or execution changes. |
| `agent.keyword-binding-agent` | `workflow.keyword.bind` | `prompts/keywords_binding_prompt.txt` | Canvas/nodes | Bind task keywords to graph elements. |

All except syntax analysis link `prompts/default_preamble.txt` as the system asset unless a reviewed manifest declares a different system prompt. Syntax analysis links `prompts/syntax_analysis_preamble.txt`. Repository inspection on 2026-07-16 found no `evaluate_generated_content_prompt.txt` or current call site; `OQ-007` tracks sourcing/approval and that agent cannot ship until its artifact and contracts exist.

Live fields such as installation state, publication state, and execution status must not be stored in the immutable manifest. They are joined into view models by application mappers. This corrects the conceptual shorthand in `11-agent-manifest-and-product-model.md` while preserving its UI mapping.

### Validation and compatibility

- Reject unknown schema major versions; tolerate documented additive minor fields.
- Normalize IDs, SemVer, categories, target kinds, semantic capability IDs/contract versions, role/delegate IDs, prompt asset paths, and schema references.
- Detect duplicate `(publisherNamespace, id, exactVersion)` and reject a different digest for that coordinate; identical coordinate/digest registration is idempotent.
- Validate defaults against configuration schemas and capability taxonomy, tool, and delegated-agent existence. Reject prompt-like capability IDs containing `_prompt`, file extensions, or path separators.
- Resolve provider compatibility before run and surface actionable missing capabilities.
- Preserve unknown JSON-safe output payloads for audit while mapping supported text, object, list/tuple-equivalent arrays, tabular, artifact, tool-call, and streaming-delta result types.
- Validate that manifests only declare server-registered typed tool IDs. Declarations request capabilities; they never grant account, dataflow, provider, context, or tool permission.

## 7. LangChain Creation and Instantiation Flow

### Stable runtime contracts

`AgentRuntime` application port:

- `instantiate(definition, attachment, provider, contextSnapshot) -> RuntimeHandle`
- `run(handle, command, idempotencyKey) -> ExecutionReceipt`
- `stream(executionId, cursor) -> AsyncIterator<AgentEvent>`
- `status(executionId)` and `cancel(executionId)`; event-stream resume reads persisted events after a cursor and does not resume or replay provider/tool work.

Normalized events: `queued`, `started`, `plan`, `agent_delegated`, `tool_requested`, `tool_started`, `tool_result`, `message_delta`, `review_required`, `mutation_applied`, `completed`, `cancelled`, `interrupted`, `failed`.

### Instantiation sequence

1. Load the private `AttachedAgentInstance`, its selected-project `ProjectAgentTemplate`, and the template/instance's resolved immutable definition manifest; verify project membership, attachment revision, source coordinate/digest, and trust without retargeting the instance from a newer import/catalog/template source.
2. Authorize the actor independently for the project template, attachment, target, each context read, provider profile/destination, tool grant, and requested mutation. Import, project installation, or attachment alone grants none of these permissions.
3. Validate target compatibility, required config, opaque credential references, data classification/egress eligibility, provider capabilities, custom-endpoint network policy, and local resource health.
4. Snapshot only manifest-declared context reads and record provenance.
5. Resolve requested semantic capabilities only across compatible templates installed in the active project, persist the chosen project template/source definition, then resolve its digest-verified prompt assets, explicit delegates, and allowlisted tools.
6. Resolve provider adapter and create the LangChain chat model through a provider bridge.
7. Construct LangChain prompts, structured-output parser, tools, memory/checkpointer, and executor inside `LangChainRuntimeAdapter`.
8. Persist source definition digest, project settings revision, attachment revision, prompt digest, provider-profile revision, effective-policy snapshot, reservations, execution record, and lease before invoking the model; renew its heartbeat while work is owned and emit ordered events.
9. Pause at `review_required` for any mutation; apply only an authorized, revision-checked proposal.
10. Normalize results/errors, persist transcript/events/usage, release resources, and update terminal status.

The adapter owns LangChain callbacks, message conversion, tool wrappers, retry integration for safe provider transport operations, and checkpointer mapping. Domain and UI code see only contracts above. Startup reconciliation marks expired nonterminal leases `interrupted`, preserves committed events/transcript, and never replays a provider or tool call automatically. An explicit retry creates a new `executionId` with `retryOfExecutionId`; mutation idempotency and audit state prevent a prior side effect from being applied twice.

### Orchestration

Dataflow Builder uses the same runtime contract as specialized agents. Delegation requests semantic capabilities and resolves manifest-defined templates installed in the active project by contract, target, provider/tool requirements, trust, and source policy. `delegatesTo` may express a compatible preferred implementation but does not replace capability discovery. A missing template produces a reviewed explicit `Install in project` proposal for a definition already visible to that actor; it never silently imports, installs, grants permissions, attaches, executes, publishes, shares, or falls back remotely. Child executions are linked by `parentExecutionId`. The orchestrator may plan/evaluate without confirmation, but project install and every graph/dataset mutation remain reviewed proposals.

## 8. Import, Project Installation, Attachment, Publication, and Sharing

### Lifecycle distinctions

| State | Source of truth | Key behavior |
| --- | --- | --- |
| Immutable definition artifact | content-addressed `AgentDefinitionArtifactRepository` | Exact manifest/package bytes are keyed by `AgentArtifactCoordinate`; versions coexist and never mutate in place. |
| Account imported | `AccountImportedAgentRepository` | Private reusable definition ownership/provenance/validation created only by explicit Import; no project state changes. |
| Global/built-in visible | deployment catalog/built-in registry | Reusable definition is browseable and eligible for explicit project install; a global/built-in item is not user-republishable. |
| User published | publication repository keyed by `publicationId` | Owner-only validated promotion sourced only from one `AccountImportedAgent`; publication never installs it. |
| Restricted/quarantined | artifact restriction repository | Security state independent of publication; blocks new install and execution while preserving evidence and installed references. |
| Project installed | `ProjectAgentTemplateRepository` keyed by `projectAgentTemplateId` + project/dataflow key | Explicit selected-project palette entry referencing one visible exact definition and independent project default profile. |
| Attached instance | private attachment repository keyed by `attachmentId` | Target-bound configured derivation of one project template; optimistic revision only, no version/publication/share lifecycle. |
| Session/execution | session, execution, and event stores | Persistent interaction/audit state; an ephemeral runtime owner is represented by a lease/heartbeat. |
| Garbage-collection eligible | repository-derived projection | Artifact bytes may be removed only after no installation, attachment, active work, retained history, publication, or backup obligation requires them. |

- Import validates one bounded manifest package in private staging and atomically creates its immutable artifact plus `AccountImportedAgent`. It succeeds without an open project, changes no project/palette, and never installs or publishes automatically.
- Publish accepts only an owned validated imported-agent ID plus exact artifact; it never accepts a global/built-in/project-template/attachment ID and never invokes Install. System-curated catalog ingestion is a separate administrative path.
- Install requires an explicit visible exact source plus selected authorized `projectId`/current `dataflowId`, then atomically creates one `ProjectAgentTemplate` and independent `ProjectAgentSettingsProfile`. Only that project's drawer/palette cache changes; import is not a prerequisite for globally visible definitions and Install never publishes.
- Project update is explicit: preview compatibility, retain new exact definition bytes side-by-side, and change the project template's selected source only for future attachments. Existing instances retain their operational source/template facts until an explicit migration/detach.
- Attach starts only from the active project's palette and creates a private `AttachedAgentInstance` plus session from that project's template. It has a stable `attachmentId` and optimistic `revision`, never a SemVer/publication/share record.
- Detach removes/tombstones only that private instance according to OQ-008; the project template remains installed. Project Uninstall removes only the selected template after a serialized same-project attachment/review/nonterminal-execution check and never detaches silently.
- Private imported-definition deletion and unpublish are distinct. Exact bytes remain retained or deletion is blocked while project templates, attachments, histories, publications, or backups require them; unpublish changes only global discovery.
- Quarantine/revocation is a security action distinct from unpublish: it blocks new installs and execution of affected copies, exposes a safe `Revoked/Blocked` state, preserves evidence, and requires an authorized remediation/unblock action.
- Garbage collection is internal and reference/retention aware; it is not an alias for uninstall, delete, or unpublish.

## 9. Assignment, Configuration, Refinement, Detachment, and Reuse

1. Explicit Import returns an account-private `AccountImportedAgent` and updates only My Imports. Explicit Install from My Imports or Global Catalog returns a `ProjectAgentTemplate` and updates only the selected project's Installed view/palette.
2. Drag begins only from the active project's installed-template palette. Compatibility selectors evaluate the source manifest predicates against normalized target descriptors.
3. Compatible targets receive labeled indicators; drop on incompatible targets is rejected without mutation.
4. Successful attach creates a private `AttachedAgentInstance` and `AgentSession`, then renders a persistent dock tile.
5. Clicking a tile opens the shared chat keyed by `attachmentId/sessionId`; previous/next follows a stable canvas order.
6. Governed configuration is never changed by a chat command. Clear settings controls open one shared `AgentSettingsModal` shell with dedicated Cost, Quotas, Resource policies, Prompt quality, Prompt editor, and Prompt audit screens; chat may deep-link to an authorized screen or propose a draft but cannot save, activate, release, or publish it.
7. The drawer header opens Account policy. An imported-definition detail exposes owned Prompt editor/quality/audit and separate Install in project/Publish actions. A project-template detail opens Project agent default policy with prompt provenance read-only and no Publish. The attachment chat header opens downward-only instance policy with prompt provenance read-only and no Version/Release/Publish/Share. Draggable palette rows remain action-free.
8. Cost/quota/resource and governance-policy changes follow Edit local form → Save server draft → Validate → explicit Activate. The previous active revision remains effective until activation; a running execution keeps its persisted effective-policy snapshot.
9. Prompt editing creates an authorized workspace only through an owned `AccountImportedAgent` created by explicit Import. Save affects only its draft; audit/evaluation/remediation/review precede Release of a new private imported artifact. Project-template update/Install and imported-only global Publish are separate explicit actions. Built-in/global/project-template/attachment sources remain read-only; future export/fork packaging and re-import are out of scope.
10. Reusing a visible definition in another project requires a separate Install and project profile; reusing a project template creates another private attachment/session that does not share instance configuration, memory, overrides, or execution state.
11. Disable preserves attachment and history but prevents new runs; detach requires confirmation during an active run and cancels or waits according to the chosen action.
12. Reopen, refresh, reconnect, and dataflow switch hydrate attachments/sessions and active settings from server truth, purge unauthorized/private modal state, and resume event streams from the last cursor.

## 10. LLM Provider Abstraction and Capability Model

### Provider port

`LLMProviderAdapter` must expose:

- metadata and `discoverCapabilities()`;
- account-level `ProviderProfile` configuration schema and `validateConfiguration()` without accepting raw secrets from execution commands;
- secret-reference validation without secret disclosure;
- `listModels()`, model metadata, and compatibility checking;
- destination classification, local/remote declaration, and `validateEgress(contextClassification)`;
- `initialize()`, `healthCheck()`, `invoke()`, `stream()`, `cancel()`, and `close()`;
- normalized timeout/retry/cancellation and usage metadata.

Capability flags include chat, streaming, tools, parallel tools, structured output/JSON schema, vision, embeddings if needed later, max context/output, token counting, cancellation, and local resource requirements.

### Adapter strategy

- Cloud/native API adapter for supported first-party SDK behavior.
- OpenAI-compatible adapter for existing configured endpoints, including the first local Gemma path through Ollama under DEC-016.
- A dedicated local Gemma adapter is deferred until resource profiling demonstrates a capability or isolation need that the OpenAI-compatible Ollama path cannot meet.
- Hugging Face adapter separating hosted inference from local Transformers execution because credentials, cancellation, and resource behavior differ.
- `LangChainModelBridge` is the only module translating provider adapters/configuration into LangChain model objects.

Provider errors normalize to stable codes: `credentials_missing`, `credentials_expired`, `model_not_found`, `capability_unsupported`, `egress_denied`, `destination_forbidden`, `rate_limited`, `resource_exhausted`, `timeout`, `cancelled`, `network`, `provider_unavailable`, and `invalid_response`. Retry only transient, idempotent operations with capped exponential backoff and jitter. Never retry a tool or mutation without its idempotency key.

Provider profiles store non-secret metadata plus an opaque `secretRef`; secret material is encrypted/secret-managed, write-only through credential APIs, resolved only on the server, rotated independently, and never returned by read APIs. Custom remote base URLs permit approved schemes/ports only, resolve and revalidate DNS for every connection/redirect, and deny loopback, link-local, private-network, metadata-service, credential-bearing URL, and rebinding destinations. Explicitly configured local profiles use a separate administrator-controlled allowlist. Local unavailability surfaces an error and never causes implicit remote fallback.

## 11. Reuse and Shared Abstractions

Reuse or carefully extract:

- Catalog drawer/layout, search/filter primitives, status/version/category chips, confirmation patterns, and `CatalogPublishPill` from package/data catalog surfaces.
- Dataset pending-install view approach and cross-surface refresh event pattern, generalized into entity-scoped mutation state where appropriate.
- Dataset palette row semantics and DnD mechanics, with agent-specific payload and compatibility resolution.
- Backend dataset domain/application/infrastructure organization, manifest validation approach, installed refs, and API error mapping.
- Existing authentication, user settings, project/dataflow persistence, toast, modal, focus, and event conventions.
- Current prompt files as registry sources after adding metadata and schemas.

Do not retain `LLMProvider.tsx` as a general-purpose owner of agent behavior. Move its agent/LLM request responsibility into the frontend `agents/` module, where it may become a temporary compatibility adapter or a thin client for the backend execution API while legacy callers migrate. Remove the old path after all consumers use the agent module public interface.

### Mandatory ownership rule

Use the following decision test for every affected file:

- If its primary purpose is to define, configure, invoke, stream, observe, display, attach, refine, or orchestrate an agent/LLM, it belongs under `agents/`.
- If it is a generic HTTP, event, auth, catalog-layout, modal, form, schema, storage, or design-system primitive used independently by multiple features, it remains shared.
- If a dataset/node/flow operation is callable by an agent but remains a first-class non-agent application operation, keep the operation in its owning domain and expose it to agents through a typed tool/context adapter inside `agents/`.
- Cross-feature imports must point to documented public entry points; deep imports into agent infrastructure are prohibited.

## 12. Proposed Folder and Module Structure

```text
utk_curio/backend/app/agents/
  __init__.py          public application API only
  domain/              manifest.py, models.py, policies.py, errors.py
    settings/           scope.py, revision.py, cost.py, quota.py, resource.py,
                       prompt_quality.py, prompt_audit.py, effective_policy.py
    authoring/          workspace.py, prompt_revision.py, evaluation.py
  application/         catalog.py, artifacts.py, imports.py, project_templates.py, attachments.py, sessions.py,
                       executions.py, lifecycle.py, publishing.py, orchestration.py,
                       provider_profiles.py, ports.py,
                       settings_query.py, settings_drafts.py, settings_activation.py,
                       execution_admission.py, cost_policy.py, quota_policy.py,
                       resource_policy.py, prompt_authoring.py, prompt_evaluation.py,
                       prompt_release.py, prompt_audit.py
  infrastructure/
    repositories/      catalog.py, imported.py, project_templates.py, attachments.py, sessions.py,
                       settings.py, reservations.py, usage_ledger.py,
                       authoring.py, evaluations.py, prompt_audit.py
    runtime/            langchain_adapter.py, events.py, checkpoints.py
    providers/          registry.py, openai.py, openai_compatible.py,
                       ollama_profile.py, huggingface_hosted.py, huggingface_local.py
    prompts/            registry.py, loader.py, asset resolver and metadata
    tools/              registry.py, adapters.py
  schemas/              manifest-v1.json, api.py, events.py
  routes.py

utk_curio/frontend/urban-workflows/src/agents/
  index.ts                 public feature API; no infrastructure exports
  api/                     agentApi.ts, executionStream.ts
  components/              catalog/, palette/, attachment/, dock/, chat/, settings/
  settings/                types/, api/, hooks/, state/, services/, components/
                           AgentSettingsModal.tsx, AgentSettingsButton.tsx,
                           CostPolicyScreen.tsx, QuotaPolicyScreen.tsx,
                           ResourcePolicyScreen.tsx, PromptQualityScreen.tsx,
                           PromptEditorScreen.tsx, PromptAuditScreen.tsx
  hooks/                   catalog, import, project-template, attachment, session, execution, settings hooks
  services/                mappers, commands, compatibility adapters
  state/                   normalized query keys, selectors, execution reducer
  providers/               AgentExecutionProvider.tsx, legacy LLM bridge
  utils/                   agent-only validation, status, DnD helpers
  types/                   DTOs, events, view models
  tests/                   unit/, components/, integration/, accessibility/

  (no sharedResults/ module — reuse existing flow-sharing per D-0 = B; no SharedResultViewer/API/DTO is built)

agents/                    versioned built-in/imported agent artifacts
```

Exact file naming should follow neighboring modules when implementation begins. Shared catalog extractions belong under existing shared catalog directories, not inside `agents`.

### Existing-file reorganization plan

The implementation phase must inventory the repository again before moving files. Based on the current tree, the initial migration map is:

| Current responsibility/path | Target ownership | Migration rule |
| --- | --- | --- |
| `frontend/.../src/providers/LLMProvider.tsx` | `frontend/.../src/agents/providers/` | Move request/state behavior; expose a narrow agent client/context. Keep a temporary re-export only during migration. |
| `frontend/.../src/components/LLMChat.tsx` and its stylesheet | `frontend/.../src/agents/components/chat/` | Move because the component is LLM/agent-specific; migrate toward unified attachment chat. |
| LLM logic embedded in `WorkflowGoal.tsx`, `components/styles.tsx`, and `MainCanvas.tsx` | `src/agents/hooks`, `services`, and public commands | Extract raw prompt/request/orchestration behavior. Migrate `MainCanvas.tsx` flow-level `explanation_prompt` specifically to project-installed `agent.dataflow-explainer`, not the node-explanation workflow. |
| `components/editing/NodeEditor.tsx` and `components/editing/NodeExplanation.tsx` | **No change (`DEC-041`)** — the Explanation tab, its nav/loading/error states, cache, and direct `single_box_explanation_prompt` request are retained as-is; the former removal task is cancelled and must not be reintroduced. An optional `Explain with Node Explainer` affordance may additionally open the standard install/attach/chat path. | Retention verified by a regression test that the tab renders (`RISK-EXPLAIN-002`). |
| `components/packages/editing/NodeTemplateConfigModal.tsx`, `utils/canvasTemplateConfig.ts`, and `UniversalNode.tsx` explanation flags | **No change (`DEC-041`)** — `hasExplanation` authoring/UI behavior and propagation are retained. | Saved flags keep their current meaning; no migration. |
| Agent catalog/palette/dock/attachment/refinement code introduced by this project | `src/agents/components`, `hooks`, `state`, `services` | Create directly in the feature module; do not place it in dataset/node menu trees. |
| Agent cost/quota/resource settings, prompt quality/editor/audit UI, API clients, drafts, selectors, and authorization projections | `src/agents/settings/` | Create as one feature-owned modal system with six dedicated screens; only generic dialog/form/editor primitives stay shared. |
| Generic `apiFetch`, auth, toast, modal, catalog layout, and design-system elements | Existing shared locations | Preserve and consume through adapters; do not move into agents. |
| LLM dispatch and configuration logic currently embedded in `backend/app/api/routes.py` | `backend/app/agents/application` and `infrastructure/providers` | Extract provider selection, validation, invocation, streaming, and errors; route layer delegates to agent services. |
| `utk_curio/llm-prompts/*` | Exact, content-addressed `agents/<publisher>/<id>@<major>/versions/<version>/<digest>/prompts/` artifacts managed by backend agents infrastructure | Move into one canonical package per prompt-backed agent; load through the prompt asset registry and update packaging. |
| Future LangChain executors, checkpoints, callbacks, tools, manifests, and orchestration | `backend/app/agents/` submodules | Must never be introduced into general API, project, dataset, node, or collaboration modules. |
| Settings revision, admission/reservation, prompt authoring/evaluation/release/audit behavior | `backend/app/agents/domain`, `application`, and `infrastructure` settings/authoring modules | Keep server-authoritative policy and prompt-governance behavior out of generic settings, catalog, provider, and route modules. |
| Dataset/node/flow mutations exposed as tools | Original domain service plus `backend/app/agents/infrastructure/tools/` adapter | Preserve domain ownership; the adapter authorizes and normalizes agent tool calls. |
| `backend/app/projects/routes.py` shared GET and `projects/services.py::load_shared_project` | Unchanged (D-0 = B) | No agent change to flow sharing; the agents feature adds no `SharedFlowResult` projector and does not modify or retire the existing share route. |
| `useWorkflowOperations.ts::loadSharedProject` | Unchanged (D-0 = B) | No agent change; no new shared-result client/viewer is built. |

After each move, update all imports, package manifests, test mocks/fixtures, build configuration, and documentation in the same focused change. Do not leave parallel old/new implementations.

## 13. Data and State Handling

### Sources of truth

| Data | Authority |
| --- | --- |
| Immutable definition artifacts | `AgentDefinitionArtifactRepository` keyed by exact `AgentArtifactCoordinate` |
| Catalog agents and versions | Deployment catalog repository referencing exact coordinates |
| Account imports | `AccountImportedAgentRepository` keyed by `accountImportedAgentId`, owning one current private exact artifact/provenance/validation state |
| User publications | Publication repository keyed by `publicationId`, eligible imported-agent ID, and exact coordinate |
| Project templates/palette | `ProjectAgentTemplateRepository` keyed by `projectAgentTemplateId` and selected project/dataflow scope key |
| Attached instances/config | Private project/dataflow attachment records keyed by stable `attachmentId` plus concurrency `revision`, referencing one project template |
| Sessions/transcripts | Server session/event store |
| Runtime instances/status | Execution/event store plus lease-aware runtime coordinator; terminal and `interrupted` history persisted |
| Provider/model config | Account provider-profile repository; encrypted secret vault/reference store |
| Artifact restrictions | Server security restriction/quarantine repository |
| Provider capability snapshot | Provider registry/health cache with timestamp |
| Policy bindings and revisions | Account-private settings repository keyed by scope and setting kind; independent active/draft revision pointers |
| Per-agent defaults | Reviewed default-profile registry plus independently materialized project-template settings profiles/bindings |
| Effective policy per run | Immutable execution/evaluation snapshot containing definition digest, project settings revision, attachment revision, prompt/provider pins, and resolved policy |
| Cost/quota/resource admission | Reservation repositories, provider price snapshots, and append-only usage ledger |
| Prompt drafts | Account-private authoring workspace and contained prompt-draft object store; never the artifact repository |
| Prompt quality evidence | Versioned suite/fixture and evaluation-run repositories pinned to exact content and policy inputs |
| Prompt audit | Append-only integrity-linked audit repository; protected content snapshots/diffs remain separately authorized and encrypted |
| Derived UI state | Memoized frontend selectors over normalized query data |

### Mutation and synchronization rules

- Use entity-keyed query caches and mutation keys. Cancel/merge superseded reads and ignore responses older than the entity revision.
- Optimistically show pending import/project-install/publish/attach rows only when rollback is deterministic; otherwise retain current content with an inline busy state.
- Import/project-install/uninstall/publish/unpublish/attach/detach and settings draft/activate/release endpoints accept idempotency keys and expected revisions; no command invokes another lifecycle command.
- Each settings screen queries only its own active/draft/inherited/effective read model. Dirty form/editor text remains local and account-scoped; prompt bodies are memory-only and never enter shared/global query caches, local storage, URLs, analytics, or transcripts.
- A policy save changes only that setting kind's draft. Activation compare-and-swaps the binding pointer and invalidates only exact settings/effective-policy query keys; stale writers receive a stable conflict with server revision/diff metadata.
- Execution/evaluation admission resolves the strictest deployment ∩ account ∩ project-template ∩ attached-instance constraints, atomically reserves budget/quota/resource capacity, persists all reproducibility pins plus reservation IDs, then queues work. Clients cannot authorize work with an estimate.
- Settlement appends actual usage against the provider price snapshot; expired or ambiguous reservations reconcile through leases and never disappear, undercount, or trigger replay. Unknown pricing fails closed when a monetary hard cap applies.
- Any prompt edit changes the draft digest and marks older evaluation evidence stale. Release compare-and-swaps the workspace head, verifies evidence/review against the exact digest, creates a new immutable coordinate, and appends audit evidence atomically.
- Stream events carry monotonic sequence numbers. Reconnect with `Last-Event-ID`/cursor and deduplicate.
- Project/dataflow switching namespaces template/palette/attachment/session/settings queries by the current project key, tears down subscriptions for the prior project, and never carries installed templates/instances across projects.
- Logout/account switching cancels streams and clears account-import/global/project-template/palette/attachment queries, optimistic messages, prompt bodies/drafts, and selection before another principal can render.
- Never clear catalog, palette, dock, or transcript while background revalidation runs; show stale-while-revalidate indicators where useful.
- Active execution status is derived from the latest execution event, not duplicated independently on the manifest or attachment.
- Attachment creation and final project-template uninstall check use the same project-template lock/serializable transaction so one side of a race succeeds and no dangling instance exists. Imported-definition delete/Release/Publish use independent locks and retained-reference rules.

State after actions:

- Import: My Imports changes for the account; no project template/palette/attachment/publication changes.
- Install/update: only the selected project's Installed view/palette/default profile changes; other projects and existing attachments remain unchanged.
- Project uninstall: only that project's palette row disappears after server confirmation and same-project zero-live-reference check; imported/global definition bytes/publication remain independent.
- Private delete, unpublish, quarantine/revocation, and garbage collection update only their own lifecycle projections according to Section 8.
- Imported-only Publish/unpublish: global discovery badge changes; account import, every project template, and every attachment remain unchanged.
- Attach/configure/detach: only the selected project's instance/session collections update; project template/import/publication remain unchanged, and the revision is never shown as a version.
- Save settings draft: active/effective policy remains unchanged and a visible Saved draft state is scoped to that setting kind.
- Activate settings: new executions use the new immutable effective snapshot; already-admitted/running executions retain their prior snapshot unless a separate privileged kill switch/quarantine stops them.
- Prompt Save/audit/evaluate/release: applies only to an owned import/workspace. Release adds a new private imported definition artifact; audit/evaluation never install/publish, and every project template/attachment remains unchanged until separate explicit actions.
- Reconnect/refresh: server snapshot hydrates, then event cursors resume.

## 14. API and Service-Layer Requirements

Canonical resource API (transport schemas return exact definition coordinates where applicable; mutable resources use their own typed IDs):

- `GET /api/agents/catalog` lists globally visible reusable definitions. It supports project-install discovery but no user republish command for global/built-in entries.
- `GET/POST /api/agents/imports`; `GET/PATCH/DELETE /api/agents/imports/{accountImportedAgentId}`. POST streams a bounded manifest package through private staging and atomically returns one private import/artifact; it accepts no project key and never installs or publishes.
- `GET/POST /api/agents/publications`; `GET /api/agents/publications/{publicationId}`; `POST /api/agents/publications/{publicationId}/unpublish`. User publication creation requires an owned validated `accountImportedAgentId` plus its exact artifact and rejects global/built-in/project-template/attachment IDs. It never invokes project Install.
- `GET/POST /api/agents/artifact-restrictions`; `GET/PATCH /api/agents/artifact-restrictions/{restrictionId}` is privileged and targets an `artifactId` plus exact coordinate; it never aliases unpublish or private deletion.
- `GET/POST /api/dataflows/{dataflowId}/agent-templates`; `GET/PATCH/DELETE /api/dataflows/{dataflowId}/agent-templates/{projectAgentTemplateId}`. The dataflow ID is the current project scope key. POST explicitly installs a visible exact definition, materializes independent defaults, and updates only that project's palette; DELETE repeats a same-project live-reference check and never detaches.
- `GET /api/dataflows/{dataflowId}/agent-templates/{projectAgentTemplateId}/usage` returns only same-project blocking references visible to the authorized actor; destructive services recheck transactionally.
- `GET/POST /api/dataflows/{dataflowId}/agent-attachments`; `GET/PATCH/DELETE /api/dataflows/{dataflowId}/agent-attachments/{attachmentId}`. Creation accepts a same-project `projectAgentTemplateId`; PATCH uses optimistic instance `revision`. No attachment route accepts SemVer, Release, Publish, or Share.
- `GET/POST /api/dataflows/{dataflowId}/agent-attachments/{attachmentId}/sessions/{sessionId}/messages`.
- `POST /api/dataflows/{dataflowId}/agent-attachments/{attachmentId}/executions`; `GET /api/dataflows/{dataflowId}/agent-attachments/{attachmentId}/executions/{executionId}`; nested event-stream, cancel, retry, and review-decision routes are explicit. Retry always returns a new execution linked to the interrupted/failed predecessor.
- `GET/POST /api/agents/provider-profiles`; `GET/PATCH/DELETE /api/agents/provider-profiles/{providerProfileId}`. `PUT /api/agents/provider-profiles/{providerProfileId}/credential` accepts write-only secret material and never returns it; nested models/capabilities/health reads remain account-scoped and server-authorized.
- Account policy uses `GET /api/agents/settings/account` plus typed draft/validate/activate/reset routes. Project-template defaults use matching operations under `/api/dataflows/{dataflowId}/agent-templates/{projectAgentTemplateId}/settings/{settingKind}`; attached-instance overrides use `/api/dataflows/{dataflowId}/agent-attachments/{attachmentId}/settings/{settingKind}` and can only tighten.
- Project-template and attachment `effective-policy` reads explain provenance. `POST /api/agents/cost-estimates` remains advisory; only execution/evaluation admission reserves capacity. Prompt screens are read-only at template/attachment scope and expose no release/publish command.
- `POST /api/agents/imports/{accountImportedAgentId}/authoring-workspaces` creates an owned draft only when that import was created by explicit drawer Import and remains authorized. Workspace prompt/validate/evaluation/audit/Release routes remain account-private; Release returns a new immutable private definition artifact/import revision and never installs, updates a project template, retargets an attachment, publishes, or shares. There is no authoring route for a built-in/global/project-template/attachment source.
- Prompt-audit policy uses the owned artifact/workspace setting draft/validate/activate contract where applicable. `GET/POST /api/agents/authoring-workspaces/{workspaceId}/prompt-audits`, `POST .../prompt-audits/{auditRunId}/cancel`, and finding-remediation routes create exact-digest/ruleset/policy-pinned runs and typed findings; unresolved required findings fail the Release gate.
- `GET /api/agents/imports/{accountImportedAgentId}/prompt-audit-events` and `/api/agents/authoring-workspaces/{workspaceId}/prompt-audit-events` provide the separate append-only governance-event facet with authorized cursor pagination and filters. Full reveal/diff/export requires narrower authorization, is rate-limited, and appends its own audit event.
- Sharing: no new agent sharing routes (D-0 = B). The agents feature adds no `/shared-results` or `/shared-flow-results/{shareId}` endpoint and does not modify or retire the existing `/api/projects/{projectId}/shared` route. It only guarantees agent-private data is not added as a new shared surface.

All write APIs require auth, authorization, CSRF protection where applicable, structured validation errors, idempotency, audit metadata, and revision conflicts. Draft/activation/attachment writes use `If-Match`/`expectedRevision`; stale state returns `412`. Exhausted cost/quota admission returns stable `429`/`retryAfter` where applicable. Imported-agent/publication/project-template/attachment/workspace IDs are never interchangeable. Nested dataflow routes retain project authorization. There is no Publish/Share route for project templates or attachments and no Install side effect on account import/publication routes. SSE is authenticated and cannot resume after logout/project/account switch; the existing shared result contains no SSE/execution continuation.

## 15. UI and UX Requirements

### Catalog and palette

- The Agents drawer clearly separates `Global Catalog`, `My Imports`, and `Installed in this project`; search/filter/sort/count/pagination state is scoped to the selected view.
- `Import package` validates a manifest package and ends on its private imported-definition detail. `Install in project` and eligible `Publish` are separate buttons; neither runs automatically.
- Global/built-in cards expose `Install in project`, never user Publish. My Imports exposes Install and only owned/validated Publish. Project-template cards expose `Installed in this project`, Settings, and Uninstall from project, never Publish/Share/global release.
- Install/orchestrator proposals name the selected project and requested context/tool/provider needs, while explaining that approval installs only that project template and does not import, attach, run, publish, share, or grant permissions.
- `AGENTS` palette lists only the active project's templates: icon, name, source definition version/category; whole row draggable. Project switch replaces the list and purges mismatched template/instance settings/session state.
- Buttons preserve width between pending/success states to prevent layout shift. Announce completion/failure through existing toast plus an ARIA live region.

### Attachment and dock

- Keyboard users can invoke “Attach agent,” move through compatible targets, and confirm/cancel without drag.
- Compatibility is communicated by label/icon as well as color. Incompatible reasons are available on focus/hover.
- Dock tiles are semantic buttons with agent name, target, status, and unread/review state in accessible text. Magnification must not move adjacent hit targets; honor reduced motion.
- Attached UI names its source project template, target, private scope, and status, but has no Version, Release, Publish, Share, or catalog action; optimistic `revision` is never user-facing version metadata.
- Focus returns to the originating tile when chat closes and to the palette row when attachment mode cancels.

### Unified chat

- Static Agents Catalog top bar; attachment navigation, name/icon, index/total, session label, editable pinned initial intent, target, transcript, quick replies, and composer.
- Transcript messages and tool/review/result cards use correct list/log semantics. Streaming updates are throttled and announcements summarized to avoid screen-reader noise.
- Review cards show exact proposed effects and explicit Apply/Reject. Destructive or graph-changing actions cannot be triggered by Enter on unrelated controls.
- Closing and reopening resumes the same transcript without clearing content or jumping scroll unexpectedly.
- Meet WCAG 2.2 AA with keyboard-complete workflows, non-color state communication, meaningful live announcements, focus restoration, zoom/reflow, reduced motion, and forced-colors support.

### Governed settings modals

- The drawer header exposes `Account policy`; an imported definition exposes owned Prompt editor/quality/audit; a project template exposes `Project agent default`; an attached chat exposes `Attached instance settings`. Compact cogs keep tooltip, unique accessible name, `aria-haspopup="dialog"`, and at least a 44-by-44 target. Shared views receive no trigger.
- One `AgentSettingsModal` dialog shell renders six directly addressable screens—Cost, Quotas, Resource policies, Prompt quality, Prompt editor, and Prompt audit—with icon-plus-text navigation. Screens are never nested dialogs; only one is open at a time.
- The modal header identifies agent/source and Account policy, Imported definition, Project agent default, or Attached instance scope. Account exposes Cost/Quotas/Resources; imported definition owns Prompt Editor/Quality/Audit; project template owns Cost/Quotas/Resources while prompt provenance/evidence is read-only; instance policy only tightens and prompt evidence is read-only. Project/instance screens never expose Release/Publish.
- Policy fields show editable, inherited, immutable-ceiling, and effective values plus Reset provenance naming the selected project template. Save cannot activate; Reset never changes another project, import, or instance.
- Prompt Editor exposes contained assets, variables/schema validation, diff/compare, private Save draft, and a separate Release workflow. Prompt Quality exposes static/schema/safety/regression checks, exact evaluator/provider/locality and estimated evaluation cost, Run/Cancel, stale evidence, and `Unavailable` when no approved evaluator exists; it never publishes. Prompt Audit supports typed policy Save/Validate/Activate where applicable, Run/Cancel of versioned static security/compliance/provenance audits, findings by severity/location, authorized remediation notes/state, and a separate append-only governance-history facet with filters and guarded reveal/export; it is not an execution transcript and never activates/releases/publishes by running.
- Prompt text stays in memory-only editor state and is purged on close, logout, or account switch. Unsaved-close/Escape requires confirmation. Small viewports use a full-screen dialog; focus is trapped and restored; navigation, editor fallback, validation summary, conflict resolution, evaluation progress, zoom/reflow, reduced motion, and forced colors are accessible.

### Node explanation

- Sharing is out of scope (D-0 = B): agents reuse Curio's existing flow-sharing; the feature adds no agent-private data as a new shared surface. No agent sharing UI is built.
- The Explanation tab in `NodeEditor.tsx` (tabs/nav/keyboard/accessibility state), the direct `NodeExplanation.tsx` call/cache, `hasExplanation` template configuration/propagation, and saved UI flags are all **retained unchanged** (`DEC-041` — the former removal is cancelled).
- `Explain with Node Explainer` may appear as a discoverability affordance into the standard selected-project Install → node Attach → unified Chat path, which **coexists** with the retained Explanation tab. Flow-level explanation in `MainCanvas.tsx` separately migrates to `agent.dataflow-explainer`.

## 16. Loading, Empty, Error, Success, and Recovery States

- Initial drawer/palette load: skeletons matching final geometry; distinguish empty Global Catalog, My Imports, and Installed in this project states.
- Background refresh: retain rows and indicate quiet refresh; no blanking.
- Pending mutation: disable only conflicting actions, allow navigation, and provide cancellability where safe.
- Stream interruption: show “Reconnecting,” retain partial transcript, resume from cursor, then offer Retry if exhausted.
- Expired execution lease/server restart: show `Interrupted`, retain committed transcript/events, and offer an explicit retry that creates a linked execution rather than replaying work.
- Provider/config error: identify missing credential/model/capability without exposing secret values; link to authorized settings.
- Settings: retain prior active/effective content while loading or saving a draft; distinguish inherited/read-only, dirty, validating, saved, conflict, forbidden, and stale states without layout shift.
- Admission denial: show which cost/quota/resource rule blocked work, its scope and reset/retry time, without exposing other-account usage or secret provider facts; no provider/tool call has begun.
- Prompt evaluation: show queued/running/completed/failed/cancelled/stale and evaluator-unavailable states; retain the draft and prior evidence while refreshing. Release remains disabled until exact-current required evidence and review pass.
- Import/Install/Publish remain separate pending/success/error states; completion copy says exactly which account import, selected project template, or global publication changed.
- Review conflict: re-fetch target revision, show changed context, and require regeneration or explicit refreshed review.
- Success: update all affected caches atomically and announce the result. Toasts supplement, not replace, persistent state.
- Partial orchestrator failure: preserve successful child results, identify failed children, and offer targeted retry.

## 17. Edge Cases and Failure Modes

- Missing/malformed/unsupported manifests, duplicate IDs/versions, invalid defaults, absent prompts/tools, digest mismatch.
- Unsupported provider/model capabilities, missing/expired credentials, provider initialization failure, invalid/empty response.
- Local model absent, loading slowly, out of memory, incompatible hardware, or terminated mid-run.
- Null, scalar, nested object, array/list, tuple-normalized array, binary/artifact, tool-call, tabular, and malformed streaming payloads.
- Double clicks and repeated import/project-install/publish/attach/detach/share/save; stale tabs; out-of-order fetches and events.
- Attachment target deleted, duplicated, retyped, or moved while an execution/review is pending.
- Imported/global source updated/unpublished/deleted while independently configured project templates/instances run; exact referenced bytes must remain retained.
- Project-template uninstall with same-project attachments, pending reviews, or active executions; another project's independent template must not participate.
- Drawer/modal reopened after failure, refresh during streaming, browser offline/reconnect, dataflow switched mid-request.
- Account/deployment policy changes while a modal is dirty or execution admission is resolving; another tab activates a revision; the actor loses authorization while a settings screen is open.
- Project-template/attached-instance override attempts to loosen a ceiling; concurrent runs reserve the last budget/quota slot; pricing is missing/stale or actual usage arrives after interruption; a streaming run reaches a hard limit.
- Prompt draft changes contained path, variables, encoding, or output schema; a non-import source fabricates authoring access; evaluation fixtures contain sensitive/injected content; a candidate attempts self-evaluation; exact-digest evidence becomes stale after an edit.
- Audit append/integrity check or required review fails during activation/release; protected prompt content contains a secret and requires restriction, rotation, redaction/crypto-shredding, and an immutable remediation event.
- A reviewed selected-project Install proposal succeeds but orchestration fails, or child execution succeeds but parent merge fails; no import/attach/publish is inferred.
- Cancellation arrives after terminal completion; timeout races with tool completion; late provider chunks after cancel.
- Migration encounters legacy prompt calls, incomplete early agent records, or unknown target types.
- Same publisher/agent/exact-version arrives with another digest; a project template changes source while existing attachments keep their operational pins; attach races project uninstall across tabs/devices.
- User Publish fabricated for a global/built-in/project template/attachment; Import completes without a project; the same definition is installed with different defaults in two projects; a recipient guesses private IDs.
- When agent output is surfaced through Curio's existing flow-sharing, visible output must never embed a dataset URL, account/project ID, prompt/tool response, secret, package/source-code metadata, or hostile nested payload (no-leak regression guard — D-0 = B).
- Node Explainer agent missing/not installed/detached/provider-blocked/over quota — the node UI offers the normal install/attach/retry route while the retained Explanation tab keeps working independently (`DEC-041`; no removal-migration edge cases apply).
- Remote provider receives ineligible data, custom endpoint resolves/redirects to a forbidden network, local provider fails, or account changes while a stream/draft is active.
- Server restarts after provider response or during mutation review; retention, export, account deletion, publication ownership, restore, and backup expiry interact.
- Imported archive exceeds bounded extraction limits or contains traversal, duplicate normalized paths, links, device/FIFO entries, or malformed content; model/tool output contains active HTML, unsafe URLs, or malicious Markdown.

Each must resolve to a stable state, retain auditability, avoid duplicate side effects, and present a recovery action.

## 18. Security, Credentials, Trust Boundaries, and Observability

- Store credentials encrypted or in the existing secret store behind account `ProviderProfile` records and opaque `secretRef` values; manifests, transcripts, logs, URLs, and client DTOs contain references/redacted metadata only. Credential writes/rotation never return secret material.
- Derive the account store key from the authenticated server principal; never accept a user/account key from an agent path, manifest, query parameter, or request body.
- Authorize every context read and tool action against user, dataflow, target, and manifest permissions.
- Before project Install, attach, or execution, independently authorize visible definition, selected project/template, target, imported/private source where applicable, and actor. Cross-user/project failures must not disclose whether a private resource exists.
- Treat imported manifests, prompts, model output, tool output, external datasets, and catalog metadata as untrusted input.
- Stream imported archives into a private bounded staging area; enforce allowed media/archive types, compressed and expanded byte limits, entry-count and expansion-ratio limits, canonical unique relative paths, regular-file-only entries, and cleanup on every failure before atomically committing validated bytes.
- Allowlist tools and validate arguments/results with schemas. Execute risky tools in the existing sandbox with time/resource/network limits.
- Prevent prompt injection from expanding permissions; system policy and tool authorization are enforced outside the model.
- Render model/tool Markdown and rich text through one agent-owned allowlist sanitizer. Raw HTML, scripts, event handlers, unsafe URL schemes, and unapproved embeds stay disabled; server content types and browser CSP remain defense in depth.
- Import/template installation/capability/tool declarations grant no permission. Authorize provider destination and data egress independently, validate custom endpoints against SSRF/DNS-rebinding/redirect policy, and prohibit implicit local-to-remote fallback.
- Imported-definition settings, prompt drafts, evaluation fixtures/results, and prompt audit records are account-private; project-template and attachment policies are project-private. All use non-enumerating denial and separate reveal/export authorization where applicable. None enters public/catalog DTOs beyond approved definition metadata, generic telemetry, URLs, local storage, transcripts, or the existing shared result.
- Prompt audit records store redacted integrity-linked metadata and content digests by default. Optional encrypted snapshots/diffs are separate protected content; disclosure/export is itself audited. Mandatory governance event categories cannot be disabled by a manifest or account setting.
- Evaluation runs isolate the candidate from evaluator policy, disable unapproved tools/network, authorize fixture/provider egress independently, enforce an evaluation-specific budget/quota, and cannot self-approve, auto-activate, release, or publish.
- Redact secrets and sensitive dataset values before telemetry; OQ-008 must define retention, deletion, backup/restore, reveal/export, protected-content, remediation/tombstone, and account-closure policy for transcripts/events plus prompt drafts, evaluations, and audit evidence before production release.
- Verify published artifacts with digest/signature/provenance and scan for embedded secrets/path traversal.
- Authorize user publication exclusively through `AccountImportedAgent`; server rejects every other source type regardless of fabricated client controls.
- Record correlation IDs across settings draft/activation, prompt workspace/revision/evaluation/audit/release, session, execution, reservation, parent/child, provider call, tool call, review, and mutation.
- Capture latency, token/usage, retries, cancellation, provider/model, tool outcome, and normalized errors without prompt/secret leakage by default.
- Ship server-authoritative feature flags, execution/tool/publish kill switches, account/provider concurrency and token/cost quotas, queue/lease health, interruption counts, stream gaps, and audit dashboards with the first runtime slice.

## 19. Testing Strategy

### Required suites

- Unit: manifest parser/validator/migrations; bounded import; exact artifact coordinates/collisions; definition → account import → project template → attachment legal transitions; imported-only publication; unversioned attachment revision; retained refs/GC; target compatibility; view selectors; prompt/tool/provider policy; event reducer/leases/retry; stable errors.
- Settings/policy unit and contract: six setting kinds, profile fixtures, independent per-project-template materialization, strict deployment/account/project-template/attached-instance intersection, downward-only overrides, project-specific Reset provenance, prompt-screen read-only applicability, effective snapshots, stale ETags, and stable admission errors.
- Cost/quota/resource: pricing revisions and unknown prices; currency/time-window boundaries; estimate versus actual settlement; concurrent/idempotent execution, child, retry, and evaluation reservations; last-slot races; cancellation and stale-reservation reconciliation; provider/model/locality, context/output/tool/timeout/CPU/RAM/GPU constraints; queue behavior; egress/SSRF; and no remote fallback.
- Prompt editor/quality/audit: explicit-import ownership checks and denial for built-in/global/project-template/attachment sources, memory-only UI state, path/variable/schema validation, save conflicts, immutable release/SemVer/digest collision, attachment pins, deterministic quality gates, exact evaluation pins/staleness, evaluator isolation/unavailable OQ-007 state, evaluation budget denial, versioned security/compliance/provenance rules, exact audit-run pins, typed findings/severity/location/remediation/release gates, append-only event ordering/integrity, redaction, reveal/export authorization and audit, retention tombstones, and tamper detection.
- Capability registry/resolution: semantic ID syntax, taxonomy and contract versions, multiple implementations, deterministic selection, explicit delegate preference, target/provider/tool filtering, deprecated/unknown capabilities, and rejection of prompt filenames as capability IDs.
- Prompt-agent contracts: thirteen enabled manifest fixtures plus an explicit blocked-evaluator fixture until OQ-007 is resolved; package-local path containment, asset digests, preamble/instruction linkage, required variables, output schemas, and deterministic legacy request-contract parity.
- Contract: every provider adapter against a shared suite; LangChain runtime port; manifest fixtures; API schemas; execution event ordering/resume.
- Component: three-view Agents drawer/action eligibility, active-project palette, DnD/keyboard attach, unversioned private instance/dock/chat, six scope-aware settings screens, the retained node Explanation tab rendering (`DEC-041` regression guard), Node Explainer agent standard path, hostile content, focus and empty/error/retry states.
- Integration: Import (no project mutation) → explicit Install in selected project → defaults → Attach → tighten → reserve/run/review; imported draft → audit/evaluate/review/Release → separate project update and/or imported-only Publish; project switch isolation; project uninstall/detach/delete/unpublish/quarantine separation; attach/uninstall and reservation races.
- Publication: server accepts only owned validated `AccountImportedAgent`; global/built-in/project-template/attachment IDs and fabricated clients fail; Import/Install/Publish never cause each other.
- Sharing (D-0 = B): no new sharing mechanic. Regression-test that the agents feature adds no agent-private data (datasets/lineage, packages/code, definitions/imports/templates/attachments/agent flows, settings/prompts/evaluation/audit/transcripts/tools/providers/usage/cost/private IDs/URLs) as a new shared surface in Curio's existing flow-sharing.
- Node explanation (`DEC-041`): the `NodeEditor` Explanation tab/nav/keyboard target, the `NodeExplanation` direct request/cache, and `hasExplanation` configuration/propagation all remain present and functional (regression test: the tab renders); the coexisting Node Explainer agent chat executes exactly once per request through the standard agent path; `MainCanvas` flow explanation independently uses Dataflow Explainer.
- Backend integration: auth, persistence, idempotency, project/attachment optimistic concurrency, SSE recovery, execution pins, imported-only publication, project isolation, tool authorization, account/project-switch cleanup, credential migration, backup/restore.
- Failure injection: delay/reorder/drop streams, restart after provider response or during review, provider timeouts/rate limits, partial tool/publish failures, local resource exhaustion, forbidden endpoint/egress, stale revisions, duplicate requests, and disk/restore inconsistency.
- Accessibility: WCAG 2.2 AA drawer lifecycle labels/actions/project announcements, attachment/chat/review/modal workflows, cogs/targets/focus/conflicts, the retained Explanation tab's existing tab order (unchanged — `DEC-041`), Node Explainer chat navigation, non-color states, contrast, zoom/reflow, reduced motion, and forced colors.
- Migration/backward compatibility: legacy dataflows and LLM prompt callers, exact request construction, provider parameters, context selection, independently evaluated grants, review gates, and normalized-error parity under deterministic adapters; curated semantic-output rubric rather than byte equality; no double execution; schema migration; and rollback/read compatibility.
- Traceability: automated check that implemented `REQ-*` entries map to tasks and tests in the KGGraph matrices/build logs.

### Phase gates

- Phase 1: definition/import/project-template/attached-instance/publication on-disk stores/registries/lockfile and legal transitions, side-by-side definition retention, typed project-default/prompt-workspace stores, attach/project-uninstall concurrency, and on-disk load/validate/write round trips pass.
- Phase 2: provider/LangChain contracts, strict effective-policy resolution, atomic cost/quota/resource reservations, secret/egress/SSRF rules, authenticated streams, lease interruption/retry, flags/kill switches/telemetry, cancellation, security, and failure injection pass in the approved OQ-009 topology.
- Phase 3: three-view drawer, explicit Import/project Install/imported-only Publish, active-project palette, per-template defaults, and policy-screen suites pass.
- Phase 4: private unversioned attachment/chat, downward-only instance settings, project switching, modal accessibility, event-resume, and concurrency suites pass.
- Phase 5: prompt governance/immutable imported release, three first-release flows, and orchestration failure tests pass. (The former "Node Explainer direct-caller/tab removal" gate is cancelled — `DEC-041`.)
- Phase 6: no sharing build (D-0 = B); the only sharing gate is a regression suite proving the agents feature adds no agent-private data as a new shared surface in the existing share.
- Release: full backend/frontend regression suites, migration and backup/restore rehearsals, privacy/security review, WCAG 2.2 AA audit, provider release smoke tests, operational threshold review, resolved OQ-008/OQ-010 policy gates, and traceability check pass.

## 20. Migration and Incremental Implementation Phases

### Phase 0 — design closure and foundations

- Resolve or explicitly gate OQ-007 through OQ-011; DEC-029 through DEC-032 define the canonical lifecycle (DEC-033 is superseded by DEC-041 — Explanation tab retained), DEC-034/DEC-035 the composite and node-package capabilities, while platform prompt quality remains independent of OQ-007.
- Pin dependency versions and write ADRs for exact-coordinate persistence, streaming, deployment topology, retention/backup policy, and data classification/egress enforcement.
- Finalize definition/import/project-template/attachment/publication schemas and legal commands; manifest `settingsDefaults`; project profile/effective-policy/reservation/authoring/evaluation/audit schemas; canonical risks/requirements; and traceability.
- Define frontend/backend agent public APIs, dependency rules, allowed shared imports, and automated import-boundary checks before moving behavior.

### Phase 1 — domain, persistence, and read APIs

- Add exact definition artifacts, account imports, imported-only publications, project templates, private unversioned attached instances, execution pins, bounded import, validators/filesystem repositories, and project/dataflow spec (`dataflow.agents` lockfile / graph) updates.
- Add settings revisions, independently materialized project profiles, prompt workspaces/drafts, audit/evaluation evidence, and additive on-disk format evolution; keep prompt bodies/private resources out of shared storage.
- Add side-by-side content-addressed artifacts and the manifest prompt resolver; seed the thirteen valid definitions independently. Do not register `agent.generated-content-evaluator` until OQ-007 is resolved and its package validates.
- No UI beyond development fixtures.

### Phase 2 — provider/runtime vertical slice

- Create `backend/app/agents/` as the sole backend owner; move provider dispatch and prompt loading from broad API/prompt locations behind its application and infrastructure interfaces.
- Add provider registry/profiles/opaque secrets, OpenAI-compatible Ollama bridge, project-template capability/prompt/delegate/tool resolution, egress checks, project/instance effective policy, reservations/ledger, execution pins, LangChain leases/events/retry, flags/telemetry, and one Node Explainer chat run.
- Keep temporary compatibility endpoints thin and explicitly deprecated; do not preserve duplicate LLM implementations.

### Phase 3 — account import, project install, imported publication, and palette

- Add Global Catalog/My Imports/Installed in this project views; explicit Import, selected-project Install/uninstall, imported-only Publish/unpublish; active-project palette; project-keyed cache reconciliation; and no hidden chaining.
- Materialize reviewed defaults per project template and add Account/Imported definition/Project agent default/Attached instance settings applicability and policy screens.
- Move existing frontend LLM provider/chat behavior and extract raw LLM logic from flow/node/canvas components behind the agent module public API; update imports and colocate tests.

### Phase 4 — attachment, dock, and unified chat

- Add target compatibility, DnD/keyboard attach from active-project templates, private `attachmentId` + concurrency revision, sessions/dock/chat, instance settings, execution pins, recovery, detach/project-uninstall guards, and project-switch cleanup.

### Phase 5 — first-release agents and orchestration

- Deliver Dataset Finder → Data Load, Node Explainer → node, and Dataflow Builder → canvas.
- Add Node Builder handoff, orchestrator child executions and reviewed missing-agent installation, validation/evaluation loop, and explicit apply gates.
- Add Prompt Editor, Prompt Quality, and Prompt Audit screens and services for owned explicit imports only; save/validate/static-audit/remediate/evaluate/review/release flow; read-only provenance for every other lifecycle scope; exact audit/evaluation evidence staleness; platform evaluators independent of OQ-007; and guarded append-only event reveal/export.
- Migrate the thirteen available prompt behaviors from raw dispatch to manifest-defined agents in functional slices; prove deterministic request-contract parity and curated semantic quality before removing each legacy call. Add the fourteenth only after OQ-007 is resolved.
- Keep the `NodeEditor` Explanation tab, `NodeExplanation` direct request/cache, and `hasExplanation` configuration/propagation unchanged (`DEC-041` — no removal, no parity-migration); migrate flow-level explanation separately to Dataflow Explainer.

### Phase 6 — provider expansion and hardening

- Sharing: **no new build (D-0 = B).** Do not replace flow sharing, add a `SharedFlowResult` pipeline/viewer/endpoint, or retire the existing share route. The only sharing work is a regression guard: verify the agents feature adds no agent-private data (definitions, imports, templates, attachments, prompts, evaluations, audits, settings, provider secrets, transcripts, private IDs) as a new shared surface. Then add justified providers/resource/performance/backup/retention hardening.

Roll out behind server-authoritative capability flags with UI flags as presentation only. Migrate one call site at a time with single-write/single-execution behavior; never shadow-call a paid or mutating provider. On-disk spec/registry/lockfile format changes are additive first and tested with old-reader fixtures. Rollback kill switches disable creation/execution/tools/publish independently while retaining records and read-only history; rollback never re-enables duplicate raw prompt execution.

## 21. KGGraph Design and Build Tracking

The Design mapping and source inventory live in `2.1-Agents-Catalog-Design-Traceability.md`. Implementation uses `3.1-Agents-Catalog-Build-Log.md` as an index and creates one append-only modular log per phase or focused workstream, for example:

```text
Stage-3-Build-Phase/agents-catalog/
  BL-P0-foundations.md
  BL-P1-domain-persistence.md
  BL-P2-runtime-providers.md
  BL-P3-catalog-install-publish.md
  BL-P4-attachments-chat.md
  BL-P5-first-release-orchestration.md
  BL-P6-hardening.md
```

Each entry records date, author, linked IDs, status, design-to-code decision/deviation, files, tests, commit, issue/regression, resolution, evidence, follow-up, risk, and open question. Never rewrite history; append corrections and superseding links.

## 22. Traceability Identifier Scheme

| Prefix | Meaning | Example |
| --- | --- | --- |
| `SRC` | source artifact | `SRC-ARCH-09` |
| `ART` | design/UI artifact | `ART-PNG-01` |
| `REQ` | requirement | `REQ-PROJECT-INSTALL-001` |
| `DEC` | decision | `DEC-007` |
| `ASM` | assumption | `ASM-004` |
| `OQ` | open question | `OQ-007` |
| `RISK` | risk | `RISK-SEC-002` |
| `TASK` | implementation task | `TASK-P4-ATTACH-004` |
| `TEST` | test/verification | `TEST-E2E-003` |
| `BL` | build-log entry | `BL-P4-20260715-01` |
| `COMMIT` | commit evidence | `COMMIT-<short-sha>` |

Requirements are immutable once implementation starts. Superseded entries retain their ID and link to the replacement. Code changes include task/requirement IDs in the build log and preferably PR/commit metadata, not noisy inline comments. Tests use IDs in names or metadata where practical. The release traceability check requires `REQ -> DEC/design -> TASK -> files/commit -> TEST -> evidence` in both directions.

## 23. Acceptance Criteria

### Product and lifecycle

- `REQ-CAT-001`: Users can browse, search, filter, sort, and page the deployment-shared Agents Catalog with stable loading/empty/error states.
- `REQ-ARTIFACT-001`: Every artifact is immutable and addressed by `{publisherNamespace, agentId, exactVersion, artifactDigest}`; the same publisher/ID/version with a different digest is rejected.
- `REQ-PRIVACY-001`: Imported definitions are account-private; project templates/settings and attached instances/sessions/executions are isolated by selected project and cannot be enumerated across account/project boundaries.
- `REQ-PRIVACY-002`: Imported-only publication copies validated definition assets only; it includes no templates, instances, settings, prompts/private governance, transcripts, or execution state. (Result sharing is out of scope — D-0 = B — and reuses existing flow-sharing.)
- `REQ-PRIVACY-003`: Unpublish removes global discoverability without deleting the publisher's private import or other projects' retained exact `ProjectAgentTemplate` sources; retention, quarantine, and garbage collection remain separate.
- `REQ-VERSION-001`: Definition artifacts/project-template sources pin exact coordinates, but attached instances have only concurrency revision. Updates never silently retarget an existing instance.
- `REQ-VERSION-002`: Exact definition versions coexist and referenced bytes remain available until project templates, instances, active work, retained history, publication, and approved backup policy permit collection.
- `REQ-LIFECYCLE-001`: Import deletion, project uninstall, attachment detach, imported-only unpublish, restriction, and garbage collection have distinct typed IDs/authorization/effects.
- `REQ-IMPORT-002`: Explicit bounded Import creates exactly one private `AccountImportedAgent` plus immutable definition and performs no project install, attachment, publication, or active-project cache mutation.
- `REQ-PROJECT-INSTALL-001`: Explicit Install requires a selected authorized project/dataflow key and visible exact definition, atomically creates one project template plus independent defaults, updates only that project's palette, and never imports/publishes/attaches. Detach never uninstalls it; project uninstall serializes with attachment creation and is blocked only by protected same-project instance/review/nonterminal-execution references.
- `REQ-PUBLISH-002`: User Publish accepts only an owned validated manifest-based `AccountImportedAgent`; global/built-in/project-template/attached sources are rejected, and Publish never installs.

### Assignment and UX

- `REQ-ATTACH-001`: Only compatible targets accept an agent; compatibility is understandable by pointer, keyboard, and screen reader.
- `REQ-ATTACH-002`: Multiple attachments of the same definition have unique IDs and independent configuration/history.
- `REQ-ATTACH-003`: An attached instance derives privately from a same-project template, has stable `attachmentId` plus optimistic revision only, exposes no SemVer/Release/Publish/Share contract, and each execution pins source definition, project settings, attachment, prompt, provider, and effective-policy revisions.
- `REQ-DOCK-001`: Every attachment remains visible in an accessible dock with name, target, and status; reduced-motion behavior is supported.
- `REQ-CHAT-001`: The unified chat resumes the correct session, navigates all attachments, retains history, and restores focus on close.
- `REQ-REVIEW-001`: No graph/data mutation occurs without an explicit, revision-safe review action.
- `REQ-PERM-001`: Import/template install/attachment and manifest declarations grant no permission; execution independently authorizes project template/instance/target/context/provider/tools/mutation.
- `REQ-SETTINGS-001`: Labeled Account policy, Imported definition, Project agent default, and Attached instance cogs use one six-screen shell with server-defined applicability; templates/instances show prompt governance read-only and governed settings cannot activate through chat.
- `REQ-POLICY-001`: Every project template materializes its own reviewed profile/revisions. Instance overrides only tighten deployment/account/project policy, Reset affects only the selected template, and every execution/evaluation persists all effective sources/pins.
- `REQ-SETTINGS-A11Y-001`: Settings triggers/screens meet WCAG 2.2 AA for accessible names/tooltips, 44-by-44 targets, one-dialog focus trap/return, keyboard screen/editor navigation, dirty-close/conflict/error/evaluation announcements, zoom/reflow, reduced motion, and forced colors.

### Runtime and providers

- `REQ-RUNTIME-001`: UI/domain modules do not import LangChain; all executions use the runtime port and normalized events/errors.
- `REQ-RUNTIME-002`: Executions persist leases/heartbeats; startup reconciliation marks expired nonterminal work `interrupted`, never replays provider/tool calls automatically, and explicit retry creates a new linked execution.
- `REQ-PROVIDER-001`: Provider/model compatibility, credentials, health, invocation, streaming, cancellation, retry, timeout, and unsupported capabilities are handled through one typed provider contract.
- `REQ-PROVIDER-002`: Cloud, OpenAI-compatible—including the initial Ollama/Gemma path—and Hugging Face adapters pass the shared contract suite before their individual release flags are enabled; a dedicated local Gemma adapter requires the DEC-016 capability-gap justification. The **default** provider/model/API/runtime config is seeded from the existing `dev/aiconn/` OpenAI-compatible sage200 endpoint (`llama4-nim`+`gemma4`, `AICONN_API_KEY`, chat-completions), not separate LangChain defaults (`DEC-039`); additional profiles are explicit account additions.
- `REQ-PROVIDER-003`: Account provider profiles expose only non-secret metadata and opaque references; credentials are encrypted/write-only/rotatable and never returned to clients, logs, manifests, or transcripts.
- `REQ-EGRESS-001`: Remote processing is explicit and classification-authorized; custom endpoints fail closed under scheme/port/DNS/redirect/SSRF policy, and local failure never triggers remote fallback.
- `REQ-COST-001`: Before provider/tool work, server admission uses an immutable provider-price/effective-policy snapshot and an atomic idempotent budget reservation; estimates are advisory, actual usage is append-only and reconciled, and unknown pricing fails closed when a hard monetary cap applies.
- `REQ-QUOTA-001`: Request, execution, token, tool, evaluation, concurrency, and queue quotas use atomic windowed reservations and stable reset/retry metadata so concurrent attempts cannot oversubscribe or silently discard ambiguous usage.
- `REQ-RESOURCE-001`: Effective provider/profile/model/locality, context/output/time/tool/network and local CPU/RAM/GPU limits are server-enforced before and during work; lower scopes cannot loosen them and local exhaustion never triggers implicit cloud fallback.
- `REQ-ORCH-001`: Dataflow Builder resolves only active-project templates and gates selected-project Install/mutations; it never silently imports, installs, attaches, publishes, shares, or uses another project's template.
- `REQ-AGENT-001`: Dataset Finder, Node Explainer, and Dataflow Builder complete their approved attachment workflows.
- `REQ-PACKAGE-001`: `agent.package-recommendation` (`package.recommend`/`package.identify`) and the build agents that delegate to it (`agent.node-builder`, `agent.connection-builder`, `agent.dataflow-builder`) identify a required node package, surface it as a reviewed install proposal, and install it only through the existing package flow (`InstallPermissionsDialog` permissions/dependencies/conflicts → `installToProject` on the current project lockfile). Agents never install silently, never propose a `curio.builtin@*` package, never author/publish a package, and recommended/identified packages stay agent-private and out of shares (D-0 = B). See `16-agent-node-package-capabilities-memo.md`.
- `REQ-PROMPT-001`: Each enabled prompt behavior has a versioned hookable-agent manifest with package-local, digest-verified prompt links, typed inputs/outputs, compatible targets, provider requirements, and runtime/review policy; thirteen may ship independently while the fourteenth remains blocked.
- `REQ-PROMPT-002`: The thirteen current prompt callers preserve exact request construction, provider parameters, context selection, independently evaluated grants, review gates, schemas, and normalized errors under deterministic adapters plus approved semantic-quality thresholds; raw dispatch is removed only after parity passes with no double execution.
- `REQ-PROMPT-003`: `agent.generated-content-evaluator` cannot be published, installed, or run until the missing approved prompt asset and output contract resolve OQ-007 and pass manifest validation.
- `REQ-PROMPT-EDIT-001`: Prompt Save changes only an authorized account-private draft owned by an `AccountImportedAgent` created through explicit Import, using contained asset IDs and optimistic concurrency. Built-in/global/project-template/attachment sources are read-only. Release creates a new immutable exact imported-definition artifact and never mutates source bytes, publishes, updates a project template, or retargets an attachment implicitly; future fork/export packaging and re-import are out of scope.
- `REQ-PROMPT-QUALITY-001`: Static and approved model-based quality evidence pins exact draft/suite/evaluator/provider-profile/fixture/policy revisions, becomes stale after any input change, cannot self-approve or auto-activate/release/publish, and shows an unavailable state rather than substituting the OQ-007 package.
- `REQ-PROMPT-AUDIT-001`: Prompt Audit runs versioned static security/compliance/provenance rules pinned to exact draft/ruleset/policy revisions, exposes typed findings and authorized remediation, and blocks Release for required unresolved findings. Its separate mandatory governance-event history is append-only, ordered, integrity-checked, separately authorized from transcripts, redacted/retention-aware, and audits narrow rate-limited reveal/export itself.
- `REQ-CAP-001`: Every agent manifest declares semantic capabilities that describe behavior independently of agent IDs, roles, tools, prompt filenames, and framework/provider implementation.
- `REQ-CAP-002`: Capability resolution filters active-project templates by contract/target/provider/tools/trust/source and persists selected project-template plus exact execution pins.
- `REQ-CAP-003`: Manifest validation rejects prompt filenames/paths as capability IDs and reports unknown, deprecated, or contract-incompatible capabilities clearly.

### Quality and operations

- `REQ-STATE-001`: Refresh, reconnect, slow/out-of-order responses, repeated actions, and dataflow switching cannot create duplicated records or regress visible state.
- `REQ-STATE-002`: Project/account switch terminates streams and clears mismatched imports/templates/palette/instances/settings/prompts/sessions before another scope renders.
- `REQ-CONCURRENCY-001`: Attachment creation and final project-template uninstall serialize on that project template; imported-definition deletion/Release/Publish use independent locks so races yield stable conflict and no dangling ref.
- `REQ-SEC-001`: Secrets never enter manifests/client/logs; imported content and tools cross explicit validation/authorization boundaries.
- `REQ-IMPORT-001`: Agent package import uses private bounded staging, rejects traversal/duplicate paths/links/special files/unsupported media and archive bombs, cleans up partial state, and exposes an immutable artifact only after complete validation and atomic commit.
- `REQ-SHARE-001` (D-0 = B): The agents feature builds no new sharing mechanic and reuses Curio's existing flow-sharing. The only acceptance is negative — a regression suite proving the feature adds no agent-private data (definitions, imports, templates, attachments, prompts, evaluations, audits, settings, provider secrets, transcripts, private IDs) as a new shared surface in the existing share. (`REQ-SHARE-002` retired: no `/shared-flow-results/{shareId}` endpoint or `SharedResultViewer` is built.)
- `REQ-NODE-EXPLAIN-001`: **retired (`DEC-041`)** — this requirement mandated the tab removal and must not be implemented; the identifier is not reused.
- `REQ-NODE-EXPLAIN-002`: the node Explanation tab/menu/keyboard/cache/direct `single_box_explanation_prompt` path and `hasExplanation` flags remain present and functional; the selected-project Node Explainer template/attachment unified chat coexists as an additional node-explanation surface; flow explanation independently uses Dataflow Explainer.
- `REQ-SEC-002`: Agent/model/tool rich content is rendered only through a centralized allowlist sanitizer with active HTML, scripts, unsafe URL schemes, event handlers, and unapproved embeds disabled and tested.
- `REQ-A11Y-001`: WCAG 2.2 AA keyboard, focus, semantic, meaningful-announcement, non-color-state, contrast, zoom/reflow, reduced-motion, and forced-colors checks pass.
- `REQ-ROLLOUT-001`: Server-authoritative flags and independent execute/tool/publish kill switches prevent double execution and support read-only rollback from the first runtime slice.
- `REQ-OPS-001`: Enforced concurrency/token/cost/queue limits, lease and stream health, privacy-safe metrics, provider release smoke tests, performance thresholds, and operational recovery evidence gate enablement.
- `REQ-RETENTION-001`: Transcript/event and prompt draft/snapshot/diff, evaluation fixture/result, prompt-audit metadata/protected-content, reveal/export, secret-remediation/crypto-shredding tombstone, account closure, publication ownership, backup expiry, and restore behavior follow the approved OQ-008 policy and never overstate completed deletion or invent a duration.
- `REQ-BACKUP-001`: Backup/restore preserves account/project isolation, definition coordinates, project-template/instance refs, and fails closed on unverifiable bytes/dangling refs.
- `REQ-TRACE-001`: Every implemented requirement has linked design, task, code/commit, test, and evidence in KGGraph logs.
- `REQ-REG-001`: Existing node/dataset catalog and dataflow regression suites remain green.
- `REQ-MODULE-001`: All frontend agent/LLM UI, hooks, services, state, utilities, and provider-integration behavior is owned by `src/agents/`; non-agent features use only its public API.
- `REQ-MODULE-002`: All backend orchestration, LangChain, provider invocation, tool adapters, prompts, manifests, sessions, and runtime behavior is owned by `backend/app/agents/`; route and domain consumers use only application ports.
- `REQ-MODULE-003`: Import-boundary checks prove that provider SDKs, LangChain, prompt loading, raw LLM calls, and agent lifecycle state do not exist outside approved agent infrastructure, and all moved imports/tests/docs resolve without duplicate implementations.

## 24. Recommended Commit Breakdown

1. `docs(agents): establish schemas, ADRs, risks, defaults, and traceability baseline`.
2. `feat(agents-domain): add definition, import, project-template, private-instance, execution-pin, and publication filesystem stores/registries/lockfile` with tests.
3. `feat(agent-settings): add typed bindings/revisions, per-agent defaults, strict policy resolution, and APIs` with tests.
4. `feat(agent-admission): add cost/quota/resource reservations, price snapshots, settlement, and usage ledger` with concurrency tests.
5. `feat(prompt-authoring): add private workspaces, contained prompt drafts, validation, and immutable release` with tests.
6. `feat(prompt-governance): add evaluation suites/runs, exact evidence gates, and integrity-linked audit events` with tests.
7. `feat(agents-api): add explicit import, imported-only publication, selected-project template, attachment, session, and governance contracts` with tests.
8. `feat(llm-providers): add provider registry and initial adapter contract` with tests.
9. `feat(agent-runtime): add LangChain boundary, events, cancellation, prompts, tools, and policy snapshots` with tests.
10. `refactor(catalog): extract verified shared catalog UI/modal/form primitives` with regression tests.
11. `feat(agents-ui): add three-view drawer, independent Import/project Install/imported-only Publish flows, active-project palette, and settings entry points` with tests.
12. `feat(agent-policy-ui): add the shared settings shell and Cost/Quotas/Resource policy screens` with accessibility tests.
13. `feat(prompt-governance-ui): add Prompt Quality/Editor/Audit screens` with privacy and end-to-end tests.
14. `feat(agent-attachments): add compatibility, DnD/keyboard attach, persistence, dock, and downward-only settings` with tests.
15. `feat(agent-chat): add unified sessions, reviews, stream recovery, settings deep links, and focus behavior` with tests.
16. ~~`refactor(node-explanation): remove the Explanation tab/direct caller/hasExplanation flags …`~~ **Cancelled (`DEC-041`)** — the Explanation tab is retained; no commit removes or hides it. Flow-level explanation still migrates separately to Dataflow Explainer under its own commit.
17. `test(sharing): regression guard proving the agents feature adds no agent-private data as a new shared surface in existing flow-sharing` (no new sharing mechanic — D-0 = B).
18. `feat(agent-orchestration): add first-release agents, handoffs, and Dataflow Builder` with end-to-end tests.
19. Separate commits per additional provider adapter, followed by hardening, migration, regenerated documentation evidence, and cleanup commits.

Every commit updates its modular Build Log entry. Avoid mixing provider, UI, persistence, and unrelated refactors in one commit.

## 25. Engineering Quality Checklist

- [ ] No duplicated catalog, manifest, provider, prompt, tool, compatibility, or state logic.
- [ ] Six settings areas use independent typed domains/revisions and reviewed per-agent defaults; no unvalidated mega-configuration blob or chat-only policy mutation remains.
- [ ] Effective-policy source revisions and atomic cost/quota/resource reservation IDs are persisted for every execution/evaluation and race-tested before provider/tool work.
- [ ] Prompt bodies remain private and memory-only in the browser; Save/validate/evaluate/review/Release preserve immutable artifacts, exact evidence, and existing attachment pins.
- [ ] Prompt audit is mandatory, append-only, integrity-checked, redacted, separate from transcripts, narrowly authorized, and retention-aware.
- [ ] Domain, application, UI, persistence, LangChain, and provider boundaries are enforced.
- [ ] Types/schemas are explicit at storage, API, event, tool, provider, and UI boundaries.
- [ ] Immutable exact artifact coordinates, account-import ownership, project-template source/settings references, attachment concurrency revisions, execution pins, idempotency keys, leases, retry links, and event sequences are persisted where required; no account installation pointer remains.
- [ ] Project-template APIs require the selected project/dataflow key and mutate only that project's palette/defaults; Import and imported-only Publish APIs accept no implicit project Install/Attach side effect.
- [ ] Account-import privacy, project-template/attachment isolation, imported-only publication, project-switch cache clearing, same-project uninstall guards, and multi-tab active-project palette synchronization are verified.
- [ ] Components remain focused; shared abstractions reflect real node/dataset/agent commonality.
- [ ] Loading, empty, error, success, partial-failure, cancel, reconnect, and recovery states are tested.
- [ ] No stale-data flicker, unnecessary full reload, duplicate side effect, or unstable layout is introduced.
- [ ] WCAG 2.2 AA keyboard, focus, semantics, meaningful announcements, non-color states, contrast, zoom/reflow, reduced motion, and forced colors are verified.
- [ ] Secrets and sensitive context are excluded from manifests, clients, transcripts where prohibited, and telemetry.
- [ ] Tools and mutations are authorized, schema-validated, sandboxed where needed, and review-gated.
- [ ] Imported packages pass bounded staging/extraction tests and cannot escape, expand without limits, create link/special-file entries, or leave visible partial artifacts.
- [ ] All agent/tool rich content passes one tested safe renderer; hostile HTML, URL, and Markdown fixtures cannot execute browser content.
- [ ] Provider and LangChain adapters pass shared contract and failure-injection suites.
- [ ] The three first-release workflows pass end to end.
- [ ] The thirteen enabled prompt-backed packages resolve only contained, digest-verified assets and pass manifest/contract/parity tests; the evaluator remains absent and blocked until OQ-007 is resolved, after which the same gates apply to the fourteenth package.
- [ ] Project uninstall, attachment detach, private import deletion, unpublish, quarantine/revocation, and garbage collection remain separate, authorized lifecycle operations.
- [ ] First-slice server flags, kill switches, quotas, privacy-safe telemetry, lease recovery, and read-only rollback are verified before execution is enabled.
- [ ] All enabled agents declare semantic capabilities, and capability resolution/validation tests prove prompt assets are implementation details rather than capability identities.
- [ ] Existing node/dataset/catalog/dataflow behavior and tests remain intact.
- [ ] Node Explanation tab/menu/cache/direct request and `hasExplanation` propagation remain present and unchanged (`DEC-041`); Node Explainer and Dataflow Explainer each execute exactly once through their distinct standard agent paths when used.
- [ ] Sharing adds no new mechanic (D-0 = B): the agents feature introduces no agent-private data (definitions, imports, templates, attachments, agent flows, settings, prompts, governance, transcripts, private IDs) as a new shared surface in Curio's existing flow-sharing.
- [ ] KGGraph requirements, decisions, tasks, commits, tests, evidence, deviations, risks, and follow-ups are bidirectionally traceable.
- [ ] Frontend and backend `agents/` modules own every primarily agent- or LLM-specific responsibility.
- [ ] Dataset, node, flow, canvas, API route, and shared UI modules contain no raw LLM/provider/LangChain logic.
- [ ] Import-boundary tests prevent future agent logic from leaking into unrelated modules.
