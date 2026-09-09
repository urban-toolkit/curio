# Implementation Memo: Persistent Chat Sessions for Attached Agents

Date: 2026-07-21
Status: **implemented** (2026-07-21; `BL-P4-20260721-12` — commits `f96d60b`/`906ad92`/`2d3478a`)
Feature slice: P4 — attachments & chat (closes the last deferred P4 item in `3.1`)
Companion memo: `19-agent-chat-concept-alignment-memo.md` (shared surface: chat panel, provider state, `run_attachment`). The two can land in either order; integration points are called out below.
Design sources: `docs/08-unified-agent-chat.md` ("Re-opening the dock tile resumes the same session with its full transcript. The transcript **is** the execution/run history."), `DEC-040` (FS-backed persistence), `DEC-031` (attachment identity), memo `17` §3.5 / `OQ-008` (retention).

## 1. Problem Statement

Every attachment record already carries a `sessionId` (uuid, minted at attach — `attachments.attach`), but nothing uses it: `run_attachment` is stateless single-turn (system prompt + one user message), and chat history lives in component memory, so it is lost on panel close (pre-memo-19), page reload, and browser restart. The concept requires the dock tile to resume the same session with its full transcript, and defines the transcript as the run history. Memo 19 fixes close/reopen within one app session only; reload/restart still wipes history, and the agent itself never sees prior turns, so multi-turn refinement ("now explain it technically") doesn't work.

Expected behavior: each attachment's conversation persists server-side under its `sessionId`; reopening the chat (including after reload) restores the transcript; runs include bounded prior context so conversation is genuinely multi-turn; detaching or pruning an attachment disposes of its session; transcripts stay private (never in the spec, never in shared results).

## 2. Scope

**Included**

- Backend: new `app/agents/sessions.py` (session transcript store), `services.py` (`run_attachment` context + persistence, `get_session`, `clear_session`, detach/prune GC), `routes.py` (GET/DELETE session), `app/projects/services.py` (one-line GC extension where `prune_orphaned_attachments` is already wired), `docs/AGENTS.md`.
- Frontend: `agentsApi.ts` (session methods + types), `useAgentAttachments.ts`/`AgentAttachmentsProvider.tsx` (hydrate transcripts from the server; memo 19's in-memory map becomes a cache over the server session), `AgentChatPanel.tsx` (loading state for history hydration; optional "Clear conversation" affordance).
- Tests in §7.

**Out of scope (unchanged)**

- Streaming/SSE (P2 runtime item), execution leases/retry semantics, multi-instance topology (`OQ-009`).
- Cross-attachment or cross-project session sharing; sessions remain strictly per-attachment (`sessionId` 1:1).
- Final retention durations (`OQ-008`); this memo ships the fail-closed interim default (delete with the attachment).
- Attachment/dock/palette behavior, the retained Explanation tab (`DEC-041`).

## 3. Recommended Implementation Approach

**Storage — a private per-project sidecar, not the spec.** Transcripts must never ride in `spec.trill.json`: the spec feeds the share pipeline and canvas saves, and bloating it violates the privacy invariant (`docs/08`: transcript never appears in the shared result) — keeping transcripts out of the spec makes that true by construction. Store them FS-backed (`DEC-040`) next to the project:

```
.curio/users/<key>/projects/<pid>/agent-sessions/<sessionId>.json
{ "sessionId": ..., "attachmentId": ..., "turns": [ {"role": "user"|"agent", "text": ..., "ts": ...}, ... ] }
```

1. `sessions.py` (pure-ish, mirrors `storage.py` style): `read_session`, `append_turns`, `delete_session`, `sessions_dir` — path built via the existing `safe_join` helpers; missing file → empty turns; writes are whole-file JSON like `write_spec`.
2. `run_attachment` becomes session-aware:
   - Load the record's session turns; build messages = system (intent override else resolved instruction — memo 19; plain `_resolve_instruction_text` if 19 hasn't landed) + the last **N turns (interim N=20)** mapped to `user`/`assistant` roles + the new user message. The window bound is a cost/context guard; N is a module constant, flagged for tuning.
   - On success, append `{user, agent}` turns and persist. On provider error, persist the user turn plus an `{"role": "agent", "text": "(error) …", "error": true}` marker so history matches what the user saw; the error turn is **excluded** from future context windows.
3. API:
   - `GET /api/agents/projects/<pid>/attachments/<attachment_id>/session` → `{sessionId, turns}` (404 unknown attachment).
   - `DELETE …/session` → clears turns (keeps the session file/id) — powers "Clear conversation".
   - `run` response unchanged (`reply`), so memo-19 frontend code composes without a contract break.
4. GC: `detach_agent` deletes the record's session file; in `projects/services.update_project`, the records returned by `prune_orphaned_attachments` (already wired, already returns removed records) get their session files deleted in the same pass. The original fail-closed rule—a transcript lives exactly as long as its attachment—is now part of the `DEC-057` lifecycle-bound deletion model; OQ-008 is closed.

**Frontend — server as source of truth, provider as cache.**

5. `agentsApi.ts`: `AgentSessionTurn { role, text, error? }`, `getSession(projectId, attachmentId)`, `clearSession(projectId, attachmentId)`.
6. Provider: on first `openChat(attachmentId)` (or when the cached copy is absent), fetch the session and seed the transcript map; subsequent opens use the cache; each successful `run` appends locally (server already persisted). Project switch/detach drops cache entries as today. This subsumes memo 19's "in-memory lift" — same map, now hydrated.
7. `AgentChatPanel`: a muted "Loading conversation…" line during hydration; existing empty-state when the session has no turns; optional header overflow action "Clear conversation" → `clearSession` + cache reset (confirm-first, since it's destructive to history but not to the attachment).

## 4. Data and State Handling

- **Source of truth**: the session file. The provider map is a read-through cache keyed by `attachmentId`; it is never the only copy after this memo.
- **Consistency**: run persists server-side before the reply returns, so a reload immediately after a send shows the full exchange. Hydration overwrites the cache entry wholesale (no merge logic).
- **Races**: two panels for the same attachment can't occur (single `selectedId`); concurrent runs are blocked by the existing `sending` guard. Whole-file writes are last-writer-wins within one attachment's serial sends — acceptable at this stage; no cross-attachment contention (one file per session).
- **Loading/empty/error**: hydration failure shows a soft-tone inline error with retry, and the input stays usable (a send still works — the server has the authoritative history).
- **Privacy**: transcripts live outside the spec; the share regression guard (tracking rule 9) gains an assertion that `agent-sessions/` content never appears in a shared result payload.

## 5. UI and UX Requirements

- Reopening a dock tile/badge resumes the conversation with full history (after reload too) — matching `docs/08` sessions semantics; the transcript renders identically to live turns (memo 19 styling).
- Hydration is visually quiet: no layout jump; loading line replaced by turns.
- "Clear conversation" (if included in this slice) is keyboard-accessible, confirm-first, and clearly distinct from Close and Detach.
- No changes to dock, badges, palette, attach/detach affordances.

## 6. Edge Cases

- Attachment with a legacy record predating sessions-on-disk: GET returns empty turns (missing file ≡ empty) — no migration needed.
- Corrupt/unreadable session JSON: treat as empty, log server-side; next run rewrites it.
- Very long histories: context window bounds provider input (N=20 turns); the full transcript still renders (existing scroll).
- Error turns: persisted for display, excluded from provider context; retry after an error just sends the next message.
- Detach → re-attach the same agent: new `attachmentId`/`sessionId`, fresh empty session (old file deleted on detach) — matches `DEC-031` (the attachment, not the agent, is the session identity).
- Node deleted on canvas → attachment pruned on save → session file GC'd in the same update; the dock refresh (existing) drops the tile.
- Project switch mid-hydration: stale fetch resolves into a cleared cache — guard with the current projectId before seeding.
- `DELETE session` racing a `run`: whole-file semantics make either order consistent; the panel reconciles on next hydration.

## 7. Testing Strategy

Backend (`tests/test_agents/`):
- `test_sessions.py` (new): read missing → empty; append/read round-trip; delete; corrupt file → empty; path safety (session id never escapes the project dir — reuse the `safe_join` behavior).
- `test_routes.py`: run twice → GET session returns 4 turns in order; second run's provider call includes the first exchange in messages (mock asserts context window); error run persists user + error turn and excludes the error turn from the next context; GET/DELETE session 404 on unknown attachment; DELETE clears; detach removes the file; prune-on-save removes the orphaned attachment's file (extends `TestPruneAttachmentsOnDelete`).
- Share regression: shared-result payload contains no `agent-sessions` content (rule 9 evidence).

Frontend (`src/tests/`):
- `api/agentsApi.test.ts`: `getSession`/`clearSession`.
- provider test: open → hydrates from `getSession`; reopen uses cache (single fetch); detach clears cache; simulated reload (fresh provider) re-hydrates.
- `AgentChatPanel`: hydration loading line; restored turns render; clear-conversation flow (if shipped).
- Regression: dock/badges/palette/drawer suites unchanged.

## 8. Acceptance Criteria

- [ ] Sending messages, closing the chat, reloading the page, and reopening the same attachment shows the full prior conversation.
- [ ] The agent receives bounded prior context: a follow-up message is answered with awareness of earlier turns (verified via the mocked provider's message list).
- [ ] Detaching an agent (or its node being deleted + saved) removes its transcript from disk; re-attaching starts clean.
- [ ] Transcripts never appear in the project spec or any shared-result payload.
- [ ] `run`'s response contract is unchanged; memo-19 UI needs no rework to adopt this.
- [ ] All existing agent suites pass; attachment/dock/palette behavior is unchanged.

## 9. Recommended Commit Breakdown

1. `feat(agents): FS session store (sessions.py) with unit tests`.
2. `feat(agents): session-aware run — bounded context + persisted turns, with route tests`.
3. `feat(agents): GET/DELETE attachment session routes + detach/prune GC + docs/AGENTS.md, with tests`.
4. `feat(agents): hydrate chat transcripts from the server session in the attachments provider/panel, with tests`.
5. Build-log entry `BL-P4-…` in the same commit as 4 (tracking rule 13).

## 10. Engineering Quality Checklist

- Session I/O centralized in `sessions.py`; no transcript logic in routes or components.
- Spec stays transcript-free (privacy by construction; share guard tested).
- Explicit types for turns end-to-end; error turns modeled, not stringly inferred.
- Race-safe within the feature's actual concurrency (single panel, serial sends); no new global state.
- Fail-closed interim retention (delete-with-attachment) recorded against `OQ-008`.
- Composes with memo 19 without contract changes; neither blocks the other.
- No unrelated node/agent functionality modified.
