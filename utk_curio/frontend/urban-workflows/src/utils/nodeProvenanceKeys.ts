import type { NodeExecRecord } from "../providers/ProvenanceProvider";

/**
 * Per-node runs are keyed by node id. Dataflows saved before #448 carry them
 * under everything after the first dash of `nodeType + "-" + nodeId`
 * (`loading@1-<uuid>` for a data-loading node), where the Provenance tab never
 * finds them. Move each such entry under the longest node id it ends with,
 * merging with runs already filed there in run order. Keys that already are a
 * node id, or that match no node, are kept as they are.
 */
export function rekeyNodeProvenance(
    saved: Record<string, NodeExecRecord[]>,
    nodeIds: string[],
): Record<string, NodeExecRecord[]> {
    const ids = new Set(nodeIds);
    const byLength = [...nodeIds].sort((a, b) => b.length - a.length);
    const out: Record<string, NodeExecRecord[]> = {};
    for (const [key, records] of Object.entries(saved)) {
        if (!Array.isArray(records)) continue;
        const target = ids.has(key) ? key : byLength.find((id) => key.endsWith("-" + id)) ?? key;
        out[target] = out[target] ? [...out[target], ...records].sort((a, b) => a.id - b.id) : records;
    }
    return out;
}
