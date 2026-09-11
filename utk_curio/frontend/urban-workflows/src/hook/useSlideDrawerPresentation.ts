import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

/**
 * The two-phase presentation behind every sliding panel in the app (memo
 * dev/43, #295).
 *
 * A panel that slides cannot simply mount open: the browser would paint it at
 * its final transform and there would be nothing to animate from. And it cannot
 * unmount on close either, or the exit slide plays to an element that is
 * already gone. So presentation is two pieces of state, not one:
 *
 *   - `mounted` — is it in the DOM at all? Owns the portal.
 *   - `presented` — is it at its resting transform? Owns the CSS class.
 *
 * Opening mounts closed, then flips `presented` on a later frame so the
 * transition has a start and an end. Closing flips `presented` back and keeps
 * the panel mounted until the slide finishes - reported by the panel through
 * `finishExit`, with a timer as the fallback for the case where no
 * `transitionend` ever arrives (a display:none ancestor, a browser that drops
 * the event under load, reduced motion).
 *
 * **Double rAF, not one.** One frame is not enough: React commits the mount and
 * the class change can land in the same paint, so the element is born at its
 * final transform and nothing animates. Two frames guarantee the browser has
 * painted the closed state first. The Dataset drawer used a single rAF and was
 * the one that intermittently appeared without sliding.
 *
 * **`mounted` is the open signal, not `presented`.** A consumer asking "is the
 * drawer open?" is asking whether it is on screen, and during the exit slide it
 * still is. Gating on `presented` reported a drawer as closed while it was
 * visibly sliding out - and, where the body scroll-lock used the same signal,
 * released the lock a frame into the exit so the page jumped behind it.
 *
 * The hook deliberately owns motion and focus restoration and nothing else.
 * Escape handling, pinning, and per-drawer open payloads stay with the provider
 * that has the context for them: Escape in particular has to coordinate with
 * `modalStackDepth()` for a modal opened from inside the drawer, which is a
 * question about that drawer's content, not about sliding.
 */

/** Slide duration. Keep in sync with `.drawer` in CatalogDrawerShell.module.css. */
export const DRAWER_MOTION_MS = 300;

/**
 * Grace added to the fallback timer, so it only ever fires when the real
 * `transitionend` did not. Long enough to lose a race, short enough that a
 * panel cannot sit unmountable.
 */
export const EXIT_FALLBACK_GRACE_MS = 80;

// jsdom (tests) has no matchMedia - degrade to "no reduced motion". Only one of
// the three providers guarded this, which is why only one of them had a render
// test: the other two threw on mount under jsdom.
function subscribeReducedMotion(onStoreChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return () => undefined;
  }
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  mq.addEventListener("change", onStoreChange);
  return () => mq.removeEventListener("change", onStoreChange);
}

function getReducedMotionSnapshot(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;
}

const NO_REDUCED_MOTION = () => false;

export interface SlideDrawerPresentation {
  /** In the DOM. Render the portal on this, and report "open" from it. */
  mounted: boolean;
  /** At its resting transform. Pass to the panel as its presented class. */
  presented: boolean;
  /** Mount closed and slide in. Re-opening mid-exit cancels the exit. */
  open: () => void;
  /** Slide out; unmounts on `finishExit` or the fallback timer. */
  close: () => void;
  /** The panel's `onExitComplete`: the slide is over, drop it from the DOM. */
  finishExit: () => void;
}

export function useSlideDrawerPresentation(
  { motionMs = DRAWER_MOTION_MS }: { motionMs?: number } = {},
): SlideDrawerPresentation {
  const prefersReducedMotion = useSyncExternalStore(
    subscribeReducedMotion,
    getReducedMotionSnapshot,
    NO_REDUCED_MOTION,
  );

  const [mounted, setMounted] = useState(false);
  const [presented, setPresented] = useState(false);
  const preOpenFocusRef = useRef<HTMLElement | null>(null);
  const exitTimerRef = useRef<number | null>(null);
  // Idempotence for `finishExit`: the transitionend and the fallback timer can
  // both arrive, and a second unmount would steal focus back a second time.
  const exitSettledRef = useRef(false);
  const rafRef = useRef<number | null>(null);

  const clearExitTimer = useCallback(() => {
    if (exitTimerRef.current != null) {
      window.clearTimeout(exitTimerRef.current);
      exitTimerRef.current = null;
    }
  }, []);

  const cancelPendingPresent = useCallback(() => {
    if (rafRef.current != null) {
      window.cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  const finishExit = useCallback(() => {
    if (exitSettledRef.current) return;
    exitSettledRef.current = true;
    clearExitTimer();
    setMounted(false);
    setPresented(false);
    // Focus goes back where it was before the panel took it. In a microtask
    // because the element may still be inside the portal React is unmounting
    // in this same commit.
    const el = preOpenFocusRef.current;
    preOpenFocusRef.current = null;
    queueMicrotask(() => el?.focus?.());
  }, [clearExitTimer]);

  const close = useCallback(() => {
    clearExitTimer();
    cancelPendingPresent();
    setPresented(false);
    exitTimerRef.current = window.setTimeout(
      finishExit,
      prefersReducedMotion ? 0 : motionMs + EXIT_FALLBACK_GRACE_MS,
    );
  }, [cancelPendingPresent, clearExitTimer, finishExit, motionMs, prefersReducedMotion]);

  const open = useCallback(() => {
    // Re-opening during an exit slide cancels it: the panel is still mounted,
    // so it slides back from wherever it had got to rather than restarting.
    clearExitTimer();
    cancelPendingPresent();
    exitSettledRef.current = false;
    preOpenFocusRef.current = document.activeElement as HTMLElement | null;
    setMounted(true);
    setPresented(false);
    if (prefersReducedMotion) {
      setPresented(true);
      return;
    }
    rafRef.current = window.requestAnimationFrame(() => {
      rafRef.current = window.requestAnimationFrame(() => {
        rafRef.current = null;
        setPresented(true);
      });
    });
  }, [cancelPendingPresent, clearExitTimer, prefersReducedMotion]);

  useEffect(
    () => () => {
      clearExitTimer();
      cancelPendingPresent();
    },
    [cancelPendingPresent, clearExitTimer],
  );

  return { mounted, presented, open, close, finishExit };
}
