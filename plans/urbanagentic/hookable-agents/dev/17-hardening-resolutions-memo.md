# Implementation Memo: Hardening Resolutions (H-2, H-3, H-4, H-6, H-7)

This memo resolves the remaining open hardening items in `14-plan-hardening-and-open-decisions-memo.md`
(H-5 was closed by `dev/15`, and its OQ-011 offshoot partly closed by `dev/16`). It records four new decisions (`DEC-036` provenance boundary,
`DEC-037` evaluation-budget scope, `DEC-038` v1/v2 phasing, `DEC-039` `aiconn/` as the default provider
source), one architecture decision record (`ADR-AG-012` provider-credential migration), and interim
retention defaults that keep `OQ-008`'s final durations with Product/Security. It uses the reconciled model (`DEC-029`–`DEC-035`), D-0 = B, and the
existing package/credential/lifecycle facts. Where this memo and an image differ, this specification is
authoritative.

## 1. Problem Statement

Five hardening items are open:

- **H-2 (P0)** — A `ProjectAgentTemplate` sourced from user A's *unpublished* private import could let a
  project collaborator (user B) read A's prompt provenance/evidence. The memos assume a single-owner
  project without stating it where templates/attachments reference private imports, and never define who
  may read a *published* definition's prompt bytes.
- **H-3 (P0)** — The plan layers heavy governance (audit hash chains, reservation ledgers, crypto-
  shredding, leased execution) on top of what is fundamentally "13 prompt behaviors as hookable packages."
  There is no explicit MVP cut, so the shippable core is buried under demand-gated governance.
- **H-4 (P1)** — Plaintext `user.llm_api_type`/`llm_api_key` must migrate to an account
  `ProviderProfile` + encrypted secret store, and the legacy `/llm/chat` endpoint needs a cutover bridge.
  No ADR exists; it is net-new infra with no repo precedent.
- **H-6 (P1)** — The Cost screen supports account / project-template / attachment scopes, but the
  evaluation sub-budget applies to prompt evaluation, an **Imported-definition** activity with no Cost
  scope home.
- **H-7 (P1)** — `OQ-008` punts retention wholesale: no purge-on-revoke, no purge-on-underlying-delete,
  no per-account import quota, and the Node Explainer migration discards historical explanation *text*.

## 2. Scope

**Included.** The provenance/visibility authorization boundary (H-2); an explicit v1 (MVP) / v2
(governance) release cut mapped onto the build-log phases (H-3); the provider-credential migration ADR +
legacy bridge + sequencing (H-4); the evaluation-budget scope decision (H-6); fail-closed **interim**
retention defaults, a per-account import quota, and the explanation-content migration + old-artifact
retention edge cases (H-7). New decisions `DEC-036`/`DEC-037`/`DEC-038`, `ADR-AG-012`, and traceability
wiring.

**Out of scope.** `OQ-008`'s **final** retention/deletion/backup-expiry/export durations (remain
Product + Security; this memo sets only fail-closed interim defaults); H-8 residual-traceability items
(largely addressed in the prior review batch); application code; any new sharing mechanic (D-0 = B).

## 3. Recommended Implementation Approach

### 3.1 H-2 — Provenance is owner-only; execution is project-scoped (`DEC-036`)

**Decision.** Attach/run access and *definition-inspection* access are separated:

- A `ProjectAgentTemplate` sourced from an **unpublished** private `AccountImportedAgent` may be attached
  and executed by any authorized member of the project (execution is project-scoped), **but its prompt
  bytes, prompt provenance/evidence, evaluation, and audit are visible only to the importing owner** —
  never to other collaborators, regardless of project membership. For non-owners the prompt/governance
  panel is **absent**, not merely redacted; they see the template as an opaque installed capability
  (name, category, capability contract, hooks, non-secret settings).
- **Publish-time prompt-visibility model.** Publishing a definition to the global Catalog Hub is exactly
  what makes the *definition itself* shareable: the published artifact's prompt bytes become readable to
  any installer of that published version (installers receive the package). So the rule is binary and
  simple: **unpublished import → prompt owner-only; published definition → prompt readable by installers
  of that published artifact.** There is no partial cross-collaborator prompt exposure for unpublished
  imports.
- Installing an unpublished private import into a project that has (or later gains) collaborators surfaces
  a one-time reviewed notice: "Collaborators can run this agent but cannot view its prompt or governance.
  Publish it to the Catalog Hub to share the definition itself." This replaces the implicit single-owner
  assumption; it does **not** block the install.

**Rationale.** This preserves the plan's core invariant (imported-definition governance is account-
private) while allowing collaborative projects, and it makes "Publish" the single, intentional act that
widens prompt visibility — consistent with how datasets/node packs expose their contents only once
published.

### 3.2 H-3 — Explicit v1 (MVP) / v2 (governance) release cut (`DEC-038`)

**Decision.** Ship a demand-gated MVP first. The cut overlays the existing build-log phases (`3.1`):

- **v1 (MVP) — ships the core "prompt behaviors as hookable packages" product:**
  - manifest/artifact store, capability registry, `Import`/`Install`/`Attach`, imported-only
    `Publish` to the Catalog Hub;
  - provider adapter extracted from `app/api/routes.py` (per `ADR-AG-012`, §3.3), SSE runtime, basic
    **quota** admission (simple counters — not reservation ledgers);
  - the 13 prompt-agent migrations;
  - the three-scope catalog + project palette + attachments/dock/unified chat;
  - ~~Node Explainer tab/direct-caller removal~~ *(cancelled by `DEC-041`, `dev/18` — the tab is retained; this item is deleted from the v1 cut)*;
  - the settings modal shell with **Cost / Quotas / Resource policies** (policy screens).
  - Maps to build-log **P0–P4** minus the governance sub-parts of P1/P2.
- **v2 (governance + orchestration, demand-gated):**
  - **Prompt editor / Prompt quality / Prompt audit** (the three governance settings screens),
    evaluation fixtures/isolation, append-only governance hash chains, reservation/budget ledgers beyond
    simple quota, secret crypto-shredding;
  - the three composite agents (`dev/15`) and `agent.package-recommendation` (`dev/16`), i.e. build-log
    **P5**, and P6 hardening.

The six-screen settings modal remains the end-state; v1 renders the three policy screens and shows the
three governance screens as an explicit "available in v2" disabled state rather than a broken tab.

**Rationale.** The catalog/manifest/lifecycle parts have repo precedent (node/dataset catalogs) and are
the user-visible value; the governance stack is enterprise-grade and has no precedent to mirror. Cutting
along that seam ships value early without discarding the governance design.

### 3.3 H-4 — Provider-credential migration + `aiconn/` as the default provider source (`ADR-AG-012`, `DEC-039`)

**Decision (ADR-AG-012).**
- **Model.** Introduce account-level `ProviderProfile {providerProfileId, accountId, providerType,
  model/endpoint defaults, non-secret config}` plus an **encrypted secret store** keyed by
  `providerProfileId`. Secrets are never stored in user/config fields, never returned by any API, and are
  referenced only by ID (matches `RISK-SECRET-001`).
- **Default provider source = existing `aiconn/` configuration (`DEC-039`).** The LangChain provider
  adapter and the seed/default `ProviderProfile` derive their provider, model, API settings, and runtime
  options from the existing `dev/aiconn/` LLM configuration — **not** from separate LangChain-specific
  defaults. Concretely, the default profile is:
  - `providerType`: **OpenAI-compatible** (the sage200 LiteLLM proxy; reuses the existing OpenAI-compatible
    **adapter class** — the same class `REQ-PROVIDER-002` also uses for the local Ollama/Gemma path, though
    sage200 is a remote proxy, not Ollama);
  - `baseURL`: `https://sage200.evl.uic.edu` with `/v1` appended when missing (per `aiconn/test_llm_connection.py::normalize_base_url`);
  - `model`: default **`gemma4`** (Google Gemma), with `llama4-nim` available — the same `DEFAULT_MODELS`
    roster as `aiconn/` *(amended 2026-07-23: the default flipped from `llama4-nim` to `gemma4` by
    explicit product decision; `config.DEFAULT_LLM_MODEL` and its test assert `gemma4`)*;
  - API key: from `AICONN_API_KEY` (or the account's stored secret), moved into the encrypted secret store,
    never inlined — reusing `aiconn`'s ASCII/homoglyph normalization as an input-hardening step;
  - runtime options: OpenAI **chat-completions** with `aiconn`'s defaults (e.g. `max_tokens` baseline,
    default system prompt) as the seed, overridable per agent manifest `providerRequirements`/`runtime`
    and per settings Resource-policy scope.
  LangChain therefore has no independent default provider/model/endpoint; `aiconn/` is the single source of
  truth for the default, and any per-agent or per-scope value is an explicit override of it. `aiconn/` is
  the **default seed**, not a hardcoded runtime dependency — an account may add other `ProviderProfile`s
  (cloud, Hugging Face, local Ollama) per `REQ-PROVIDER-002`.
- **Migration.** A one-time migration moves each existing `user.llm_api_type`/`llm_api_key`
  (`app/api/routes.py:74-91`) into a per-account default `ProviderProfile`, relocating the key into the
  encrypted store; the plaintext columns are then nulled/dropped. The plaintext removal is irreversible;
  the migration is idempotent and fails closed on an unverifiable secret.
- **Legacy bridge.** The existing `/llm/chat` + `/llm/check` handler reads the migrated `ProviderProfile`
  through a time-bounded compatibility adapter instead of the plaintext user fields, so legacy callers
  keep working during migration. The bridge is removed at cutover when all callers use agent runtime.
- **Sequencing.** `ADR-AG-012` lands in **P0/P2, before** any Resource-policy settings screen that
  selects a `providerProfileId` (the Resource screen depends on the profile + secret store existing).
- **Lifecycle.** Rotation/rekey, non-return contract, and account-switch cleanup are required
  (`RISK-SECRET-001`).

### 3.4 H-6 — Evaluation sub-budget lives at account scope (`DEC-037`)

**Decision.** Bind the prompt-evaluation sub-budget to **account policy** (the Cost screen's account
scope). Prompt evaluation is a pre-release governance activity that runs against an owned
`AccountImportedAgent` before Release — it is account-owned and independent of any project install, so it
has no project-template or attachment scope. The Cost screen shows the evaluation sub-budget **only** in
the account scope; project-template and attachment scopes do not show it. A per-import evaluation cap may
**tighten** (never loosen) the account budget and is displayed read-only where inherited.

**Rationale.** Simpler and more correct than adding a whole new "Imported-definition Cost sub-scope" UI
surface: evaluation cost is genuinely an account concern, and account scope already exists.

### 3.5 H-7 — Fail-closed interim retention defaults + missing edge cases

**Decision (interim, pending `OQ-008` final sign-off by Product + Security).**
- **Existing flow-sharing (D-0 = B).** No agent-specific share TTL exists — agents reuse Curio's existing
  flow-sharing and add no agent-private data, so there is nothing agent-specific to expire.
- **Mandatory purge-on-revoke and purge-on-underlying-delete.** Deleting a private import/definition
  purges or tombstones its dependent private artifacts (drafts, evaluation results, audit content) per
  retention; no orphaned prompt/governance bytes survive a delete.
- **Per-account import quota / mass-import DoS.** Cap concurrent private imports per account (fail-closed
  interim default: **200**) and rate-limit import creation; over-cap import fails closed with an
  actionable error.
- **Node-explanation content migration.** **Moot (`DEC-041`, `dev/18`).** The Explanation-tab removal
  (formerly `DEC-033`/`dev/12`) is permanently cancelled: the tab and its saved explanation content stay
  in place, so no archival/export migration exists. (Historical intent: on removal, migrate explanation
  text into an archived Node Explainer chat entry rather than discarding it.)
- **Old-artifact retention for attached instances.** When a template's source is updated, existing
  attachments stay pinned to their current source snapshot and the old immutable artifact bytes are
  **retained** (never GC'd) while any attachment/execution pins them; GC only reclaims bytes with no live
  pin.
- **`OQ-008` still owns** final transcript/draft/evaluation/audit retention durations, deletion SLA,
  backup expiry, and export scope. These interim defaults are fail-closed and must never claim
  irreversible deletion while retained backups or public caches exist.

## 4. Data and State Handling

- **H-2:** authorization derives prompt/governance visibility from `AccountImportedAgent` ownership (and,
  for published artifacts, from installer access to the published version) — never from project
  membership. The `ProjectAgentTemplate`/`AttachedAgentInstance` read models expose the prompt/governance
  projection only when the requester is the source-import owner or the source is published.
- **H-4:** `ProviderProfile` + encrypted secret store are account-scoped resources; the Resource-policy
  settings binding stores a `providerProfileId` reference, never a secret. Migration state is tracked so
  it runs once and is verifiable.
- **H-6:** the account Cost policy carries the evaluation sub-budget field; project/attachment Cost read
  models omit it. Admission for an evaluation run reserves against the account evaluation budget.
- **H-7:** delete/revoke operations cascade to dependent private artifacts atomically; GC checks live pins
  before reclaiming artifact bytes; import creation checks the per-account quota before staging.

## 5. UI and UX Requirements

- **H-2:** non-owner collaborators see no prompt/quality/editor/audit panel on a template/attachment
  sourced from an unpublished import; the install flow shows the one-time collaborator-visibility notice.
- **H-3:** v1 renders Cost/Quotas/Resource; the Prompt editor/quality/audit tabs appear as an explicit
  "available in a later release" disabled state, not a missing or broken tab.
- **H-4:** the Resource-policy screen selects a provider profile by name; secrets are never shown or
  returned (a masked "configured" indicator only).
- **H-6:** the evaluation sub-budget appears only under the account Cost scope; other scopes show it as
  read-only inherited where relevant.
- **H-7:** delete/revoke confirmations state truthfully what is purged now vs retained in backups; the
  Node Explainer migration surfaces the archived prior explanation as chat history.

## 6. Edge Cases

- A project adds a collaborator *after* an unpublished import was installed → the collaborator gains
  execution but not prompt/governance visibility; no retroactive exposure (H-2).
- A definition is published, then the published version is unpublished → new installs stop; existing
  installers of the already-distributed artifact retain what they lawfully received (H-2).
- Migration encounters a malformed/undecryptable legacy key → fail closed, leave the user unable to run
  until re-entered; never silently drop to plaintext (H-4).
- Two evaluation runs race the account budget → atomic reservation prevents oversubscription (H-6).
- A source import is deleted while an attachment still pins its old artifact → the pinned bytes are
  retained; the delete is blocked or tombstoned per retention, never orphaning a running attachment (H-7).
- Mass-import attempt beyond the per-account quota → fail closed with a clear limit message (H-7).
- Node Explainer migration on a project with historical explanation text → text is archived into chat,
  not discarded (H-7).

## 7. Testing Strategy

- **H-2:** authorization tests proving a non-owner collaborator cannot read prompt/provenance/evaluation/
  audit of an unpublished-import-sourced template/attachment, and that a published artifact's prompt is
  readable by installers of that version; the collaborator-visibility notice fires on shared-project
  install.
- **H-3:** a v1 acceptance suite that passes without any prompt-governance/evaluation/ledger module
  present; a feature-flag test that the governance tabs render a disabled "later release" state.
- **H-4:** idempotent migration test (plaintext → profile + encrypted secret, columns nulled); secret
  non-return contract; legacy `/llm/chat` bridge reads the migrated profile; account-switch secret
  cleanup; sequencing test that the Resource screen cannot bind a profile before the store exists.
- **H-6:** account-scope evaluation-budget admission/atomicity; project/attachment scopes omit the field;
  per-import cap can only tighten.
- **H-7:** purge-on-revoke and purge-on-underlying-delete cascade tests; per-account import-quota fail-
  closed test; explanation-content migration preserves text; GC retains bytes with live pins and reclaims
  only unpinned artifacts; deletion copy never claims irreversible deletion while backups exist.

## 8. Acceptance Criteria

- `DEC-036`: prompt/provenance/evaluation/audit of an unpublished-import-sourced template are visible only
  to the importing owner; collaborators get execution only; publishing is the single act that widens
  prompt visibility to installers.
- `DEC-038`: `dev/03` and the build log carry an explicit v1/v2 cut; v1 ships lifecycle + 13 migrations +
  policy settings without the governance stack; composites/package-recommendation and prompt governance
  are v2.
- `ADR-AG-012`: a provider-credential migration + encrypted secret store + legacy bridge is specified and
  sequenced before any provider-profile-referencing settings screen; secrets are never returned.
- `DEC-039`: the LangChain adapter and default `ProviderProfile` derive provider/model/API/runtime
  defaults from the existing `aiconn/` config (OpenAI-compatible sage200 endpoint, `llama4-nim`+`gemma4`,
  `AICONN_API_KEY`, chat-completions runtime), with no separate LangChain-specific defaults; per-agent and
  per-scope values are explicit overrides of that seed.
- `DEC-037`: the evaluation sub-budget is bound to account Cost scope and absent from project/attachment
  scopes.
- H-7: mandatory purge-on-revoke and purge-on-underlying-delete, a per-account import quota, explanation-
  content migration, and old-artifact-retention-for-pinned-attachments are specified as fail-closed
  interim defaults; `OQ-008` retains final durations.

## 9. Recommended Commit Breakdown

1. `docs(plan): add DEC-036/DEC-037/DEC-038 and ADR-AG-012; mark H-2/H-3/H-4/H-6/H-7 resolved` (this memo + wiring).
2. `feat(agents-auth): owner-only prompt/governance visibility; project-scoped execution` with authorization tests (H-2).
3. `feat(providers): ProviderProfile + encrypted secret store + legacy /llm/chat bridge + migration` (H-4).
4. `feat(agents-cost): bind evaluation sub-budget to account scope` (H-6).
5. `feat(agents-retention): purge-on-revoke/underlying-delete, per-account import quota, explanation-content migration, pinned-artifact retention` (H-7).
6. Release-gate the v1 cut; defer governance/composite/package modules behind the v2 flag (H-3).

## 10. Engineering Quality Checklist

- [ ] Prompt/governance visibility derives from import ownership or published-artifact access, never project membership (H-2).
- [ ] Publish is the only act that widens an unpublished import's prompt visibility (H-2).
- [ ] `dev/03` + build log carry an explicit, testable v1/v2 cut; v1 needs no governance/ledger/evaluation module (H-3).
- [ ] Provider secrets live only in the encrypted store, are never returned, and migrate idempotently with a removable legacy bridge sequenced before the Resource screen (H-4).
- [ ] The default provider/model/API/runtime config comes from `aiconn/` (sage200 OpenAI-compatible, `llama4-nim`/`gemma4`), not separate LangChain defaults; per-agent/per-scope values only override that seed (`DEC-039`).
- [ ] Evaluation sub-budget exists only at account Cost scope; lower scopes omit it (H-6).
- [ ] Purge-on-revoke and purge-on-underlying-delete are mandatory; per-account import quota is enforced fail-closed (H-7).
- [ ] Node Explainer migration archives historical explanation text rather than discarding it (H-7).
- [ ] Old artifact bytes are retained while any attachment/execution pins them; GC reclaims only unpinned artifacts (H-7).
- [ ] Deletion/revocation copy never claims irreversible deletion while retained backups or caches exist; final durations remain `OQ-008` (H-7).
