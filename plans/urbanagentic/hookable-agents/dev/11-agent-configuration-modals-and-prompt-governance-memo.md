# Implementation Memo: Agent Configuration Modals and Prompt Governance

## 1. Problem Statement

The current plan supports attachment configuration through chat and mentions runtime cost, quota, and resource limits, but it does not define clear configuration screens, per-agent defaults, prompt authoring, repeatable prompt-quality evaluation, or prompt-governance history. Treating these concerns as chat commands or one untyped configuration object would make effective limits difficult to understand, allow concurrent runs to overspend, weaken immutable prompt provenance, and expose sensitive prompt content or audit records through inappropriate caches and shared views.

The application needs clear cog/settings entry points and six dedicated modal screens for Cost, Quotas, Resource policies, Prompt quality, Prompt editor, and Prompt audit. Every explicit `ProjectAgentTemplate` installation must start with an isolated validated per-agent default configuration. Policy changes remain server-authoritative, prompt authoring applies only to owned `AccountImportedAgent` definitions created through explicit Import, and the shared result contains no private settings or prompt-governance data.

## 2. Scope

Included: account policy, imported-definition, project-template, and attached-instance settings scopes; per-project-agent defaults; cost estimation/reservation/settlement; quotas/resources; imported-definition prompt drafts; deterministic evaluation; versioned compliance/security audits and append-only governance history; authorization; APIs; persistence; module ownership; accessibility; tests; rollout; and traceability.

Out of scope: marketplace billing, clients raising deployment ceilings, provider-credential editing in these screens, mutating released/published prompt bytes, project-private prompt overrides, publishing/sharing project templates or instances, account-wide installed palettes, silently using the unresolved evaluator, final retention decisions outside `OQ-008`, or application implementation.

## 3. Recommended Implementation Approach

### Settings shell and dedicated screens

Use one shared `AgentSettingsModal` dialog shell with six dedicated, directly addressable screens. Only one dialog is open at a time; screens are not nested dialogs. Per the `DEC-038` release cut, the three **policy** screens (Cost / Quotas / Resource policies) ship in **v1**; the three **governance** screens (Prompt quality / Prompt editor / Prompt audit) are **v2** (demand-gated) — v1 renders them as an explicit "available in a later release" disabled state, and the six-screen shell is the v2 end-state.

| Screen | Primary responsibility | Supported scopes |
| --- | --- | --- |
| Cost | Estimates, actual usage, warning/hard budgets, pricing snapshot, and the **account-scope-only** evaluation sub-budget (`DEC-037`) | Account policy; project-template defaults; instance tightening — **the evaluation sub-budget appears only under account policy** |
| Quotas | Execution/request/token/tool/evaluation/concurrency/queue allowances and reset windows (evaluation allowances are account-scope, `DEC-037`) | Account policy; project-template defaults; instance tightening |
| Resource policies | Provider/profile/model/locality allowlists, context/output/time/tool/network and local compute bounds | Account policy; project-template defaults; instance tightening |
| Prompt quality | Versioned suites, fixtures, rubrics, thresholds, evaluation runs, stale evidence, release gates | Owned account import only; authorized lower scopes read-only |
| Prompt editor | Package-local system/instruction assets, variables, schema validation, diff, private draft revisions | Owned account import created through explicit Import only |
| Prompt audit | Static security/compliance/provenance runs/findings plus append-only edit/evaluate/review/release/publish history | Owned account import only; authorized lower scopes read-only |

The catalog header exposes `Agent settings` for account policy. An owned item under `My Imports` exposes prompt authoring/quality/audit and imported-definition release. A project-installed-template detail exposes `Project agent settings` for that project's Cost/Quota/Resource defaults; its prompt evidence is read-only **and, when the source is an unpublished private import, visible only to that import's owner — collaborators get execution only until the import is published to the Catalog Hub** (`DEC-036`). Attached chat exposes `Attached instance settings` for downward-only overrides. Palette rows remain action-free. Server authorization determines applicability; project templates/instances never expose Release/Publish/Share.

### Policy hierarchy and per-agent defaults

The server computes the effective configuration as the strictest intersection:

```text
deployment hard ceilings
  ∩ account policy/defaults
  ∩ selected project's ProjectAgentSettingsProfile
  ∩ attached-instance downward-only overrides
  ∩ atomic execution reservation
  = EffectiveAgentPolicySnapshot persisted on the execution
```

Manifest `settingsDefaults` are immutable seed suggestions for one definition. Each explicit project install materializes a distinct project-private revisioned profile. Reset restores that selected project's default under current account/deployment policy; it never changes another project, the imported definition, or another instance. Instance overrides may only tighten.

All enabled agents share these conservative defaults unless their reviewed profile is stricter:

- Cost inherits account budgets, displays estimate source/time, pauses or blocks before a hard limit, and never assumes unapproved overage.
- Quota inherits account windows, starts with at most one concurrent execution per project template, and uses atomic reservation before provider/tool work.
- Resources use the deployment's `standard` resource class, an explicitly selected provider profile, provider-and-authorized-tool network access only, and no local-to-remote fallback.
- Prompt quality runs static/schema/safety/regression checks after edits and before activation/release; model-as-judge is unavailable until an explicitly approved evaluator artifact/profile is selected.
- Prompt editing always uses a private draft owned by an explicit account import with optimistic concurrency; Save never activates or publishes.
- Prompt compliance/security auditing after edits and append-only governance event capture are mandatory and cannot be disabled by an agent manifest or account user.

Portable manifests must not hardcode one universal dollar amount, provider price, or hardware size. Deployment/account policy supplies environment-specific monetary and resource ceilings; the per-agent profile supplies safe behavior, relative bounds, execution/review mode, and any stricter agent-specific limits. The settings screens always materialize concrete effective values for the current account/provider and identify their source.

| Default profile | Agents | Additional defaults |
| --- | --- | --- |
| `interactive-report` | `agent.chat-agent`, `agent.dataflow-explainer`, `agent.node-explainer` | Foreground interaction, report-only output, no mutation tools, evaluation required after prompt changes. |
| `planning-analysis` | `agent.dataset-finder`, `agent.execution-subtask-planner`, `agent.dataflow-task-planner`, `agent.workflow-suggester`, `agent.plan-coherence-validator`, `agent.syntax-analysis-agent`, `agent.task-refresh-agent`, `agent.keyword-binding-agent` | Structured output, bounded background work, no direct mutation, deterministic regression suite required before release. |
| `mutation-proposal` | `agent.node-builder`, `agent.debug-agent`, `agent.node-content-builder`, `agent.connection-builder`, `agent.package-recommendation` | Review-before-apply, stricter tool/resource limits, quality gate plus authorized human approval before releasing/publishing an owned imported definition. |
| `orchestration-mutation` | `agent.dataflow-builder` | Parent and child work share an aggregate reservation, delegated agents keep their own tighter policies, concurrency is bounded, and every install or graph mutation remains review-gated. |
| `evaluation-disabled` | `agent.generated-content-evaluator` | Definition remains unavailable and cannot run or self-certify until `OQ-007` supplies an approved prompt and contract. |

These mappings are portable definition seeds. Every later definition validates a bounded seed, and every explicit project installation materializes its own reviewed profile; no account-wide installed profile exists.

### Prompt authoring and release

Prompt editing follows:

```text
immutable exact artifact
  -> private PromptAuthoringWorkspace / PromptDraftRevision
  -> static + security/compliance audit
  -> pinned PromptEvaluationRun
  -> authorized review
  -> Release version
  -> new AgentArtifactCoordinate and digest
  -> new private AccountImportedAgent artifact/revision
  -> optional explicit Install/update in a selected project and/or user Publish
```

Third-party, built-in, global, project-template, and attached-instance prompt sources are read-only. The current phase does not create a fork implicitly from those screens. A future fork/export must be packaged and explicitly re-imported before it can become an owned authoring source and is out of scope. Existing project templates/instances remain unchanged. Prompt quality is separate from `agent.generated-content-evaluator`; a candidate cannot judge/approve itself, and evaluation/audit never auto-releases, installs, or publishes.

## 4. Data and State Handling

Use typed, independently revisioned records rather than a single settings JSON blob:

- `AgentSettingsBinding {bindingId, scopeType, scopeId, settingKind, activeRevisionId, draftRevisionId, revision}`.
- `AgentSettingsRevision<T> {revisionId, bindingId, ordinal, state, schemaVersion, baseActiveRevisionId, bodyHash, createdBy, createdAt, activatedAt}`.
- `CostPolicy`, `QuotaPolicy`, and `ResourcePolicy` typed bodies with independent validators.
- `EffectiveAgentPolicySnapshot` containing every contributing revision ID and the resolved values used by one execution.
- `ProviderPriceSnapshot`, `BudgetReservation`, `QuotaReservation`, and append-only `UsageLedgerEntry` records for estimate/reserve/settle/reconcile behavior.
- `PromptAuthoringWorkspace`, `PromptDraftRevision`, and `PromptDraftFile` records tied to one owned `AccountImportedAgent`, base artifact coordinate, and contained package path.
- `PromptEvaluationSuite` and `PromptEvaluationRun` pinned to the exact draft digest, suite revision, evaluator coordinate when used, provider-profile revision, fixture digests, policy snapshot, usage, and cost.
- `PromptAuditPolicy`, `PromptAuditRun`, and typed `PromptAuditFinding` records pinned to the exact draft digest, ruleset revision, policy revision, status, severity, locations, and remediation state.
- `PromptAuditEvent` as an append-only, integrity-linked metadata record; optional encrypted prompt snapshots/diffs remain separately protected and may be policy-redacted or crypto-shredded while retaining a tombstone/hash.

Policy form flow is Edit local form → Save server draft → Validate → explicit Activate. The prior active revision stays effective until atomic activation. A running execution keeps its persisted snapshot; ordinary changes affect only later executions. Emergency kill switches/quarantine remain separate privileged actions.

Execution admission resolves policy, reserves cost/quota/resource capacity atomically, persists the snapshot and reservation IDs, and only then queues work. Settlement records provider-reported usage; expired or ambiguous reservations are reconciled with leases rather than silently discarded or replayed. Unknown pricing fails closed when a monetary hard cap is configured, while deterministic token/request ceilings remain enforceable.

Prompt editor content stays in memory-only local state and is never stored in local storage, shared/global query caches, URLs, analytics, transcripts, or generic catalog DTOs. Close, project switch, logout, and account switch purge it. Save uses `If-Match`/`expectedRevision`; conflicts return revision/diff metadata. Any edit invalidates evidence for the old digest.

## 5. UI and UX Requirements

- Every settings trigger uses a cog plus the scope-correct visible label where space permits — `Agent settings` (account policy), `Definition settings for <agent>` (owned import), `Project agent settings` (project template), or `Attached instance settings` (attachment) — matching `../docs/03-ui-decisions.md` and `../docs/11-agent-manifest-and-product-model.md`; compact controls retain a tooltip, unique accessible name, 44-by-44 CSS-pixel target, and `aria-haspopup="dialog"`.
- The modal header shows definition/template/instance name, source digest where applicable, ownership, project, and scope: Account policy, Imported definition, Project agent default, or Attached instance.
- Left navigation uses icon plus text for all six screens. Inapplicable or unauthorized screens are omitted or read-only with a server-provided reason.
- Every policy field shows effective value, inherited source, editable value, immutable ceiling, and that Reset restores the selected project's template default for an instance.
- Policy screens use Save draft, Validate, Activate, Cancel, and Reset to project agent default where applicable. Prompt Editor uses Save draft and Compare. Prompt Quality uses Run/Cancel evaluation and never Publish. Prompt Audit can Run/Cancel a compliance audit and manage authorized remediation notes; governance events remain append-only, while filters/export are separately authorized. Release, project Install/update, and Publish remain explicit separate actions.
- Prompt Quality distinguishes static/schema checks from advisory model-based judgment, displays evaluator/provider/locality and estimated evaluation cost before run, and shows Unavailable rather than substituting an evaluator.
- Prompt Audit runs versioned static security/compliance/provenance rules and shows findings/remediation state alongside governance history; it is not the execution transcript. `Run audit` never activates or publishes. Full-content reveal/export requires narrower authorization and is itself audited and rate-limited.
- Small viewports use a full-screen dialog. Focus is trapped and restored to the opener; Escape/close with unsaved changes requires confirmation; navigation, fields, code editor fallback, errors, conflict resolution, and evaluation progress are keyboard and screen-reader accessible.
- Loading, inherited/read-only, dirty, validating, saving, saved, conflict, forbidden, unavailable, queued, running, completed, failed, cancelled, and stale states use text/icons as well as color and avoid layout shift.

## 6. Edge Cases

- Account/deployment policy or selected project changes while a template/instance settings modal is open or work is admitted.
- Project-template or instance overrides attempt to loosen a hard ceiling, provider allowlist, egress rule, tool grant, or retention rule.
- Concurrent executions reserve the last available budget/quota; exactly one succeeds.
- Provider pricing is missing, stale, changes currency/revision, or reports usage after a timeout/interruption.
- A hard cost/quota limit is reached during streaming; the run stops safely with `quota_exceeded`/`budget_exceeded` and no unreviewed mutation is applied.
- Local resources are exhausted; work queues or fails according to policy and never falls back to cloud implicitly.
- Modal draft save/activation conflicts with another tab/device or the actor loses permission while the modal is open.
- Prompt draft changes variables, encoding, schema, contained path, or safety-sensitive instructions; validation fails without altering the active artifact.
- A built-in/global/project-template/instance prompt is edited without an owned explicit import; the server denies authoring and leaves the source read-only.
- Evaluation fixtures contain sensitive or injected content, a remote evaluator violates egress policy, evaluation exceeds its own budget, or the candidate tries to self-evaluate.
- An evaluation result references an older draft/suite/evaluator/policy revision and becomes stale.
- A compliance audit uses an older draft/ruleset/policy revision, produces unresolved high-severity findings, or fails to persist its required event; release remains blocked.
- Audit write, integrity check, or required reviewer decision fails during activation/release; the operation fails closed.
- Prompt content accidentally contains a secret; rotate the secret, restrict content, append remediation events, and apply policy-controlled redaction/crypto-shredding without rewriting event history.
- Rollback targets a quarantined digest or would mutate an existing project template/instance; it is rejected or creates a new private import revision followed by separate reviewed project update.
- Project/account switch occurs with editor text, evaluation streams, optimistic mutations, or modal drafts active; mismatched private state/streams clear.

## 7. Testing Strategy

- Unit/contract: typed policy schemas, per-project-template defaults, strict precedence, instance downward-only overrides, independent revisions, project-isolated resets, effective snapshots, authorization flags, and stable errors.
- Cost/quota: price revisions, estimate-versus-actual settlement, unknown prices, currency/window boundaries, idempotent atomic reservations, concurrent overspend prevention, child/retry/evaluation charging, cancellation, stale-reservation reconciliation, `429` plus `retryAfter`.
- Resource: provider/model/locality intersections, context/output/tool/timeout/CPU/RAM/GPU bounds, queue behavior, egress/SSRF checks, and no remote fallback.
- Prompt editor: explicit-import ownership authorization and denial for every other source, memory-only state, contained path/schema validation, conflicts, immutable released imported artifacts, SemVer/digest collision, and project-template/instance preservation.
- Prompt quality: deterministic checks, exact-digest evidence, suite/evaluator/policy pinning, stale detection, evaluation-budget denial, sensitive-fixture minimization, evaluator isolation with tools/network disabled, OQ-007 unavailable state, and no auto-activate/publish.
- Prompt audit: exact-digest/ruleset pinning, static security/compliance/provenance findings, severity/remediation gates, stale-result invalidation, append-only order/integrity, mandatory event categories, redaction, non-enumerating authorization, filters/pagination, step-up export/reveal, export auditing, retention/tombstone behavior, and tamper detection.
- Component/accessibility: all cog names/tooltips, correct scope and authorization, six dedicated screens, inherited/effective displays, dirty-close guard, focus trap/return, keyboard navigation, error summary/field focus, live announcements, zoom/reflow, reduced motion, and forced colors.
- Integration/E2E: owned import edit → validate → evaluate → audit → review → release new private definition → separate project Install/update and/or Publish. Existing templates/instances remain unchanged; Cost/Quota/Resource denial precedes provider work.
- Privacy/regression: no prompt/policy/audit data in public DTOs, logs, telemetry, URLs, local storage, another project/account cache.

## 8. Acceptance Criteria

- Clear authorized cogs open one shell with six screens at Account policy, Imported definition, Project agent default, or Attached instance scope.
- Every explicit project install materializes a reviewed isolated default profile; Reset affects only that project/template and remains bounded.
- Cost, quota, and resource admission is server-authoritative, atomic, revisioned, auditable, and persisted on every execution snapshot.
- Settings changes cannot grant provider, egress, context, tool, mutation, or retention permissions.
- Prompt Save changes only an owned explicit-import draft; Release creates a new immutable private imported artifact and never installs, publishes, or mutates a template/instance automatically.
- Prompt quality evidence is reproducible for an exact digest and cannot self-approve, auto-activate, or auto-publish. The missing generated-content evaluator is never silently substituted.
- Prompt audit provides exact-digest compliance/security findings and append-only integrity-checked governance history, is separately authorized from transcripts, and redacts prompt/context/secret content by default.
- Modal state, concurrency conflicts, unknown pricing, unavailable evaluators/resources, and limit enforcement have stable recovery behavior and accessible feedback.
- Frontend and backend settings, prompt authoring, evaluation, and audit responsibilities remain inside their respective `agents/` modules; only generic dialog/form/editor primitives remain shared.

## 9. Recommended Commit Breakdown

1. Add settings/prompt-governance decisions, schemas, project-template default profiles, revised scopes, and traceability IDs.
2. Add independently revisioned policy records, precedence, effective snapshots, usage reservations/ledger, and contract tests.
3. Add account-import prompt workspaces, private content APIs, validation, and immutable private-definition release flow.
4. Add versioned evaluation suites/runs, cost/quota enforcement, stale-evidence gates, and audit events.
5. Add the shared settings shell, three policy screens, entry points, permissions, and accessibility tests.
6. Add Prompt Quality, Prompt Editor, and Prompt Audit screens with privacy and end-to-end governance coverage.
7. Align product docs, KGGraph Build Logs, visual sources, and regenerated PNG/SVG/workbook evidence in a dedicated artifact commit.

## 10. Engineering Quality Checklist

- [ ] Six settings areas use typed independent domains, not one unvalidated JSON object.
- [ ] Per-project-template defaults are explicit, isolated, resettable, and bounded; instances only tighten.
- [ ] Effective policy source revisions are persisted on every execution.
- [ ] Cost/quota reservations are atomic, idempotent, reconciled, and race-tested.
- [ ] Resource settings cannot bypass provider, egress, tool, context, or secret policy.
- [ ] Prompt bodies remain private, memory-only on the client, and absent from generic DTOs/logs/telemetry.
- [ ] Prompt edit/save/release is limited to owned explicit imports and preserves all project templates/instances; other sources remain read-only.
- [ ] Evaluation evidence is exact-version reproducible, isolated, budgeted, non-self-approving, and never auto-publishes.
- [ ] Prompt audit events are append-only, integrity-checked, redacted, authorized, and retention-aware.
- [ ] Cog buttons, modal navigation, dirty-state handling, focus, announcements, and responsive behavior meet WCAG 2.2 AA.
- [ ] Cross-project and cross-account denial is non-enumerating and fully tested.
- [ ] Chat remains the conversational refinement/run/review history; governed settings and prompt authoring use the shared modal system.
- [ ] All business logic remains under frontend/backend `agents/` modules with shared primitives kept feature-neutral.
- [ ] Documentation, tests, commits, and KGGraph evidence remain bidirectionally traceable.
