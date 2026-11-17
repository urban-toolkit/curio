import { useCallback } from "react";
import type { UIEvent } from "react";
import { useStoreApi, type ReactFlowState } from "reactflow";
import { setViewportNow } from "../utils/fitViewWithMenuOffset";

/** What the handler reads and moves: React Flow's view and its d3 zoom. */
type FlowViewStore = { getState: () => Pick<ReactFlowState, "transform" | "d3Zoom" | "d3Selection"> };

/**
 * Keeps React Flow's own element, `.react-flow`, unscrolled: spread the
 * handler on a `<ReactFlow onScroll>` inside its provider.
 *
 * The element hides its overflow and React Flow draws a pan as its viewport's
 * transform, but the browser still scrolls the element to bring something in it
 * into view: a node or a control past the canvas's edge that Tab reaches, a
 * field a node focuses, a find in the page, Playwright's scroll before a click.
 * React Flow 11 never scrolls it back, so the dot grid, the pane and the zoom
 * buttons then sat that far off the window until a reload, and every fit, drop
 * and pan landed that far off where it meant to.
 *
 * The scroll becomes the same pan, and the element is back at 0,0: what the
 * browser brought into view stays where it is drawn. React Flow 12 does the two
 * apart: it scrolls its element back (12.4.3, xyflow#4991), and pans to a node
 * Tab reaches outside the view (12.7.0, `autoPanOnNodeFocus`). With *pans*
 * false, for a view that is held where it is (the notebook view's), the element
 * is only put back.
 */
export function useFlowScrollAsPan(pans = true): (event: UIEvent<HTMLDivElement>) => void {
  const store = useStoreApi();
  return useCallback(
    (event: UIEvent<HTMLDivElement>) => {
      // A scroll inside a node, its editor's or its table's, is its own.
      if (event.target !== event.currentTarget) return;
      scrollAsPan(event.currentTarget, pans ? store : null);
    },
    [store, pans],
  );
}

/**
 * Put *element* back at 0,0 and pan *store*'s view by as much as the element
 * was scrolled, set at once. The browser fires a scroll when it draws its next
 * frame, before it paints it, and the view's new transform reaches the page in
 * the microtask React renders it in, so no frame shows the canvas moved.
 *
 * A scroll at 0,0, which putting the element back fires, does nothing: a view
 * set at once stops a move still on its way, a fit's.
 */
export function scrollAsPan(element: HTMLElement, store: FlowViewStore | null): void {
  const across = element.scrollLeft;
  const down = element.scrollTop;
  if (across === 0 && down === 0) return;
  element.scrollLeft = 0;
  element.scrollTop = 0;
  if (!store) return;
  const [x, y, zoom] = store.getState().transform;
  setViewportNow(store, { x: x - across, y: y - down, zoom });
}
