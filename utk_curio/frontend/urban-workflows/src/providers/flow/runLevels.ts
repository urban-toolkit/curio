// The order Run All runs a dataflow in: the edges it follows, the levels of
// nodes it runs one after another, and the nodes a play runs.
import type { Edge, Node } from "reactflow";
import { runKeyWithShared, sharedWidgetsOf } from "../../utils/references/sharedParameters";

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

/**
 * The nodes playing *target* runs: the node, or every node of a list (a
 * scenario's levers, #662), and each ancestor whose output cannot be reused.
 * Read by the in-browser walk and by a run on the server, which reuses the
 * outputs of the other ancestors.
 */
export function nodesToRunUpTo(
    target: string | readonly string[],
    currentNodes: Node[],
    currentEdges: Edge[],
    emittedForInput: Map<string, unknown>,
): { ancestorIds: Set<string>; willRun: Set<string> } {
    const targets = typeof target === "string" ? [target] : [...target];
    const directedEdges = directedEdgesOf(currentEdges);

    const predecessors = new Map<string, string[]>();
    for (const n of currentNodes) predecessors.set(n.id, []);
    for (const e of directedEdges) {
        predecessors.get(e.target)?.push(e.source);
    }

    const ancestorIds = new Set<string>();
    const queue = [...targets];
    while (queue.length > 0) {
        const id = queue.shift()!;
        for (const pred of predecessors.get(id) ?? []) {
            if (!ancestorIds.has(pred)) {
                ancestorIds.add(pred);
                queue.push(pred);
            }
        }
    }
    targets.forEach(id => ancestorIds.add(id));

    // Which ancestors actually need to run again.
    //
    // "It succeeded once" is not enough: a node whose code has changed since
    // that run holds an artifact its current source would not produce, and
    // reusing it made the whole downstream chain report success off stale
    // data. `executedCode` (mirrored in useNodeState) is the source that
    // produced the current output, so a mismatch means re-run.
    //
    // The last clause is what makes invalidation transitive - a node feeding
    // off a re-running ancestor must re-run too, or it would pass the old
    // artifact down while its parent computed a new one.
    const ancestorNodes = currentNodes.filter(n => ancestorIds.has(n.id));
    const ancestorEdges = currentEdges.filter(
        e => ancestorIds.has(e.source) && ancestorIds.has(e.target)
    );
    const willRun = new Set<string>();
    const ancestorLevels = computeTopologicalLevels(ancestorNodes, ancestorEdges);
    // computeTopologicalLevels drops anything inside a cycle. Those nodes
    // still have to be judged, or a cycle upstream of the target would
    // silently remove it from the run.
    const levelled = new Set(ancestorLevels.flat());
    const decisionOrder = [
        ...ancestorLevels,
        ancestorNodes.filter(n => !levelled.has(n.id)).map(n => n.id),
    ];
    // The Parameter nodes' widgets: a node whose code names one runs again
    // when its value changed, though no edge leads from it.
    const shared = sharedWidgetsOf(currentNodes);
    for (const level of decisionOrder) {
        for (const nodeId of level) {
            const node = currentNodes.find(n => n.id === nodeId);
            if (!node) continue;
            // A success on node.data.output, or, for the kinds that never
            // write one there, an emission for the input the node still
            // has. A node whose last run failed always runs again.
            const outputCode = node.data.output?.code;
            const emittedCurrent =
                emittedForInput.has(nodeId) && emittedForInput.get(nodeId) === node.data.input;
            const neverSucceeded =
                outputCode !== "success" && !(outputCode !== "error" && emittedCurrent);
            // #662: the key covers the node's widget values, the shared tags
            // it names and its selection tags' ids too, so a changed value or
            // a new selection counts as changed code.
            const codeChanged =
                node.data.executedCode !== undefined &&
                node.data.executedCode !==
                    runKeyWithShared(node.data.code, node.data.widgets, shared, node.data.selections);
            const upstreamRerunning = ancestorEdges.some(
                e => e.target === nodeId && willRun.has(e.source)
            );
            if (
                targets.includes(nodeId) ||
                neverSucceeded ||
                codeChanged ||
                upstreamRerunning
            ) {
                willRun.add(nodeId);
            }
        }
    }
    return { ancestorIds, willRun };
}
