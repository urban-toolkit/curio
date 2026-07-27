# Agent Manifest & Product Model

Every reusable agent definition is an immutable manifest package, but definitions, account
imports, project installations, and configured attachments are different product objects. Import,
Publish, Install in project, and Attach are explicit independent commands. The UI must never make a
private project derivation look publishable or make a shared flow/Trill look like access to the
saved project/spec and its dependencies.

## Product model (shared conventions, agent-specific lifecycle)

```text
Manifest package ── explicit Import ──► AccountImportedAgent (private My Imports)
                                             ├─ explicit Publish ──► Global Catalog
                                             └─ explicit Install in project ─┐
Global Catalog ───────── explicit Install in project ────────────────────────┤
                                                                             ▼
                                                            ProjectAgentTemplate
                                                                             │ explicit Attach
                                                                             ▼
                                                            AttachedAgentInstance
```

The card action controls reuse the **exact Data / Node Catalog primitives** — a dark `Install`
primary, a neutral white-outline `Uninstall` secondary, the shared `Publish` → `Published` pill,
and `Delete` — with matching styling, placement, spacing, pill states, and behavior.

- **Global Catalog.** Browse built-in/system-curated and user-published definitions. Cards offer
  `Install` (available) or `Uninstall` (already installed). Global/built-in items cannot be
  user-republished and have no agent Share action.
- **My Imports.** `Import package` validates into private account storage and creates one
  `AccountImportedAgent`; it does not modify the open project, install, or publish. An owned,
  validated imported definition exposes `Install`, the shared `Publish` → `Published` pill, and
  `Delete`. `Install` and `Publish` are separate actions and neither triggers the other.
- **Installed in this project.** Explicit Install creates one `ProjectAgentTemplate` plus its
  project-private settings profile. It appears only in that project's AGENTS palette. Project
  templates expose `Uninstall` (settings open from the `Project agent settings` cog), never
  Publish, Share, or global release controls.
- **Project palette.** Rows contain only templates installed in the active project. The whole row
  is draggable and action-free. Switching projects replaces the palette and clears mismatched
  attachment/settings/session state.
- **Attached instance.** Dragging a project template to a compatible target creates a private
  `AttachedAgentInstance`. It has chat/settings/runtime state but no SemVer, definition release,
  Publish, Share, or catalog lifecycle.
- **Settings applicability.** Account policy owns Cost/Quotas/Resources upper bounds. Owned My
  Imports definitions own Prompt Editor/Quality/Audit and immutable releases. Project templates
  own project Cost/Quotas/Resource defaults; attachment policy only tightens them. Project and
  attachment prompt screens are provenance/evidence read-only.

Import, publication, project installation, attachment, execution, quarantine/revocation,
uninstallation, and retention are independent state machines. Updating/publishing an imported
definition never mutates a project template or attached instance. Project uninstall checks only
that project's live attachments/reviews/executions and never silently detaches.

## Aggregate Identity And Sharing Boundary

`AgentArtifactCoordinate { publisherNamespace, agentId, exactVersion, artifactDigest }` identifies
immutable reusable definition bytes. Reusing the same publisher/ID/exact-version tuple with a
different digest fails closed.

```text
AccountImportedAgent { accountImportedAgentId, accountId, artifactCoordinate, validationState }
ProjectAgentTemplate { projectAgentTemplateId, projectId, sourceArtifactCoordinate, settingsProfileId }
AttachedAgentInstance { attachmentId, projectId, projectAgentTemplateId, target, configuration, revision }
```

`projectId` is the current repository's private flow/Trill project-scope key; it is neither part of
an installable definition's identity nor exposed in the shared result.

Attachment `revision` is only optimistic concurrency. The instance has no version string or
publication coordinate. Each execution privately persists the resolved definition digest, project
settings revision, attachment revision, prompt digest, provider-profile revision, and effective
policy snapshot. These pins make a run reproducible without turning the attachment into an artifact.

Sharing a flow/Trill never exposes the raw saved Trill/spec, a live-project projection, or
agent-private data in the shared result. Datasets/paths/credentials/lineage, node packages/code/
runtime configuration, definitions/imports/project templates/attachments, agent flows/docks,
settings, prompts, evaluations/audits, transcripts/history, providers/tools, usage/cost, private
URLs, and account/project/storage IDs never appear in the public result view.

Mutable settings and prompt governance use separate identities rather than mutable manifest
fields:

```text
AgentSettingsBinding     { bindingId, scopeType, scopeId, settingKind, activeRevisionId,
                           draftRevisionId, revision }
AgentSettingsRevision<T> { revisionId, bindingId, ordinal, state, schemaVersion, bodyHash }
ProjectAgentSettingsProfile { settingsProfileId, projectAgentTemplateId, seedCoordinate,
                              costBindingId, quotaBindingId, resourceBindingId, revision }
EffectivePolicySnapshot  { contributingRevisionIds, resolvedValues, reservationIds }
PromptDraft              { draftId, accountImportedAgentId, basedOnArtifactCoordinate,
                           revision, status }
PromptEvaluation         { evaluationId, promptRevision, suiteVersion, evaluatorCoordinate?, status }
PromptAuditRun           { auditId, promptRevision, ruleSetVersion, status, findings }
PromptAuditEvent         { eventId, sequence, actor, action, hashes, reason, timestamp }
```

The server computes an `EffectiveAgentPolicy` from deployment hard limits, account policy,
project-template defaults, an optional attachment override, and an atomic execution reservation.
Lower scopes may narrow inherited policy but cannot relax it. Policy records and draft/evaluation/
audit records are private and absent from the shared result.

## Agent manifest

A single manifest consolidates the agent's description. The catalog card, palette row,
attachment rules, and refinement drawer are all derived from it.

```json
{
  "$schema": "../../docs/schemas/agent-package.v1.json",
  "id": "agent.example",
  "name": "Example Agent",
  "category": "node",
  "version": "1.0.0",
  "purpose": "One-line description.",
  "roles": ["explanation"],
  "capabilities": [{ "id": "node.explain", "contractVersion": "1" }],
  "delegatesTo": ["agent.node-builder"],
  "prompts": {
    "system": { "path": "prompts/default_preamble.txt", "sha256": "<sha256>", "variables": [] },
    "instruction": { "path": "prompts/instruction.txt", "sha256": "<sha256>", "variables": ["nodeContext"] }
  },
  "contracts": {
    "inputSchema": "schemas/input.schema.json",
    "outputSchema": "schemas/output.schema.json"
  },
  "compatibleTargets": [{ "kind": "node", "requires": ["code-or-output"] }],
  "inputs": { "reads": ["nodeContext"], "requiredConfig": ["geography"] },
  "outputs": ["explanation"],
  "configuration": { "options": [], "defaults": {} },
  "runtime": { "execution": "foreground", "reviewPolicy": "report-only" },
  "providerRequirements": { "capabilities": ["structured-output"] },
  "tools": [{ "id": "catalog.search", "required": false }],
  "settingsDefaults": {
    "profileId": "interactive-report",
    "profileVersion": "1",
    "suggestions": {
      "quota": { "maxConcurrentExecutions": 1 },
      "resource": {
        "resourceClass": "standard",
        "network": "provider-and-authorized-tools-only"
      },
      "promptQuality": {
        "staticChecksAfterEdit": true,
        "requiredBeforeRelease": true
      }
    }
  },
  "provenance": { "publisher": "curio", "license": "MIT", "trust": "built-in" }
}
```

The manifest is immutable definition metadata. Account-import ownership, global-publication state,
project installation, attachment configuration, effective cost/quota/resource policy, prompt
drafts/evaluations/audit, and execution status are separate server records joined into drawer,
palette, settings, and runtime read models. They must never be persisted
as user-specific mutable fields inside a shared manifest. Canonical `manifest.json` uses
camelCase field names. Provider credentials are selected through an authorized account-level
`providerProfileId` outside the manifest; only provider requirements belong here. Tool entries
are typed allowlisted requirements, not executable code or permission grants.

`settingsDefaults` is immutable metadata for one exact artifact. It contains only non-secret,
schema-valid seed suggestions and a reviewed profile-family ID/version. It is not active policy,
does not create a generic/global agent preset, and cannot grant or loosen provider, egress,
context, tool, mutation, retention, budget, quota, or resource permissions. A manifest cannot
create a new trusted profile family implicitly.

### Manifest → UI mapping

| Manifest field | Surfaces in |
| --- | --- |
| `name`, `category`, `purpose` | Catalog card, AGENTS palette row |
| `roles`, `outputs` | Catalog labels/classification and refinement chat |
| `capabilities` | Catalog discovery, orchestration resolution, compatibility, and substitution; never authorization |
| `prompts`, `contracts` | Server-side artifact validation/runtime construction plus read-only provenance in Prompt quality/editor/audit; paths are not primary UI labels |
| `compatibleTargets` | Attachment (which nodes/canvas glow; palette drag targets) |
| `inputs.reads`, `inputs.requiredConfig` | Refinement drawer context/configuration; secrets are represented only by provider-profile selection |
| `configuration.options` | Unified chat (lightweight quick replies / behavior choices); these are not server cost/quota/resource policy |
| `runtime.execution` plus execution projection | Dock running dots; orchestration status chips |
| `runtime.reviewPolicy` | "review required / suggestions only" labels |
| `providerRequirements`, `tools` | Required runtime features shown before independently authorized profile/tool grants |
| `settingsDefaults` | Seed provenance in `Project agent settings`; each explicit project install materializes private typed revisions after policy clamping |
| account-import projection | My Imports validation/ownership state plus separate `Install in project`, prompt-governance cog, and eligible `Publish` actions |
| publication projection plus manifest version | Global Catalog publication/publisher state and immutable definition `v{N}` pill; never attachment versioning |
| project-template projection | Installed in this project detail, `Project agent settings`, `Uninstall from project`, and the active project's action-free palette row |
| attachment projection | Private dock/chat/target/status and `Attachment settings`; no version, release, Publish, or Share action |

### Mutable settings → UI mapping

| Mutable projection | Surface |
| --- | --- |
| account settings bindings/revisions | Catalog-header `Agent settings` → account policy/defaults and ceilings |
| project-template settings bindings/revisions plus effective-policy read model | Project-installed detail `Project agent settings` → independent per-project Cost, Quotas, and Resource policies defaults |
| attachment settings bindings/revisions plus effective-policy read model | Chat-header `Attachment settings` → downward-only Cost, Quotas, Resource policies overrides |
| usage ledger/reservations | Cost/Quotas current usage, estimates/actuals, reset windows, and enforcement state |
| `PromptDraft` plus server authorization capabilities | My Imports `Definition settings for <agent>` Prompt editor; editable only for an owned definition created through explicit Import, otherwise provenance-only |
| `PromptEvaluation` | Prompt quality run state, pinned suite/evaluator, findings, usage/cost, and stale-result warning |
| `PromptAuditRun` plus append-only `PromptAuditEvent` | Prompt audit compliance rules/findings plus filters/pagination/export where authorized; distinct from the execution transcript |

## Shared Agent Settings Product Model

One modal shell contains six labeled screens: **Cost**, **Quotas**, **Resource policies**,
**Prompt quality**, **Prompt editor**, and **Prompt audit**. It is shared by every agent and does
not reintroduce bespoke refinement panels. The same navigation stays visible while server-returned
capabilities make a screen editable, provenance-only, or unavailable for the current scope:

| Entry point and modal scope | Editable screens | Read-only / unavailable behavior | Lifecycle actions outside the modal |
| --- | --- | --- | --- |
| Drawer `Agent settings` → **Account policy** | Cost, Quotas, Resource policies | Prompt screens are not definition governance | None |
| Owned My Imports `Definition settings for <agent>` → **Imported definition** | Prompt editor, Prompt quality, Prompt audit | Cost/Quota/Resource policy is inherited or not applicable | Separate `Install in project` and, when eligible, `Publish`; `Release` produces a new private imported artifact |
| Installed-project detail `Project agent settings` → **Project agent default** | Cost, Quotas, Resource policies | Prompt source, quality evidence, and audit provenance are read-only | `Uninstall from project`; never Publish/Share/Release |
| Chat `Attachment settings` → **Attached instance** | Cost, Quotas, Resource policies only when narrowing inherited values | Prompt source, quality evidence, and audit provenance are read-only | Detach/disable where authorized; never Version/Release/Publish/Share |

Draggable project-palette rows remain action-free. The modal always names the applicable account,
imported definition, project template, or attachment; it shows an exact artifact coordinate only
for reusable definitions, never as an attachment version. Policy controls show effective value,
inherited source, reset source, and locked constraints.

Cost covers monetary per-run/rolling budgets and alerts, with pricing effective dates and
`Estimated` versus provider-reported `Actual` labels; it is not marketplace billing. Quotas cover
execution/token/tool/concurrency/rate windows and reset information. Resource policies cover
authorized provider profile/model, Local versus Remote processing, context/output/time limits,
egress, tools/network, and supported local-resource bounds. Secret values never enter the read
model. The server reserves and enforces usage atomically; UI calculations are explanatory only.

There is no shared generic agent preset. On explicit project installation, the server validates
the exact artifact's immutable `settingsDefaults`, looks up the reviewed profile family/version,
intersects the seeds with current deployment/account constraints, and atomically creates one
independent project-private `ProjectAgentSettingsProfile` with the `ProjectAgentTemplate`. A
failure exposes neither a partial template nor partial settings. Installing the same definition in
two projects creates two profiles; two agents that reuse a family also receive separate profiles.
Editing or resetting one can never change another project template.

The trusted profile families are reviewed application configuration, not manifest-created policy:

| Profile family | Planned agents | Required posture |
| --- | --- | --- |
| `interactive-report` | `agent.chat-agent`, `agent.dataflow-explainer`, `agent.node-explainer` | Foreground/report-only execution, no mutation tools, and quality evaluation after prompt changes. |
| `planning-analysis` | `agent.dataset-finder`, `agent.execution-subtask-planner`, `agent.dataflow-task-planner`, `agent.workflow-suggester`, `agent.plan-coherence-validator`, `agent.syntax-analysis-agent`, `agent.task-refresh-agent`, `agent.keyword-binding-agent` | Structured output, bounded background work, no direct mutation, and deterministic regression before release. |
| `mutation-proposal` | `agent.node-builder`, `agent.debug-agent`, `agent.node-content-builder`, `agent.connection-builder`, `agent.package-recommendation` | Review before apply, stricter tool/resource limits, prompt-quality evidence, and human approval. |
| `orchestration-mutation` | `agent.dataflow-builder` | Aggregate reservation, tighter child policies, bounded delegate concurrency, and review for installs or graph mutations. |
| `evaluation-disabled` | `agent.generated-content-evaluator` | Unavailable until OQ-007 approves its authoritative prompt and output contract; never silently substituted. |

These profile-family tables cover the full **eighteen-agent** product roster. Fourteen are the
prompt-migration roster (thirteen source-backed packages plus the blocked
`agent.generated-content-evaluator`; see `10-prompt-architecture.md` and `../dev/06-prompt-to-hookable-agent-migration-memo.md`).
Three more — `agent.dataset-finder`, `agent.node-builder`, and `agent.dataflow-builder` —
are net-new **compositions** over migrated capabilities (via `delegatesTo`), specified in
`../dev/15-composite-agent-specifications-memo.md`. The eighteenth, `agent.package-recommendation`
(`package.recommend`/`package.identify`), is specified in `../dev/16-agent-node-package-capabilities-memo.md`.
Package Recommendation, Validation, and Optimization were originally named-only; Package Recommendation
is now specified (dev/16), while Validation and Optimization remain open (`OQ-011`) and are not counted
in the eighteen until specified. The "fourteen-agent planned roster" phrasing elsewhere refers only to
the prompt-migration subset, not this full product roster.

A manifest may reference only a known profile family/version and cannot create or relax a trusted
family. Family values remain seeds subject to the normal deployment/account/project/attachment
intersection.

`Reset to agent default` revalidates the selected project template's exact artifact seeds and
re-clamps them using deployment/account ceilings currently in force; it never restores a stale,
universal, or looser value and never changes another project. Attachment overrides can only
tighten their source project-template profile. Each
execution persists the contributing revisions and resolved effective-policy snapshot, so later
settings changes affect later work rather than rewriting a running or historical execution.

Prompt Editor never changes a manifest or prompt file in an existing artifact. Only an authorized
owned `AccountImportedAgent` created through explicit Import can create a revisioned private draft.
The authoring service validates package-local paths, variables, and schemas and produces a diff. Prompt Quality pins that
draft/artifact revision, suite/rubric version,
thresholds, provider profile, and any explicitly approved evaluator. It does not silently use the
blocked generated-content evaluator and does not auto-release or publish. Release creates a new
private imported immutable version/digest; `Install in project`, a project-template source update,
attachment migration, and `Publish` are separate reviewed actions, so existing project templates
and attachments stay unchanged.

Prompt Audit pins versioned privacy/security/compliance rules, records audit runs/findings, and
appends governance history for edit, validation, evaluation, release, project-template update,
migration, and publication events. It is not chat/run history and is redacted by server
authorization. The shared result exposes no settings cog or private settings/governance data. Third-party/built-in/global, project-template, and attachment
prompts remain read-only. Any future fork/export must be packaged and explicitly re-imported and
is out of scope.

The modal supports loading, inherited/read-only, dirty, validating, saving, saved, conflict,
forbidden, and unavailable states; quality runs add queued/running/completed/failed/cancelled/stale
states. Closing or changing scope/account guards dirty edits. It traps focus, supports keyboard
screen navigation and a plain-text editor fallback, announces saves/evaluations, returns focus to
the opening cog, and meets WCAG 2.2 AA for zoom/reflow, contrast, forced colors, reduced motion,
error association, and non-color state communication.

## Example manifest (Dataset Finder)

```json
{
  "id": "agent.dataset-finder",
  "name": "Dataset Finder",
  "category": "data",
  "version": "1.0.0",
  "purpose": "Discover and select relevant datasets for a data-loading step.",
  "capabilities": [
    { "id": "dataset.discover", "contractVersion": "1" },
    { "id": "dataset.select", "contractVersion": "1" }
  ],
  "delegatesTo": ["agent.node-builder"],
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
  "settingsDefaults": {
    "profileId": "planning-analysis",
    "profileVersion": "1",
    "suggestions": {
      "quota": { "maxConcurrentExecutions": 1 },
      "resource": { "network": "provider-and-authorized-tools-only" },
      "promptQuality": { "deterministicRegressionRequiredBeforeRelease": true }
    }
  },
  "provenance": { "publisher": "curio", "license": "MIT", "trust": "built-in" }
}
```

Prompt-backed agents use the same manifest and lifecycle. Their package contains the linked
system/instruction files under `prompts/` plus input/output schemas. Paths are relative to the
versioned agent artifact and digest-verified, following the same self-contained principle as a
dataset manifest's `dataFile` and node-package template/code assets. See
`10-prompt-architecture.md` for the fourteen-agent planned roster. Thirteen source-backed
packages may be enabled independently; `agent.generated-content-evaluator` remains disabled
until its authoritative prompt and output contract are approved.

`capabilities` and `prompts` are intentionally independent: `node.explain` is a semantic
capability, while `prompts/single_box_explanation_prompt.txt` is one version's implementation
asset. Multiple agents may implement the same capability, and prompt files may change without
renaming the capability. Capability validation rejects prompt filenames and paths.

`agent.node-explainer` is the agent-based product path for node explanation: explicitly install
its template in the active project, attach it to a compatible node, and use unified chat. Per
`DEC-041` (`dev/18`) it coexists with the retained built-in node `Explanation` tab, direct
prompt/provider caller, tab state, and node-store explanation cache — the removal formerly stated
here is cancelled. `agent.dataflow-explainer` remains a separate canvas/full-flow agent.

The Finder is **discovery + selection only**. An external selection hands off to the **Node
Builder** agent, which owns the executable fetch-node implementation (request code, params,
auth, parsing, error handling, output); a Data Catalog selection reuses the existing dataset
**dataset-only install flow** (the catalog dataset may auto-install if not installed). This
does not authorize automatic installation of an agent. See
`06-dataset-finder-source-review.md` for the canonical two-lane workflow.

See `01-consolidated-plan` for the roster and `09-agent-architecture` for how the
manifest's prompt assets, delegates, and runtime policy are implemented (LangChain) behind the swappable
runtime abstraction.
