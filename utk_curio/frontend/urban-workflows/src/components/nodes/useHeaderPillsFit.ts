import { useLayoutEffect, useRef, useState } from "react";

/** The least a node's title shows in its header, about eight characters with
 *  its "…": below it, the header's pills make room. */
export const TITLE_FLOOR_PX = 64;

/**
 * Whether a node header shows its pills compact: the category pill left out,
 * and the PACKAGE, DATASET and OUTPUT pills as their icons alone, each still
 * the button it is, with its name and its tooltip. Only while its title would
 * show less than `TITLE_FLOOR_PX` beside the whole pills, so a narrow node
 * shows its name, and a node that has room shows its pills whole.
 *
 * The header's width is read through a ResizeObserver, and the title is
 * measured after each render with the pills whole. Once compact, the pills
 * stay compact until the header is as wide as the whole pills and the title's
 * floor need, so they never flicker between the two. *resetKey* changes when
 * the title or the pills do, and the pills are shown whole and measured anew.
 */
export function useHeaderPillsFit(header: HTMLElement | null, resetKey: string): boolean {
  const [compact, setCompact] = useState(false);
  const [width, setWidth] = useState(0);
  // The header width at which the whole pills fit again beside the title's floor.
  const fitsAt = useRef(0);

  useLayoutEffect(() => {
    if (!header || typeof ResizeObserver === "undefined") return;
    setWidth(header.clientWidth);
    const observer = new ResizeObserver(() => setWidth(header.clientWidth));
    observer.observe(header);
    return () => observer.disconnect();
  }, [header]);

  useLayoutEffect(() => {
    setCompact(false);
  }, [resetKey]);

  useLayoutEffect(() => {
    if (!header) return;
    if (compact) {
      if (width >= fitsAt.current) setCompact(false);
      return;
    }
    const title = header.querySelector<HTMLElement>("[data-curio-node-title]");
    if (!title) return;
    const shown = title.clientWidth;
    const whole = title.scrollWidth;
    const floor = Math.min(TITLE_FLOOR_PX, whole);
    if (whole > shown + 1 && shown < floor) {
      fitsAt.current = header.clientWidth + (floor - shown);
      setCompact(true);
    }
  }, [header, compact, width, resetKey]);

  return compact;
}
