/**
 * The order a dataflow reads in as a list: every node after the nodes it
 * reads from. Export as notebook writes its cells in this order and the
 * canvas's notebook view lays its cells out in it, so the two always agree.
 *
 * Chains stay together: each node is followed by the nodes it feeds, as soon
 * as their last input has been placed, before the next node waiting. Of the
 * nodes one feeds, the newest connection comes first, so a cell added under
 * another in the notebook view (wired from it) lands right below it. The nodes
 * nothing feeds start the chains, in the order given.
 * Nodes caught in a cycle are never ready, so they are appended at the end in
 * the order given rather than dropped: a view that lost them would hide a node
 * from its user (agent edits can wire a cycle, since they skip `onConnect`'s
 * check).
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

  const waiting = nodes.filter((n) => (inDegree.get(n.id) ?? 0) === 0);
  const result: N[] = [];

  while (waiting.length > 0) {
    const node = waiting.shift()!;
    result.push(node);
    const ready: N[] = [];
    for (const depId of dependents.get(node.id) ?? []) {
      const newDeg = (inDegree.get(depId) ?? 1) - 1;
      inDegree.set(depId, newDeg);
      if (newDeg === 0) {
        const depNode = byId.get(depId);
        if (depNode) ready.push(depNode);
      }
    }
    // Ahead of everything already waiting, newest connection first (the
    // edges come oldest first).
    waiting.unshift(...ready.reverse());
  }

  const placed = new Set(result.map((n) => n.id));
  for (const node of nodes) {
    if (!placed.has(node.id)) result.push(node);
  }

  return result;
}
