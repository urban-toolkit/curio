# Plan-Hardening and Open Decisions Memo

## Purpose

This memo records the unresolved design decisions and hardening items surfaced by a four-part
review of the development planning set (`dev/01`–`dev/13` plus the KGGraph Design/Build artifacts),
each cross-checked against the real Curio repo and the canonical concept docs (`docs/03`, `docs/05`,
`docs/08`, `docs/11`).

Mechanical inconsistencies were already fixed in place and are listed under "Applied fixes" at the
end. The items below are **not** mechanical edits — each needs a human decision or a net-new
specification before build. They are ordered by leverage: one gating decision (D-0), then P0/P1/P2
hardening items.

Overall the core is strong and repo-faithful (the catalog/lifecycle/capability/module-boundary model
extends real conventions — the `datasets/` module layout, the `.curio/users/<key>/…` private-store +
project-installed-ref split, and the versioned node-package manifest). The two systemic risks are
**scope** (governance machinery dwarfs the current codebase) and a small set of **privacy boundaries
that are asserted rather than designed**.

---

## D-0 — Sharing scope — DECIDED: (B) reuse existing sharing (2026-07-18)

**Decision.** Option **(B)**. The agents feature adds **no new sharing mechanic** and does **not**
change existing flow sharing. Agents participate only in Curio's **existing** flow-sharing behavior.

**Normative rule (SHARING-SCOPE).** The build MUST NOT introduce a new `SharedFlowResult` object or
projection pipeline, an allowlist projector, a `/api/projects/{projectId}/shared-results` or
`/api/shared-flow-results/{shareId}` endpoint, a `SharedResultViewer`/`sharedResultApi` client, or
retire/replace the existing `/api/projects/{projectId}/shared` route. Sharing endpoints, viewer,
retention, and revocation are **out of scope**. The only agent-side requirement is negative: the
agents feature must not add agent-specific private data — definitions, imports, project templates,
attachments, prompts, evaluations, audits, settings, provider secrets, transcripts, or private IDs —
as any **new** shared surface, and must not expand what the existing share already emits. Whether the
existing flow-sharing itself needs broader privacy hardening is a **separate, pre-existing concern
outside this feature.**

**Supersession.** Any `SharedFlowResult` build content — a new record/repository, projector,
endpoints, public viewer, legacy-route retirement, or share preview/recipient flows, plus the
associated requirements/risks/commit/tracking rules — is **superseded by this decision and is not an
implementation source.** The affirmative build directives that previously appeared in `dev/03`
(share-preview surface, `shared_result_redaction.py`, share rows/endpoints, share-projection recovery,
shared-result schemas/tests/gate/commit) and `dev/12` (the "Output-Only Sharing" title, share-generation
edge cases, and shared-result acceptance/checklist items) have been **removed in this hardening pass**
and rewritten as negative no-leak invariants. Any remaining sharing references — in `dev/02`, `dev/05`,
`dev/09`, `dev/10`, `dev/12`, and the KGGraph `REQ-SHARE`/`RISK-SHARE` rows and Build-Log share rule —
are negative privacy invariants or generic "shared result" phrasing only, governed by this rule. The
concept screens for sharing were already removed (former screens 20/21).

**Note.** This does not weaken H-2 below: the multi-user private-import provenance boundary is about
Attach/collaborator access, independent of sharing, and still applies.

---

## H-1 — RESOLVED by D-0 = B (no longer applicable)

The visible-content classification / redaction / public-media-hosting problem existed only for the
net-new sanitized sharing pipeline. Under D-0 = B that pipeline is out of scope, so H-1 is closed. If
the *existing* flow-sharing needs the same hardening, that is a separate, pre-existing concern outside
this feature.

---

## H-2 (P0, applies regardless of D-0) — Multi-user project + private-import provenance boundary — RESOLVED by `dev/17` (`DEC-036`)

**Problem.** A `ProjectAgentTemplate` can be sourced from user A's **unpublished** private account
import. If a project has collaborators (Curio dataflows plausibly do), user B can attach/run the
template and inspect its read-only prompt provenance/evidence — leaking A's unpublished definition.
The memos assume a single-owner project and defer "multi-tenant collaboration" (`dev/10`) without
stating that dependency where it matters (`dev/12` template/attachment references).

**Recommendation.** Either state the single-owner-project assumption **explicitly** wherever a
template/attachment references a private import, or design authorization so a template/attachment
sourced from an unpublished import is not exposable to collaborators. Also define the **publish-time
prompt-visibility model**: who may read a *published* definition's prompt bytes (all installers?).

**Resolution (`DEC-036`, `dev/17` §3.1).** Execution is project-scoped but prompt/provenance/evaluation/
audit of an unpublished-import-sourced template/attachment is **owner-only** (absent, not redacted, for
collaborators). Publishing to the Catalog Hub is the single act that widens prompt visibility to
installers of the published artifact; a shared-project install of an unpublished import shows a one-time
collaborator-visibility notice.

---

## H-3 (P0) — Phase aggressively: ship the MVP before the governance stack — RESOLVED by `dev/17` (`DEC-038`)

**Problem.** Today's LLM path is a single backend route doing `open("./llm-prompts/"+file+".txt")` +
an inline SDK call. The plan layers ~19 ADRs, ~30 repositories, append-only audit hash chains with
crypto-shredding, reservation/budget ledgers with atomic admission, and leased execution with fencing
tokens on top. The actual deliverable — 13 prompt behaviors as hookable packages mirroring node
packages — is buried under enterprise governance that has no repo precedent to mirror (unlike the
catalog/manifest parts, which do).

**Recommendation.** Make the phase split explicit in `dev/03`:
- **v1 (MVP):** manifest/artifact store, capability registry, Import/Install/Attach, provider adapter
  extracted from `app/api/routes.py`, SSE runtime, the 13 prompt-agent migrations, and the
  three-scope catalog + project palette. Ship this.
- **v2 (governance, demand-gated):** prompt authoring/evaluation/audit (ADR-AG-018/019), reservation
  ledgers beyond simple quota, secret crypto-shredding, evaluation fixtures.

**Resolution (`DEC-038`, `dev/17` §3.2).** The v1/v2 cut is adopted and mapped onto the build-log phases:
v1 = P0–P4 minus the governance sub-parts (lifecycle + 13 migrations + three-scope catalog + attachments/
chat + Cost/Quotas/Resource policy screens); v2 = the three governance settings screens, evaluation/audit/
ledger machinery, and the P5 composites + `agent.package-recommendation`. The build-log phase index carries
the cut.

---

## H-4 (P1) — Provider-credential migration ADR (currently missing) — RESOLVED by `dev/17` (`ADR-AG-012`, `DEC-039`)

**Problem.** Existing plaintext `user.llm_api_type`/`llm_api_key` (`app/api/routes.py:74-91`) must
migrate to an account `ProviderProfile` + encrypted secret store (ADR-AG-012), and the legacy
`llm_chat` endpoint's per-user creds need a cutover bridge. This is the highest unaddressed
integration point and is net-new infra with no existing repo pattern.

**Recommendation.** Add an ADR for the credential migration + legacy-endpoint bridge, sequenced
before any settings/resource-policy screen that references a provider profile.

**Resolution (`ADR-AG-012` + `DEC-039`, `dev/17` §3.3).** Specifies the account `ProviderProfile` +
encrypted secret store, the one-time plaintext migration, and the time-bounded `/llm/chat` bridge,
sequenced before the Resource-policy screen. Also resolves the follow-up request that **LangChain use the
existing `aiconn/` configuration as the default source** for provider/model/API/runtime (sage200
OpenAI-compatible endpoint, `llama4-nim`+`gemma4`, `AICONN_API_KEY`, chat-completions) rather than
separate LangChain defaults — `aiconn/` is the default seed and every other value is an explicit override.

---

## H-5 (P1) — Specify the three composite agents before Phase 5 ships them — RESOLVED by `dev/15`

**Problem.** Phase 5 leads with Dataset Finder, Node Builder, and Dataflow Builder, but these have
**no migration source and no manifest**: the `docs/11` profile-family tables list them, yet the
`dev/06` prompt-migration roster does not (that roster is 13 source-backed + 1 blocked evaluator).
They are net-new compositions over migrated capabilities. (The 17-vs-14 count discrepancy has the
same root cause and is now reconciled in `docs/11` and `dev/06`.)

**Recommendation.** Author a manifest + capability set + `delegatesTo` composition (and net-new-vs-
reused prompt provenance) for `agent.dataset-finder`, `agent.node-builder`, and `agent.dataflow-
builder` before Phase 5 — or explicitly descope them from first release.

**Resolution.** Done in `15-composite-agent-specifications-memo.md`: full camelCase manifests, five
net-new capability contracts (`dataflow.orchestrate`, `dataset.discover`, `dataset.select`,
`node.build`, `dataset.fetch.author`), the `delegatesTo` composition over the fourteen migrated
identities and each other, net-new prompt provenance, hooks/compatible targets, and the reviewed
settings profile families. That memo also opens **OQ-011** (Package Recommendation / Validation /
Optimization are referenced by the concept screens but are neither in the fourteen-agent roster nor
among the three composites — specify or descope separately). **Update:** `16-agent-node-package-
capabilities-memo.md` specifies **Package Recommendation** (`package.recommend`/`package.identify` and
the node-package identify/suggest/reviewed-install flow), so OQ-011 now covers only **Validation** and
**Optimization**.

---

## H-6 (P1) — Give evaluation cost a scope home — RESOLVED by `dev/17` (`DEC-037`)

**Problem.** The Cost screen supports account / project-template / attachment scopes, but the
"evaluation sub-budget" it also owns applies to prompt evaluation — an **Imported-definition**
activity, a scope Cost does not support (`dev/11`).

**Recommendation.** Add an Imported-definition Cost sub-scope, or explicitly bind the evaluation
sub-budget to account policy.

**Resolution (`DEC-037`, `dev/17` §3.4).** Bind the evaluation sub-budget to **account** Cost scope
(evaluation is account-owned pre-release governance on an owned import); project-template and attachment
scopes omit it. A per-import cap may only tighten the account budget.

---

## H-7 (P1) — Convert deferred OQ-008 into concrete share/retention defaults — RESOLVED by `dev/17` (interim; final durations remain `OQ-008`)

**Problem.** Retention/expiry is punted wholesale: no default share TTL, no snapshot-purge-on-revoke,
no purge-on-underlying-delete, no backup handling. Missing edge cases: per-account import quota /
mass-import DoS; loss of prior node-explanation *content* on Node Explainer migration (`dev/12`
removes the UI state but discards historical explanation text rather than migrating it into chat);
old-artifact retention for still-attached instances after a template's source is updated.

**Recommendation.** Set concrete defaults or time-box the decision with an interim safe default
(e.g., no default TTL yet, but **mandatory purge-on-revoke**), and add the missing edge cases.

**Resolution (`dev/17` §3.5, interim).** Fail-closed interim defaults: mandatory purge-on-revoke and
purge-on-underlying-delete; a per-account import quota (interim 200) against mass-import DoS; Node
Explainer migration **archives** historical explanation text into chat instead of discarding it (amends
`dev/12`) — *this sub-item is now moot: `DEC-041` (`dev/18`) cancels the Explanation-tab removal, so no
explanation content migrates anywhere*; old artifact bytes are retained while any attachment/execution
pins them. Final retention durations, deletion SLA, backup expiry, and export scope **remain `OQ-008`**
(Product + Security).

---

## H-8 (P2) — Traceability and residual consistency

- **Decompose compound acceptance criteria.** `REQ-PRIVACY-001`, `REQ-PROJECT-INSTALL-001`,
  `REQ-SETTINGS-001`, `REQ-STATE-001`, `REQ-PROMPT-AUDIT-001` each bundle 3–6 assertions under one
  ID, which the `REQ → TASK → TEST` scheme cannot bind. Split into sub-IDs. Enumerate the 13 packages
  as first-class tracked units. Add a one-line note in `dev/03`'s DEC table pointing to `dev/13`'s
  retirement policy so the intentional DEC-ID gaps don't read as errors.
- **Resolve the prompt-override hedge.** `dev/12` leaves the door open to a "project-private prompt
  override" while `dev/09`/`dev/10`/`dev/11` and `docs/03`/`docs/11` list it as flatly out of scope —
  pick one.
- **Note dataflow-explainer survival in the memos.** `dev/09`–`dev/12` discussed removing the node
  Explanation tab but did not state that `agent.dataflow-explainer` survives as the separate
  canvas/full-flow agent; only `docs/03`/`docs/11` and `dev/06` do. *(Largely mooted by `DEC-041`,
  `dev/18`: the Explanation tab itself is retained, so no reader can infer explanation is removed;
  `agent.dataflow-explainer` remains the separate canvas/full-flow agent.)*

---

## Applied fixes (mechanical, done in this pass)

- **D-0 decided (B) — sharing out of scope.** Recorded the SHARING-SCOPE rule above and **removed the
  affirmative share-build directives** rather than merely bannering them: `dev/03` §2 out-of-scope
  excludes any new sharing mechanic, and its share-preview surface, `shared_result_redaction.py` module,
  share rows/endpoints, share-projection recovery/authorization, and shared-result schema/test/gate/commit
  lines were deleted or rewritten as no-leak invariants; `dev/12` lost its "Output-Only Sharing" title and
  had its share-generation edge cases and shared-result acceptance/checklist items rewritten as negative
  invariants; the Build-Log share rule (9) is a no-leak regression guard. Remaining sharing references
  across `dev/02`/`dev/05`/`dev/09`/`dev/10`/KGGraph are negative privacy invariants or generic "shared
  result" phrasing only, governed by the D-0 rule, and are not an implementation source. Also removed the
  residual "Share"-as-a-command enumerations in `dev/04`/`dev/05`/`dev/08` and the traceability register
  (`DEC-030`), and registered `dev/14` as `SRC-MEMO-HARDEN-014`.
- **Manifest schema reconciled** to canonical `docs/11` in `dev/03` §6: `$schema` (not
  `schemaVersion`), `provenance` (not `publishing`), `contracts.{inputSchema,outputSchema}` +
  `inputs.{reads,requiredConfig}` + named `outputs[]`, with an explicit precedence note.
- **`dev/13` delete/retain hazard closed:** added filename-level delete/retain lists making clear the
  removed items are the former `docs/00-*` workflow/visual memos, and that the numbered specs
  `docs/06`/`docs/08`/`docs/09`/`docs/10` are retained and must never be deleted by the descriptive
  wording.
- **Identifier convention** added to `dev/13`: standardize one `dataflowId`/`projectId` key; never use
  both interchangeably (reconcile blueprint `05`).
- **`dev/06` migration-boundary notes** added: the backend `routes.py` `/llm/chat` + `/llm/check`
  handler is the true legacy dispatch site; the provider/LangChain layer is net-new (not relocated);
  the three composite product agents are out of the prompt-migration roster.
- **`docs/11` roster reconciliation:** noted the full **18-agent** product roster = 14 prompt-migration
  identities + 3 net-new composites + `agent.package-recommendation` (`dev/16`).
- **`dev/11` cog labels** aligned to the canonical scope-correct set (`Agent settings` /
  `Definition settings for <agent>` / `Project agent settings` / `Attached instance settings`).
- **Build Log rule 19** DEC citation fixed to enumerate `DEC-025, DEC-027, DEC-028` (drop the retired
  `DEC-026` implied by the range).
