import { useCallback, useMemo, useRef } from "react";
import type { FocusEvent, UIEvent } from "react";
import { flushSync } from "react-dom";
import { useStoreApi, type ReactFlowState } from "reactflow";
import { paneInSight, setViewportNow } from "../utils/fitViewWithMenuOffset";

/** What the handlers read and move: React Flow's view and its d3 zoom. */
type FlowViewStore = { getState: () => Pick<ReactFlowState, "transform" | "d3Zoom" | "d3Selection"> };

/** A box on the page: its edges, in pixels from the window's top left corner. */
export type Box = { left: number; top: number; right: number; bottom: number };

/** The handlers a canvas spreads on its `<ReactFlow>`. */
export type FlowInSight = {
  onScroll: (event: UIEvent<HTMLDivElement>) => void;
  onFocus: (event: FocusEvent<HTMLDivElement>) => void;
};

/**
 * What the browser shows on a canvas stays in sight, and React Flow's own
 * element, `.react-flow`, stays unscrolled: spread the result on a
 * `<ReactFlow>` inside its provider.
 *
 * The element hides its overflow and React Flow draws a pan as its viewport's
 * transform, but the browser still scrolls the element to bring something in
 * it into view: a node or a control past the canvas's right or bottom edge
 * that Tab reaches, a field a node focuses, a find in the page, Playwright's
 * scroll before a click. React Flow 11 never scrolls it back, so the dot grid,
 * the pane and the zoom buttons then sat that far off the window until a
 * reload, and every fit, drop and pan landed that far off where it meant to.
 * Nor can the browser scroll the element to a negative offset, so a node left
 * of the view or above it, which Tab reaches too, stayed out of sight.
 *
 * - `onScroll` turns the element's scroll into the same pan and puts the
 *   element back at 0,0: what the browser brought into view stays where it is
 *   drawn.
 * - `onFocus` pans a node the keyboard reaches, from any side, into the part of
 *   the canvas the rail, the bar and the dataflow's title leave in sight
 *   (`panIntoSight`).
 *
 * React Flow 12 does both: it scrolls its element back (12.4.3, xyflow#4991),
 * and pans to a node Tab reaches outside the view (12.7.0,
 * `autoPanOnNodeFocus`). With *moves* false, for a view held where it is (the
 * notebook view's, whose page scrolls instead), the element is only put back.
 */
export function useFlowInSight(moves = true): FlowInSight {
  const store = useStoreApi();
  // The node the keyboard reached, until the browser's next frame: its scroll
  // of that node into view comes then, as a scroll of the element.
  const reached = useRef<HTMLElement | null>(null);
  const onScroll = useCallback(
    (event: UIEvent<HTMLDivElement>) => {
      // A scroll inside a node, its editor's or its table's, is its own.
      if (event.target !== event.currentTarget) return;
      const flow = event.currentTarget;
      // Drawn at once, so the node read below is where the page shows it.
      flushSync(() => scrollAsPan(flow, moves ? store : null));
      // A node taller or wider than the sight, which the browser then scrolled
      // to the window's edge, under the bar or the rail, is brought back.
      const node = reached.current;
      if (moves && node && node === document.activeElement) showInSight(node, flow, store);
    },
    [store, moves],
  );
  const onFocus = useCallback(
    (event: FocusEvent<HTMLDivElement>) => {
      const node = event.target;
      if (!moves || !isNodeOf(node, event.currentTarget) || !reachedByKeyboard(node)) return;
      reached.current = node;
      const forget = () => {
        if (reached.current === node) reached.current = null;
      };
      if (typeof requestAnimationFrame === "function") requestAnimationFrame(forget);
      else setTimeout(forget, 0);
      showInSight(node, event.currentTarget, store);
    },
    [store, moves],
  );
  return useMemo(() => ({ onScroll, onFocus }), [onScroll, onFocus]);
}

/**
 * Put *element* back at 0,0 and pan *store*'s view by as much as the element
 * was scrolled, set at once. The browser fires a scroll when it draws its next
 * frame, before it paints it, and the handler draws the new view before it
 * returns, so no frame shows the canvas moved.
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

/**
 * How far to move *box* to bring it into *sight*, across and down, each way
 * on its own: nothing when it is in sight, to the middle when it is wholly
 * out of it, else the least distance. A box larger than the sight shows its
 * left or top edge, where a node has its header.
 */
export function panIntoSight(box: Box, sight: Box): [number, number] {
  return [
    distanceInto(box.left, box.right, sight.left, sight.right),
    distanceInto(box.top, box.bottom, sight.top, sight.bottom),
  ];
}

function distanceInto(start: number, end: number, from: number, to: number): number {
  if (end - start > to - from) return from - start;
  if (start >= from && end <= to) return 0;
  if (end <= from || start >= to) return (from + to - start - end) / 2;
  return start < from ? from - start : to - end;
}

/** Whether *target* is one of *flow*'s own nodes, not one of a flow drawn inside a node. */
function isNodeOf(target: EventTarget, flow: HTMLElement): target is HTMLElement {
  return (
    target instanceof HTMLElement &&
    target.classList.contains("react-flow__node") &&
    target.parentElement?.closest(".react-flow") === flow
  );
}

/** Whether the browser shows *element*'s focus as the keyboard's: Tab's, not a click's. */
function reachedByKeyboard(element: Element): boolean {
  try {
    return element.matches(":focus-visible");
  } catch {
    return false;
  }
}

/**
 * Pan *store*'s view so *node* is in the sight of *flow*, set at once and
 * drawn before the handler returns. After a node's focus events the browser
 * scrolls it into view, and it then finds the node there: it scrolls nothing.
 */
function showInSight(node: HTMLElement, flow: HTMLElement, store: FlowViewStore): void {
  const sight = sightOf(flow);
  if (!sight) return;
  const r = node.getBoundingClientRect();
  const [across, down] = panIntoSight({ left: r.left, top: r.top, right: r.right, bottom: r.bottom }, sight);
  if (across === 0 && down === 0) return;
  const [x, y, zoom] = store.getState().transform;
  flushSync(() => {
    setViewportNow(store, { x: x + across, y: y + down, zoom });
  });
}

/** The part of *flow* in sight, on the page: right of the rail, below the bar and the title. */
function sightOf(flow: HTMLElement): Box | null {
  const sight = paneInSight();
  if (!sight) return null;
  const pane = flow.getBoundingClientRect();
  const left = pane.left + sight.left;
  const top = pane.top + sight.top;
  return { left, top, right: left + sight.width, bottom: top + sight.height };
}
