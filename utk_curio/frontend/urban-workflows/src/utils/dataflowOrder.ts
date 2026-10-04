/**
 * The order a dataflow reads in as a list: every node after the nodes it
 * reads from. Export as notebook writes its cells in this order and the
 * canvas's notebook view lays its cells out in it, so the two always agree.
 *
 * One first-in first-out queue: the nodes nothing feeds come first, in the
 * order given, then each node as soon as its last input has been placed.
 * Nodes caught in a cycle never reach the queue, so they are appended at the
 * end in the order given rather than dropped: a view that lost them would
 * hide a node from its user (agent edits can wire a cycle, since they skip
 * `onConnect`'s check).
 *
 * Callers pass only the edges that order a run. An interaction link carries
 * no data, so each caller filters it out in its own representation: the
 * export by the saved `type: "Interaction"`, the canvas by `directedEdgesOf`.
 */
export function dataflowOrder<N extends { id: string }>(
  nodes: readonly N[],
  directedEdges: readonly { source: string; target: string }[],
): N[] {
  const inDegree = new Map<string, number>(nodes.map((n) => [n.id, 0]));
  const dependents = new Map<string, string[]>(nodes.map((n) => [n.id, []]));
  const byId = new Map<string, N>(nodes.map((n) => [n.id, n]));

  for (const edge of directedEdges) {
    inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1);
    dependents.get(edge.source)?.push(edge.target);
  }

  const queue = nodes.filter((n) => (inDegree.get(n.id) ?? 0) === 0);
  const result: N[] = [];

  while (queue.length > 0) {
    const node = queue.shift()!;
    result.push(node);
    for (const depId of dependents.get(node.id) ?? []) {
      const newDeg = (inDegree.get(depId) ?? 1) - 1;
      inDegree.set(depId, newDeg);
      if (newDeg === 0) {
        const depNode = byId.get(depId);
        if (depNode) queue.push(depNode);
      }
    }
  }

  const placed = new Set(result.map((n) => n.id));
  for (const node of nodes) {
    if (!placed.has(node.id)) result.push(node);
  }

  return result;
}
