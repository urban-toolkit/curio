# Implementation Memo: P2 Runtime Maturation — Tranche 3: Ledgers + Pricing

Date: 2026-07-28
Status: implemented 2026-07-28 (`BL-P2-20260728-09`, `DEC-044`; commits `a69ab1ca`, `0224bf42`, `1bb6f1a0`, `157889f6`)
Feature slice: v2 runtime maturation, third tranche (`DEC-038`; the dev/37 tranche map — "atomic reservations replacing the advisory counters, a price table, true 'Actual' USD on the Cost screen")
Design sources: `REQ-COST-001` (immutable price/policy snapshot + atomic idempotent budget reservation before provider work; estimates advisory; actual usage append-only; **unknown pricing fails closed when a hard monetary cap applies**), `REQ-QUOTA-001` (atomic windowed reservations; concurrent attempts cannot oversubscribe), `RISK-COST-001` (concurrent/ambiguous work overspends because admission/settlement aren't atomic), memo `11` (Estimated vs **Actual** labeling; "fail closed when a hard-cost price is unknown"), `dev/05` blueprint (:1242-1244 price-snapshot / reservation / usage-ledger-entry shapes — append-only, corrections append never rewrite; :1200 `CostPolicyService` responsibilities), `DEC-040` (FS-backed, no SQL — the ledger must be a filesystem structure), `docs/08` Cost screen ("current usage, **pricing effective date**, explicit Estimated versus provider-reported Actual"), memo `dev/37` T1 (the Actual token counts this tranche prices), `dev/24` (the advisory counters + estimate-only gate this tranche replaces)
New decision required: **`DEC-044`** (next free number) — the deployment-owned price table + the FS ledger realization of `REQ-COST-001`/`REQ-QUOTA-001` below; registered in the dev/03 table + 2.1 ledger with this memo.

## 1. Position in the Maturation Program

Tranche 3 of the dev/37 map. T1 gave every run an execution record and Actual token counts; T2 gave the typed envelope. This tranche makes the money and quota accounting *true*: the advisory daily counters (dev/22/24 — explicitly documented as "racing writers may briefly over-admit by one") are **replaced** by an atomic, append-only usage ledger, and a deployment-owned price table turns T1's Actual tokens into Actual USD where — and only where — a real price exists. Remaining after this: T2b (executing tools/review-apply), T4 (provider profiles + secret store).

**Explicitly not in this tranche**: concurrency/queue quotas and leases (`REQ-QUOTA-001` names them; they gate background execution, which doesn't exist — a reservation here lives for one synchronous request), reconciliation workflows for ambiguous provider work (same dependency; the ledger *shape* supports appending reconciliation entries later), evaluation sub-budgets (`DEC-037`, v2 governance), and any UI for editing prices (the table is a deployment artifact, not a screen).

## 2. Problem Statement

Three dishonesties survive T1/T2, each a named requirement violation:

- **Admission races** (`RISK-COST-001`, `REQ-QUOTA-001`): `quotas.admit` does an unlocked read-modify-write of `quota.json`. Two concurrent runs at 199/200 both read 199, both admit, both write 200 — the limit over-admits, and the budget gate double-spends the same headroom. This was an accepted v1 posture, documented as such; T3 is where the accepted debt is called.
- **Settlement isn't linked to admission** (`REQ-COST-001`): the run counter increments at admit time and the usage counters at completion, with no shared identity. Nothing can ever say "this run was admitted against this budget headroom and actually cost this much" — which is exactly the reservation→settlement pair the requirement demands, and what T2b's child/retry attribution will need.
- **No Actual USD** (`docs/08`, memo 11): the Cost screen's Actual line names tokens as available and USD as pending "the T3 price table" (T1's honest upgrade). There is no price table, so a deployment whose provider *does* have real per-token prices still can't see actual spend, and the budget gate can only ever compare against the user-typed estimate.

## 3. Scope

**Included**

- Backend: an append-only, flock-guarded **daily usage ledger** (`app/agents/ledger.py`) with reserve → settle semantics replacing `quotas.admit`/`record_usage`; a **price table** (`app/agents/pricing.py`) resolving immutable per-run price snapshots; runtime wiring (reserve before dispatch, settle at completion, price-aware budget gate incl. the `REQ-COST-001` fail-closed rule); `costUsd` on the execution record (Actual-only, nullable); settings payloads gain `actualSpendTodayUsd` + a no-secrets pricing summary; a one-time same-day seed of the new ledger from the legacy `quota.json` window (so deploy day cannot re-open an exhausted quota).
- Frontend: the Cost screen's Actual line becomes real — `$X.XX today · N in / M out tokens (provider-reported)` with the pricing effective date when priced, and an honest "no USD price configured for `<provider> · <model>`" otherwise; types.
- Tests throughout, including a genuine concurrency race test on the reservation path.

**Out of scope**: everything in §1's "explicitly not in this tranche"; changes to the policy screens' *editable* fields (budget/estimate editing is unchanged); the legacy `/llm/*` routes (never quota-gated, stays that way); Windows mandatory locking (the ledger reuses the repo's existing dual-layer locking pattern — see §4.1 — which already degrades the same way for `projects/storage.py`).

## 4. Design

### 4.1 The ledger (`app/agents/ledger.py`) — append-only, atomic, FS-backed

Per `DEC-040`, filesystem only:

```text
.curio/users/<key>/agents/ledger/<YYYY-MM-DD>.jsonl   # append-only entries
.curio/users/<key>/agents/ledger/.lock                # flock guard
```

One JSON entry per line, three kinds (the blueprint's usage-ledger-entry shape, :1244):

```json
{"kind": "reserve", "reservationId": "<executionId>", "ts": "...",
 "templateKey": "<pid>/<coord>", "holdUsd": 0.002|null,
 "holdSource": "estimate"|null, "price": {<snapshot>}|null}
{"kind": "settle", "reservationId": "<executionId>", "ts": "...", "status": "ok"|"error",
 "usage": {"inputTokens": n, "outputTokens": n}|null, "costUsd": 0.0013|null}
{"kind": "usage", "ts": "...", "note": "title-call",
 "usage": {...}, "costUsd": ...|null}
```

- **Atomicity**: every reserve is a single flock-guarded critical section — read the day's aggregates, check every limit, append the reserve entry, fsync. Two concurrent last-slot attempts serialize; exactly one admits (`REQ-QUOTA-001`). The module mirrors the repo's existing dual-layer pattern (`projects/storage.py`): a per-account in-process `threading.Lock` (the Flask-threaded case, all platforms) plus `fcntl.flock` on `.lock` (cross-process, POSIX; degrades to thread-only on Windows exactly as project-spec writes already do).
- **Append-only** (`dev/05`:1244): corrections and settlements append; nothing rewrites. A corrupt line is skipped on read (same tolerance posture as every other FS store); the file never needs repair.
- **Idempotency**: `reservationId` **is** the T1 `executionId` — one reservation per execution, no new identity. A second settle for the same reservation is a no-op (first-write-wins); a settle without a reserve appends and is counted (never lost).
- **Windowing**: the day file is the window; both reserve and settle append to the *reservation's* day file (a run crossing midnight settles into the day it was admitted). A reservation with no settlement (crashed process) simply keeps its hold for the rest of its window — conservative, fail-closed, and self-expiring at the day boundary; lease-based reconciliation stays with background execution (§1).
- **Aggregates** (derived by reading the day file, ≤ `runsPerDay` × ~2 lines — trivially cheap): `runs` (reserve count), `byTemplate`, `usage` (settled + housekeeping token sums), `actualSpendUsd` (settled `costUsd` sums), `heldUsd` (reserves not yet settled: their `holdUsd`), `settledEstimatedUsd` (settles where cost was unknown: the reservation's `holdUsd` — see the budget ladder below).
- **Legacy seed**: on the first reserve of a day, if the legacy `quota.json` window is the *same* day and no ledger file exists yet, append one `{"kind": "seed", "runs": n, "byTemplate": {...}, "usage": {...}}` entry carrying the advisory counts forward, so the deploy-day switch cannot re-open an exhausted quota or re-zero the token counters. The legacy file is left in place (read-only from then on) and dies of natural staleness.

Public API: `reserve(user_key, *, account_limit, template_key, template_limit, daily_budget_usd, estimated_cost_per_run_usd, price) -> reservation` (raises the existing `QuotaExceeded` — the route contract, 429 body, and `reason: "quota"|"budget"` are unchanged); `settle(user_key, reservation_id, *, usage, status, day)`; `record_housekeeping_usage(...)` (the dev/25 title call — usage/cost counted, never run-counted, unchanged posture from T1); `aggregates(user_key) -> {runs, byTemplate, usage, actualSpendUsd, ...}`. `quotas.runs_used_today`/`usage_today` become thin reads over `aggregates` so every existing settings surface keeps working; `quotas.admit`/`record_usage`/`check_and_count` are **retired** (T1 said "T3 replaces, not patches" — no parallel counter store remains).

### 4.2 The price table (`app/agents/pricing.py`) — deployment-owned, never fabricated

- Source: an operator-provided JSON file at `.curio/agents-pricing.json` (path overridable via `CURIO_AGENT_PRICE_TABLE`), mapping `"<provider>/<model>"` → `{"inputUsdPerMtok": x, "outputUsdPerMtok": y, "effectiveDate": "YYYY-MM-DD"}`. **The built-in table is empty**: Curio's default provider is a self-hosted aiconn endpoint with no per-token USD price, and fabricating one would violate memo 11's honesty rule. Actual USD exists exactly when the operator states a price. Missing/corrupt file ≡ empty table (standard FS tolerance).
- `price_snapshot(provider, model) -> dict | None`: the immutable snapshot pinned into the reserve entry and used at settlement — `{inputUsdPerMtok, outputUsdPerMtok, effectiveDate, currency: "USD"}`. Pinning at reserve time satisfies `dev/05`:1242 ("immutable per reservation/ledger attribution"): a table edit mid-day never rewrites what an earlier run was charged.
- Settlement math: `costUsd = inputTokens × in/1e6 + outputTokens × out/1e6`, rounded to 6 places, only when both a snapshot and Actual usage exist — otherwise `costUsd: null` (Actual or absent, never estimated into the field).

### 4.3 The budget gate — actual-first, fail-closed on unknowns (`REQ-COST-001`)

Admission checks, in the existing order (account runs/day → template runs/day → budget), with the budget check upgraded from `(runs+1) × estimate` to a **spend ladder** computed inside the same critical section:

```text
charged = actualSpendUsd            (settled runs with a real price)
        + settledEstimatedUsd       (settled runs that had no price: their held estimate)
        + heldUsd                   (concurrent in-flight reservations)
        + thisRunHold
```

`thisRunHold` = the account's `estimatedCostPerRunUsd` (the user-stated advisory estimate — a price table cannot predict a run's tokens before it happens). Deny with the existing stable 429 (`reason: "budget"`) when `charged > dailyBudgetUsd`.

**Fail-closed rule** (the one deliberate behavior change, mandated by `REQ-COST-001`/memo 11): when `dailyBudgetUsd` is configured but **no** `estimatedCostPerRunUsd` is set **and** the model has **no** table price, the run's cost is unknowable under a hard monetary cap → deny (429, `reason: "budget"`, message naming what's missing: "a daily budget is set but no cost estimate or price is configured"). Today that combination silently disables the gate; a configured hard cap that enforces nothing is the dishonesty this requirement exists to kill. Deployments that want no monetary gate simply leave the budget unset (unchanged). This change is called out in its own test, the build-log entry, and the Cost screen's gate-status line.

### 4.4 Runtime + surfaces

- `run_attachment`/`stream_attachment`: `quotas.admit(...)` → `ledger.reserve(...)` (passing the price snapshot resolved from the run's provider config — the same values already pinned in `pins`); `_record_usage(...)` → `ledger.settle(execution_id, usage, status)` on both the ok and error paths (an error settles with whatever usage exists — releasing the hold and recording the truth, consistent with T1's error-record posture). The title call's `_record_usage` becomes `ledger.record_housekeeping_usage`.
- **Execution record** gains `costUsd` (nullable, Actual-only) next to `usage` — the transcript remains the single run history; what a run cost rides the same record as what it consumed.
- **Settings payloads** (`get_account_settings`, project-defaults GET): gain `actualSpendTodayUsd` (number | null — null when no settled entry has ever been priced *and* no price is configured) and `pricing: {provider, model, effectiveDate} | null` (no secrets — provider type + model only, same fields as the pins). `estimatedSpendTodayUsd` stays, still labeled Estimated (memo 11 keeps both, distinctly labeled, forever).
- **Cost screen**: the Actual line becomes `Actual: $X.XX today · N in / M out tokens (provider-reported) · pricing effective <date>` when priced; `Actual: N tokens today — no USD price configured for <provider> · <model>` otherwise (the T1/T2 wording upgraded from "arrives with the price table" to naming the concrete gap). The gate-status sentence covers the new fail-closed state: "A daily budget is set but no estimate or price is configured — runs are blocked until one is provided or the budget is cleared."
- **Quotas screen**: unchanged (runs + tokens; aggregates now come from the ledger).

## 5. Data and State Handling

- Source of truth: the per-day ledger file, per account — reservations, settlements, and housekeeping usage in one append-only stream; every aggregate is derived, none stored (no drift). The old `quota.json` is read exactly once per account (the same-day seed) and never written again.
- Price snapshots are pinned per reservation; the table file is read per resolution (small, cached per-request only — no process-lifetime cache to go stale).
- No migrations: absent ledger dir ≡ zero usage; old sessions/turns unaffected; `costUsd` is additive on the execution record; settings fields are additive.
- Privacy: ledger entries hold coord/template keys, token counts, and USD — no message content, no secrets; the ledger lives under the user dir, outside every share surface (rule-9 posture unchanged).
- The 429 contract (`{error, quota, reason, resetAt}`) is byte-compatible; only the accounting behind it changes.

## 6. Edge Cases

- Two concurrent runs at the last quota slot / last budget dollar: exactly one admits (flock-serialized critical section) — the race test, both threads and (POSIX) processes.
- Crash between reserve and settle: the hold persists for the window (conservative over-count of at most one run's estimate/slot per crash), self-expires at the day boundary; no reconciliation daemon in this tranche.
- Provider reports no usage (sink empty): settle with `usage: null`, `costUsd: null`; the hold's estimate is what the budget keeps (as `settledEstimatedUsd`) — budget accounting never silently drops a run it admitted.
- Price exists but usage doesn't / usage exists but price doesn't: `costUsd` null in both; only priced-usage settles into `actualSpendUsd`.
- Budget set, estimate set, no price: today's behavior, now atomic (estimate charged at settle).
- Budget set, no estimate, no price: **denied** (the §4.3 fail-closed change).
- Budget set, no estimate, price known: admitted with `thisRunHold = 0` + a known settlement price — actuals accrue and gate future runs (the estimate becomes optional once real prices exist).
- Price-table edit mid-day: earlier entries keep their pinned snapshots; only new reservations see the new price (pinning test).
- Stateless legacy attachment (no session): reserve/settle still occur (the ledger is account-scoped, not session-scoped); only the turn record has nowhere to persist — unchanged from T1.
- Same-day redeploy with legacy counts (190/200 used): seed entry carries the 190 forward; cross-day redeploy seeds nothing (window naturally reset).
- Corrupt ledger line / corrupt price file: line skipped / table empty; reads never raise.
- Midnight boundary: a reservation admitted at 23:59:59 settles into that day's file; `resetAt` semantics unchanged.
- Windows: cross-process flock degrades to in-process locking exactly as project-spec writes already do (documented in-module, same wording as `projects/storage.py`).

## 7. Testing Strategy

Backend — `test_ledger.py` (new): reserve/settle round-trip and aggregates; idempotent double-settle; settle-without-reserve counted; append-only (settle never mutates prior bytes); corrupt-line tolerance; window keying incl. the midnight case; legacy same-day seed (and cross-day non-seed); **the race test** — N threads reserving the last slot concurrently, exactly one admitted (and a fork-based two-process variant on POSIX). `test_pricing.py` (new): table load/missing/corrupt, snapshot shape, settlement math incl. rounding, empty-by-default. `test_routes.py`/`test_quotas.py` updates: 429 contract byte-compatibility for quota and budget denials; the spend ladder (actual + settled-estimate + held + this-run); the fail-closed unknown-price-with-budget denial (its own test, named as the behavior change); `costUsd` on the execution record (priced and unpriced); settings payloads' `actualSpendTodayUsd`/`pricing`; title-call usage still counted, still recordless, never run-counted; error-path settlement releases the hold. Regression: every existing quota/usage test green over the ledger-backed reads.
Frontend: Cost screen states — priced (USD + tokens + effective date), unpriced (named gap), fail-closed gate message; types; existing suites green.

## 8. Acceptance Criteria

- [x] Concurrent reservations cannot over-admit a run limit or overspend a budget: the race test proves exactly-one-admit at the last slot, cross-thread and (POSIX) cross-process.
- [x] Every run is a reserve→settle pair keyed by its `executionId` in an append-only daily ledger; settlements are idempotent; corrections/settlements append, never rewrite; the advisory counters are retired with no parallel store left.
- [x] Actual USD exists exactly where a deployment-stated price exists: pinned per reservation, settled from T1's Actual tokens, surfaced as `costUsd` on the execution record and `actualSpendTodayUsd` on the settings payloads — never estimated into an Actual field, and the built-in table is empty.
- [x] The Cost screen shows Actual USD + tokens + pricing effective date when priced, names the missing price when not, and states the fail-closed gate condition; Estimated stays separately labeled.
- [x] A configured `dailyBudgetUsd` always enforces: known price or estimate → the spend ladder; neither → the run is refused with the stable 429 (`REQ-COST-001` fail-closed — the tranche's one deliberate behavior change, tested by name).
- [x] The 429 body, settings payload shapes (additive), execution records (additive `costUsd`), and legacy same-day counts all carry over — no migrations, old data reads clean.

## 9. Recommended Commit Breakdown

1. `feat(agents): append-only flock-guarded usage ledger — reserve/settle/aggregates + legacy seed, with race tests`.
2. `feat(agents): deployment-owned price table + immutable per-reservation snapshots, with tests`.
3. `feat(agents): runtime on the ledger — reserve/settle wiring, spend-ladder budget gate incl. REQ-COST-001 fail-closed, costUsd on execution records, settings exposure; advisory counters retired, with tests`.
4. `feat(agents): frontend — Actual USD on the Cost screen (priced/unpriced/fail-closed states), types, with tests`.
5. Docs + ledgers: build-log entry `BL-P2-2026…-08`; register **`DEC-044`** (dev/03 table + 2.1 ledger); update the P2 phase row; `docs/AGENTS.md`; memo status flip.

## 10. Engineering Quality Checklist

- One critical section owns admission (read-check-append under one lock) — no check-then-act gap anywhere; every aggregate derived from the single append-only stream, none duplicated.
- Actual and Estimated never share a field, a label, or a ledger kind (memo 11); `costUsd` and `actualSpendTodayUsd` are null before they are fabricated.
- Fail-closed where money is capped and unknowable (`REQ-COST-001`); fail-open only for model *content* (T2's rule — unchanged and untouched).
- Additive everywhere users can see: 429 body, settings payloads, execution records; the only behavior change (the fail-closed gate) is named, tested, and surfaced in the UI.
- Reuses the repo's existing locking pattern and FS-tolerance idioms (`projects/storage.py` precedent) rather than inventing new ones; `QuotaExceeded` and the route layer are untouched.
- The ledger shape (reservation id = execution id; append-only kinds) is exactly what T2b's child/retry attribution and future reconciliation will consume — no rework planned into the next tranche.
