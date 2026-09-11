import { useCallback, useSyncExternalStore } from "react";
import {
  getAgentDropHoverEdgeId,
  subscribeAgentDropHover,
} from "../utils/agentDropHover";

/** Server/initial snapshot: nothing is ever hovered outside a live drag. */
const NOT_HOVERED = () => false;

/**
 * Is a palette-agent drag currently over *this* edge? (#296)
 *
 * `useSyncExternalStore` rather than a context or canvas state: it compares the
 * derived boolean with `Object.is`, so a hover moving from one edge to another
 * re-renders exactly those two edges, not every edge on the canvas - and
 * `dragover` fires at pointer rate, so that difference is the whole design.
 */
export function useAgentDropHoverEdge(edgeId: string | undefined): boolean {
  const getSnapshot = useCallback(
    () => Boolean(edgeId) && getAgentDropHoverEdgeId() === edgeId,
    [edgeId],
  );
  return useSyncExternalStore(subscribeAgentDropHover, getSnapshot, NOT_HOVERED);
}
