import { useCallback, useEffect, useRef } from "react";
import { OnMove, useStoreApi, Viewport } from "reactflow";

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
 */
export function useViewportMotionHint(): ViewportMotionHint {
  const store = useStoreApi();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

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
    (event: MouseEvent | TouchEvent | null) => (event ? moving() : settle()),
    [moving, settle],
  );

  useEffect(() => settle, [settle]);

  return { onMoveStart: moving, onMove, onMoveEnd: settle };
}

export default useViewportMotionHint;
