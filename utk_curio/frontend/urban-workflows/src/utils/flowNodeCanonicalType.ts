import { CURIO_UNIVERSAL_NODE_TYPE } from "../constants";

/**
 * React Flow uses one stable ``node.type`` so the palette map never churns when
 * pack descriptors reload. The real dispatcher id stays in ``data.nodeType``.
 */
export function getFlowNodeCanonicalType(node: {
    type?: string | null;
    data?: { nodeType?: string | null };
}): string {
    const rf = node.type ?? "";
    if (rf === CURIO_UNIVERSAL_NODE_TYPE) {
        return String(node.data?.nodeType ?? "");
    }
    return rf;
}
