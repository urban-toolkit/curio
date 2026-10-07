import { useCallback, useState, type DragEvent } from "react";

/**
 * Lets a card dragged out of a canvas drawer through to the canvas beneath it.
 *
 * An open drawer's scrim covers the whole window, so without this it takes the
 * drop and the card lands nowhere. While a card's drag lasts, the root carries
 * `data-dragging="true"`, and the shell's stylesheet
 * (CatalogDrawerShell.module.css) then takes the pointer off the root and the
 * scrim and leaves it on the panel.
 *
 * Every drawer spreads the result on its overlay root: a card's dragstart and
 * dragend bubble up to it. A drag counts only when it starts on a draggable
 * element, so text dragged out of a field leaves the scrim where it is.
 */
export function useDrawerDragThrough() {
  const [dragging, setDragging] = useState(false);
  const onDragStart = useCallback((event: DragEvent<HTMLElement>) => {
    const { target } = event;
    if (target instanceof Element && target.closest('[draggable="true"]')) setDragging(true);
  }, []);
  const onDragEnd = useCallback(() => setDragging(false), []);
  return {
    "data-dragging": dragging ? ("true" as const) : undefined,
    onDragStart,
    onDragEnd,
  };
}
