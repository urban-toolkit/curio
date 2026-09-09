# Implementation Memo: P2 Runtime Tail — Provider-Config Extraction, SSE Streaming, Basic Quota Admission

Date: 2026-07-22
Status: **implemented** (2026-07-22; `BL-P2-20260722-03/-04/-05` — commits `1cd6359`…`7a06e20`; `/llm/chat` kept un-gated per approval)
Feature slice: P2 — runtime/providers (`BL-P2` continuation; completes the P2 portion of the v1 cut, `DEC-038`)
Design sources: `ADR-AG-012`/`DEC-039` (memo `17` §3.3), `SRC-AICONN`, `docs/08` (streaming chat), `DEC-040` (FS-backed), memo `04` (`agents/` ownership boundary)

## 1. Problem Statement

Three v1 runtime items remain open after the P4 close-out:

1. **Provider-config resolution violates the `agents/` boundary.** Dispatch was extracted to `app/agents/providers.py` (`BL-P2-20260719-02`), but the *resolution* — `_resolve_llm_config()` (guest key, per-user `user.llm_*` fields, aiconn sage200 default) — still lives in `app/api/routes.py:79`, and `app/agents/routes.py::run_attachment` lazy-imports it from the main API routes. Agent/LLM behavior must be owned by `agents/` (memo `04`); `ADR-AG-012` names this extraction as the v1 step (the full `ProviderProfile` model + encrypted secret store + plaintext-column migration are the v2 remainder, already flagged in `BL-P2-…-01`).
2. **No streaming.** `run_attachment` blocks until the full reply exists; the chat shows nothing until then. The unified-chat concept assumes streaming ("the same focus, keyboard, **streaming** … behavior as every attached agent", memo `12`), and the deferred chat cards/SUGGESTED PROMPTS work is queued behind a runtime that can emit incremental content.
3. **No quota admission.** Any authenticated user can run agents without limit; the v1 cut requires "basic **quota** admission (simple counters — not reservation ledgers)". Denial must be stable and non-destructive (`REQ-QUOTA-001`'s v1 subset; the atomic reservation/ledger model is v2).

## 2. Scope

**Included**

- Backend: new `app/agents/provider_config.py` (resolution moved from `app/api/routes.py`), new `app/agents/quotas.py` (FS counters + admission), `app/agents/providers.py` (`stream_chat_completion` port), `app/agents/services.py` (`stream_attachment`), `app/agents/routes.py` (`POST …/run/stream` SSE route; admission on both run paths), `app/api/routes.py` (consume the moved resolver — legacy `/llm/*` keeps behavior via the same function), `docs/AGENTS.md`.
- Frontend: `api/agentsApi.ts` (`runAttachmentStream` over `fetch` + ReadableStream), `AgentAttachmentsProvider.tsx` (`sendMessage` streams deltas into a live agent turn; falls back to the blocking `run` when streaming fails before any delta), `AgentChatPanel` (no structural change — the last agent turn simply grows).
- Tests in §7.

**Out of scope (unchanged)**

- The v2 remainder of `ADR-AG-012`: `ProviderProfile` records, the encrypted secret store, crypto-shredding, the plaintext-column migration, additional provider profiles (`REQ-PROVIDER-002` contract suite). `user.llm_*` fields and the guest/env config remain the storage; only *where the resolution lives* changes.
- Reservation/budget ledgers, per-scope effective-policy computation, concurrency leases, retries, tool/event contracts — v2 runtime.
- The Cost/Quotas/Resource settings screens (next slice; they will *edit* the limits this memo introduces).
- Chat structured-content cards / SUGGESTED PROMPTS chips (unblocked by this memo, delivered separately).
- The legacy `/llm/chat` per-minute token check (`/llm/check`) — untouched.

## 3. Recommended Implementation Approach

**Slice 1 — provider-config resolution into `agents/` (behavior-preserving).**
Move `_resolve_llm_config` to `app/agents/provider_config.py` as `resolve_provider_config(user) -> ProviderConfig` (returning the existing dataclass instead of a 4-tuple; guest/unconfigured/user-configured branches verbatim; aiconn default via the existing `config.DEFAULT_LLM_*` seed — `DEC-039` single source). `app/agents/routes.py` drops the lazy import and calls its own module; `app/api/routes.py` imports the moved function for `/llm/chat` (the legacy bridge direction `ADR-AG-012` prescribes: legacy callers read through the agents-owned resolver). An import-boundary check (test) asserts `app/agents/` no longer imports from `app/api/`.

**Slice 2 — streaming provider port.**
`providers.stream_chat_completion(config, messages) -> Iterator[str]` yielding text deltas, implemented per backend: `openai_compatible` via `stream=True` chunks; `anthropic` via `client.messages.stream(...)` text events; `gemini` via `send_message(..., stream=True)`. The non-streaming `run_chat_completion` stays (tests, fallback, legacy chat).

**Slice 3 — SSE run route + session persistence.**
`POST /api/agents/projects/<pid>/attachments/<id>/run/stream` returns `text/event-stream` (Flask generator response). Events: repeated `event: delta` (`{"text": …}`), then `event: done` (`{"reply": full_text}`); failures emit `event: error` (`{"error": msg}`) and end the stream. `services.stream_attachment` reuses the exact message-building from `run_attachment` (intent override → instruction, bounded session context) and persists the same turn pairs after the stream finishes — full reply on success; user turn + display-only error marker on failure, exactly like `run` (dev/20 semantics). The blocking `run` endpoint is unchanged.

**Slice 4 — basic quota admission (simple counters).**
`app/agents/quotas.py`: an FS counter per account (`.curio/users/<key>/agents/quota.json`, `DEC-040`) holding `{window: "YYYY-MM-DD", runs: n}` — a fixed daily window, reset by date change on read. `check_and_count(user_key, limit)` increments and admits, or raises `QuotaExceeded` once `runs >= limit`. The limit comes from config (`CURIO_AGENT_RUNS_PER_DAY`, fail-closed interim default **200/day**, mirroring memo 17's interim-default style; final values are the settings screens' job / `OQ-008`-adjacent product tuning). Both `run` and `run/stream` call admission *before* provider dispatch; denial is a stable `429` with `{"error", "quota", "resetAt"}` — the user's message is not consumed (client keeps it renderable; nothing persists to the session on denial). Counters are advisory simple counts (racing writers may briefly over-admit by one — explicitly acceptable at v1; ledgers are v2).

**Slice 5 — frontend streaming consumption.**
`agentsApi.runAttachmentStream(projectId, attachmentId, message, onDelta) -> Promise<string>` using `fetch` + `ReadableStream` SSE parsing (POST body, so `EventSource` is unsuitable). Provider `sendMessage`: append the user turn, append an empty agent turn, grow it per delta, replace with the final reply on `done`. If the stream errors **before any delta**, fall back to the blocking `run` once; after first delta, surface the soft error turn as today. Quota `429` renders the stable denial as an error turn with the reset time. The `sending` guard, transcript cache, and reload-hydration are untouched (the server persists the same turns either way).

## 4. Data and State Handling

- **Source of truth — provider config**: unchanged storage (`user.llm_*`, guest env, aiconn defaults); resolution relocated only. No schema/data migration in this slice.
- **Source of truth — transcripts**: the session file, written once per exchange by the server after stream completion — never per-delta (no partial-turn files; a reload during a stream shows the conversation up to the previous exchange until `done` lands).
- **Quota counters**: per-account FS JSON, date-windowed; read-modify-write whole-file like the session store. Denial changes no state.
- **Streaming UI state**: the growing agent turn lives only in the provider's transcript cache during the stream; `done` reconciles it with the server-persisted text (identical by construction).
- **Races**: one in-flight send per panel (existing guard); admission-then-dispatch ordering means a denied run never reaches a provider; stream disconnects (client gone) stop provider iteration via generator close, and nothing persists for that exchange beyond the error-marker rule.

## 5. UI and UX Requirements

- Replies appear incrementally in the existing agent-row styling — no new visual language, no layout shift; the auto-scroll-to-newest behavior keeps the growing turn in view.
- The send button's busy state covers the whole stream; Escape/Close still work mid-stream (the panel unmounts; the server finishes or aborts safely).
- Quota denial reads as a soft error turn ("Daily agent-run limit reached — resets at …"), input stays usable; no red flash, no modal.
- No changes to header, dock, badges, palette, roster drawer, or the retained Explanation tab (`DEC-041`).

## 6. Edge Cases

- Provider that ignores/errs on streaming (e.g., a proxy without SSE support): the port raises on the first read → frontend falls back to blocking `run` (single retry, no duplicate user turn — the fallback reuses the same already-rendered user turn and the server persists once, from whichever path completed).
- Disconnect mid-stream (tab closed): generator cleanup stops provider iteration; the exchange persists only if `done` was reached server-side before disconnect (write happens at completion, which is reached independent of client reads — acceptable: reload shows the full exchange).
- Error after N deltas: `event: error` → partial text stays visible, error turn appended, session records user turn + error marker (not the partial), matching dev/20's context-exclusion rule.
- Date rollover mid-day-window / clock skew: window key is the server date; a stale window resets on first read.
- Corrupt/missing quota file: treated as a fresh window (fail-open for the counter file itself, fail-closed via the limit — mirrors the session store's corrupt-file posture).
- Guest users: same admission path, keyed by the guest storage key.
- `run` and `run/stream` both count once each; the fallback path therefore costs two admissions only when a stream fails pre-delta — acceptable v1 rounding, noted in the log.
- Legacy `/llm/chat` is *not* quota-gated (out of scope; it has its own token check).

## 7. Testing Strategy

Backend (`tests/test_agents/`):
- `test_provider_config.py` (new): guest with/without key, unconfigured→aiconn defaults, configured user passthrough — ported assertions from the current inline behavior; import-boundary test (`app.agents` has no `app.api` import).
- `test_providers.py`: `stream_chat_completion` chunk assembly per backend (SDKs mocked); iterator close stops consumption.
- `test_routes.py`: SSE route happy path (deltas → done, session persisted once with the full reply); provider error mid-stream → `event: error` + user turn + error marker persisted; unknown attachment 404; quota: N admitted runs then `429` with stable body on both `run` and `run/stream`, nothing persisted on denial; window reset admits again.
- `test_quotas.py` (new): count/limit/deny, date-window reset, corrupt file → fresh window, denial mutates nothing.
- Regression: full `test_agents/` suite (intent/session/compat behavior unchanged).

Frontend (`src/tests/`):
- `agentsApi` stream parser: delta/done/error framing over a mocked ReadableStream.
- Provider: deltas grow the last agent turn; `done` finalizes; pre-delta failure falls back to `run` exactly once; `429` renders the denial turn.
- Existing panel/dock/roster suites unchanged and green.

## 8. Acceptance Criteria

- [ ] `app/agents/` resolves provider config itself; `app/api/routes.py` consumes the moved resolver; no `app.agents` → `app.api` import remains; `/llm/chat` behavior is byte-for-byte preserved.
- [ ] Sending a chat message streams the reply incrementally into the transcript; the persisted session and a post-reload view show the identical final exchange.
- [ ] A provider/stream failure degrades gracefully (fallback pre-delta; soft error turn after), never losing the user's message from view.
- [ ] The N+1-th run of the day returns a stable `429` on both run paths, consumes nothing, and the UI shows the reset time; the next day admits again.
- [ ] The blocking `run` endpoint's contract is unchanged (memo 19/20 clients and tests untouched except where they gain quota coverage).
- [ ] All backend and frontend suites pass; no changes to attachment/dock/palette/drawer/header behavior.

## 9. Recommended Commit Breakdown

1. `refactor(agents): move provider-config resolution into app/agents/provider_config.py` + boundary test (behavior-preserving; legacy /llm/chat consumes it).
2. `feat(agents): streaming provider port (stream_chat_completion) with per-backend tests`.
3. `feat(agents): SSE run/stream route + session persistence parity, with route tests`.
4. `feat(agents): basic quota admission — FS daily counters + 429 on run paths, with tests`.
5. `feat(agents): stream replies into the chat (fetch/SSE client, delta-growing turn, run fallback), with tests`.
6. Build-log entries `BL-P2-2026…-03/-04/-05` (+ docs/AGENTS.md) alongside the slices per tracking rule 13.

## 10. Engineering Quality Checklist

- Resolution/dispatch/streaming/quota each live in one `agents/` module; no logic duplicated into routes.
- Behavior-preserving extraction proven by ported tests, not assertion-free refactor.
- Streaming reuses the exact run message-builder (no second prompt/context path).
- Fail-closed limit with a stable, typed denial; counters advisory by design and documented as such.
- Session/persistence semantics identical across run and stream (dev/20 invariants hold).
- No new shared surface, no secret handling changes, `DEC-041`/`DEC-042` untouched.
