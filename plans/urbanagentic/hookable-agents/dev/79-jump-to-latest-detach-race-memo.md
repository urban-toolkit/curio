# dev/79 — Jump to latest "not working": the detach race and the momentum-canceled jump

**Status:** implemented (2026-08-18 — eager detach + jump landing guarantee in `useTranscriptAutoScroll`; hook-only change; full frontend jest 836 passed / 76 suites, `tsc --noEmit` nothing new in touched files). BL-P5-20260818-24. Commit `62c36c17` (single squash per §9's allowance — the two fixes interleave in the same functions). Renumbered from dev/78 → dev/79: a parallel session claimed 78 for the transcript code-copy button. Recorded deviation from §7: the dev/75 test "user wheel input during a programmatic jump wins over the animation" encoded the exact behavior Fix 2 removes (momentum canceling the jump), so it is replaced by the flight-contract pair (momentum-ignored + deadline snap; post-landing wheel-up detaches normally) rather than passing unmodified.
**Date:** 2026-08-14
**Fixes:** the dev/75 follow-at-bottom contract (`useTranscriptAutoScroll` + `TranscriptJumpButton`, now under `agents/attach/` per dev/76)

---

## 1. Problem Statement

The owner reports the Jump-to-latest button "is not working" in the real app,
while all 813 jsdom tests pass. Diagnosis found two real-browser defects in
`useTranscriptAutoScroll`; the primary one is reproduced by an event-ordering
test against the current hook.

**Root cause 1 — the detach race (primary; reproduced).** The hook unpins only
inside its `scroll` listener. Real browsers coalesce scroll events and dispatch
them in the render steps, AFTER queued tasks. During streaming, turns update on
every SSE chunk, so this ordering occurs constantly: (1) the user wheels up —
`wheel` fires and `scrollTop` moves synchronously; (2) before the coalesced
`scroll` event dispatches, the next chunk's layout effect runs — `pinnedRef` is
still `true`, so it yanks `scrollTop` back to the bottom; (3) the scroll event
finally fires at the *final* position (the bottom) → `isNearBottom` is true →
the hook stays pinned. The user's upward scroll is eaten on every attempt: they
can never detach during streaming, the pill never appears, and the feature
presents exactly like the original dev/75 bug. The `wheel` listener today only
clears the programmatic-scroll suppress flag — it never unpins, which is the
gap. (Reproduced: a throwaway ordering test — wheel-up, then a chunk re-render,
then the scroll event — shows `scrollTop` yanked back to the bottom and
`atBottom` still `true`.)

**Root cause 2 — momentum cancels the jump (secondary; macOS trackpads).** When
the pill *is* clicked (reachable when the transcript is idle), the jump uses
native `scrollTo({behavior: "smooth"})`. Browsers cancel an in-flight smooth
scroll on any user wheel input — and a trackpad flick keeps emitting decaying
momentum `wheel` events for ~1–2s. Clicking the pill during momentum aborts the
animation partway; the transcript barely moves and the pill's promise is
broken. There is no landing guarantee.

**Expected:** scrolling up during streaming detaches immediately and reliably;
the pill appears; clicking it always ends pinned at the bottom.

## 2. Scope

**In:** `components/agents/attach/useTranscriptAutoScroll.ts` only, plus its
test suite (`tests/attach/useTranscriptAutoScroll.test.tsx`) and, if needed,
one `AgentChatPanel` regression test. **Out:** `TranscriptJumpButton` (UI is
fine), `AgentChatPanel` wiring, all styling, `LLMChat` (untouched per dev/76).

## 3. Recommended Implementation Approach

Two mechanisms, both inside the hook:

**Fix 1 — synchronous eager detach on user intent.** User input that expresses
"leave the bottom" must unpin *in the input handler itself* (a ref write —
takes effect before any subsequent chunk's layout effect), not wait for the
scroll event:
- `wheel` with `deltaY < 0` → `setPinned(false)` immediately (plus the existing
  suppress-clear). Wheel-down keeps today's behavior (position-driven).
- `touchmove` → eager detach; the scroll handler re-pins on the next scroll
  event if the position is still near the bottom (transient, invisible).
- `keydown` for up-scroll keys (`ArrowUp`, `PageUp`, `Home`) → eager detach.
- `pointerdown` on the scrollbar region (`offsetX >= clientWidth`, the one part
  of the container where a drag scrolls it) → eager detach; clicks on content
  (text selection) keep today's behavior.
False-positive detaches (e.g. a 5px wheel nudge still within the threshold) are
self-healing: the next genuine scroll event re-evaluates `isNearBottom` and
re-pins — while streaming continues un-scrolled for that instant, which is the
safe direction to fail.

**Fix 2 — jump landing guarantee.** `jumpToLatest` keeps the smooth scroll but
becomes an assured arrival: mark a jump in flight with a short deadline
(~450ms); while in flight, user-intent handlers do NOT eager-detach (momentum
must not cancel the user's explicit jump — a genuine cancel is still possible
the moment the flight ends); a rAF loop watches the position — landed near the
bottom → done; deadline passed and not landed (the browser canceled the native
animation) → instant `scrollTop` snap. `prefers-reduced-motion` keeps its
existing instant path. rAF is jsdom-guarded like the other browser APIs.

## 4. Data and State Handling

Unchanged externally — same hook API, same consumers. Internally: eager detach
writes `pinnedRef` synchronously in native event handlers (the whole point);
`atBottom` state still flips only on transitions; the in-flight jump mark is a
ref (deadline timestamp) so no re-renders. `performance.now()` (monotonic) for
the deadline.

## 5. UI and UX Requirements

- During streaming, one upward wheel/touch/key gesture visibly detaches: the
  viewport holds still and the pill appears — every time, not probabilistically.
- Clicking the pill always ends at the newest message, pinned, pill hidden —
  including mid-momentum on a macOS trackpad (worst case: the smooth animation
  degrades to a snap at the deadline).
- No change to the pill's look, placement, a11y, or the panel's behavior
  otherwise.

## 6. Edge Cases

1. Wheel-up nudge within the 48px threshold → transient detach, re-pinned by
   the next scroll event (streaming pauses for one beat — invisible).
2. Wheel-down while detached mid-transcript → no eager re-pin; position-driven
   re-pin at the bottom only (unchanged).
3. Momentum wheel events arriving during the jump flight → ignored for detach;
   post-flight momentum that genuinely leaves the bottom re-shows the pill
   (matches native scroll semantics).
4. Jump clicked while streaming → per-chunk pinned scrolls and the rAF watcher
   both drive toward the (growing) bottom; the guarantee's "near bottom" check
   uses live geometry so growth can't strand it.
5. Keyboard scrolling requires container focus (`tabIndex={-1}` already set) —
   up-keys detach; `End`/`PageDown` stay position-driven.
6. jsdom: no rAF loop assumptions in tests — the deadline snap is testable with
   fake timers/manual rAF stubs; all browser APIs guarded as today.
7. Scrollbar drag detection uses `offsetX >= clientWidth` — RTL layouts would
   need the mirror check; the app is LTR-only today, note it in a comment.

## 7. Testing Strategy

- **The reproduced race, inverted (regression):** wheel-up → chunk re-render →
  scroll event; assert `scrollTop` stays at the user's position and `atBottom`
  is false (this exact sequence passes against the broken hook when asserting
  the buggy outcome — it must now assert the fixed outcome).
- Eager-detach unit tests: wheel-up detaches synchronously; wheel-down does
  not; touchmove detaches; up-key detaches; content `pointerdown` does not.
- Jump guarantee: in-flight wheel does not cancel; deadline with a stalled
  position snaps to the bottom; landing before the deadline ends the flight.
- Existing 10 hook tests + panel suite must pass unmodified (the suppress
  handshake and position-driven pinning are untouched paths).

## 8. Acceptance Criteria

1. With a reply streaming, a single upward scroll gesture detaches: the view
   holds, chunks keep arriving below, the pill appears — reliably.
2. Clicking the pill always lands pinned at the newest message, pill hidden,
   even during trackpad momentum.
3. Manual bottom-return still re-pins and hides the pill.
4. The race regression test and the guarantee tests pass; the full suite stays
   green; no API or visual changes.

## 9. Recommended Commit Breakdown

- Commit 1: eager-detach fix + race regression test.
- Commit 2: jump landing guarantee + its tests.
(Small enough to squash into one if preferred; both touch only the hook + its
tests.)

## 10. Engineering Quality Checklist

Single-hook change (no consumer edits); refs for all hot-path state (no
per-chunk re-renders introduced); jsdom guards on every browser API; failure
direction is always "hold the user's position" (never yank); tests encode the
real-browser orderings, not just jsdom-idealized ones.
