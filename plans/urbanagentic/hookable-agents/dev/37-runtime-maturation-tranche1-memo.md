# Implementation Memo: P2 Runtime Maturation — Tranche 1: Execution Records, Usage Capture, Typed Event Envelope

Date: 2026-07-27
Status: implemented 2026-07-27 (`BL-P2-20260727-06`; commits `f6b2696b`, `d2fe8457`, `8d62932a`, `ab1cf29f`)
Feature slice: v2 runtime maturation, first tranche (`DEC-038`; the "point 3" program)
Design sources: `DEC-031` (per-execution reproducibility pins — the unimplemented half), memo `12`/`docs/08` ("the transcript **is** the execution/run history"), memo `11` (Estimated vs **Actual** labeling), `DEC-040` (FS-backed), `dev/20`/`dev/22` (the session + SSE substrate this extends), `RISK-COST-001` context

## 1. The Maturation Program (map, then this slice)

The v2 runtime work decomposes into ordered tranches; this memo specifies and implements **Tranche 1** only:

1. **Execution records + usage capture + typed event envelope** (this memo) — makes every run a first-class, pinned, measurable thing. No new capability for agents; pure substrate.
2. **Tool contracts + structured content** — typed tool/card events over the Tranche-1 envelope; unlocks the chat suggestion/preview/result cards, SUGGESTED PROMPTS, and review-before-apply mutations.
3. **Ledgers + pricing** — atomic reservations replacing the advisory counters, a price table, true "Actual" USD on the Cost screen (needs Tranche 1's token counts).
4. **Provider expansion** — `ProviderProfile` records + encrypted secret store + plaintext migration (`ADR-AG-012` remainder), multi-provider contract suite (`REQ-PROVIDER-002`).

**Open decision surfaced (yours, not taken here): LangChain adoption.** It remains uninstalled; the provider port makes it optional. Recommendation: keep deferring until Tranche 2's tool orchestration shows a concrete need the port can't cover cleanly — adopting it now would be a heavy dependency with no current consumer. Tranche 1 needs nothing from it.

## 2. Problem Statement (Tranche 1)

Runs are ghosts. A run today leaves only two chat turns behind: no execution identity, no record of what actually ran (which prompt bytes, which provider/model, what effective policy admitted it), and no measurement (the SDKs report token usage — openai 2.36 via `stream_options={"include_usage": true}`, anthropic 0.109 on responses and stream deltas — and we discard it). Consequences: `DEC-031`'s "pin reproducibility inputs on each execution" is unimplemented; the Cost screen can only ever say "Actual: not available"; Tranche 3's ledgers would have nothing to settle against; and the SSE protocol has no envelope for anything but text.

## 3. Scope

**Included**

- Backend: an `execution` object recorded on each exchange's agent turn (the transcript *is* the run history — no new store), token-usage capture in both provider-port functions, usage counters in the daily quota window, an additive SSE `execution` event + enriched `done`, execution/usage exposure in the settings payloads.
- Frontend: parse the new events (ignore-if-absent), show "tokens used today (actual)" on the Quotas screen and an honest upgrade to the Cost screen's Actual line ("N tokens today · USD pricing arrives with the price table").
- Tests throughout.

**Out of scope (later tranches)**: tool/card events and any structured agent content (T2); reservations/ledgers, price tables, USD "Actual" (T3); provider profiles/secret store/LangChain (T4); leases/background executions — with completion-time writes, a crashed run simply leaves no record, which is correct until background execution exists.

## 4. Design

**Execution record — on the agent turn** (extends `sessions.make_turn`, additive keys; old turns simply lack them):

```json
{"role": "agent", "text": "...", "ts": "...",
 "execution": {
   "executionId": "<uuid>",
   "pins": {"coord": "...", "promptSha256": "<manifest digest or null>",
             "intentEdited": false, "provider": "openai_compatible", "model": "gemma4",
             "policy": {"runsPerDay": 200, "maxOutputTokens": 4096,
                         "dailyBudgetUsd": null, "estimatedCostPerRunUsd": null}},
   "usage": {"inputTokens": 123, "outputTokens": 456} ,
   "durationMs": 1234, "status": "ok" }}
```

- Pins are resolved at dispatch time from what actually ran (`_prepare_run` already has coord/policy; the prompt digest comes from the resolved definition's manifest asset; no secrets ever). Error turns carry the same execution object with `"status": "error"` and whatever usage exists (usually none).
- `usage` is `null` when a provider doesn't report it — never estimated here (memo 11's labeling rule: this field is **Actual** or absent).

**Usage capture in the port**: `run_chat_completion`/`stream_chat_completion` gain an optional `usage_out: dict` sink (mutated in place; the streaming generator can't return a value to its consumer mid-protocol). openai: `stream_options={"include_usage": True}` final chunk / `completion.usage`; anthropic: `message_start`/`message_delta` usage via the stream object / `resp.usage`; gemini: `usage_metadata` when present. Missing attributes → sink stays empty.

**Daily usage counters**: the quota window file gains `"usage": {"inputTokens": n, "outputTokens": n}`, incremented post-run (advisory, like the run counters; ledgers are T3). `runs_used_today` gets a sibling `usage_today`.

**SSE envelope (additive, backward-compatible)**: `run/stream` emits `event: execution` (`{executionId}`) before the first delta, and `done` gains `{reply, executionId, usage}`. The blocking `run` response gains the same two fields. Old clients ignore unknown fields/events; the current client's parser already skips unhandled event names.

**Settings surfaces**: `get_account_settings` and the project-defaults GET gain `usageToday`; the Quotas screen shows "N runs · X in / Y out tokens today (actual)"; the Cost screen's unavailable-line upgrades to name what *is* now actual (tokens) and what still isn't (USD).

## 5. Data and State Handling

- Source of truth: the session file (execution objects ride the turns it already owns — same lifecycle, GC, share-exclusion via `strip_agent_state`/sidecar placement, and `context_messages` ignores extra keys so provider context is unaffected).
- Counters: same window file, same advisory posture, same corrupt-file-reads-fresh rules.
- No migrations: old turns/windows without the new keys read as "no data".
- Privacy: pins contain no secrets (provider type + model only); usage is numeric; nothing new crosses the share surface (the rule-9 suite already guards the spec, and sessions are sidecar).

## 6. Edge Cases

- Provider reports no usage (proxy strips it; gemini variants): `usage: null` end-to-end; counters unchanged; UI shows runs only.
- Stream disconnect mid-reply: completion-time write means no execution record for that exchange (consistent with dev/20's persistence rule).
- Stateless legacy attachment (no sessionId): run succeeds; execution record has nowhere to persist — returned in the response only.
- Prompt digest absent (manifest without sha256 — pre-upload-import built-ins are stamped, but tolerate null).
- The dev/25 auto-title call is *not* an execution (internal housekeeping): its usage still counts into the daily counters (it costs tokens) but it writes no execution record. Recorded explicitly so the counters and the transcript are allowed to disagree by the title call's small amount.
- Fallback blocking run after a failed stream: one execution record, from whichever path completed.

## 7. Testing Strategy

Backend: port tests asserting `usage_out` population per backend (mocked SDK shapes incl. the openai include_usage chunk and anthropic message_delta); route tests — run/stream persist the execution object with correct pins (coord, digest, provider/model, policy snapshot) and usage; error turns carry `status: "error"`; `execution` SSE event precedes deltas and `done` carries executionId+usage; daily usage counters accumulate and reset with the window; settings payloads expose `usageToday`; regression: context building unaffected by the new keys, title-call usage counted but recordless.
Frontend: stream-parser tolerance for the new event; provider stores executionId/usage on the finalized turn (type additions); Quotas/Cost screen rendering of actual tokens; all existing suites green.

## 8. Acceptance Criteria

- [x] Every completed run leaves an execution record on its agent turn: id, `DEC-031` pins (coord, prompt digest, provider/model, effective-policy snapshot), duration, status, and Actual token usage where the provider reports it.
- [x] The Quotas screen shows actual tokens used today; the Cost screen's "Actual" line names tokens as available and USD as pending the T3 price table — no fake numbers anywhere.
- [x] The SSE protocol carries `execution` + enriched `done` without breaking the existing client (tested both directions).
- [x] Old sessions/windows load unchanged; provider context is byte-identical to before.
- [x] LangChain remains uninstalled; no new dependencies.

## 9. Recommended Commit Breakdown

1. `feat(agents): usage capture in the provider port (usage_out sink per backend), with tests`.
2. `feat(agents): execution records on session turns — pins, duration, status — persisted by run/stream, with tests`.
3. `feat(agents): daily usage counters + settings exposure + SSE execution/done enrichment, with tests`.
4. `feat(agents): frontend — event parsing, turn types, actual-usage display on the Quotas/Cost screens, with tests`.
5. Build-log entry `BL-P2-2026…-06` + `docs/AGENTS.md`.

## 10. Engineering Quality Checklist

- Additive everywhere: turn keys, SSE events, response fields, window keys — zero migrations, old data reads clean.
- Actual-only usage (never estimated into the same field); memo 11's labeling honored on both screens.
- Pins resolved from what dispatched, in one place (`_prepare_run` neighborhood), no secrets.
- The transcript remains the single run history (memo 12) — no parallel execution store to drift.
- Counters stay advisory and documented as such; T3 replaces, not patches, them.
