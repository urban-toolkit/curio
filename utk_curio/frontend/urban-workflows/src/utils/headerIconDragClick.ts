import { useCallback, useRef } from "react";

/** Max pointer movement (px) still treated as a click, not a canvas drag. */
const CLICK_DRAG_THRESHOLD_PX = 6;

export type HeaderIconDragClickHandlers = {
  onPointerDown: (e: React.PointerEvent) => void;
  onPointerUp: (e: React.PointerEvent) => void;
  /** Swallow native click so drag-release does not double-fire actions. */
  onClick: (e: React.MouseEvent) => void;
};

/**
 * Pointer handlers for header icons on React Flow nodes: a short press activates
 * the action; press-and-drag lets the parent node move (do not use `nodrag`).
 */
export function useHeaderIconDragClick(onActivate: () => void): HeaderIconDragClickHandlers {
  const downRef = useRef<{ x: number; y: number } | null>(null);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    downRef.current = { x: e.clientX, y: e.clientY };
  }, []);

  const onPointerUp = useCallback(
    (e: React.PointerEvent) => {
      const down = downRef.current;
      downRef.current = null;
      if (!down) return;
      const dx = e.clientX - down.x;
      const dy = e.clientY - down.y;
      if (dx * dx + dy * dy > CLICK_DRAG_THRESHOLD_PX * CLICK_DRAG_THRESHOLD_PX) return;
      e.stopPropagation();
      onActivate();
    },
    [onActivate],
  );

  const onClick = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
  }, []);

  return { onPointerDown, onPointerUp, onClick };
}
