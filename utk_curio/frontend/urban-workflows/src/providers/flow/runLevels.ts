// The order Run All runs a dataflow in: the edges it follows, and the levels
// of nodes it runs one after another.
import type { Edge, Node } from "reactflow";

/** The edges a run orders nodes by: every edge but a two-way interaction link. */
export function directedEdgesOf<E extends { sourceHandle?: string | null; targetHandle?: string | null }>(
    edges: E[],
): E[] {
    return edges.filter(e => !(e.sourceHandle === "in/out" && e.targetHandle === "in/out"));
}

export function computeTopologicalLevels(nodes: Node[], edges: Edge[]): string[][] {
    const directedEdges = directedEdgesOf(edges);

    const inDegree = new Map<string, number>();
    const successors = new Map<string, string[]>();
    for (const n of nodes) { inDegree.set(n.id, 0); successors.set(n.id, []); }
    for (const e of directedEdges) {
        inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1);
        successors.get(e.source)!.push(e.target);
    }

    const roots = nodes.filter(n => inDegree.get(n.id) === 0);
    const isolated = roots.filter(n => (successors.get(n.id)?.length ?? 0) === 0).map(n => n.id);
    const sources  = roots.filter(n => (successors.get(n.id)?.length ?? 0) > 0).map(n => n.id);

    if (isolated.length === 0 && sources.length === 0) return [];

    const levels: string[][] = [];
    if (isolated.length > 0) levels.push(isolated);
    if (sources.length > 0) levels.push(sources);

    const remaining = new Map(inDegree);
    const visited = new Set([...isolated, ...sources]);
    let queue = sources;

    while (queue.length > 0) {
        const next: string[] = [];
        for (const id of queue) {
            for (const succ of successors.get(id) ?? []) {
                remaining.set(succ, (remaining.get(succ) ?? 0) - 1);
                if (remaining.get(succ) === 0 && !visited.has(succ)) {
                    next.push(succ);
                    visited.add(succ);
                }
            }
        }
        if (next.length > 0) levels.push(next);
        queue = next;
    }
    return levels;
}
