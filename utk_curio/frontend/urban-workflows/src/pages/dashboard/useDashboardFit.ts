import { RefObject, useEffect } from "react";
import { useReactFlow } from "reactflow";

import { fitViewWithMenuOffset } from "../../utils/fitViewWithMenuOffset";

/**
 * How a dashboard is framed: a thin margin, and never zoomed past 1 so a tile is
 * never blown up beyond the size it was authored at. ``duration: 0`` because an
 * animated fit would still be moving when a resize, or a screenshot, arrives.
 */
export const DASHBOARD_FIT_OPTIONS = { padding: 0.06, maxZoom: 1, duration: 0 } as const;

/** Attempts before giving up, at 50ms each: React Flow has to measure the tiles. */
const MAX_ATTEMPTS = 40;
const RETRY_MS = 50;

/**
 * Frame every pinned tile in the window.
 *
 * Asks for the pinned nodes by id and nothing else. The unpinned ones are
 * ``display: none`` so React Flow never measures them, and a fit that included
 * them would wait forever for dimensions that are never coming.
 *
 * ``maxZoom: 1`` so tiles are never blown up past the size they were authored
 * at: a dashboard of two small charts should not stretch them across a monitor.
 *
 * Retries because measurement is asynchronous and the helper reports whether it
 * managed a real fit, and re-runs from a ResizeObserver so a resized window (or
 * a sidebar appearing) reframes rather than clipping.
 */
export function useDashboardFit(
  pinnedIds: readonly string[],
  containerRef: RefObject<HTMLElement | null>,
): void {
  const reactFlow = useReactFlow();
  // A stable key: the effect must re-run when the set of tiles changes, not on
  // every render that hands it a fresh array.
  const key = [...pinnedIds].sort().join("|");

  useEffect(() => {
    if (!key) return;
    const ids = key.split("|").map((id) => ({ id }));
    let timer: number | undefined;
    let attempts = 0;
    let cancelled = false;

    const attempt = () => {
      if (cancelled) return;
      // duration 0: an animated fit would still be moving when a screenshot or
      // a follow-up resize arrives.
      if (fitViewWithMenuOffset(reactFlow, { ...DASHBOARD_FIT_OPTIONS, nodes: ids })) {
        return;
      }
      if (attempts >= MAX_ATTEMPTS) return;
      attempts += 1;
      timer = window.setTimeout(attempt, RETRY_MS);
    };
    attempt();

    const observer = new ResizeObserver(() => {
      attempts = 0;
      attempt();
    });
    if (containerRef.current) observer.observe(containerRef.current);

    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
      observer.disconnect();
    };
    // containerRef is a ref object and stable; reactFlow is stable per provider.
  }, [key, reactFlow, containerRef]);
}
