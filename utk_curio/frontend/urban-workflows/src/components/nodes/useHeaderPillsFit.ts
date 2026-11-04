import { useLayoutEffect, useRef, useState } from "react";

/** The least a node's title shows in its header, about eight characters with
 *  its "…": below it, the header's pills give way. */
export const TITLE_FLOOR_PX = 64;

/**
 * Whether a node header hides its pills (its category, PACKAGE, DATA and
 * OUTPUT pills): only while its title would show less than
 * `TITLE_FLOOR_PX`, so a narrow node shows its name before its pills, and a
 * node that has room shows them as it always did.
 *
 * The header's width is read through a ResizeObserver, and the title is
 * measured after each render with the pills shown. Once hidden, the pills
 * stay hidden until the header is as wide as they and the title's floor need,
 * so they never flicker in and out. *resetKey* changes when the title or the
 * pills do, and the pills are shown and measured anew.
 */
export function useHeaderPillsFit(header: HTMLElement | null, resetKey: string): boolean {
  const [hidden, setHidden] = useState(false);
  const [width, setWidth] = useState(0);
  // The header width at which the pills fit again beside the title's floor.
  const fitsAt = useRef(0);

  useLayoutEffect(() => {
    if (!header || typeof ResizeObserver === "undefined") return;
    setWidth(header.clientWidth);
    const observer = new ResizeObserver(() => setWidth(header.clientWidth));
    observer.observe(header);
    return () => observer.disconnect();
  }, [header]);

  useLayoutEffect(() => {
    setHidden(false);
  }, [resetKey]);

  useLayoutEffect(() => {
    if (!header) return;
    if (hidden) {
      if (width >= fitsAt.current) setHidden(false);
      return;
    }
    const title = header.querySelector<HTMLElement>("[data-curio-node-title]");
    if (!title) return;
    const shown = title.clientWidth;
    const whole = title.scrollWidth;
    const floor = Math.min(TITLE_FLOOR_PX, whole);
    if (whole > shown + 1 && shown < floor) {
      fitsAt.current = header.clientWidth + (floor - shown);
      setHidden(true);
    }
  }, [header, hidden, width, resetKey]);

  return hidden;
}
