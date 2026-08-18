import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** How close to the bottom (px) still counts as "at the bottom" — tolerant of
 * fractional scroll positions at non-100% browser zoom. */
const BOTTOM_THRESHOLD_PX = 48;

/** How long a jump's smooth scroll gets to land before the guarantee snaps
 * (dev/79): native smooth scrolls are canceled by ANY user wheel input, and a
 * trackpad flick keeps emitting momentum wheel events for ~1–2s — without a
 * deadline the jump can silently die partway. */
const JUMP_FLIGHT_MS = 450;

export interface TranscriptAutoScroll {
  /** Attach to the scrollable transcript container. */
  containerRef: React.RefObject<HTMLDivElement | null>;
  /** False while the user has scrolled away from the bottom (drives the
   * "Jump to latest" button); updates only on pinned↔detached transitions. */
  atBottom: boolean;
  /** Smooth-scroll to the newest message and re-engage auto-follow
   * (instant under prefers-reduced-motion). Arrival is guaranteed: if the
   * native animation is canceled (trackpad momentum), a deadline snap lands
   * it. */
  jumpToLatest: () => void;
  /** Instantly re-pin to the bottom regardless of position — for explicit
   * bottom-engagement moments like the user sending a message. */
  pinToLatest: () => void;
}

const isNearBottom = (el: HTMLElement) =>
  el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_THRESHOLD_PX;

/**
 * Follow-at-bottom auto-scroll for chat transcripts (memo dev/75, race fixes
 * memo dev/79).
 *
 * The transcript follows new content ONLY while the user is already at (or
 * near) the bottom. Scrolling up detaches auto-follow — streamed chunks keep
 * accumulating below without moving the viewport. Follow resumes when the
 * user returns to the bottom or calls `jumpToLatest`.
 *
 * The pinned flag lives in a ref (streaming replaces the last turn on every
 * SSE chunk — per-chunk re-renders from scroll tracking are not acceptable);
 * `atBottom` state changes only when the flag actually flips.
 *
 * Detach is EAGER (dev/79): browsers coalesce scroll events and dispatch them
 * after queued tasks, so during streaming the next chunk's layout effect runs
 * BEFORE the scroll event that would report the user's wheel-up — waiting for
 * the scroll event means the chunk re-pins over the user's scroll every time.
 * User input that expresses "leave the bottom" therefore unpins synchronously
 * in the input handler itself; a false positive (a nudge still within the
 * threshold) is re-pinned by the next scroll event.
 */
export function useTranscriptAutoScroll({
  content,
  resetKey,
  ready = true,
}: {
  /** Value that changes whenever transcript content changes (turns/messages
   * array — its reference changes per streamed chunk). */
  content: unknown;
  /** Changing this force-re-pins (e.g. switching to another agent's chat). */
  resetKey?: unknown;
  /** False while history hydrates; flipping true force-pins once. */
  ready?: boolean;
}): TranscriptAutoScroll {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const pinnedRef = useRef(true);
  /** True while a scroll we initiated is (or may still be) in flight, so the
   * scroll events it fires — including a smooth animation's intermediate
   * "not at bottom" positions — are never read as the user detaching. */
  const suppressScrollSignal = useRef(false);
  /** Non-null while a jump's landing guarantee is armed (the deadline timer).
   * While armed, user-intent handlers stand down: trackpad momentum arriving
   * right after the click must not cancel the user's explicit jump. */
  const jumpFlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [atBottom, setAtBottom] = useState(true);

  const setPinned = useCallback((pinned: boolean) => {
    pinnedRef.current = pinned;
    setAtBottom(pinned); // same-value updates bail out — no per-scroll churn
  }, []);

  const endJumpFlight = useCallback(() => {
    if (jumpFlightTimer.current !== null) {
      clearTimeout(jumpFlightTimer.current);
      jumpFlightTimer.current = null;
    }
  }, []);

  const scrollToBottom = useCallback((behavior: ScrollBehavior) => {
    const el = containerRef.current;
    if (!el) return;
    const target = el.scrollHeight - el.clientHeight;
    // Only a write that will actually move fires a scroll event; suppressing
    // around a no-op write would swallow the NEXT genuine user scroll.
    if (Math.abs(el.scrollTop - target) < 1) return;
    suppressScrollSignal.current = true;
    if (typeof el.scrollTo === "function") {
      el.scrollTo({ top: target, behavior });
    } else {
      el.scrollTop = target; // jsdom has no scrollTo
    }
  }, []);

  const pinToLatest = useCallback(() => {
    setPinned(true);
    scrollToBottom("auto");
  }, [setPinned, scrollToBottom]);

  const jumpToLatest = useCallback(() => {
    const reduceMotion =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setPinned(true);
    if (reduceMotion) {
      scrollToBottom("auto");
      return;
    }
    endJumpFlight();
    scrollToBottom("smooth");
    // Landing guarantee (dev/79): if the native animation died (momentum
    // wheel input cancels it) the deadline lands the jump with an instant
    // snap. A scroll event arriving near the bottom disarms this early.
    jumpFlightTimer.current = setTimeout(() => {
      jumpFlightTimer.current = null;
      const el = containerRef.current;
      if (!el || !pinnedRef.current || isNearBottom(el)) return;
      suppressScrollSignal.current = true;
      // Direct write, not scrollTo: the snap must land even where a smooth
      // engine is wedged; instant assignment cannot be canceled.
      el.scrollTop = el.scrollHeight - el.clientHeight;
    }, JUMP_FLIGHT_MS);
  }, [setPinned, scrollToBottom, endJumpFlight]);

  // Pinned/detached tracking. Handlers for input that expresses "leave the
  // bottom" detach EAGERLY (synchronously) — see the hook docstring — and any
  // genuine user input clears the suppress flag so a user scrolling right
  // after our programmatic scroll still wins. All of them stand down while a
  // jump flight is armed.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (jumpFlightTimer.current !== null) return; // momentum can't cancel a jump
      suppressScrollSignal.current = false;
      if (e.deltaY < 0) setPinned(false); // wheel-up = explicit detach
    };
    const onTouchMove = () => {
      if (jumpFlightTimer.current !== null) return;
      suppressScrollSignal.current = false;
      // Direction is unknowable here; detach and let the next scroll event
      // re-pin if the position is in fact still near the bottom.
      setPinned(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (jumpFlightTimer.current !== null) return;
      suppressScrollSignal.current = false;
      if (e.key === "ArrowUp" || e.key === "PageUp" || e.key === "Home") {
        setPinned(false);
      }
    };
    const onPointerDown = (e: PointerEvent) => {
      if (jumpFlightTimer.current !== null) return;
      suppressScrollSignal.current = false;
      // A drag can only scroll from the scrollbar gutter — the one pointer
      // target on the container itself past clientWidth (LTR-only app).
      // Content clicks (text selection) stay position-driven.
      if (e.target === el && e.offsetX >= el.clientWidth) setPinned(false);
    };
    const onScroll = () => {
      if (suppressScrollSignal.current) {
        // Our own scroll (or its animation) — never a detach. Once it lands
        // at the bottom the signal (and any jump flight) is done.
        if (isNearBottom(el)) {
          suppressScrollSignal.current = false;
          endJumpFlight();
        }
        setPinned(true);
        return;
      }
      setPinned(isNearBottom(el));
    };
    el.addEventListener("wheel", onWheel, { passive: true });
    el.addEventListener("touchmove", onTouchMove, { passive: true });
    el.addEventListener("pointerdown", onPointerDown, { passive: true });
    el.addEventListener("keydown", onKeyDown);
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("pointerdown", onPointerDown);
      el.removeEventListener("keydown", onKeyDown);
      el.removeEventListener("scroll", onScroll);
    };
  }, [setPinned, endJumpFlight]);

  // A pending landing-guarantee timer must not outlive the component.
  useEffect(() => endJumpFlight, [endJumpFlight]);

  // Opening/switching a chat (and history hydration completing) always lands
  // pinned at the newest turn — a previous chat's detached state never leaks.
  useLayoutEffect(() => {
    if (!ready) return;
    setPinned(true);
    scrollToBottom("auto");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey, ready]);

  // Follow content growth only while pinned — instant, not smooth (a smooth
  // scroll lags per-chunk streaming and stutters). Layout effect so the pin
  // happens before paint (no one-frame flash of the unscrolled position).
  useLayoutEffect(() => {
    if (!ready) return;
    if (pinnedRef.current) scrollToBottom("auto");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, ready]);

  // Late layout growth React deps can't see (markdown images, panel resize):
  // re-pin while pinned; while detached the observer must NOT scroll.
  useEffect(() => {
    if (typeof ResizeObserver === "undefined") return; // jsdom
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      if (pinnedRef.current) scrollToBottom("auto");
    });
    ro.observe(el);
    // The last message is where streamed markdown grows after render.
    if (el.lastElementChild) ro.observe(el.lastElementChild);
    return () => ro.disconnect();
  }, [content, ready, scrollToBottom]);

  return { containerRef, atBottom, jumpToLatest, pinToLatest };
}
