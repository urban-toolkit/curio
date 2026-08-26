import { useLayoutEffect, useRef } from "react";

export interface AutoGrowTextarea {
  /** Attach to the textarea whose height should track its content. */
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
}

/**
 * Content-driven auto-grow for chat composer textareas (memo dev/77).
 *
 * The textarea starts at its natural one-row height, grows with content up to
 * `maxHeightPx`, then scrolls internally. Height is written directly to the
 * DOM from `scrollHeight` — never held in React state — so typing costs no
 * extra re-renders and there is no stale-height flicker.
 *
 * Measurement keys on `value`, not on keystrokes: programmatic updates
 * (suggested-prompt prefills, composePrompt, the post-send reset to "")
 * re-measure exactly like typed input.
 */
export function useAutoGrowTextarea({
  value,
  maxHeightPx,
}: {
  /** The textarea's controlled value — re-measured whenever it changes. */
  value: string;
  /** Growth cap; past it the textarea scrolls its own content. */
  maxHeightPx: number;
}): AutoGrowTextarea {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Layout effect so the height lands before paint — no one-frame jump.
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    // Collapse first so scrollHeight reflects the current content, not the
    // previous (possibly larger) height.
    el.style.height = "auto";
    const measured = el.scrollHeight;
    // jsdom measures 0 — fall back to the rows-based natural height.
    el.style.height = measured > 0 ? `${Math.min(measured, maxHeightPx)}px` : "";
    // A scrollbar exists only once clamped; hidden otherwise so growth never
    // flashes a transient scrollbar.
    el.style.overflowY = measured > maxHeightPx ? "auto" : "hidden";
  }, [value, maxHeightPx]);

  return { textareaRef };
}
