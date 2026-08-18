# dev/80 — Agent chat run-status feedback: live processing indicator + session token counter

Status: IMPLEMENTED (2026-08-18 — delivered as unstaged edits; see build-log
BL-P5-20260818-25 for verification evidence and the deviations note: no
`followUp` field on runStatus — the review chip derives from the attachment's
proposal mirrors; send-busy prop semantics undefined=unwired / null=wired-idle;
status finalize ordered before the turn landing as defense-in-depth; the
blocking /run response also gained durationMs)

AMENDED same day (owner feedback; BL-P5-20260818-26): the execution status —
running with elapsed, finished with duration, failed — is PER AGENT REPLY, a
quiet meta line under each message bubble (the streaming reply carries the
live indicator; a standalone pending row covers the pre-first-delta window;
every finalized reply keeps its own duration + that run's tokens, hover for
the in/out breakdown). Token usage shows BOTH per message (in the reply's
meta line) and accumulated (the strip by the composer now carries only the
session total, right-aligned). `deriveRunStatusDisplay` was replaced by the
per-turn `turnStatusDisplay`; the review chip marks only the newest reply.

## 1. Problem Statement

While an attached agent (or a delegated agent — dev/72 reuses the same panel)
is processing a send, the only feedback surfaces are:

- the send button's glyph swap (`…` while `sending` — kept, per request), and
- the transient dev/41 `toolActivity` system lines, which appear only when the
  run happens to call tools and are cleared in `sendMessage`'s `finally`.

Consequences today:

- **The final assistant message appears with no execution status.** When the
  stream finalizes, `toolActivity` is wiped and the reply just sits there —
  nothing says "this run finished", how long it took, or whether an action
  (a pending review proposal) still awaits the user.
- **No ongoing-work indicator between deltas.** Long tool loops and the
  blocking-run fallback (no SSE) show *nothing* in the transcript for many
  seconds; users cannot tell "still working" from "hung".
- **No elapsed time, no token feedback.** The backend already persists
  provider-reported usage and `durationMs` on every turn's `execution` record
  (memo dev/37), but the transcript never shows any of it; usage is visible
  only in the settings modal.
- **Bug: the panel's local `sending` flag leaks across attachments.**
  `AgentDockOverlay` renders one un-keyed `AgentChatPanel` for whichever
  attachment is selected; cycling ‹ › mid-run carries `sending=true` into
  another agent's chat and disables *its* send button.

Affected surfaces: `AgentChatPanel` (every agent + delegated-agent chat,
opened from the dock, node badges, or delegation entries),
`AgentAttachmentsProvider.sendMessage`, `agentsApi.runAttachmentStream`, and
the backend run-stream envelope in `backend/app/agents/services.py`.

Expected behavior (Claude/Cursor-style):

- While a run is in flight: a **compact live status on the left** — minimal
  animation + a lightweight rotating label ("Cooking", "Baking", …) + elapsed
  time — and a **cumulative session token counter on the right, near the
  input**, both updating continuously.
- When the run completes: the status finalizes to a clear "finished" state
  with duration and this-run tokens, plus a follow-up marker when a review
  proposal awaits. The final assistant message is **never** visible without an
  accompanying execution status.
- The existing send-button loading animation stays exactly as is.

## 2. Scope

In scope:

- `AgentAttachmentsProvider` — new per-attachment run-status state (the source
  of truth), populated by `sendMessage` (stream path, blocking fallback, and
  error path).
- `AgentChatPanel` — a slim status strip between the suggested-prompts row and
  the composer footer: left = live/finished run status, right = session token
  counter. Send-button disable derived per attachment (leak fix); glyph
  behavior unchanged.
- New shared pieces under `components/agents/attach/`:
  `useRunTicker` (elapsed + rotating-label index off one interval),
  `AgentRunStatusLine`, `AgentSessionTokenCounter`, and a
  `sessionTokenTotals`/`formatTokenCount` utility.
- `agentsApi.runAttachmentStream` — parse a new additive `usage` SSE event and
  the `durationMs` field on `done`.
- Backend `services.py` run stream — emit interim `usage` events per provider
  loop round; add `durationMs` to the `done` payload (both additive; the
  record itself already carries them).
- Tests: `AgentChatPanel.test.tsx`, a provider-level run-status test, unit
  tests for the new hook/utilities.

Out of scope (unchanged):

- `LLMChat.tsx` (the legacy assistant chat — follow-up, same as dev/77 scoped
  it for the composer).
- The dev/52/63 Solve strip and its `solveProgress` overlay; the dev/67-9
  simulation narration — they have their own progress systems.
- The settings modal's usage display, cost/policy plumbing, and the persisted
  execution-record shape (dev/37) — read, not modified.
- The send button's visual (`…` glyph) and the transcript's `toolActivity`
  system lines (they remain, complementing the status line).
- The dev/75/79 auto-scroll hook (the strip lives *outside* the scroller —
  see §4 — so the hook needs no change).

## 3. Recommended Implementation Approach

**Source of truth in the provider, presentation in the panel** — the same
split every prior chat feature used (transcripts dev/20, toolActivity dev/41).

1. **`AgentRunStatus` map in `AgentAttachmentsProvider`.**
   `runStatus: Record<attachmentId, AgentRunStatus>` where

   ```
   AgentRunStatus = {
     phase: "running" | "done" | "error";
     startedAt: number;            // epoch ms at send
     durationMs?: number;          // done payload when present, else client-measured
     usage?: AgentUsage | null;    // this run's final Actual usage
     liveUsage?: AgentUsage | null;// interim provider-reported sums (usage events)
     followUp?: "review" | null;   // a proposal awaits the user (sawProposal)
   }
   ```

   `sendMessage` sets `phase: "running"` when it appends the user turn, feeds
   `liveUsage` from the new `usage` events, and finalizes to `done`/`error`.
   **Ordering guarantee (the "never without status" requirement):** the
   finalize `setRunStatus` call is made in the same synchronous block as the
   final `replaceLastAgentTurn`/`appendTurns`/`appendErrorTurn` call, so React
   batches them into one commit — there is no frame where the final text is
   visible with the status still "running", nor one with text and no status.
   Provider-owned state also survives close/reopen and cycling mid-run, and
   keys every indicator per attachment (concurrent runs on different agents
   stay independent).

2. **`useRunTicker(startedAt | null)`** — one 1 s `setInterval` while running:
   returns `elapsedLabel` (`0:07`, `1:23`) and `labelIndex`. The rotating word
   comes from a module constant `PROCESSING_LABELS = ["Cooking", "Baking",
   "Simmering", "Brewing", "Whisking", "Plating"]` with
   `index = floor(elapsedSec / 5) % length` — deterministic, no `Math.random`.
   Under `prefers-reduced-motion` the label pins to the first entry and the
   dot animation is disabled via the CSS media query (same convention as
   `TranscriptJumpButton`). Interval torn down when `startedAt` is null.

3. **`AgentRunStatusLine`** (left slot) renders one of:
   - *running*: pulsing dot + `Cooking… · 0:12` (label aria-hidden; the live
     region announces a static "Agent is working" once, not each rotation);
   - *done*: `✓ Finished in 12s · 1,432 tokens`, plus an `Awaiting your
     review` chip when `followUp === "review"`;
   - *error*: `✕ Failed after 8s` (the error turn itself keeps the message).
   When there is **no live `runStatus`** (reopened/rehydrated chat), the same
   component derives a *done/error* state from the **last agent turn's
   persisted `execution` record** (`status`, `durationMs`, `usage`) — so even
   a reloaded transcript never ends in a bare final message. New chats with
   no turns render nothing.

4. **`AgentSessionTokenCounter`** (right slot, beside the composer):
   cumulative conversation usage = sum of `turns[].execution.usage`
   (dev/37 Actual counts — **never an estimate**, per dev/11/37) plus the
   in-flight run's `liveUsage`. Display the total compactly
   (`4.6k tokens`) with a `title`/aria-label breaking out `in / out`. Turns
   without an execution record (pre-dev/37, error markers) contribute
   nothing; a session with zero recorded usage renders nothing rather than a
   fabricated `0`. Formatting lives in a shared `formatTokenCount` utility.

5. **Panel wiring.** A `statusStrip` row sits between the suggested-prompts
   row and `.footer` — *outside* the scroller, so it cannot scroll away, adds
   no transcript content churn for the dev/75 hook, and matches the
   Claude/Cursor "status above the composer" pattern. It renders whenever a
   status or a token total exists (hidden for pristine chats). The send
   button's `disabled` gains `runStatus[attachment.attachmentId]?.phase ===
   "running"` (fixing the cross-attachment leak); its `…` glyph and the local
   `sending` guard stay untouched.

6. **Transport (additive, tolerant).** Backend run stream: after each
   provider loop round, `yield ("usage", {"usage": <running totals>})`; add
   `"durationMs"` to the `done` payload (the `_execution_record` already
   computes it). `runAttachmentStream` handles `usage` (new `onUsage`
   observer or via the existing `onEvent`) and reads `done.durationMs`. Old
   servers: no `usage` events and no `durationMs` → the counter simply
   updates only at finalize and duration falls back to client-measured
   `Date.now() - startedAt`. Old clients skip unknown events by design.

Styling: new classes in `AgentChatPanel.module.css` (or a small
`AgentRunStatusLine.module.css`), 11–12 px muted type matching `.systemLine`
and `.sessionChip`, category tint only on the dot — subtle, no layout shift
between running/done (fixed strip height).

## 4. Data and State Handling

- **Truth:** persisted turns' `execution` records (server) for history;
  `runStatus` (provider) for the live run. The strip *derives* — it never
  stores its own copy. Elapsed time derives from `startedAt` each tick, so a
  panel close/reopen or attachment cycle resumes the correct elapsed value.
- **Token totals** are computed with `useMemo` over `turns` +
  `runStatus.liveUsage`; no duplicated running counter that could drift from
  the transcript.
- **Finalize replaces, never accumulates:** on `done`, `liveUsage` is dropped
  and the run's final `usage` lands on the turn's execution record (as today,
  now with `durationMs`) — the counter's source switches from live to
  persisted in the same commit, so no double-count and no dip.
- **Loading/empty/error:** hydrating history → strip hidden until `ready`;
  empty session → hidden; run error → error status + existing error turn;
  history-error banner unchanged.
- **Clear conversation** deletes the attachment's `runStatus` entry alongside
  the transcript (counter and status vanish together).
- **Fallback blocking run:** status stays `running` (elapsed still ticking,
  no interim usage) and finalizes from the blocking response — the indicator
  works even with SSE unavailable.
- **No stale/flicker:** state keyed by `attachmentId`; the strip's running →
  done transition happens in the single batched commit described in §3.1.

## 5. UI and UX Requirements

- Strip layout: left `AgentRunStatusLine`, spacer, right
  `AgentSessionTokenCounter`; one line, fixed height, no wrap (ellipsis).
- Running: `● Cooking… · 0:12` — dot pulses gently (CSS keyframes, disabled
  under `prefers-reduced-motion`); label rotates every 5 s from the constant
  list; elapsed updates every second.
- Done: `✓ Finished in 12s · 1,432 tokens`; with a pending proposal:
  `✓ Finished in 12s · Awaiting your review`. Error: `✕ Failed after 8s`.
- Counter: `4.6k tokens` (`title`: "1,204 in / 3,412 out — provider-reported").
- Visual identity: existing muted palette (`.systemLine` gray), category tint
  on the dot only, no new colors; nothing bold or animated enough to compete
  with the transcript.
- Send button: unchanged (`…` while in flight); additionally disabled while
  *this attachment's* run is in flight.
- Accessibility: the status line is `role="status"` `aria-live="polite"`
  announcing phase transitions only ("Agent is working" / "Finished in 12
  seconds" / "Run failed"); rotating label and elapsed are `aria-hidden`; the
  counter carries a descriptive `aria-label`; all text meets contrast on the
  panel background.

## 6. Edge Cases

- Turns with no `execution` (pre-dev/37 history, error markers) — skipped in
  sums; derived status falls back gracefully (an error turn without execution
  still derives *error* from `turn.error`).
- `usage: null` from the provider — done status shows duration only; counter
  unchanged (never a fabricated 0).
- Old server: no `usage` events / no `done.durationMs` → live counter updates
  at finalize; duration client-measured.
- Cycling attachments mid-run; opening a delegated agent's chat while the
  parent runs — each attachment shows only its own status/counter.
- Two sends racing on one attachment — already prevented by the send guard;
  the disable now also holds across cycling (the fixed leak).
- Mid-stream failure with partial text — partial text stays (existing), strip
  shows *error* with elapsed-at-failure.
- Clear conversation during/after a run; attachment detached mid-run
  (status entry pruned with the attachment list).
- Long runs (elapsed > 1 h → `61:05` minutes format is fine); rapid re-sends
  (new run overwrites the previous status atomically).
- `prefers-reduced-motion`; timer cleanup on unmount (no interval leak).
- Unknown future SSE events — still skipped (existing tolerance preserved).

## 7. Testing Strategy

- **Unit — `useRunTicker`** (fake timers): elapsed formatting, 5 s label
  rotation, deterministic index, reduced-motion pin, interval teardown.
- **Unit — token utilities:** summation over mixed turns (missing execution,
  `usage: null`, normal), live-usage merge, `formatTokenCount` boundaries
  (999 → `999`, 1000 → `1.0k`).
- **Provider integration** (mocked `agentsApi`): runStatus lifecycle for
  stream success / blocking fallback / pre-delta error / mid-stream error;
  `usage` events land in `liveUsage`; `followUp: "review"` from
  `review_required` or a proposal part; clearConversation prunes the entry;
  **regression:** the render commit that first contains the final reply text
  already has `phase: "done"` (assert via a probe component — the
  never-bare-final-message guarantee).
- **Component — `AgentChatPanel.test.tsx`:** running strip (label + elapsed +
  counter) while a send is pending; done strip with duration/tokens; error
  strip; review chip; derived done status on a rehydrated transcript whose
  last turn carries an execution record; strip hidden for a pristine chat;
  send button `…` behavior unchanged and re-enabled after finalize; cycling
  to another attachment mid-run shows *that* attachment's idle strip and an
  enabled send button (leak regression).
- **agentsApi unit:** `usage` event parsing; `done.durationMs` surfaced;
  unknown events still tolerated.
- **Backend** (`tests` for the run stream): interim `usage` events emitted per
  loop round with running sums; `done` carries `durationMs`; envelope
  backward-compatible.

## 8. Acceptance Criteria

1. During any send from any agent or delegated-agent chat, the strip's left
   side shows a pulsing dot, a rotating label from the fixed list, and a
   per-second elapsed time; the right side shows the session's cumulative
   provider-reported tokens, updating as interim `usage` events arrive.
2. The moment the final assistant message is visible, the strip already shows
   the finished (or failed) state — at no point does the final message render
   beside a "running" status or an empty strip.
3. The finished state shows duration and this-run tokens; when the run minted
   a review proposal, an "Awaiting your review" marker appears.
4. Reopening a chat (or reloading the page) whose last turn carries an
   execution record still shows the finished status and the session token
   total — never a bare final message.
5. Failed runs show a failed status with elapsed-at-failure; the existing
   error turn is unchanged.
6. The send button keeps its exact current loading glyph and behavior, and is
   disabled only while *its own* attachment's run is in flight (cycling
   agents mid-run no longer disables another chat's button).
7. Token figures are provider-reported Actuals only — no estimates, no
   fabricated zeros; sessions without usage records show no counter.
8. All indicator behavior is identical across dock-opened, node-badge-opened,
   and delegation-opened chats (single shared panel).
9. Reduced-motion users get a static dot and pinned label; screen readers
   hear phase transitions only.
10. Existing tests (auto-scroll, copy button, composer) still pass; old
    servers/clients interoperate (additive envelope only).

## 9. Recommended Commit Breakdown

1. **Provider run-status state** — `AgentRunStatus` map + `sendMessage`
   transitions (all three paths), clear/detach pruning, provider tests incl.
   the same-commit finalize regression.
2. **Shared primitives** — `useRunTicker`, token sum/format utilities, unit
   tests.
3. **Panel UI** — `AgentRunStatusLine` + `AgentSessionTokenCounter` + status
   strip + CSS + send-button disable fix, `AgentChatPanel.test.tsx` coverage.
4. **Transport** — backend interim `usage` events + `done.durationMs`;
   `runAttachmentStream` parsing; backend + api tests.
5. **Docs** — this memo marked implemented + build-log entry.

## 10. Engineering Quality Checklist

- No duplicated logic: one ticker hook, one token formatter, one status
  component reused for live and derived states; provider remains the single
  writer of run state.
- Types explicit (`AgentRunStatus`, extended `done` payload) and additive.
- Timer state isolated in the hook; per-second re-renders confined to the
  strip (the transcript subtree does not re-render on tick).
- Race-safe: batched finalize commit; per-attachment keying; guard against a
  stale run's late events overwriting a newer run's status.
- Loading/empty/error/success all defined (§4); no flicker or layout shift
  (fixed strip height).
- Accessibility per §5; reduced-motion respected.
- Follows existing conventions: CSS modules, memo-numbered comments,
  provider/panel split, dev/37 never-estimate rule, SSE unknown-event
  tolerance.
