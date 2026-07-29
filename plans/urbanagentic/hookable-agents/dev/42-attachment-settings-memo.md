# Implementation Memo: Attachment Settings — the Attached-Instance Policy Scope

Date: 2026-07-28
Status: implemented 2026-07-28 (`BL-P3-20260728-11`; commits `58d01e00`, `8675f55d`, `de1c3b67`, `786041bb`)
Feature slice: the fourth settings scope (`Attached instance`), closing the follow-up dev/24 explicitly deferred: *"Attachment-scope settings (`Attachment settings` in the chat header): tighten-only per-instance overrides need per-attachment enforcement records; deferred — no enforcement gap, since project + account scopes gate every run. Logged as the P6-adjacent follow-up."*
Design sources: `docs/08` ("**Attached instance** — `Attachment settings` may only tighten Cost, Quotas, and Resources. Prompt source/evidence is read-only and the instance has no Version/Release/Publish/Share action"; the drawer anatomy's "⚙ Attachment settings" cog below the header), `docs/03` (the four-scope modal shell; "chat-header `Attachment settings` opens downward-only Cost, Quotas, and Resource overrides"), `docs/09`/`docs/11` (attachment overrides "may only tighten the selected project profile"; effective policy = deployment → account → project template → attachment override), memo `dev/11` (scope table), memo `dev/24` (the two implemented scopes this extends — resolver, tighten-only validation, revisioned PATCH, modal shell), memo `dev/40`/`DEC-044` (the ledger that now makes "per-attachment enforcement records" a one-field change), `DEC-042` (the opened-view header the cog sits beneath), `DEC-031` (the pins that must reflect what actually gated the run)
New decision required: **none** — the attached-instance scope is already approved design (docs/08/03/11, dev/11's four-scope table); this memo implements it and closes dev/24's recorded deferral. No identifier is consumed.

## 1. Problem Statement

The design defines four settings scopes; two exist. `AgentSettingsModal`'s scope type is literally `"account" | "project"`, `policy.effective(account_settings, project_settings)` resolves two layers, attachment records carry no `settings`, and the opened chat view has **no** `Attachment settings` cog — despite the concept anatomy (docs/08) placing one directly beneath the DEC-042 header. Consequences:

- A user cannot tighten limits for one attached instance below its project's values — e.g. cap an experimental Node Content Builder at 5 runs/day while the project template keeps 50, or clamp `maxOutputTokens` for a chat attachment that only ever needs short answers. The design promises exactly this ("attachment overrides may only tighten it", docs/09).
- The chat view breaks the approved anatomy: settings for the thing you're looking at require leaving it (drawer → installed card → project scope), and what you reach there governs *every* instance of the template, not this one.
- The `DEC-031` pins' policy snapshot can never reflect an instance-level constraint, because none can exist.

Why now: dev/24's deferral reason — "need per-attachment enforcement records" — was real under the advisory counters and is trivial under the T3 ledger: reservations already carry a `templateKey`; an `attachmentKey` beside it plus one derived aggregate is the entire enforcement record.

## 2. Scope

**Included**

- Backend: `policy.effective` gains the third (attachment) layer with source `"attachment"`; `validate_patch` gains the `"attachment"` scope (tighten-only against the **project-effective** values; same field set as the project scope — no `estimatedCostPerRunUsd`, which stays account-only per dev/24); attachment records gain a `settings` dict (reusing the record's existing optimistic `revision`); `GET`/`PATCH /projects/<pid>/attachments/<aid>/settings`; the ledger's reserve entries gain `attachmentKey` + a derived `byAttachment` aggregate; `_run_policy` resolves three layers, enforces an attachment-scope runs/day limit per attachment, and the pins' policy snapshot picks the tightened values up automatically.
- Frontend: `AgentSettingsModal` gains the `"attachment"` scope (banner `Attached instance`, per docs/03's header naming); the opened chat view gains the labeled **⚙ Attachment settings** cog beneath the header (the docs/08 anatomy slot), opening the modal at this scope; `Clear overrides` as the scope's reset action.
- Tests throughout; rule-9 share suite re-run (settings ride the attachment record, which `strip_agent_state` already excludes wholesale).

**Out of scope**: the **Imported definition** scope (Prompt editor/quality/audit — v2 governance, `DEC-036`/`DEC-038`); per-attachment *budget attribution* (see §4.3 — the budget gate keeps its existing account-wide-spend semantic, exactly as the project scope already behaves); enable/disable toggles and any non-policy attachment control; the six-screen governance shell (the three v1 screens only, like the existing scopes).

## 3. Recommended Implementation Approach

Extend, don't fork: every mechanism this scope needs already exists once for the project scope — the same resolver, the same tighten-only validator with a different parent, the same revisioned-PATCH service shape, the same modal shell with a third scope value. The only genuinely new machinery is the per-attachment run count, which becomes one field on the ledger's reserve entry plus one derived aggregate (no new store, no migration — old entries without `attachmentKey` simply count nothing per-attachment, correct for daily windows).

### 4.1 Policy resolution and validation (`policy.py`)

- `effective(account_settings, project_settings=None, attachment_settings=None)` — the third layer resolves exactly like the second: a value may only *lower* the inherited effective value; source becomes `"attachment"` when it wins. Field set at this scope: `quotas.runsPerDay`, `cost.dailyBudgetUsd`, `resources.maxOutputTokens` (no estimate — account-scope pricing, dev/24).
- `validate_patch(settings, "attachment", parent_effective)` where the parent is `effective(account, project_settings)` — tighten-only server-side, 400 with field-specific messages, unknown fields rejected: byte-for-byte the project scope's contract one level down.

### 4.2 The attachment record + API

- `attachments.set_settings(spec, attachment_id, settings)` stores the cleaned dict on the record and bumps the record's existing `revision` — the same optimistic token `set_intent`/`set_title` already bump, so any concurrent edit of the instance (intent, title, settings) invalidates a stale settings draft with the standard 409 → "reloaded, reapply" flow (deliberate: one record, one revision; edge case §6).
- `GET /projects/<pid>/attachments/<aid>/settings` → `{attachmentId, coord, name, revision, settings, effective}` where `effective` is the three-layer view with per-field sources, `usedToday` on `runsPerDay` metered against the **binding** scope (attachment-source limit → this attachment's ledger count; project-source → the template count; else the account count — the meter always measures what the limit actually counts), plus the dev/37/40 `usageToday`/`actualSpendTodayUsd`/`pricing` passthroughs so the Cost screen renders identically at this scope.
- `PATCH …/settings` `{revision, settings}` — validate → store → bump → return the GET payload. `{"settings": {}}` is **Clear overrides** (falls back to the project profile; mirrors the project scope's reset semantics). Owner-auth like every attachment route.

### 4.3 Enforcement (`ledger.py`, `services._run_policy`)

- `ledger.reserve` gains `attachment_key`/`attachment_limit` beside the template pair; reserve entries record `attachmentKey`; `_aggregate` derives `byAttachment`. The check slots into the existing critical-section order: account limit → template limit → **attachment limit** → budget ladder. Additive: old entries lack the key and simply don't count toward it.
- `_run_policy` resolves `full_eff = policy.effective(acct, project_record, attachment_record.settings)`; the admit kwargs gain `attachment_key = attachment_id` (always recorded — useful attribution regardless) and `attachment_limit` (set only when the runs/day source is `"attachment"`, mirroring how the template limit works today).
- **Budget semantic — unchanged by design**: an attachment-tightened `dailyBudgetUsd` gates the *account-wide* spend ladder, exactly as a project-tightened budget already does (the tightest configured budget caps total daily spend; per-scope spend attribution is not what the existing scopes implement, and inventing it only for attachments would make the three scopes inconsistent). Stated here so the review can veto it consciously; per-attachment budget attribution is a clean later slice on the same ledger if ever wanted.
- `maxOutputTokens`: flows through `run_policy["max_output_tokens"]` to the provider port as today. Pins: `policy_pins` is built from `full_eff`, so the snapshot reflects instance tightening with **zero** changes to the pins code (`DEC-031` satisfied structurally).

### 4.4 Frontend

- `AgentSettingsModal`: `Scope = "account" | "project" | "attachment"`; banner `Attached instance`, title = the attachment's display name, subtitle the coord + target; editable fields per §4.1 (the estimate stays read-only text as at project scope); footer action `Clear overrides` (confirm-first, PATCH `{}`); everything else — provenance chips, bound hints from the parent effective values, 409 reload flow, dirty guards — inherited from the shell unchanged.
- Chat view: the labeled **⚙ Attachment settings** cog renders at the top of the white content area beneath the DEC-042 header (the exact docs/08 anatomy slot — not in the dark header, which DEC-042 fixed as identity + cycling + Close only). It opens the modal at attachment scope for this `attachmentId`; close restores focus to the cog (the dev/24 a11y contract).
- API client: `getAttachmentSettings`/`updateAttachmentSettings`; types extend the existing settings shapes with the `"attachment"` source value.

## 5. Data and State Handling

- Source of truth: the attachment record in `spec.dataflow.agentAttachments` (settings ride it; same lifecycle — detach/prune deletes them, canvas saves preserve them via `preserve_agent_state`, shares never see them via `strip_agent_state`).
- One revision per record: intent, title, and settings share the attachment's optimistic token — no second counter to drift.
- Ledger attribution is additive (`attachmentKey` on new reserves only); aggregates stay derived-never-stored; no migrations anywhere (records without `settings` ≡ no overrides; old ledger entries count nothing per-attachment).
- The effective view is always server-computed on read — the modal never composes policy client-side (unchanged posture).

## 6. Edge Cases

- Attachment override looser than the project value: 400 at PATCH (tighten-only), field-named message — never silently clamped.
- Project defaults tightened *after* an attachment override was saved above the new value: the resolver takes the minimum at read time, so the stored override becomes inert rather than invalid (same behavior the account→project pair has today); the modal's provenance chip shows which layer actually binds.
- Concurrent intent/title edit while a settings draft is open: shared record revision → 409 → the existing "changed elsewhere — reloaded, reapply" flow (deliberate, §4.2).
- Detach with overrides: settings die with the record; re-attaching creates a fresh instance with none (instances are unversioned derivations, `DEC-031`).
- Clear conversation: settings untouched (they are instance policy, not transcript state).
- Attachment runs/day exhausted while the template still has headroom: 429 `reason: "quota"` with a message naming the *attachment* limit; other attachments of the same template keep running (the ledger counts them separately).
- Old ledger entries (pre-`attachmentKey`) on the deploy day: the attachment counter starts at zero mid-window — acceptable for a tighten-only daily limit and gone at the boundary (noted in the build log, same posture as prior additive keys).
- Proposals/tool grants: unaffected — grants are manifest ∩ registry, not policy; the apply endpoint consumes no quota (T2b), so attachment limits never block a pending review.
- Stateless legacy attachment (no sessionId): settings still work (they live on the record, not the session).
- Share surface: attachment records are already stripped wholesale — rule-9 suite re-run proves no new leak.

## 7. Testing Strategy

Backend — `test_policy.py`: three-layer resolution (attachment wins only downward; source labeling; estimate absent at this scope), `validate_patch` attachment scope (tighten-only vs project-effective, unknown fields). `test_ledger.py`: `attachmentKey` recorded, `byAttachment` derived, attachment-limit check in the critical-section order, old-entry tolerance. `test_routes.py`: GET/PATCH round-trip with revision 409 (incl. the shared-revision case: an intent edit invalidates a settings draft); Clear overrides; per-attachment 429 naming the attachment limit while a sibling attachment still runs; `maxOutputTokens` tightening reaches the provider call; pins' policy snapshot reflects the tightened values; binding-scope `usedToday` metering (all three sources); owner-auth 404s. Share regression suite re-run.
Frontend: modal at attachment scope (banner, editable fields, estimate read-only, Clear overrides confirm + PATCH `{}`, 409 reload flow); the chat-view cog renders in the content-area slot (not the header — DEC-042 pin), opens the modal, and close restores focus to it; existing suites green.

## 8. Acceptance Criteria

- [x] An attached instance can tighten `runsPerDay`, `dailyBudgetUsd`, and `maxOutputTokens` below its project-effective values — and only below (400 otherwise); `{}` clears back to the project profile.
- [x] An attachment-scope runs/day limit is enforced atomically per attachment in the ledger's critical section: the capped instance 429s (message naming the attachment limit) while sibling attachments of the same template keep running.
- [x] The opened chat view carries the labeled `Attachment settings` cog beneath the header (never in it — `DEC-042`), opening the shared modal at the `Attached instance` scope with per-field provenance across all four sources; focus returns to the cog on close.
- [x] The execution pins' policy snapshot reflects instance tightening with no pins-code changes; `usedToday` meters the binding scope; the Cost screen renders identically at this scope (incl. the T3 Actual USD states).
- [x] Everything is additive — no migrations, old records/ledger entries/clients read clean; the share surface gains nothing (rule-9 re-run); no Publish/Release/Share/Version control appears at this scope.

## 9. Recommended Commit Breakdown

1. `feat(agents): three-layer effective policy + attachment-scope validation, with tests`.
2. `feat(agents): per-attachment enforcement — ledger attachmentKey/byAttachment + attachment limit in admission, with tests`.
3. `feat(agents): attachment settings record + GET/PATCH endpoints + run-policy wiring (binding-scope usedToday, pins pass-through), with tests`.
4. `feat(agents): frontend — attachment scope in the settings modal + the chat-view Attachment settings cog, with tests`.
5. Docs + ledgers: build-log entry `BL-P3-2026…-11` (the settings-screens lineage lives in the P3 log, per `BL-P3-…-09`); update the 3.1 P3 row; close dev/24's deferral note in place; `docs/AGENTS.md`; memo status flip. No decision-table change (no new DEC).

## 10. Engineering Quality Checklist

- Zero forked mechanisms: one resolver, one validator, one modal shell, one revision token, one admission critical section — the scope is a third value everywhere, not a parallel path.
- Tighten-only is server-enforced at the edge (`validate_patch`) *and* structural at read (`min()` resolution) — a stale stored override can never widen anything.
- The enforcement record lives in the ledger like every other count: derived, race-safe, self-expiring; no new store.
- The budget semantic is stated, not smuggled (§4.3): consistent with the existing scopes, flagged for conscious review.
- DEC-042's header contract is respected to the letter (the cog is below the header); docs/08's anatomy slot is finally filled.
- The scope adds no share surface, no publish affordance, no version identity — the docs/08 invariants hold by construction.
