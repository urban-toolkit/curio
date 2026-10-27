import { useCallback, useEffect, useRef } from "react";
import { OnMove, useStoreApi, Viewport } from "reactflow";
import { hideTooltip } from "../components/tooltip/tooltipStore";

/** The class on a flow's wrapper that gives its viewport ``will-change`` (MainCanvas.css). */
export const VIEWPORT_MOVING_CLASS = "curio-viewport-moving";

/** How long after the last move of a gesture the viewport keeps its layer. */
export const VIEWPORT_SETTLE_MS = 250;

export interface ViewportMotionHint {
  onMoveStart: OnMove;
  /** React Flow passes d3's source event, which is null for a programmatic move. */
  onMove: (event: MouseEvent | TouchEvent | null, viewport: Viewport) => void;
  onMoveEnd: OnMove;
}

/**
 * The viewport's GPU layer, only while the user pans or zooms it (#533).
 *
 * A ``will-change: transform`` layer pans smoothly, but Chrome keeps it painted
 * at the zoom it was rasterized at: after a fit, the nodes' text stayed a
 * scaled bitmap until something repainted it. So the hint is on while a
 * gesture moves the viewport and off once the gesture settles, and the canvas
 * is then painted at the zoom it shows.
 *
 * React Flow sends ``onMoveStart`` and ``onMoveEnd`` for gestures only. A fit,
 * ``setViewport`` or ``setCenter`` reaches ``onMove`` with no event, so it never
 * takes the hint, and one that lands mid-gesture drops it. ``onMoveEnd`` comes
 * only when the view changed: a press on the pane that does not move it ends
 * no gesture, and the settle timer drops the hint then.
 *
 * Spread the result on a ``<ReactFlow>`` inside its provider. The class goes on
 * that flow's own wrapper, and the rule reaches only its own viewport, not a
 * flow drawn inside one of its nodes.
 *
 * Any move of the view, a gesture's or a fit's, also hides the Curio tooltip:
 * the target it was placed beside is somewhere else now. React Flow reports a
 * fit that lands where the view already is as a move too (each d3 zoom event
 * reaches ``onMove``); that one moves nothing, so a tooltip shown or on its way
 * stays. On a slow page the load's fit can land that way after the pointer
 * has come to rest on a target.
 */
export function useViewportMotionHint(): ViewportMotionHint {
  const store = useStoreApi();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The view before React Flow's last change of it: its store holds the new
  // view by the time ``onMove`` is called.
  const before = useRef<Viewport | null>(null);

  useEffect(
    () =>
      store.subscribe((state, prev) => {
        if (state.transform === prev.transform) return;
        const [x, y, zoom] = prev.transform;
        before.current = { x, y, zoom };
      }),
    [store],
  );

  const settle = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
    store.getState().domNode?.classList.remove(VIEWPORT_MOVING_CLASS);
  }, [store]);

  const moving = useCallback(() => {
    store.getState().domNode?.classList.add(VIEWPORT_MOVING_CLASS);
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(settle, VIEWPORT_SETTLE_MS);
  }, [store, settle]);

  const onMove = useCallback(
    (event: MouseEvent | TouchEvent | null, viewport: Viewport) => {
      // As React Flow's own viewChanged tells a move from none.
      const was = before.current;
      if (!was || was.x !== viewport.x || was.y !== viewport.y || was.zoom !== viewport.zoom) hideTooltip();
      if (event) moving();
      else settle();
    },
    [moving, settle],
  );

  useEffect(() => settle, [settle]);

  return { onMoveStart: moving, onMove, onMoveEnd: settle };
}

export default useViewportMotionHint;
