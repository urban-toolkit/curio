import type { ReactFlowInstance, ReactFlowState, Rect } from "reactflow";
import { boundsInSight, fitBoundsWithMenuOffset, fitViewWithMenuOffset } from "./fitViewWithMenuOffset";

export type LinkedNode = { id: string; data: any };

/** What a selection asks of React Flow's store (`useStoreApi()`). */
export type SelectionStore = { getState: () => Pick<ReactFlowState, "getNodes" | "addSelectedNodes"> };

/**
 * Make the canvas nodes *ids* its selection, alone, as a click on a node makes
 * it: React Flow's own selection (`addSelectedNodes`), which hands the canvas's
 * `onNodesChange` a `select` change for each node, by its id, and unselects
 * the connections. With the multi-selection key held, the nodes join the
 * selection, as clicked ones do.
 *
 * Never `reactFlow.setNodes` on Curio's canvas. The canvas hands React Flow its
 * nodes as props, so that call hands its updater React Flow's own copy of the
 * nodes and makes what it returns the canvas's whole node list, and React Flow
 * takes that copy from the canvas in an effect after each commit. A node the
 * canvas took from the dataflow's doc in that commit, another tab's or an
 * agent's, is then dropped, and the canvas writes its removal into the doc,
 * for everyone (docs/ARCHITECTURE.md, "The canvas to the doc").
 */
export function selectOnly(flowStore: SelectionStore, ids: string[]): void {
  flowStore.getState().addSelectedNodes(ids);
}

/** How a focus frames what it shows: animated, with room around it. */
const FRAMING = { duration: 300, padding: 0.3 };

/** Frame the nodes `ids` in view, animated and with room around them: how a
 *  focus frames its nodes, and how a double-click on a node frames it. */
export function frameNodesInView(reactFlow: ReactFlowInstance, ids: string[]): boolean {
  return fitViewWithMenuOffset(reactFlow, {
    nodes: ids.map((id) => ({ id })),
    ...FRAMING,
  });
}

/**
 * Bring *rect* (canvas units) into sight, framed as `frameNodesInView` frames
 * nodes but never zoomed in, for what is drawn beside React Flow, such as a
 * collapsed scenario's box (#769). A rect already wholly in sight leaves the
 * view as it is. Returns whether the view moved.
 */
export function revealRectInView(reactFlow: ReactFlowInstance, rect: Rect): boolean {
  if (boundsInSight(reactFlow, rect)) return false;
  return fitBoundsWithMenuOffset(reactFlow, rect, { ...FRAMING, maxZoom: reactFlow.getViewport().zoom });
}

/**
 * Exclusively select every canvas node matching ``isLinked`` and frame them in
 * view. Shared by the dataset and model palette rows and the node
 * DATASET/OUTPUT chip so all of them highlight the same set of linked nodes.
 * Returns the number of matches (0 → nothing selected, caller may surface a
 * toast). The selection is React Flow's own, by node id (`selectOnly`), made
 * in *flowStore*, React Flow's store of the same canvas (`useStoreApi()`).
 *
 * ``reveal`` is the flow's ``revealNodes``: in the notebook view it scrolls the
 * first match's cell into view and returns true, and the canvas fit is skipped.
 */
export function focusLinkedNodes(
  reactFlow: ReactFlowInstance,
  flowStore: SelectionStore,
  isLinked: (n: LinkedNode) => boolean,
  reveal?: (nodeIds: string[]) => boolean,
): number {
  const ids = reactFlow.getNodes().filter(isLinked).map((n) => n.id);
  if (ids.length === 0) return 0;
  selectOnly(flowStore, ids);
  if (reveal?.(ids)) return ids.length;
  frameNodesInView(reactFlow, ids);
  return ids.length;
}
