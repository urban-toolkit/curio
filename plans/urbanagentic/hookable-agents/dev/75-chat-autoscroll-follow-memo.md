# dev/75 — Transcript auto-scroll: follow-at-bottom + Jump to latest

**Status:** implemented (2026-08-13 — `useTranscriptAutoScroll` + `TranscriptJumpButton`, adopted in `AgentChatPanel` and `LLMChat`; full frontend jest 805 passed / 75 suites, `tsc --noEmit` clean bar the two pre-existing tsconfig deprecation notices). BL-P5-20260813-20. Commits `631b96eb` / `f4d80b0c` / `724ebd3f`. Recorded deviations: none — implemented as specified.
**Date:** 2026-08-13
**Surfaces:** `AgentChatPanel` (agent chats *and* delegated-agent chats — same component, dev/72), `LLMChat` (LLM Assistant sidebar)

---

## 1. Problem Statement

Every chat transcript in Curio unconditionally forces the scroll position to the
bottom whenever its message list changes:

- `AgentChatPanel.tsx:195-198` — `useEffect` sets `el.scrollTop = el.scrollHeight`
  on every `[turns, loadingHistory]` change. Agent replies stream over SSE
  (`agentsApi.ts` posts to the SSE endpoint and calls `onDelta` per text chunk;
  the provider's `replaceLastAgentTurn` at `AgentAttachmentsProvider.tsx:186`
  replaces the last turn on **every chunk**), so during a streamed reply the
  effect fires dozens of times per second. A user who scrolls up to re-read an
  earlier turn is yanked back to the bottom on the next chunk — reading earlier
  context during a long agent reply is effectively impossible.
- `LLMChat.tsx:81-87` — the same unconditional pin (via
  `document.getElementById("messagesDiv")`) on every `messages` change. The LLM
  Assistant does not stream today, but any message append (including the
  loading→reply transition) snaps the user to the bottom regardless of where
  they were.

Delegated-agent chats are affected identically because a delegation entry opens
the delegate's attachment in the **same** `AgentChatPanel` (dev/72
`onOpenAttachment`), which carries the same effect.

**Expected behavior:** the transcript follows new content only while the user is
already at (or near) the bottom. Scrolling up detaches auto-follow: streaming
continues without moving the viewport. Auto-follow resumes when the user returns
to the bottom, or when they click a compact "Jump to latest" control that
appears only while newer content sits below the viewport.

**Why it matters:** the forced scroll is a direct usability defect (loss of user
control during the most common long-running interaction), and the fix is a
standard, well-understood chat pattern. Consistency matters too: three
transcript surfaces should share one behavior, not three ad-hoc effects.

---

## 2. Scope

**In scope**

- New shared hook in `src/hook/` (the established home for cross-component
  hooks, cf. `useMonacoExternalValue` from dev/70): pinned-to-bottom tracking,
  conditional auto-scroll, and jump-to-latest, generic over any scrollable
  transcript container.
- `src/components/agents/attach/AgentChatPanel.tsx` — replace the unconditional
  effect (lines 195-198) with the hook; add the Jump to latest button inside the
  transcript region.
- `src/components/agents/attach/AgentChatPanel.module.css` — styles for the
  button (overlay pill anchored to the bottom of `.messages`).
- `src/components/LLMChat.tsx` (+ `LLMChat.css`) — adopt the same hook; replace
  the `getElementById("messagesDiv")` lookup with a proper `ref`; add the same
  button.
- Tests: new hook unit tests; `src/tests/attach/AgentChatPanel.test.tsx`
  additions.

**Out of scope**

- The streaming transport and `replaceLastAgentTurn` per-chunk update model
  (works fine; the bug is purely the scroll effect).
- Turn rendering, suggested prompts, review cards, delegation entries, intent
  editor — untouched.
- The palette dropdowns (`PackagesPaletteDropdown`, `DatasetsPaletteDropdown`)
  also touch `scrollTop`, but those are list-position restoration, not
  transcript-follow — not changed.
- Virtualizing long transcripts (separate concern).

---

## 3. Recommended Implementation Approach

Centralize the behavior in one hook — `useTranscriptAutoScroll` — so both
surfaces (and any future transcript) share identical semantics.

**Hook contract** (shape, not code):

- Input: a dependency the caller re-triggers on content change (e.g. `turns` /
  `messages`), plus an optional "force pin" signal for initial hydration
  (`loadingHistory` flipping false, attachment switch).
- Returns: `containerRef` (attach to the scrollable div), `atBottom` (drives
  button visibility), and `jumpToLatest()` (smooth-scroll to bottom + re-pin).

**Core mechanics:**

- **Pinned state is derived from user scroll position**, held in a ref (not
  state) so per-chunk updates never re-render: a `scroll` listener on the
  container computes `scrollHeight - scrollTop - clientHeight <= THRESHOLD`
  (~48px, tolerant of fractional pixels at browser zoom). At/below threshold →
  pinned; above → detached.
- **Distinguish programmatic scrolls from user scrolls.** The hook's own
  `scrollTop` writes fire `scroll` events too. Set a
  `suppressScrollSignal` ref around programmatic writes (cleared on the next
  scroll event or a rAF tick) so the hook's own scrolling can't be misread as
  the user detaching — and, critically, so a *smooth* jump animation passing
  through "not at bottom" positions doesn't cancel itself.
- **Follow on content growth only while pinned.** A `useLayoutEffect` keyed on
  the content dep does `scrollTop = scrollHeight` (instant, not smooth — smooth
  scrolling during streaming lags behind and stutters) **only if pinned**.
  Layout effect (not `useEffect`) avoids a visible one-frame flash of the
  unscrolled position.
- **Track growth that React deps can't see.** Markdown images/late layout can
  grow the content after the effect ran. Attach a `ResizeObserver` to the inner
  content (or the container's single scroll child) that re-pins while pinned.
  This is a correctness detail, not a rewrite — a few lines in the hook.
- **`atBottom` as state, updated only on transitions** (pinned↔detached), so the
  button visibility renders without per-chunk re-render churn.
- **`jumpToLatest()`**: `scrollTo({top: scrollHeight, behavior: "smooth"})`
  under the suppress flag, then mark pinned. Respect
  `prefers-reduced-motion: reduce` by falling back to instant.

**Adoption:**

- `AgentChatPanel`: delete the effect at 195-198; `messagesRef` becomes the
  hook's `containerRef`. Re-pin unconditionally when `attachment.attachmentId`
  changes or history hydration completes (opening a chat — including a
  delegate's — always starts at the newest turn, matching today's intent).
  Button renders inside the panel next to `.messages` (the panel root is the
  positioning context), visible when `!atBottom`.
- `LLMChat`: same hook; replace the `getElementById` effect with `ref` usage
  (also removes an id-collision hazard); add the same button. Reuse one CSS
  class if practical, or mirror the pill styles in `LLMChat.css` — prefer a
  small shared CSS module (`TranscriptJumpButton.module.css`) or a tiny shared
  component `TranscriptJumpButton` so the control stays visually identical.

A small shared presentational component + shared hook is the recommended shape:
behavior and appearance both centralized, each panel just wires refs and deps.

---

## 4. Data and State Handling

- **Source of truth for content:** unchanged — `turns` from
  `AgentAttachmentsProvider` transcripts (per-chunk `replaceLastAgentTurn`),
  `messages` local state in `LLMChat`.
- **Source of truth for scroll:** the DOM container itself. The hook never
  mirrors `scrollTop` into React state; it derives two booleans (pinned ref,
  `atBottom` state on transition only). This avoids per-chunk re-renders and
  race conditions between streamed updates and user scrolling.
- **Loading/hydration:** while `loadingHistory` is true nothing scrolls; when it
  flips false the hook force-pins once (transcript opens at the latest turn).
- **Attachment switch / delegated chat open:** `attachmentId` change force-pins;
  the pinned/detached state of the previous chat must not leak into the next.
- **After user send:** sending a message is an explicit "I'm engaging at the
  bottom" — force-pin on the local user-turn append so the user always sees
  their own message and the reply start. (The input sits at the bottom; a user
  who scrolled up and then sends still expects to see their message land.)
- **No stale reads:** all geometry reads (`scrollHeight` etc.) happen inside the
  layout effect / event handlers at the moment of use, never cached across
  renders.

---

## 5. UI and UX Requirements

**Auto-follow**

- At/near bottom (≤ ~48px): new turns and streamed chunks keep the view pinned
  with no visible jitter.
- Scrolled up: content streams below with zero viewport movement — no snap, no
  layout shift, no flicker.
- Returning to the bottom manually re-engages follow with no extra action.

**Jump to latest button**

- Compact pill overlaying the bottom of the transcript, horizontally centered,
  floating ~12px above the transcript's bottom edge (above the composer, never
  overlapping it): down-chevron icon + short label ("Latest" or "Jump to
  latest"). Matches Curio chrome: dark `var(--curio-top-bar-bg, #1e1f23)`
  background, white text, ~12px font, fully rounded, subtle shadow, hover
  brightness shift — consistent with the existing dark-pill accents in the
  panel (user bubbles use the same token).
- Visible **only** while detached (i.e., newer content lies below the viewport);
  fades/hides immediately once the user is back at the bottom (via click or
  manual scroll). A short opacity transition is fine; no layout shift when it
  appears (absolute overlay).
- Click: smooth scroll to the newest message, re-engage auto-follow, hide.
- Accessibility: real `<button type="button">`, `aria-label="Jump to latest
  messages"`, keyboard focusable and Enter/Space activatable, visible focus
  ring, honors `prefers-reduced-motion` (instant jump instead of smooth). It
  must not steal focus when appearing, and hiding it while focused must not
  strand focus (return focus to the transcript container, which should have
  `tabindex="-1"` or already-focusable children).
- Identical appearance and behavior in `AgentChatPanel` (primary and delegated
  chats — same component) and `LLMChat`.

---

## 6. Edge Cases

1. **Streamed chunk while detached** — the core regression case: `scrollTop`
   must not change at all.
2. **Smooth jump in progress** — mid-animation positions are "not at bottom";
   the suppress flag must prevent the animation from being read as a user
   detach (which would cancel re-pinning).
3. **User scrolls up *during* the smooth jump** — a genuine user wheel event
   during animation should win: the next user-originated scroll clears the
   suppress flag and re-evaluates.
4. **History hydration** — turns arrive in bulk after open; force-pin exactly
   once when `loadingHistory` completes, not on every hydration re-render.
5. **Switching attachments / opening a delegate chat** — always opens pinned at
   the newest turn; previous chat's detached state must not leak.
6. **Container shorter than content threshold** — an empty or short transcript
   (`scrollHeight <= clientHeight`) is always "at bottom"; button never shows.
7. **Late layout growth** — markdown images, review cards, or fonts growing
   content after the effect ran: ResizeObserver re-pins while pinned; while
   detached it must *not* scroll.
8. **Fractional pixels / zoom** — `scrollTop` can be fractional; the ≤48px
   threshold (not `===`) absorbs this.
9. **Rapid repeated sends** — each send force-pins; no double-scroll or fight
   between force-pin and the content effect.
10. **Panel resize** (window resize, dock/overlay reflow) — resizing while
    pinned keeps the bottom in view; while detached it must not jump.
11. **jsdom** — `ResizeObserver` and `scrollTo` don't exist in jsdom; the hook
    must guard (`typeof ResizeObserver !== "undefined"`, fall back from
    `scrollTo(options)` to `scrollTop` assignment) so tests and any SSR-ish
    tooling don't crash.
12. **Turn replaced, not appended** — `replaceLastAgentTurn` changes content
    without changing turn count; the hook keys on the `turns` array reference
    (changes every chunk), so no count-based logic.

---

## 7. Testing Strategy

**Hook unit tests** (new file, e.g. `src/tests/attach/useTranscriptAutoScroll.test.tsx`
or alongside existing hook tests) — drive a fake scrollable div by defining
`scrollHeight`/`clientHeight`/`scrollTop` with `Object.defineProperty`:

- Pinned + content growth → scrolls to bottom.
- Detached (scrollTop above threshold) + content growth → `scrollTop` unchanged.
- Scroll back to within threshold → next growth follows again.
- `jumpToLatest()` → bottom + pinned; programmatic scroll does not detach.
- Force-pin signal (hydration/attachment switch) overrides detached state.
- Threshold boundary: exactly at 48px counts as bottom; 49px does not.

**Component tests** (`src/tests/attach/AgentChatPanel.test.tsx`):

- Jump button hidden at bottom, appears after simulated user scroll-up
  (dispatch `scroll` event with mocked geometry), hides after clicking it.
- Click calls scroll-to-bottom (mock `scrollTo`/`scrollTop`) and the button
  disappears.
- Streaming simulation: re-render with a replaced last turn while detached →
  container `scrollTop` untouched (the regression test for this issue).
- Button has the correct `aria-label` and is a `button` role.

**LLMChat**: a small component test verifying the same visibility contract and
that the `getElementById` pattern is gone (ref-driven).

Required before completion: hook unit tests + the AgentChatPanel regression
test (streamed update while detached does not move scroll).

Run via the `curio-feat` conda env (node/jest are only on PATH there).

---

## 8. Acceptance Criteria

1. While at/near the bottom of any agent chat (primary or delegated) a streamed
   reply keeps the newest content in view continuously.
2. After scrolling up in a chat whose reply is still streaming, the viewport
   never moves on its own; content continues to accumulate below.
3. A compact "Jump to latest" pill appears only while the user is away from the
   bottom, in every transcript surface (`AgentChatPanel` in all its uses,
   `LLMChat`), and never overlaps the composer.
4. Clicking the pill smooth-scrolls to the newest message (instant under
   `prefers-reduced-motion`), auto-follow resumes, and the pill hides.
5. Manually scrolling back to the bottom also resumes auto-follow and hides the
   pill — the button is never the only way back.
6. Opening a chat (including a delegate's chat from a delegation entry) still
   lands on the newest turn after history hydrates; sending a message always
   brings the user's new message into view.
7. No per-chunk React re-renders are introduced by scroll tracking (pinned state
   lives in refs; `atBottom` state changes only on pinned↔detached transitions).
8. The `AgentChatPanel.tsx:195` unconditional effect and the
   `LLMChat.tsx:82` `getElementById` effect are removed; both panels use the
   shared hook.
9. All new and existing tests pass; the streamed-while-detached regression test
   exists and passes.

---

## 9. Recommended Commit Breakdown

- **Commit 1** — `useTranscriptAutoScroll` hook in `src/hook/` +
  `TranscriptJumpButton` shared component/styles + hook unit tests.
- **Commit 2** — `AgentChatPanel` adoption: remove the unconditional effect,
  wire the hook and button, CSS additions; component tests incl. the streaming
  regression test.
- **Commit 3** — `LLMChat` adoption: ref-based container, hook + button wiring,
  style alignment.

(Per repo convention: no Claude co-author trailer, changes left unstaged until
you commit.)

---

## 10. Engineering Quality Checklist

- [ ] One hook owns all pinned/follow/jump logic — no duplicated scroll math in
      panels.
- [ ] One shared button component — identical UI in every transcript.
- [ ] No React state updated per streamed chunk by the scroll system.
- [ ] Programmatic vs. user scroll disambiguated (no self-canceling jumps, no
      false detaches).
- [ ] Layout effect ordering prevents flash-of-wrong-position.
- [ ] jsdom-safe guards for `ResizeObserver`/`scrollTo`.
- [ ] Explicit types on the hook's params/returns; no `any`.
- [ ] Accessibility: labeled button, keyboard operable, focus not stolen or
      stranded, reduced-motion honored.
- [ ] Existing behaviors preserved: open-at-latest, Escape-to-close, title
      edit, suggested prompts untouched.
- [ ] Tests cover core behavior, the regression, and boundary/edge cases.
