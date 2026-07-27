# Implementation Memo: Settings Shell — Cost / Quotas / Resource-Policy Screens (last v1 item)

Date: 2026-07-22
Status: **implemented** (2026-07-23; `BL-P3-20260723-09` — commits `5c7fc32`…`763d728`; closes the `DEC-038` v1 cut. Deviation: one record-level Save instead of per-screen Saves — both scopes are a single record)
Feature slice: completes the v1 cut (`DEC-038`) — the "settings modal shell with Cost / Quotas / Resource policies"; account + project scopes
Design sources: memo `11` (screens, scopes, effective values + inherited source, downward-only overrides, revisions, dirty-guards, `Reset to agent default`), memo `12` (settings-modal applicability), `docs/02` §cogs (account `Agent settings` in the roster header), `docs/08` §scopes, `DEC-037` context, `DEC-040` (FS-backed), memos `22`/`23` (the enforcement hooks and record this slice binds to)

## 1. Problem Statement

The three v1 policy screens don't exist. Concretely: the account has no editable agent policy at all (the runs/day quota is env-only), the per-project `agentDefaults` record from `dev/23` is write-never (its modal is read-only), no `Agent settings` cog exists in the roster header (`docs/02` cog #1), nothing enforces cost, and the provider `max_tokens` is hardcoded to 4096. Memo 11's full model (six screens, four scopes, reservations, alerts) is v2; v1 needs the three policy screens editing **real, enforced values** — not form theater.

**Honesty constraint that shapes the design:** there is no token/price metering in v1, so "Actual" cost does not exist. The Cost screen therefore edits a budget against **estimated** spend (`runs × estimated cost/run`, labeled Estimated per memo 11's labeling rule), with Actual explicitly shown as unavailable.

## 2. Scope

**Included**

- Backend: `app/agents/account_settings.py` (new FS record), `app/agents/policy.py` (new — effective-policy resolution + downward-only validation), `quotas.py` (admission takes the effective policy: runs/day + estimated-budget checks; per-project-template counters), `providers.py` (`max_output_tokens` parameter on both port functions), `services.py` (PATCH services + effective view + run/stream wiring), `routes.py` (GET/PATCH account settings; PATCH project defaults), `docs/AGENTS.md`.
- Frontend: `AgentSettingsModal` shell (three tabbed screens, scope-aware) evolving `dev/23`'s read-only `ProjectAgentSettingsModal`; account `Agent settings` cog in the roster drawer header (the `DEC-042`-noted exception); `agentsApi` methods; tests.

**Out of scope (v2, per `DEC-038`/memo 11)**

- Prompt quality / editor / audit screens; evaluation; governance chains.
- Attachment-scope settings (`Attachment settings` in the chat header): tighten-only per-instance overrides need per-attachment enforcement records; deferred — no enforcement gap, since project + account scopes gate every run. Logged as the P6-adjacent follow-up.
- Reservations/ledgers, alerts, pricing effective dates, token/price metering ("Actual" cost), provider profiles (`ADR-AG-012` v2 remainder), concurrency/rate windows.
- Deployment-scope editing: env vars stay the deployment ceiling/default.

## 3. Recommended Implementation Approach

**Storage — one new record + the existing one.**
- Account: `.curio/users/<key>/agents/settings.json` → `{revision, settings: {quotas: {runsPerDay?}, cost: {dailyBudgetUsd?, estimatedCostPerRunUsd?}, resources: {maxOutputTokens?}}}` (all optional; missing file ≡ empty, like siblings).
- Project: the `dev/23` `agentDefaults` record's `settings` gains the same shape **minus** `estimatedCostPerRunUsd` (the estimate is account-scope pricing, not per-template).

**Effective policy — one resolver, downward-only.** `policy.effective(account_settings, project_settings)` resolves each field as `project ?? account ?? deployment default` with sources (`"project" | "account" | "deployment"`); deployment defaults: runs/day from `CURIO_AGENT_RUNS_PER_DAY`, `maxOutputTokens` 4096, budget/estimate unset (cost gate inactive until configured). Validation (`policy.validate_patch`) enforces memo 11's tighten-only rule server-side: an account value may not exceed the deployment ceiling; a project value may not exceed the account-effective value (400 with a field-specific message). Unknown fields are rejected.

**Enforcement — admission + provider port.**
- `quotas.admit(user_key, project_id, coord, effective)` replaces the bare count: the daily counter file gains `byTemplate: {"<pid>/<coord>": n}`; admission denies (stable 429, `resetAt`, and now a `reason: "quota" | "budget"`) when the account count would exceed the effective account runs/day, the template count would exceed a project-scope runs/day, or — when a budget and estimate are both configured — `(runsToday + 1) × estimate > dailyBudgetUsd`. Same fail-closed/corrupt-file posture as today; still advisory counters.
- `run_chat_completion`/`stream_chat_completion` accept `max_output_tokens: int | None` (anthropic replaces the hardcoded 4096; openai-compatible passes `max_tokens` when set; gemini sets `generation_config`). `run`/`stream` pass the effective value.

**API.**
- `GET /api/agents/settings` → account record + effective view (+ deployment ceilings, so the UI can render bounds).
- `PATCH /api/agents/settings` `{revision, settings}` → optimistic concurrency (409 on stale revision), validate, persist, return fresh record+effective.
- `PATCH /api/agents/projects/<pid>/defaults/<coord>` `{revision, settings}` → same semantics against the `dev/23` record (revision bump); `{"settings": {}}` is `Reset to agent default` for that one template (memo 11 — clears overrides → inherit).
- `GET …/defaults/<coord>` (existing) now returns the fuller effective view with per-field sources.

**Frontend — one scope-aware shell.**
- `AgentSettingsModal` (evolves `ProjectAgentSettingsModal`): scope banner (`Account policy` / `Project agent default · <agent>`), three tabs — **Cost** (daily budget; estimate at account scope; "Estimated spend today: N runs × $X ≈ $Y · Actual: not available in v1"), **Quotas** (runs/day + used-today meter), **Resource policies** (max output tokens; read-only provider/model summary) — every field showing its effective value + source chip, editable fields bounded by the parent scope's effective value, Save per screen (PATCH with revision; 409 → "reloaded, reapply" flow), dirty-guard on close/tab-switch (confirm), project scope adds `Reset to agent default`. No Publish/Release/Share in any scope.
- Entry points: the existing project cog opens the shell at project scope; a labeled **`Agent settings`** cog joins the roster drawer header (beside the Pin — the separately-approved control noted in `DEC-042`/memo `dev/21`) opening account scope.

## 4. Data and State Handling

- Sources of truth: the two FS records; effective values always computed server-side by the one resolver — the UI never derives policy. Enforcement reads the same resolver at admission time, so what the screens show is what runs hit.
- Optimistic concurrency on both records (revision in PATCH; 409 keeps last-writer from silently losing edits — memo 11's revisions rule).
- Loading/error/empty per screen; unsaved-changes guard; after Save the returned record+effective replace local state (no refetch).
- Project records stay backend-owned spec state (preserve/uninstall semantics from `dev/23` unchanged).

## 5. UI and UX Requirements

- Memo 11 invariants, v1-sized: labeled entry points; scope identity always visible; every value with effective + inherited-source provenance; downward-only bounds surfaced as input hints and enforced server-side; Estimated-vs-Actual labeling on Cost; dialog focus trap, Escape (guarded when dirty), keyboard nav, WCAG AA contrast on the existing tokens.
- Denials in chat: the 429 error turn now distinguishes quota vs budget (`reason`) — "Daily budget reached (estimated)" vs the existing limit message.
- No changes to dock/badges/palette/chat layout, `DEC-041`/`DEC-042` chrome untouched (the roster header gains only the already-sanctioned cog).

## 6. Edge Cases

- Budget configured without an estimate (or vice versa): cost gate inactive; the screen says which half is missing.
- Estimate lowered mid-day: gate evaluates with current values (spend is always recomputed, never stored).
- Project override left above a newly-lowered account value: legal-at-write-time records are re-clamped **at resolution** (effective = min), so stale looser values can't leak through; the screen flags "clamped by account".
- Revision races on either record → 409, no partial writes; concurrent admission races stay advisory-by-one (documented).
- Template counters GC naturally with the daily window; uninstall mid-day leaves orphan counter keys that expire with the window (accepted).
- Corrupt settings/quota files → empty/fresh (existing posture); guests: account scope keyed by the guest storage key, screens work.
- `maxOutputTokens` below a provider minimum: provider error surfaces as the normal run failure.

## 7. Testing Strategy

Backend: `test_account_settings.py` (record round-trip/corrupt/missing), `test_policy.py` (resolution sources, clamping, tighten-only validation incl. deployment ceiling), `test_quotas.py` additions (per-template counting, budget denial + `reason`, budget inactive when unconfigured), `test_providers.py` (+`max_output_tokens` passthrough per backend), `test_routes.py` (GET/PATCH account with 409; PATCH project defaults + reset-to-default + tighten-only 400; run denied by project-scope quota and by budget; effective sources in GET; regression on the un-gated `/llm/chat`).
Frontend: shell tests per screen (render effective+source, save PATCH payloads, 409 flow, dirty-guard, reset-to-default, bounds hints, no Publish/Release/Share), roster-header cog test, api-client tests. Full suites green.

## 8. Acceptance Criteria

- [ ] Account `Agent settings` (roster header) and project `Project agent settings` open the same three-screen shell at their scopes, each field showing effective value + source.
- [ ] Setting a project runs/day below the account value gates that template's runs (429 after N); setting a budget + estimate gates on estimated spend with a `budget` reason; both denials render distinctly in chat and consume nothing.
- [ ] A project value above the account-effective (or account above deployment) is rejected server-side with a field-specific 400; stale looser records clamp at resolution.
- [ ] `maxOutputTokens` demonstrably reaches the provider call (test-asserted per backend).
- [ ] Stale-revision PATCHes 409 on both records; `Reset to agent default` clears one template's overrides only.
- [ ] `/llm/chat` remains un-gated; all prior suites pass; `DEC-041`/`DEC-042` surfaces untouched.

## 9. Recommended Commit Breakdown

1. `feat(agents): account settings record + effective-policy resolver with tighten-only validation, pure tests`.
2. `feat(agents): policy-aware admission (per-template counters + estimated-budget gate) and max_output_tokens on the provider port, with tests`.
3. `feat(agents): GET/PATCH account settings + PATCH project defaults (revisions, reset), route tests`.
4. `feat(agents): scope-aware AgentSettingsModal (Cost/Quotas/Resources) + roster-header Agent settings cog, component tests`.
5. Build-log entry (`BL-P3-…-09` or a new `BL-P0` foundations entry) + `docs/AGENTS.md`.

## 10. Engineering Quality Checklist

- One resolver serves both display and enforcement — no drift between what's shown and what's applied.
- Tighten-only validated at write AND clamped at read; revisions on every mutable record; no client-derived policy.
- Cost is honest: estimated-only, labeled, inactive until configured; no fake meters.
- Counters remain advisory-simple (v1), extended not replaced; `/llm/chat` untouched.
- The `dev/23` record/API shapes are extended compatibly (`settings`/`revision` PATCHed exactly as planned there).
