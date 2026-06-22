import type { ReactFlowInstance } from "reactflow";
import { fitViewWithMenuOffset } from "./fitViewWithMenuOffset";

export type LinkedNode = { id: string; data: any };

/**
 * Exclusively select every canvas node matching ``isLinked`` and frame them in
 * view. Shared by the dataset palette row and the node DATASET/OUTPUT chip so
 * both highlight the same set of linked nodes. Returns the number of matches
 * (0 → nothing selected, caller may surface a toast).
 */
export function focusLinkedNodes(
  reactFlow: ReactFlowInstance,
  isLinked: (n: LinkedNode) => boolean,
): number {
  const matches = reactFlow.getNodes().filter(isLinked);
  if (matches.length === 0) return 0;
  reactFlow.setNodes((nds) =>
    nds.map((n) => ({
      ...n,
      selected: isLinked(n),
    })),
  );
  fitViewWithMenuOffset(reactFlow, {
    nodes: matches.map((n) => ({ id: n.id })),
    duration: 300,
    padding: 0.3,
  });
  return matches.length;
}
