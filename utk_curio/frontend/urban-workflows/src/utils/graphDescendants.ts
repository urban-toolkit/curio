/**
 * The nodes a node's output reaches: every node after it along data edges,
 * in no particular order. Interaction edges (a selection between linked views)
 * carry no data, so they are not followed. The Interaction node marks these
 * stale when its edit log changes, and runs them when asked to update.
 *
 * Duck-typed edges, so this module needs no `reactflow` import.
 */
import { isDataEdge } from "./inputSlots";

type EdgeLike = { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null };

export function descendantsOf(nodeId: string, edges: readonly EdgeLike[]): string[] {
  const next = new Map<string, string[]>();
  for (const edge of edges) {
    if (!isDataEdge(edge)) continue;
    const list = next.get(edge.source) ?? [];
    list.push(edge.target);
    next.set(edge.source, list);
  }
  const seen = new Set<string>([nodeId]);
  const order: string[] = [];
  const queue = [...(next.get(nodeId) ?? [])];
  while (queue.length > 0) {
    const id = queue.shift() as string;
    if (seen.has(id)) continue;
    seen.add(id);
    order.push(id);
    queue.push(...(next.get(id) ?? []));
  }
  return order;
}
