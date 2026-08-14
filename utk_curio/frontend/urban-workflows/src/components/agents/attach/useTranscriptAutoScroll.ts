import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** How close to the bottom (px) still counts as "at the bottom" — tolerant of
 * fractional scroll positions at non-100% browser zoom. */
const BOTTOM_THRESHOLD_PX = 48;

export interface TranscriptAutoScroll {
  /** Attach to the scrollable transcript container. */
  containerRef: React.RefObject<HTMLDivElement | null>;
  /** False while the user has scrolled away from the bottom (drives the
   * "Jump to latest" button); updates only on pinned↔detached transitions. */
  atBottom: boolean;
  /** Smooth-scroll to the newest message and re-engage auto-follow
   * (instant under prefers-reduced-motion). */
  jumpToLatest: () => void;
  /** Instantly re-pin to the bottom regardless of position — for explicit
   * bottom-engagement moments like the user sending a message. */
  pinToLatest: () => void;
}

const isNearBottom = (el: HTMLElement) =>
  el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_THRESHOLD_PX;

/**
 * Follow-at-bottom auto-scroll for chat transcripts (memo dev/75).
 *
 * The transcript follows new content ONLY while the user is already at (or
 * near) the bottom. Scrolling up detaches auto-follow — streamed chunks keep
 * accumulating below without moving the viewport. Follow resumes when the
 * user returns to the bottom or calls `jumpToLatest`.
 *
 * The pinned flag lives in a ref (streaming replaces the last turn on every
 * SSE chunk — per-chunk re-renders from scroll tracking are not acceptable);
 * `atBottom` state changes only when the flag actually flips.
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
  const [atBottom, setAtBottom] = useState(true);

  const setPinned = useCallback((pinned: boolean) => {
    pinnedRef.current = pinned;
    setAtBottom(pinned); // same-value updates bail out — no per-scroll churn
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
    scrollToBottom(reduceMotion ? "auto" : "smooth");
  }, [setPinned, scrollToBottom]);

  // Pinned/detached tracking. Any genuine user input on the container (wheel,
  // touch, scrollbar drag, keyboard) clears the suppress flag first, so a user
  // scrolling DURING our smooth jump wins over the animation.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onUserIntent = () => {
      suppressScrollSignal.current = false;
    };
    const onScroll = () => {
      if (suppressScrollSignal.current) {
        // Our own scroll (or its animation) — never a detach. Once it lands
        // at the bottom the signal is done.
        if (isNearBottom(el)) suppressScrollSignal.current = false;
        setPinned(true);
        return;
      }
      setPinned(isNearBottom(el));
    };
    el.addEventListener("wheel", onUserIntent, { passive: true });
    el.addEventListener("touchmove", onUserIntent, { passive: true });
    el.addEventListener("pointerdown", onUserIntent, { passive: true });
    el.addEventListener("keydown", onUserIntent);
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("wheel", onUserIntent);
      el.removeEventListener("touchmove", onUserIntent);
      el.removeEventListener("pointerdown", onUserIntent);
      el.removeEventListener("keydown", onUserIntent);
      el.removeEventListener("scroll", onScroll);
    };
  }, [setPinned]);

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
