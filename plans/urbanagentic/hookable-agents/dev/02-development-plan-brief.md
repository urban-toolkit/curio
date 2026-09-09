# Agents Catalog Development Planning Brief

> **Amendment (2026-07-21, `DEC-041` — `18-node-explainer-tab-retention-memo.md`).** This brief is the preserved original planning record. Its requirements to remove the built-in node Explanation tab and make Node Explainer chat the sole explanation path (formerly `DEC-033`) are **superseded and must not be implemented**: the Explanation tab is retained permanently, and the Node Explainer agent chat coexists as an additional surface. Read every removal statement below through that supersession.

> **Current implementation amendment (2026-08-24).** This brief remains historical input, not the current backlog. `DEC-048` retired the proposed LangChain-first implementation in favor of the shipped direct provider/delegation ports (reopen only with `DEC-021` background execution); `DEC-055` and `DEC-057`/`DEC-058` close OQ-007/OQ-008; all three composites and the 21-agent roster ship through dev/97. Use `00-development-phase-index.md` and dev/100 for current status.

Given the current concepts documented in /Users/karla/coding/curio-feat/plans/urbanagentic/hookable-agents/, use the existing artifacts as the source of truth for the next planning and implementation steps.
Create a comprehensive, friendly, modular development planning for the Agents Catalog based on the design concepts, planning materials, and existing documentation located at:

`/Users/karla/coding/curio-feat/plans/urbanagentic/hookable-agents/dev`

The output must be an actionable implementation spec and development plan—not implementation code.

## Product Goals

The Agents Catalog should follow the product model already established for nodes and datasets, including:

- Catalog and palette discovery
- Explicit account-private import of validated manifest definitions, without automatic project installation or publication
- Explicit project-only template installation and active-project palette membership
- User publishing limited to owned validated account imports and kept independent from project installation
- Global catalog browsing
- Manifest-based metadata
- Clear agent attachment behavior within dataflows
- Clear settings cogs and dedicated Cost, Quotas, Resource policies, Prompt quality, Prompt editor, and Prompt audit modal screens

Reuse existing patterns, components, hooks, services, utilities, state-management conventions, and architecture from the datasets and nodes features wherever appropriate. Avoid duplicating logic when an existing abstraction can be reused or a shared abstraction can be extracted cleanly.

Preserve current design decisions and approved concept work. Do not introduce unrelated UI changes, behavior changes, or architectural rewrites unless they are required by the Agents Catalog.

## Core Architecture Requirements

The spec must clearly separate the following responsibilities.

### 1. Agent Creation

The original brief requested LangChain for the initial implementation phase. `DEC-048` superseded that implementation choice: the shipped runtime uses direct provider/delegation ports, with a framework revisit only when `DEC-021` background execution requires it.

Update all relevant design concepts and technical plans to reflect:

- LangChain-based agent creation
- Agent code organization
- Agent instantiation and lifecycle
- Tool registration and execution
- Prompt and instruction configuration
- Input and output contracts
- Runtime configuration and behavior
- Per-agent default settings profiles and layered cost, quota, and resource policy
- Private prompt draft, evaluation, approval, immutable release, and audit behavior
- Error handling and observability

Define how an agent manifest maps to its LangChain configuration, prompts, typed tool requirements, inputs, outputs, provider requirements, runtime policies, and instantiation flow. Manifest capabilities and tool declarations describe behavior and requested dependencies; they never grant data, provider, tool, or mutation permission.

Keep LangChain-specific code behind clear application or infrastructure boundaries so domain models, catalog behavior, and UI components do not depend directly on framework-specific implementation details.

### 2. Import, Project Installation, Attachment, and Publication

Memo `12-agent-template-installation-attachment-sharing-lifecycle-memo.md` supersedes every account-wide installation/palette concept. Define the lifecycle as separate explicit commands and aggregates:

- `AgentDefinitionArtifact`: immutable reusable manifest package with exact coordinate and digest.
- `AccountImportedAgent`: explicit account-private Import result and ownership/provenance record; Import never installs or publishes.
- `ProjectAgentTemplate`: explicit Install result for one selected authorized project; it supplies only that project's palette entry and per-agent defaults.
- `AttachedAgentInstance`: explicit private derivation of one project template at a node/canvas/dataflow target; it uses `attachmentId` plus optimistic concurrency `revision`, not SemVer or artifact/publication identity.

Only an owned validated `AccountImportedAgent` may enter the user Publish workflow. Built-ins/global catalog items, project templates, and attached instances are not user-publishable. Publish, Import, Install, and Attach never auto-chain. System-curated catalog ingestion is a separate administrative path.

The AGENTS palette is populated only from `ProjectAgentTemplate` records for the active project. Switching projects replaces its palette/default/configuration/session state without leaking another project's templates or instances. Project uninstall checks attachments, paused reviews, and nonterminal executions in that project and never detaches silently.

An attachment has no version/release/publish lifecycle. Each execution instead pins the resolved source definition digest, project-template settings revision, attachment concurrency revision, prompt digest, provider-profile revision, and effective-policy snapshot for reproducibility. Updating an imported definition, publication, or project template never silently mutates an existing attachment.

~~Remove the built-in node Explanation tab, state/cache, and direct prompt/provider caller.~~ **Superseded by `DEC-041`:** retain that surface unchanged. Node Explainer project installation/attachment/unified chat is an additional independent path with no implicit fallback or double execution.

Every project installation materializes an independent revisioned per-agent settings profile. Deployment ceilings, account safety/privacy policy, the selected project-template profile, attached-instance downward-only overrides, and an atomic reservation resolve to one effective policy snapshot. Settings remain separate from immutable manifests and private runtime/history state.

### 3. LLM Provider Abstraction

Define a flexible provider interface capable of supporting:

- Third-party LLM providers
- Cloud API providers
- Local Gemma models
- Hugging Face models
- Future provider integrations

Do not hardcode agent behavior to a single provider.

The provider layer must be extensible, testable, type-safe, and isolated from UI-specific logic. Define provider capability discovery, configuration, model selection, account-level provider profiles, opaque secret references, validation, initialization, health checks, invocation, streaming where applicable, error normalization, cancellation, retries, timeouts, and unsupported-capability handling. Manifests and dataflow state may declare provider requirements or select a `providerProfileId`; they must never contain API keys or secret values.

Document how provider selection and configuration connect to LangChain without exposing provider-specific details throughout the application. Distinguish Local from Remote processing, apply data-egress policy before context leaves the deployment, validate custom endpoints against SSRF policy, and never silently fall back from local to remote execution.

### 4. Configuration Modals and Prompt Governance

Define one shared agent-settings dialog shell with six dedicated screens: Cost, Quotas, Resource policies, Prompt quality, Prompt editor, and Prompt audit. The catalog header provides account safety/policy defaults; an imported-definition cog owns Prompt editor/quality/audit; a project-template cog owns that project's Cost/Quota/Resource defaults; and an attached-instance cog owns downward-only Cost/Quota/Resource overrides. Project templates/instances may inspect authorized source prompt evidence read-only but cannot edit, Release, or Publish it. Palette rows remain action-free. Each trigger must have visible text where space permits, a unique accessible name, and server-provided authorization state.

Policy values are typed and independently revisioned rather than stored in one generic configuration object. The server is authoritative for precedence, hard ceilings, reservations, admission, settlement, and stable denial codes. Project-template and attached-instance settings may tighten but never grant or loosen provider, egress, context, tool, mutation, retention, or deployment safety policy. Running work retains its persisted policy snapshot; ordinary edits affect later executions, while privileged kill switches/quarantine remain separate.

Prompt Save must create a private draft revision only for an owned `AccountImportedAgent` created through explicit Import and must never mutate a published artifact, project template, or attachment. Built-in/global/project-template/attachment sources remain read-only; any future fork/export must be packaged and explicitly re-imported and is out of scope. Prompt bodies stay out of generic catalog DTOs, transcripts, logs, telemetry, URLs, persistent browser storage, and shared/global caches. Static/security validation and reproducible prompt-quality evidence are pinned to the exact draft digest, suite, fixtures, evaluator/provider revision, and policy snapshot. Release creates a new private imported definition artifact; subsequent project Install/update and Publish are separate explicit actions, and existing templates/attachments remain unchanged.

Prompt quality is a platform governance workflow, not an implicit use of `agent.generated-content-evaluator`. `DEC-055` closed OQ-007 by shipping that agent as an authored advisory report-only evaluator; it still cannot evaluate/approve itself or silently become the platform release judge. Model-based judgment is isolated, typed, budgeted, egress-authorized, and unable to activate or publish. Prompt Audit runs versioned security, privacy, compliance, and provenance rules against an exact draft digest, records typed findings and remediation state, and also exposes a separate append-only governance event history. Neither facet is an execution transcript. Full-content reveal/export requires narrower authorization and is itself audited. `DEC-057`/`DEC-058` now govern retention/deletion rather than open OQ-008.

## KGGraph Documentation and Traceability Requirements

All design preparation and future development progress must be fully tracked using the process established by the KGGraph methodology.

Before defining implementation work, unpack and organize the current concept artifacts into the appropriate structure within the KGGraph Design Phase.

The Design Phase documentation must capture:

- Source concept artifacts
- Design rationale
- Approved concept decisions
- UI artifacts
- Interaction flows and state transitions
- Architecture decisions
- Assumptions and constraints
- Open questions
- Dependencies and risks
- Traceability between concepts and planned implementation work

Map existing artifacts into the correct KGGraph Design Phase files without losing or weakening approved decisions. Create or update modular Design Phase documentation only where needed. Do not overwrite existing documentation unless the change is necessary, intentional, and clearly documented.

Prepare the corresponding KGGraph Development or Build Phase structure for implementation tracking. Development must use modular Build Log files that incrementally record:

- Implementation progress
- Design-to-code decisions
- Architectural decisions and deviations
- Files and modules changed
- Tests added or updated
- Commits
- Issues discovered and resolved
- Regressions
- Follow-up work
- Remaining risks and open questions

Every implementation step, issue resolution, and design-to-code decision must be traceable to the relevant concept artifact, design rationale, requirement, or acceptance criterion.

Define a stable identifier scheme for requirements, decisions, artifacts, risks, open questions, implementation tasks, tests, commits, and Build Log entries to maintain bidirectional traceability throughout development.

## Required Spec Content

The development plan must include:

1. Current design and concept review
2. KGGraph Design Phase artifact mapping
3. Approved decisions, assumptions, constraints, and open questions
4. Proposed Agents Catalog architecture
5. Agent domain model and manifest structure
6. LangChain-based agent creation and instantiation flow
7. Agent installation, uninstallation, versioning, and publishing model
8. Agent assignment and attachment flow for dataflows
9. Agent configuration, six dedicated settings screens, prompt governance, refinement, detachment, and reuse behavior
10. LLM provider abstraction and capability model
11. Reusability opportunities from nodes and datasets
12. Proposed folder and module structure
13. Data and state-management strategy
14. API and service-layer requirements
15. UI integration and accessibility plan
16. Loading, empty, error, success, and recovery states
17. Edge cases and failure modes
18. Security, credential-handling, and trust-boundary considerations
19. Testing strategy
20. Migration and incremental implementation phases
21. KGGraph Build Phase and modular Build Log structure
22. Requirement-to-design-to-code-to-test traceability strategy
23. Acceptance criteria
24. Recommended commit breakdown
25. Engineering quality checklist

## Data and State Requirements

The spec must identify the source of truth for:

- Immutable definition artifacts and global catalog projections
- Explicit account-private imported definitions and user publication eligibility
- Project-installed templates and active-project palette membership
- Private attached instances and concurrency revisions
- Attachment-specific configuration
- Runtime agent instances
- Provider and model configuration
- Settings bindings and typed Cost, Quota, and Resource policy revisions
- Per-project-template default profiles and attached-instance downward-only overrides
- Effective execution policy snapshots, price snapshots, reservations, and usage ledger entries
- Private prompt authoring workspaces and draft revisions
- Prompt evaluation suites/runs, review/release evidence, prompt-audit policies/runs/findings, and append-only governance events
- Agent execution status
- Manifest versions
- Publishing and installation state

Explain how derived values should be computed and how state changes after explicit import, project install/uninstall, imported-definition publish/unpublish/delete, project-template update, attach/configure/detach, reconnect, refresh, or project switching. Account imports remain private across projects; the installed palette/defaults/templates/attachments change with the active project.

Immutable artifact bytes, account imports, publications, project templates, project settings, private attached instances, provider profiles, effective policy snapshots, reservations/usage ledgers, prompt drafts, evaluation/audit/governance records, sessions, and executions/events must have distinct sources of truth.

Prompt editor content must remain in memory-only local form state and be purged on modal close, logout, and account switch. Policy editing follows local form → server draft → validation → explicit activation, with `If-Match`/expected-revision conflict handling; the prior active revision remains effective until atomic activation. Any prompt edit invalidates evaluation evidence not pinned to the new digest.

Treat imported packages and agent/model/tool output as hostile input. Package import must use bounded private staging, contained regular-file extraction, full validation, failure cleanup, and atomic visibility. Agent-authored Markdown or rich content must use one centralized allowlist renderer with raw active HTML, scripts, unsafe URL schemes, event handlers, and unapproved embeds disabled.

The design must avoid duplicated state, stale catalog data, conflicting mutations, async race conditions, visible flicker, unnecessary full reloads, and inconsistent state across the catalog, palette, dataflow, and refinement UI.

## UI and UX Requirements

Maintain visual and behavioral consistency with the existing nodes and datasets product patterns and the approved Agents Catalog concepts.

Document:

- Catalog and palette responsibilities
- Labels, titles, buttons, pills, icons, references, categories, counts, filters, sorting, pagination, and actions
- Installation and publishing feedback
- Drag, select, attach, configure, and detach interactions
- Attached-agent visibility
- Loading, empty, error, disabled, retry, and success states
- Focus behavior and restoration
- Keyboard interactions
- Semantic labels and screen-reader announcements
- Prevention of layout shift, flicker, jank, and accidental destructive actions
- Clear `Global Catalog`, `My Imports`, and `Installed in this project` states and separate `Import package`, `Install in project`, eligible imported-definition `Publish`, and `Attach` commands
- Project-only palette replacement and scope announcements on project switch
- Absence of Version/Release/Publish actions on attached instances and absence of Publish on project templates/global items
- ~~Removal of the node Explanation tab~~ **Cancelled by `DEC-041`**; retain the tab and add the standard Node Explainer install/attach/chat discoverability path
- Labeled settings cog placement at account, agent, and attachment scopes without adding controls to draggable palette rows
- Six directly addressable, non-nested modal screens that show scope, effective value, inherited source, immutable ceiling, revision, authorization, dirty/conflict state, and recovery action
- Prompt-content privacy, unsaved-change protection, evaluation progress/cancellation, read-only audit navigation, and focus restoration to the exact cog opener

## Edge Cases

At minimum, address:

- Missing, malformed, incompatible, or unsupported manifests
- Duplicate agent identifiers or versions
- Missing tools, prompts, provider capabilities, or credentials
- Unsupported provider/model combinations
- Provider initialization or runtime failures
- Slow, interrupted, cancelled, or out-of-order requests
- Repeated install, publish, attach, detach, or save actions
- Conflicting global-catalog, account-import, project-template, and attachment state
- Reopened drawers, modals, refinement panels, or dataflows
- Definition/project-template updates while an existing unversioned attachment remains private and pinned for execution reproducibility
- Same publisher/agent/exact-version coordinate supplied with a different artifact digest
- Project uninstall attempts while a template remains attached or active in that project
- Deleted/unpublished imports or catalog artifacts still referenced by project templates/execution pins
- Unpublished agents versus quarantined/revoked agents, and retained history versus garbage-collection eligibility
- Partial publishing or installation failures
- Oversized, high-expansion, malformed, traversal, duplicate-path, link, or special-file agent archives and abandoned staging state
- Hostile Markdown/HTML/URL/embed content returned by an agent or tool
- Null values, lists, tuples, nested objects, streaming responses, tool-call results, and unexpected runtime payloads
- Local-model unavailability and resource constraints
- Provider credential expiry or revocation
- Remote data egress denial, custom-provider SSRF targets, and unavailable local providers without cloud fallback
- Migration from early agent concepts to the LangChain-based architecture
- Account/deployment policy changes while a modal is open or an execution is being admitted
- Attempts to loosen inherited policy, concurrent admission for the final budget/quota unit, unknown/stale pricing, and delayed usage settlement
- Prompt edits to immutable, unowned, unlicensed, quarantined, or concurrently changed artifacts
- Sensitive or injected evaluation fixtures, stale evidence, missing/unauthorized evaluator, evaluation cost denial, and self-evaluation attempts
- Audit write/integrity failure, restricted content reveal/export, secret remediation, retention/tombstone behavior, and rollback to a quarantined or still-pinned artifact
- Logout/account switch with prompt text, modal drafts, optimistic settings mutations, or evaluation streams active
- Import without an open project; repeated/concurrent Import/Install/Publish; fabricated Publish from a built-in/global item, project template, or attachment
- Same definition installed in multiple projects with independent defaults and project-switch cache isolation
- Concurrent attached-instance edits that must produce a revision conflict rather than an attachment version
- Node Explainer unavailable/not installed/provider-blocked/over quota, plus legacy saved Explanation-tab state

## Testing Strategy

Define required:

- Unit tests for manifests, validators, mappers, selectors, utilities, provider adapters, LangChain factories, and state transitions
- Contract tests for provider implementations and agent manifests
- Component tests for catalog, palette, attachment, refinement, publishing, and error-state behavior
- Integration tests for definition/import or catalog source → explicit project install → attach → run, with no automatic command chaining
- State consistency tests across catalog, palette, dataflow, and refinement surfaces
- Exact definition-coordinate collision, account-import idempotency, project-template isolation, attach/project-uninstall concurrency, and attachment revision-without-SemVer tests
- Regression tests for each reported or anticipated failure mode
- Accessibility tests for keyboard, focus, semantics, and announcements
- Failure-injection tests for malformed data, delayed responses, cancellation, provider errors, partial failures, and race conditions
- Privacy/security tests for imported-definition-only user publication, project-only palettes/defaults, provider-secret non-return, data-egress denial, and account/project-switch cleanup
- Policy contract tests for typed schemas, strict precedence, per-agent defaults, downward-only overrides, revision conflicts, reset semantics, and immutable execution snapshots
- Cost/quota/resource tests for atomic reservations, concurrent overspend prevention, estimate/settlement, unknown price, retry/child/evaluation charging, resource exhaustion, stable `429`/recovery responses, and no remote fallback
- Prompt-governance tests for memory-only editor state, private draft concurrency, contained assets, immutable release, exact-digest evaluation, isolated advisory judges, stale evidence, versioned audit rules and exact-digest findings/remediation gates, append-only/tamper-evident governance events, authorized reveal/export, and OQ-007 fail-closed behavior
- Component and accessibility tests for each cog and dedicated screen, scope/effective/inherited values, dirty-close confirmation, focus trap/return, keyboard editor fallback, error focus, live evaluation status, responsive full-screen behavior, and non-color state communication
- Node UI/migration tests proving the Explanation tab/menu/state/cache/direct request remains present (`DEC-041`), Node Explainer chat uses one execution, and its discoverability route follows normal explicit project install/attach behavior
- Migration and backward-compatibility tests
- Traceability checks linking requirements and design decisions to implementation and test coverage

Clearly state which tests must pass before each implementation phase can be considered complete.

## Engineering Principles

The plan must:

- Follow the existing project architecture and naming conventions.
- Keep domain logic, UI rendering, state management, services, LangChain integration, and provider integrations clearly separated.
- Prefer reusable components, hooks, selectors, services, utilities, constants, factories, adapters, and mappers.
- Avoid duplicated business, formatting, provider, and state logic.
- Remain type-safe, modular, testable, maintainable, and extensible.
- Avoid circular dependencies and scattered agent-specific logic.
- Preserve existing behavior unless a requirement explicitly changes it.
- Support adding new agent types and LLM providers with minimal changes.
- Prevent provider and LangChain implementation details from leaking into unrelated UI and domain code.
- Keep documentation modular, intentional, traceable, and suitable for incremental development.
- Keep settings policy, usage admission, prompt authoring/evaluation/release, and audit business logic inside the frontend/backend `agents/` modules; share only feature-neutral dialog, form, editor, HTTP, and schema primitives.

## Acceptance Criteria Requirements

Provide specific, verifiable, implementation-ready acceptance criteria covering:

- What users see in the Global Catalog, My Imports, active-project installed palette, and private attached-agent UI
- What happens after install, uninstall, publish, unpublish, attach, configure, detach, retry, reconnect, and refresh actions
- What each authorized account/agent/attachment cog opens, which of the six screens applies, and how effective/inherited values and downward-only limits are presented
- How policy activation, execution admission/reservation/settlement, prompt draft save/evaluate/review/release, audit capture, and explicit rollback behave without auto-publishing or retargeting attachments
- What behavior must no longer occur
- How definition artifacts, account imports, publications, project templates/defaults, unversioned private attachments, and executions remain distinct and consistent
- How exact definition coordinates and execution pins preserve reproducibility without giving attachments SemVer/release/publication identity
- How the Explanation tab/direct caller is retained under `DEC-041` and Node Explainer unified chat coexists as an additional path
- How LangChain agents are created from validated manifests
- How providers can be added or changed without rewriting agent-domain or UI logic
- How failures are surfaced and recovered from
- How accessibility requirements are satisfied
- How KGGraph traceability is maintained from concept through design, implementation, commits, tests, and follow-up work

## Recommended Commit Breakdown

Propose small, reviewable commits with focused purposes. The plan should generally separate:

1. KGGraph Design Phase organization and traceability foundations
2. Shared domain models, manifest schema, validation, and tests
3. Provider abstraction, capability contracts, adapters, and contract tests
4. LangChain agent factory and runtime integration
5. Account import, imported-only publication, and explicit project-template installation services
6. Private unversioned attached-instance/configuration state
7. Catalog, palette, attachment, and refinement UI integration
8. Error handling, accessibility, observability, and regression coverage
9. KGGraph Build Logs, migration notes, and final documentation reconciliation

Add focused commits for typed settings/policy domains, cost/quota/resource admission, private prompt authoring and immutable release, prompt evaluation/audit governance, and the six accessible modal screens rather than combining them with unrelated catalog or runtime work.

Adjust the breakdown to match the existing repository architecture. Do not mix unrelated changes into the same commit.

## Engineering Quality Checklist

Before considering the plan complete, verify that it ensures:

- No duplicated business logic is introduced.
- Shared logic is centralized where appropriate.
- Types and boundaries are explicit and safe.
- Components remain focused and readable.
- State updates are predictable and race-condition-safe.
- UI behavior is consistent across all affected surfaces.
- Loading, empty, error, success, retry, and recovery states are handled cleanly.
- Accessibility is included in design and testing.
- Tests cover core behavior, contracts, integrations, edge cases, and regressions.
- LangChain and provider-specific details remain isolated.
- New providers and agent types can be added with minimal changes.
- Existing nodes and datasets conventions are reused where appropriate.
- Approved concept work is preserved.
- Every planned implementation unit is traceable through KGGraph documentation.
- Cost, quota, and resource limits are server-authoritative, revisioned, atomically enforced, and cannot be loosened by a lower scope.
- Every installed project template has a reviewed per-agent default profile, and every execution persists the project-template, attached-instance, prompt/provider, and effective-policy revisions used.
- Every explicit project installation has an isolated reviewed default profile; no account-wide installed palette/pointer remains.
- Only owned validated account imports are user-publishable, and Import/Install/Publish never auto-chain.
- Attachments are project-private derivations with concurrency revision only and no SemVer/Release/Publish action.
- Node Explainer chat and the retained Explanation tab/direct path are independent coexisting workflows (`DEC-041`); neither double-runs the other.
- Prompt content remains private and memory-only on the client; Save creates a private draft, and Release creates a new immutable artifact.
- Prompt quality cannot self-approve or silently use the unresolved generated-content evaluator; Prompt Audit records exact-digest compliance/security findings and append-only governance history, both separately authorized from transcripts.
- Six dedicated modal screens are owned by `agents/`, authorization-aware, conflict-safe, and WCAG 2.2 AA accessible.
- The plan does not introduce unnecessary re-renders, flicker, slow updates, or visual instability.

Do not implement application code as part of this task. Produce only the organized KGGraph design documentation, implementation spec, development tracking structure, and recommended plan. Use the cursor editor style for spec writing.
