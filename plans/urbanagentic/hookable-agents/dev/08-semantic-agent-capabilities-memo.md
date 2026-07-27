# Implementation Memo: Restore Semantic Agent Capabilities

## 1. Problem Statement

The prompt-to-agent migration correctly made each prompt behavior a hookable package, but some planning language replaced semantic `capabilities` with roles, delegates, or prompt assets. These concepts are not interchangeable. A prompt path describes implementation; a capability describes stable behavior. Removing capabilities weakens discovery, orchestration, compatibility, and substitution. Conversely, treating a capability as authorization would improperly grant data or tool access from descriptive metadata.

## 2. Scope

Included: restore manifest `capabilities`, define semantic capability IDs for all fourteen planned prompt-backed definitions, distinguish capabilities from lifecycle commands, roles/delegates/prompts/tools/provider requirements/permissions/settings/prompt governance, constrain resolution to explicitly project-installed templates, and add tests/criteria. Thirteen source-backed packages can be enabled; the evaluator remains blocked. Out of scope: changing prompt text, creating packages, retention decisions, or implementation.

## 3. Recommended Implementation Approach

Each manifest declares semantic IDs such as `node.explain`. Capability IDs remain independent of agent/display/prompt/framework names, permissions, settings, evaluator approval, audit roles, and Import/Install/Attach/Publish commands. Orchestrators resolve only compatible `ProjectAgentTemplate` records installed in the current project; a visible global definition or account import is not executable merely because it matches. `delegatesTo` expresses a preferred/required implementation, not auto-import/install. Prompt assets implement capabilities but never identify them. Declarations/default seeds grant nothing; each attach/execution independently authorizes project, target, provider, context, tools, mutations, policy, and admission.

Prompt quality is a platform governance workflow. It may invoke an explicitly approved evaluator artifact through the normal runtime, but a `content.quality.evaluate` declaration neither authorizes fixture access nor grants reviewer/approval/publish authority. A candidate prompt cannot resolve itself as its own judge. `agent.generated-content-evaluator` remains blocked by `OQ-007`; another capability implementation must not be silently substituted merely to close that blocker.

## 4. Data and State Handling

Capabilities are immutable definition metadata indexed by the catalog/registry. Runtime resolution combines capability contract, target/provider/tools/trust, current-project template availability, and its source definition. `AttachedAgentInstance` persists `projectAgentTemplateId` and has only identity/concurrency revision; the execution—not the attachment—pins the exact source definition/prompt/settings/provider/effective-policy revisions. Authorization, lifecycle state, settings, and prompt drafts/evaluation/audit remain separate projections and never capability-registry state.

## 5. UI and UX Requirements

Catalog/import/project-template details may expose friendly labels. Capability labels never imply `Imported`, `Installed in this project`, publish eligibility, attachment version state, or prompt-governance authority. The node `Explanation` tab is removed; `node.explain` discovery may offer the normal Node Explainer project-install/attach/chat path only.

## 6. Edge Cases

- Two agents implement the same capability with different contracts or target support.
- A manifest declares an unknown or deprecated capability.
- Capability requirements match an agent but provider/tool/target requirements do not.
- Capability resolution succeeds but the user or policy denies a requested context/tool/provider grant.
- A prompt filename is mistakenly registered as a capability ID.
- An orchestrator resolves a newer incompatible capability contract version.
- An evaluator implements the requested semantic capability but lacks authorized fixture, provider, budget, egress, reviewer, or audit access.
- A candidate draft is selected as its own evaluator or an evaluation result is treated as activation/publication approval.
- A manifest attempts to encode cost ceilings, mutable prompt drafts, reviewer identity, or audit state as capabilities.
- A matching definition is globally visible/imported but not installed in the current project; resolution must produce a reviewed install proposal, not auto-install/run.
- A project template/attachment claims user Publish/Share/version authority from its capability declaration.
- Node explanation falls back to a direct caller when no project-installed Node Explainer implements `node.explain`.

## 7. Testing Strategy

Test syntax/taxonomy, duplicates, contracts, targets/providers, deterministic current-project-template resolution, explicit delegate preference, unknown/deprecated IDs, and prompt-name rejection. Negative tests prove declarations cannot auto-import/install/attach, authorize runtime/settings/prompt governance, or make a template/instance publishable/shareable/versioned. Node explanation tests require an installed/attached Node Explainer and reject raw fallback. Evaluation tests keep OQ-007 unavailable.

## 8. Acceptance Criteria

- Every prompt-backed agent declares at least one semantic capability.
- No capability equals or derives mechanically from a prompt filename.
- Orchestration can resolve agents by capability and persist the selected exact artifact coordinate.
- Prompt assets remain package-local, digest-verified implementation references.
- Roles, capabilities, delegates, typed tool requirements, prompts, provider requirements, and permission grants have distinct documented semantics.
- Capabilities and installation never grant context, provider, tool, or mutation access.
- Capabilities never grant policy override, prompt edit/evaluate/review/audit, activation, or publication authority.
- Capabilities never grant Import/Install/Attach/Publish/Share or make an attachment an artifact/version.
- Resolution uses only current-project templates and records exact execution pins without versioning the attachment.
- `node.explain` is delivered through Node Explainer unified chat; the retained node Explanation tab (`DEC-041`) is a separate legacy surface outside the capability system.
- Prompt-quality resolution persists the exact evaluator coordinate and independent grants/effective policy; a candidate cannot evaluate or approve itself.
- `OQ-007` remains a content/contract blocker for one agent package and is not bypassed through capability matching.

## 9. Recommended Commit Breakdown

1. Add capability taxonomy/schema and registry tests.
2. Add semantic capabilities to built-in agent manifests.
3. Implement capability-based resolution and deterministic selection tests.
4. Update catalog/read models, documentation, and migration validation.

## 10. Engineering Quality Checklist

- [ ] Capability IDs are semantic and stable.
- [ ] Capability contracts are typed/versioned where required.
- [ ] Capabilities remain semantic behavior metadata, never permissions.
- [ ] Prompt paths are never capability IDs.
- [ ] Resolution considers target, contracts, provider, trust, install, and version.
- [ ] Selected implementations are persisted for reproducibility.
- [ ] Runtime grants are authorized and audited separately from capability resolution.
- [ ] Mutable settings, prompt drafts, evaluation evidence, approvals, and audit events are never encoded as capabilities.
- [ ] Lifecycle/publication state is never encoded or inferred from capabilities.
- [ ] A matching catalog/import definition cannot execute until explicitly installed in the current project and attached/delegated through policy.
- [ ] Attached instances remain unversioned private derivations; shared results carry no capability/private-agent data.
- [ ] Prompt-quality capability matching cannot imply evaluation-fixture access or release approval.
- [ ] Candidate/self-evaluator and silent OQ-007 substitution paths fail closed.
- [ ] Unknown/deprecated/incompatible capabilities fail clearly.
