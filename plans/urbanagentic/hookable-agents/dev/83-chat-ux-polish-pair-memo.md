# Dev/83 — Chat-UX polish pair: Solve-strip status unity + unread count on the Jump pill

Status: implemented (2026-08-18, commits `21f54ed2` primitives / `5c0c6f82` strip
adoption / `656c9ea7` badge wiring; build-log entry BL-P5-20260818-29). Implementation
notes: no deviations from §3; the one test-authoring wrinkle was the panel suite's
jump-then-redetach flow needing the jump's landing scroll event emulated explicitly
(the suppress-flag handshake from dev/75/79 — same pattern the hook suite already used).

Implements the two recorded chat-UX polish follow-ups as one change set:

- **A (dev/80 follow-up):** the Dataflow Builder strip's batch progress adopts
  `AgentRunStatusLine` for visual unity with the per-reply run status.
- **B (dev/75 follow-up):** the Jump-to-latest pill carries an unread count of messages
  that arrived while the user was scrolled away.

Both live entirely under `components/agents/attach/` (the dev/76 encapsulation rule);
`LLMChat` stays untouched per the dev/76 owner directive.

---

## 1. Problem Statement

### A. The Solve strip signals a running batch with a bare text note

While a Solve batch (or a dev/67-9 simulation drive) runs, `AgentBuilderStrip` renders a
static `"solving…"` span (`AgentBuilderStrip.tsx:185-187`, `.solvingNote`) plus busy
button labels ("Solving…", "Building…"). Two lines below, every agent *reply* in the same
panel shows the dev/80 status language: pulsing tinted dot, deterministic label, live
tabular elapsed (`AgentRunStatusLine`). The strip is the one running-work surface in the
chat that doesn't speak it — no elapsed time, no motion, no progress fraction, visibly
inconsistent with the panel it sits in. The per-node rows (`:203-214`) list statuses but
give no glanceable "how far along is this batch" summary.

### B. The Jump pill says "Latest" no matter how much arrived

While detached (scrolled up), streamed replies accumulate below the viewport and the
pill (`TranscriptJumpButton.tsx`) renders a constant chevron + "Latest"
(`AgentChatPanel.tsx:751-754`). The user cannot tell whether one message or ten landed —
in long-running builder sessions (delegated researcher/builder chats, dev/72) that is
the difference between "keep reading" and "go catch up now". Recorded as a dev/75
follow-up ("consider an unread-count badge on the pill").

### Expected behavior

- A running Solve/simulation batch shows the shared status line — dot, fixed batch label
  ("Solving" / "Building" / "Stepping"), live elapsed, and a `done/total nodes` detail —
  in place of the `"solving…"` note. Terminal states keep their existing surfaces (phase
  chips, per-node rows, notice/error hints); this is a running-state adoption only.
- While detached with N ≥ 1 turns newly landed, the pill reads "N new" (aria: "Jump to
  N new messages"); with nothing new it keeps reading "Latest". Any re-pin (bottom
  return, jump, send, chat switch) resets the count.

### Why it matters

One status language across every running-work surface in the chat (the dev/80 goal, and
the Solve strip was its explicitly recorded remainder); the unread count turns the pill
from a scroll control into an actual notification affordance. Both are small,
self-contained, and touch only agents-owned code.

---

## 2. Scope

### In scope

- `components/agents/attach/AgentRunStatusLine.tsx` — three additive optional props for
  the running variant (fixed label, detail suffix, screen-reader label).
- `components/agents/attach/AgentBuilderStrip.tsx` + `.module.css` — running-batch
  adoption; `.solvingNote` removed.
- `components/agents/attach/useTranscriptAutoScroll.ts` — optional `itemCount` input,
  `unreadCount` output.
- `components/agents/attach/TranscriptJumpButton.tsx` + `.module.css` — optional
  `count` prop.
- `components/agents/attach/AgentChatPanel.tsx` — passes `itemCount={turns.length}` and
  `count={unreadCount}` (two wiring lines).
- Test suites: `tests/attach/{AgentRunStatusLine via agentRunStatus/AgentChatPanel,
  AgentBuilderStrip, useTranscriptAutoScroll, AgentChatPanel}`.

### Out of scope (intentionally)

- `LLMChat` (dev/76 directive: untouched by agents work) and any promotion of these
  pieces out of `agents/attach/` — that is the separate LLMChat-parity decision.
- Done/error rendering in the strip: the phase chips, per-node rows, `notice`/`error`
  hints, and `simulationActivity` narration line all stay exactly as they are. The
  strip adopts only the *running* variant; "Finished" semantics belong to the per-reply
  meta lines (dev/80 amendment) and are not duplicated onto the strip.
- The dev/80 provider `runStatus` map — a Solve batch is not an agent reply; the strip's
  indicator is strip-local (see §4) and never writes into the per-attachment run state.
- The pill's positioning/behavior contract (dev/75/79) — only its label changes.

---

## 3. Recommended Implementation Approach

### A. Solve strip → `AgentRunStatusLine`

- **Additive props, defaults preserve dev/80 byte-identically**
  (`AgentRunStatusLine.tsx`):
  - `runningLabel?: string` — a fixed label replacing the rotating
    `PROCESSING_LABELS` ("Cooking/Baking…" is reply-flavored; a batch says what it is).
    When absent, rotation stays (chat surfaces unchanged).
  - `runningDetail?: string` — suffix appended inside the existing aria-hidden ticking
    span: `Solving… · 0:42 · 3/7 nodes`.
  - `srLabel?: string` — the visually-hidden live-region text (default "Agent is
    working"); the strip passes "Solve batch running". Announcement semantics unchanged:
    phase transitions announce once, the ticking span stays `aria-hidden`.
- **One `activeBatch` derivation in the strip** replacing the `solvingNote` condition:
  `solving || phase === "solving"` → label "Solving"; `simBusy === "auto"` → "Building";
  `simBusy === "step"` → "Stepping". Detail from the existing `entries` overlay
  (`AgentBuilderStrip.tsx:77`): `done/total nodes`, where done counts statuses in
  `{solved, failed, skipped}` (the terminal set of the
  `nodeRuns` vocabulary, `agentsApi.ts:105`). Simulation drives render without the
  fraction when `entries` is empty.
- **`startedAt` is strip-local observation time.** Capture `Date.now()` in an effect when
  `activeBatch` flips on, clear when it flips off. `builderSession` persists no batch
  start timestamp, so a panel reopened mid-run shows elapsed since this panel observed
  the batch — honest and unlabeled-as-total (same posture as dev/80's client-measured
  fallback). No fabricated server timing.
- Reuse, not duplication: elapsed/rotation stay in `useRunTicker`; the strip imports the
  component, not the primitives. The `.solvingNote` class is deleted with its usage.

### B. Unread count on the pill

- **`useTranscriptAutoScroll` owns the count** — it already owns the pinned/detached
  transitions the count is defined by:
  - New optional input `itemCount?: number` (the panel passes `turns.length`; a ref
    mirrors it so event handlers see the current value without re-subscribing).
  - `setPinned(false)` on a pinned→detached transition records `countAtDetach`;
    `unreadCount` is the pure render-time derivation
    `atBottom || itemCount == null ? 0 : max(0, itemCount - countAtDetach)` — no new
    effects, no extra renders (the panel already re-renders per turn change), and the
    per-chunk streaming path is untouched because chunk growth replaces the last turn
    without changing the count.
  - Every existing re-pin path resets for free (bottom return, `jumpToLatest`,
    `pinToLatest` on send, `resetKey` switch, hydration `ready`) because the derivation
    keys off `atBottom`.
  - Counting all turns, not only agent turns: while detached the user's own send calls
    `pinToLatest` (`AgentChatPanel.tsx:337`), so user turns cannot accumulate unseen in
    practice; role-filtering would buy nothing and cost a props contract (the hook
    stays ignorant of turn shapes — it takes a number).
- **Pill** (`TranscriptJumpButton.tsx`): optional `count?: number`. Label "Latest" when
  falsy, `"{n} new"` when n ≥ 1 (display cap "99+"); `aria-label` becomes
  "Jump to N new messages". Same absolute overlay, same focus-fallback behavior; a
  width change from the label swap is inside the floating pill and shifts no layout.
- **Panel wiring**: `itemCount: turns.length` into the hook, `count={unreadCount}` into
  the pill. Delegated-agent chats get both for free (dev/72 — same panel).

---

## 4. Data and State Handling

| Data | Source of truth | Consumers |
| --- | --- | --- |
| Batch running/label | `AgentBuilderStrip` locals (`solving`, `simBusy`) + server `builderSession.phase` | the strip's status line |
| Batch progress fraction | existing `entries` = persisted `nodeRuns` ⊕ live `solveProgress` overlay (dev/63) | detail suffix + per-node rows (unchanged) |
| Batch `startedAt` | strip-local observation effect | `useRunTicker` via the line |
| `countAtDetach` / `unreadCount` | `useTranscriptAutoScroll` internals | pill label |

- No new provider state, no persistence, no backend involvement anywhere in this change.
- The strip's indicator ends exactly when the batch condition ends (terminal refetch
  flips `phase` / clears `solveProgress` — the same signal that stops today's note).
- Loading/empty/error: pristine strip (no batch) renders no line; an errored batch keeps
  the existing `error` hint (the line simply stops); the pill with `count` undefined is
  byte-identical to today, so any future consumer that doesn't pass it regresses nothing.
- Race safety: the ticker is the existing 1 s interval (one per running line — the strip
  line and a streaming reply's line may tick concurrently, same cost as two replies);
  the unread derivation is pure and cannot race the eager-detach path (dev/79) because
  it reads the same `atBottom` state the pill's visibility already reads.

---

## 5. UI and UX Requirements

- Strip running line matches the reply meta lines exactly: same dot, same tabular
  elapsed, same type ramp (`AgentRunStatusLine.module.css` — no new styles beyond
  deleting `.solvingNote`); placed where the note sat today (inside the `.phases` row).
- `prefers-reduced-motion`: dot animation already disabled by the component's media
  query; a fixed `runningLabel` never rotates by construction.
- Pill: "Latest" ↔ "3 new" swap only; chevron, position, dark `--curio-top-bar-bg`
  token, appear/disappear behavior all unchanged; no layout shift (absolute overlay).
- Accessibility: the strip line announces "Solve batch running" once (polite), elapsed
  and fraction stay `aria-hidden`; the pill's accessible name carries the count; the
  per-node list keeps its `aria-live="polite"` label. No focus behavior changes.
- No flicker: the line mounts/unmounts with the batch exactly as the note does today;
  the count updates only when a whole turn lands, never per streamed chunk.

---

## 6. Edge Cases

1. **Panel reopened mid-solve**: elapsed restarts from observation (documented; no
   fabricated total) — the fraction is still exact from `nodeRuns`.
2. **Solve cancelled** (`onCancelSolve`): `solving` clears on the settle → line
   disappears; the existing cancelled `notice` hint renders as today.
3. **Retry-failed batch**: `entries` still spans all nodes → fraction counts prior
   `solved` as done; acceptable and truthful ("5/7" while retrying the 2 failed).
4. **Simulation step/auto with no plan nodes yet**: `entries` empty → line without
   fraction.
5. **Detach with zero new turns**: pill shows "Latest" (count 0) — never "0 new".
6. **Streaming while detached**: the pending reply becomes a turn at its first delta →
   +1 once; subsequent chunks don't increment (count-, not content-based). The dev/80
   standalone pending row is not a turn and never counts.
7. **User sends while detached**: `pinToLatest` re-pins → count resets — their own
   message is never "unread".
8. **Attachment switch / clear conversation while detached**: `resetKey` force-pins →
   count resets; a shrunken turns array can't go negative (`max(0, …)`).
9. **Very long detach**: display caps at "99+"; the aria-label uses the real number.
10. **jsdom**: ticker and pill already test under fake timers; the observation effect
    uses `Date.now()` (mockable) — no new environment constraints.

---

## 7. Testing Strategy

Frontend only (`npx jest` via the curio-feat conda env; baseline 864/78 suites):

- **`agentRunStatus`/line rendering** (extend `tests/attach/AgentChatPanel.test.tsx`'s
  line assertions or add a small `AgentRunStatusLine` suite): `runningLabel` replaces
  rotation; `runningDetail` renders after the elapsed; `srLabel` replaces the hidden
  text; **regression: with none of the three props, output is byte-identical to
  dev/80** (label rotation, sr text, no suffix).
- **`AgentBuilderStrip.test.tsx`**: running line with "Solving" + fraction during a
  batch (`solveProgress` overlay); "Building"/"Stepping" for the simulate drives; line
  absent when idle and after the terminal state; `solvingNote` text gone (the old
  assertion inverted); fraction counts `solved/failed/skipped` as done.
- **`useTranscriptAutoScroll.test.tsx`**: detach → itemCount +2 → `unreadCount === 2`;
  bottom-return → 0; `jumpToLatest` → 0; `resetKey` → 0; send-path `pinToLatest` → 0;
  `itemCount` omitted → always 0; content-reference churn without count change (the
  streaming chunk case) → unchanged.
- **`AgentChatPanel.test.tsx`**: wheel-up detach → streamed reply lands → pill reads
  "1 new" with the aria-label carrying the count; jump click hides it and a fresh
  detach starts from 0; pill still reads "Latest" when detached with nothing new.
- Full suite + `tsc --noEmit` (the two pre-existing tsconfig notices only).

Required before completion: the dev/80-output regression on `AgentRunStatusLine`, the
strip's running-line + fraction test, and the detach→count→jump-reset panel test.

---

## 8. Acceptance Criteria

1. During a Solve batch the strip shows dot + "Solving… · m:ss · d/t nodes" in the
   shared status style; during simulate drives, "Building"/"Stepping" likewise; the
   static "solving…" note no longer exists.
2. Chat reply status lines render pixel-identically to dev/80 (no prop → no change).
3. Scrolled up, each newly landed turn increments the pill to "N new" (cap "99+",
   accessible name "Jump to N new messages"); any re-pin path resets it; "Latest"
   renders whenever nothing new is below.
4. No per-chunk re-render regression: streaming updates change neither `unreadCount`
   nor the hook's state-update pattern (dev/75 zero-per-chunk contract holds).
5. Delegated-agent chats show both behaviors with no additional wiring.
6. `LLMChat` diff is empty; nothing moves out of `agents/attach/`.
7. Full jest suite green (baseline + new tests only); `tsc` clean.

---

## 9. Recommended Commit Breakdown

1. **Commit 1 — shared primitives:** `AgentRunStatusLine` additive props +
   `useTranscriptAutoScroll` `itemCount`/`unreadCount` + `TranscriptJumpButton` `count`,
   with their unit tests (incl. the dev/80-output regression). No consumer behavior
   changes yet.
2. **Commit 2 — Solve strip adoption (A):** `AgentBuilderStrip` running line +
   `.solvingNote` removal + strip tests.
3. **Commit 3 — unread badge wiring (B):** `AgentChatPanel` two-line wiring + panel
   tests.
4. **Docs commit:** memo flip + BL-P5 build-log entry.

Commits 2 and 3 are independent consumers of commit 1 and can land in either order.

---

## 10. Engineering Quality Checklist

- [ ] All three new `AgentRunStatusLine` props optional with dev/80-identical defaults,
      proven by a regression test.
- [ ] No duplicated elapsed/label logic — the strip imports the component; `useRunTicker`
      remains the single ticker.
- [ ] The unread count lives in the hook that owns pinned state; the pill and panel
      stay presentation-only; the hook still takes a number, never turn objects.
- [ ] Zero-per-chunk contract re-verified (no new state updates on content churn).
- [ ] Live-region semantics: one polite announcement per phase change on both surfaces;
      ticking spans aria-hidden.
- [ ] No fabricated timing: strip elapsed is observation-based and documented as such.
- [ ] dev/76 encapsulation honored: every touched file is under `agents/attach/`;
      LLMChat untouched.
- [ ] Full jest + tsc verified before each commit, per the build-log convention.
