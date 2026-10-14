import { CURIO_UNIVERSAL_NODE_TYPE } from "../constants";
import { splitCanonicalNodeType } from "../registry/packageKeys";

/**
 * React Flow uses one stable ``node.type`` so the palette map never churns when
 * package descriptors reload. The real dispatcher id stays in ``data.nodeType``.
 */
export function getFlowNodeCanonicalType(node: {
    type?: string | null;
    // `| null` because a ReactFlow node's `data` legitimately is null on some
    // paths; the body already reads it with optional chaining.
    data?: { nodeType?: string | null } | null;
}): string {
    const rf = node.type ?? "";
    if (rf === CURIO_UNIVERSAL_NODE_TYPE) {
        return String(node.data?.nodeType ?? "");
    }
    return rf;
}

/**
 * Strip a trailing ``@<major>`` from a canonical node type. Palette-dragged
 * nodes carry the versioned form (``curio.builtin/vis-vega@1``) while
 * programmatic nodes use the unversioned enum — both coexist in canvases and
 * saved specs, so membership checks against unversioned sets must normalize
 * first (#169). Mirrors the backend ``unversioned_node_type``.
 */
export function unversionedNodeType(nodeType: string): string {
    return splitCanonicalNodeType(nodeType)?.unversioned ?? nodeType;
}

/** ``getFlowNodeCanonicalType`` with the ``@<major>`` suffix stripped. */
export function getUnversionedFlowNodeType(node: {
    type?: string | null;
    data?: { nodeType?: string | null };
}): string {
    return unversionedNodeType(getFlowNodeCanonicalType(node));
}

/**
 * Node kinds that were removed, and the kind a saved dataflow's node of one
 * opens as. Both were Python nodes with starter code, so their code runs
 * unchanged as a Python node's. Kept in sync with `NAMESPACED_TO_LEGACY` in
 * `execution/workflow_spec.py`.
 */
const REPLACED_NODE_TYPES: Readonly<Record<string, string>> = {
    "curio.builtin/raster-calculator": "curio.builtin/computation-analysis",
    "curio.builtin/raster-statistics": "curio.builtin/computation-analysis",
};

/** *nodeType*, or the kind it opens as if it was removed, its `@<major>` kept. */
export function currentNodeType(nodeType: string): string {
    const replacement = REPLACED_NODE_TYPES[unversionedNodeType(nodeType)];
    if (replacement === undefined) return nodeType;
    const major = /@\d+$/.exec(nodeType);
    return replacement + (major ? major[0] : "");
}
