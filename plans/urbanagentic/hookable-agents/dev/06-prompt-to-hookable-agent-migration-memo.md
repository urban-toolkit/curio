# Implementation Memo: Transform Current Prompts into Manifest-Defined Hookable Agents

> **Update (2026-08-18):** the one blocked row is closed — `OQ-007` was resolved by
> `DEC-055` (decision memo `dev/85`, owner-approved): `agent.generated-content-evaluator`
> shipped as a net-new **authored** built-in (implementation `dev/86`), honoring this
> memo's guardrail — its prompt is a deliberate authorship under the decision, never a
> fabricated migration. Statements below that describe it as absent/blocked are the
> accurate historical record of this memo's time.

## 1. Problem Statement

Curio currently invokes named prompt files directly from general LLM call sites. Those prompts are not independently discoverable, installable, attachable, versioned, or traceable through the Agents Catalog. The fourteen requested prompt behaviors must become manifest-defined hookable agent packages whose manifests link to prompt assets stored inside their own `agents/` artifact directories.

Repository inspection confirms thirteen named `.txt` files and their current call sites. `evaluate_generated_content_prompt` is documented conceptually but has no prompt file or call site in the current checkout; its content must be sourced and approved before its package can be valid. That blocker applies only to `agent.generated-content-evaluator`; the other thirteen independently valid packages can be registered, migrated, tested, and released without it.

## 2. Scope

Included: fourteen built-in agent definitions, package layout, prompt-file references, preamble handling, manifest validation, migration of direct callers, account-import/project-template/private-attachment semantics, project defaults, imported-definition prompt authoring/release, quality/audit evidence, the Node Explainer agent path (the direct-caller/tab removal is cancelled — `DEC-041`, `dev/18`), tests, traceability, and related architecture documentation. Out of scope: creating runtime packages, inventing the missing evaluator text, project-private prompt overrides, publishing templates/instances, deciding final retention outside `OQ-008`, or changing application code.

## 3. Recommended Implementation Approach

Create one versioned, self-contained directory per prompt-backed agent under the repository `agents/` artifact root. Each directory contains `manifest.json` and a `prompts/` directory. The canonical manifest is camelCase JSON and references prompt assets by safe relative path and digest. Runtime code resolves only validated paths inside the installed artifact; callers invoke an `agent.`-prefixed ID rather than a raw prompt filename.

### Canonical migration map

| Current caller | Hookable agent package | Semantic capabilities | Package-local instruction asset |
| --- | --- | --- | --- |
| `components/LLMChat.tsx` | `agent.chat-agent` | `conversation.respond`, `attachment.refine` | `prompts/chat_prompt.txt` |
| `MainCanvas.tsx` | `agent.debug-agent` | `code.debug.diagnose`, `code.fix.propose` | `prompts/debug_prompt.txt` |
| `MainCanvas.tsx` | `agent.dataflow-explainer` | `dataflow.explain` | `prompts/explanation_prompt.txt` |
| `editing/NodeExplanation.tsx` tab/direct caller is **retained** (`DEC-041` — removal cancelled); the project-installed/attached Node Explainer unified chat coexists | `agent.node-explainer` | `node.explain`, `node.output.interpret` | `prompts/single_box_explanation_prompt.txt` |
| `components/styles.tsx` | `agent.node-content-builder` | `node.content.generate` | `prompts/new_content_prompt.txt` |
| `components/styles.tsx` | `agent.execution-subtask-planner` | `execution.followup.plan` | `prompts/new_subtask_from_exec_prompt.txt` |
| `WorkflowGoal.tsx` | `agent.dataflow-task-planner` | `workflow.plan.create` | `prompts/new_subtasks_prompt.txt` |
| `components/styles.tsx` | `agent.connection-builder` | `connection.propose` | `prompts/new_connection_prompt.txt` |
| `WorkflowGoal.tsx` | `agent.workflow-suggester` | `workflow.suggest` | `prompts/workflow_suggestions_prompt.txt` |
| `WorkflowGoal.tsx` | `agent.plan-coherence-validator` | `workflow.coherence.validate` | `prompts/evaluate_coherence_subtasks_prompt.txt` |
| No current call site or approved asset | `agent.generated-content-evaluator` | `content.quality.evaluate` | `prompts/evaluate_generated_content_prompt.txt` — ~~blocked by `OQ-007`~~ **resolved: authored net-new under `DEC-055`** (dev/85/86) |
| `WorkflowGoal.tsx` | `agent.syntax-analysis-agent` | `code.syntax.analyze` | `prompts/syntax_analysis_prompt.txt` |
| `WorkflowGoal.tsx` | `agent.task-refresh-agent` | `workflow.plan.refresh` | `prompts/task_refresh_prompt.txt` |
| `WorkflowGoal.tsx` | `agent.keyword-binding-agent` | `workflow.keyword.bind` | `prompts/keywords_binding_prompt.txt` |

Prompt filenames remain implementation assets, never capability IDs. Every source-backed package also links a validated system preamble: `prompts/default_preamble.txt`, except Syntax Analysis Agent, which links `prompts/syntax_analysis_preamble.txt`.

### Migration boundary notes

- **The backend handler is the true legacy dispatch site.** The map's "Current caller" column lists
  frontend components, but the prompt files are loaded and dispatched server-side in
  `utk_curio/backend/app/api/routes.py` (`/llm/chat` ≈ `:674`, file loads ≈ `:691`/`:700`, gated by
  `/llm/check`); the frontend only passes filename strings. Removing "direct legacy prompt dispatch"
  (Acceptance §8) therefore means replacing this handler, not only editing the frontend callers.
  The client-supplied-filename path-traversal fix (`RISK-PROMPT-001`) should land first as the
  migration's initial correctness win.
- **The provider/LangChain layer is net-new, not relocated.** There is no LangChain or backend
  `agents/` module today (direct `openai`/`anthropic` SDK calls in `routes.py`). Acceptance §8's
  "Prompt/provider/LangChain loading remains inside backend `agents/` infrastructure" is a build
  target for P2, not an existing boundary to preserve.
- **Composite product agents are out of this migration roster.** The user-facing agents
  `Dataflow Builder`, `Dataset Finder`, and `Node Builder` (concept docs `01`/`05`/`11` and the
  `docs/11` profile-family tables) are net-new **compositions/orchestrations** over the capabilities
  above (via `delegatesTo`); none is backed by a single migrated prompt. They must be specified with
  their own manifest, capability set, and prompt provenance before Phase 5 ships them — do not assume
  a migrated prompt exists for them. The full product roster is eighteen agents (these three composites,
  the fourteen prompt-migration identities, and `agent.package-recommendation` specified in `dev/16`).
- **`agent.connection-builder` gains a package delegate (addendum from `dev/16`).** Its migrated
  `connection.propose` capability and prompt are unchanged, but `16-agent-node-package-capabilities-memo.md`
  adds `delegatesTo: [agent.package-recommendation]` so a proposed connection that needs a node package
  surfaces a reviewed package-install proposal. Apply this `delegatesTo` addition to the connection-builder
  manifest when building it; it is the only migrated agent that gains a `delegatesTo` edge.

Each enabled package selects a reviewed settings-default seed profile. Manifest `settingsDefaults` are immutable suggestions only; every explicit project install materializes an independent `ProjectAgentSettingsProfile` clamped by deployment/account policy. Prompt editing never modifies package/project-template/instance bytes in place. Only an owned `AccountImportedAgent` created through explicit Import can create a `PromptAuthoringWorkspace`; Release creates a new private imported definition artifact after validation, evaluation, compliance audit, and review. Install/update and Publish remain separate explicit actions. Any future fork/export must be packaged and explicitly re-imported and is out of scope.

## 4. Data and State Handling

The manifest and prompt assets are immutable `AgentDefinitionArtifact` content identified by `{publisherNamespace, agentId, exactVersion, artifactDigest}`. Explicit Import creates a private `AccountImportedAgent` but never installs/publishes. Explicit Install creates a `ProjectAgentTemplate` and project-only defaults/palette entry. Explicit Attach creates a project-private `AttachedAgentInstance` identified by `attachmentId` plus concurrency `revision`; it has no SemVer/release/publication identity. Executions pin source definition/prompt/project-settings/attachment/provider/effective-policy revisions for reproducibility.

Private prompt drafts, evaluation suites/runs, versioned compliance-audit policies/runs/findings, reviewer decisions, releases, and append-only governance events are distinct imported-definition records, not manifest/template/instance/transcript fields. Editor content uses an authorized imported-definition content contract, stays memory-only, and clears on close/project/account switch. Releasing a draft never changes a publication, project template, palette, or attachment automatically. The shared result excludes all prompt/governance/evaluation content and private IDs.

## 5. UI and UX Requirements

Each prompt-backed definition appears in the Global Catalog or My Imports with readable metadata. Only explicit project-installed templates appear in that project's AGENTS palette and may attach. Internal prompt filenames remain provenance metadata. Project templates/instances expose no Publish/Share/Release/version action.

An imported-definition cog opens Prompt Editor/Quality/Audit only for an owned definition created through explicit account Import. Built-in/global/project-template/instance screens may inspect authorized source evidence read-only but cannot edit, Release, Publish, or Share. Save creates only a private draft; quality/audit never activates or publishes. Any future fork/export must be packaged and explicitly re-imported and is out of scope. `agent.generated-content-evaluator` ~~remains unavailable under `OQ-007`~~ *(since resolved — `DEC-055`)*. The Node Explainer is explicitly installed in a project and attached to a node; its unified chat coexists with the retained node Explanation tab (`DEC-041`).

## 6. Edge Cases

- Missing or unreadable prompt file; path traversal; symlink escape; digest mismatch.
- Missing system preamble or incompatible prompt variables.
- Duplicate agent IDs/versions or two manifests linking the same mutable external file.
- Prompt output that fails its declared schema.
- Direct legacy call and agent execution both firing during migration.
- Missing `evaluate_generated_content_prompt.txt` must fail validation, not silently substitute another prompt.
- An editor attempts to modify immutable, foreign, unlicensed, or concurrently revised prompt assets.
- An evaluation references stale draft/suite/evaluator/policy revisions, exceeds its cost/quota policy, or tries to use sensitive fixtures through an unauthorized remote provider.
- A candidate prompt attempts to evaluate or approve itself, or a quality run is confused with `agent.generated-content-evaluator`.
- Audit capture or required review fails during release; release fails closed and leaves the prior artifact active.
- Prompt text, diffs, evaluation cases, or audit details leak through generic DTOs, transcripts, logs, telemetry, URLs, persistent browser storage, public shares, or another account's cache.
- Import silently installs/publishes, a project template/instance fabricates Publish/Share, or one project's palette/defaults appear in another.
- One user action triggers both the Explanation tab request and a Node Explainer agent execution at once (the two surfaces coexist per `DEC-041` but a single action must drive only the surface the user invoked).

## 7. Testing Strategy

Add manifest fixture tests for thirteen valid packages plus the blocked evaluator fixture. Add asset containment/digest, variables, schemas, and migration parity for thirteen legacy behaviors. Lifecycle coverage must prove explicit Import/project Install/Attach separation, project palette/default isolation, imported-only Publish, and attachments without version contracts.

Migration parity is not byte-for-byte model output equality. Under deterministic provider/tool adapters, parity requires the same prompt/preamble composition, input variables and context selection, input/output schemas, provider parameters, semantic capability contract, requested tool requirements, review gates, and normalized error behavior. Output quality is assessed separately with a curated semantic rubric.

Add prompt-governance tests for explicit-import ownership authorization and denial for every non-imported source, private optimistic-concurrency drafts, memory-only editor cleanup, contained paths/declared variables, exact-digest evaluation evidence, sensitive-fixture minimization, egress and evaluation-budget denial, isolated advisory evaluators with tools/network disabled, stale-evidence invalidation, pinned audit rules/findings/remediation gates, append-only governance-event integrity/redaction, and release-to-new-coordinate behavior. Confirm the thirteen migration parity suites do not depend on the missing evaluator and that no evaluation or audit result auto-activates, auto-publishes, or updates an attachment.

Add Node Explainer agent tests proving the unified chat handles request/context/provider/error behavior correctly, one user action causes one execution, and unavailable/not-installed behavior uses the normal project install/attach/chat route. Per `DEC-041`, also keep a regression test that the `NodeExplanation.tsx` tab and its request path remain present and functional — no removal-migration tests apply.

## 8. Acceptance Criteria

- Fourteen planned manifest identities are specified; the thirteen source-backed packages link to package-local prompt assets, while `agent.generated-content-evaluator` remains unregistered until its authoritative asset and contract exist.
- Thirteen existing prompt behaviors have an explicit legacy-call-to-agent migration mapping.
- The missing evaluation prompt blocks only `agent.generated-content-evaluator`; the other thirteen packages can ship independently.
- Runtime callers use agent IDs/contracts rather than raw prompt names after migration.
- Prompt/provider/LangChain loading remains inside backend `agents/` infrastructure.
- Direct legacy prompt dispatch is removed per call path only after its defined migration-parity tests pass.
- Every explicit project installation materializes an isolated reviewed default profile; mutable template/instance policy remains outside the manifest.
- Prompt Save/Quality/Audit/Release applies only to an owned explicit import; Release creates a new immutable import artifact and never mutates a template/instance.
- Prompt quality is reproducible, budgeted, non-self-approving, and explicitly separate from the unresolved `agent.generated-content-evaluator` package.
- Prompt bodies and governance evidence remain account-private and absent from generic/public/shared DTOs, transcripts, logs, telemetry, URLs, and persistent client storage.
- Only owned validated imports are user-publishable; project templates/instances expose no Publish/Share/Release/version behavior.
- Node Explainer unified chat is a coexisting node-explanation path; the Explanation tab/direct caller is retained (`DEC-041`).

## 9. Recommended Commit Breakdown

1. Add agent-package schema and prompt-asset validation.
2. Add and independently validate the thirteen source-backed built-in packages and fixtures.
3. Migrate those direct callers by functional group with defined parity tests.
4. Remove each legacy raw prompt dispatch after its replacement passes parity — **except** the Explanation-tab/direct-caller path, which is retained permanently (`DEC-041`, `dev/18`).
5. Add private prompt authoring, exact-digest evaluation, versioned compliance auditing, append-only governance events, and new-version release contracts for migrated packages.
6. Independently add `agent.generated-content-evaluator` after its authoritative prompt and contracts are approved.

## 10. Engineering Quality Checklist

- [ ] Every prompt-backed behavior has one stable agent ID and owner.
- [ ] Every manifest path is relative, contained, digest-verified, and packaged.
- [ ] Inputs/outputs and hook compatibility are explicit and typed.
- [ ] Mutating behaviors declare review-before-apply.
- [ ] No prompt body is duplicated across runtime modules.
- [ ] Missing assets fail closed with actionable diagnostics.
- [ ] Migration parity covers construction, contracts, parameters, context, requested tool/context requirements and independently evaluated grants, review gates, and normalized errors under deterministic adapters.
- [ ] The thirteen valid packages are not release-coupled to the missing generated-content evaluator asset.
- [ ] Per-agent defaults are seed metadata only and cannot override deployment/account policy.
- [ ] Each project install materializes its own defaults; no account-wide installed palette/pointer remains.
- [ ] Attachments use identity/concurrency revision only and cannot Publish/Share/Release.
- [ ] Only owned validated account imports can author/release/user-publish prompt packages.
- [ ] Node Explainer chat coexists with the retained Explanation tab/direct caller (`DEC-041`) without double execution; the tab remains functional.
- [ ] Prompt editing uses private revisions and immutable new-version release rather than in-place asset mutation.
- [ ] Evaluation evidence is pinned, isolated, cost/quota constrained, and unable to self-approve or auto-publish.
- [ ] Prompt Audit has exact-digest rules/runs/findings and separately append-only governance events; both are redacted, authorized, and distinct from the execution transcript.
- [x] ~~OQ-007 blocks only the generated-content evaluator package~~ *(OQ-007 resolved by `DEC-055` — the evaluator shipped, dev/85/86)*; OQ-008 owns final prompt/evaluation/audit retention policy.
