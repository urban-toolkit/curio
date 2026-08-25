import { CURIO_UNIVERSAL_NODE_TYPE } from "../constants";
import { splitCanonicalNodeType } from "../registry/packageKeys";

/**
 * React Flow uses one stable ``node.type`` so the palette map never churns when
 * package descriptors reload. The real dispatcher id stays in ``data.nodeType``.
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

/**
 * Strip the ``@<major>`` manifest version from a canonical dispatcher id
 * (``curio.builtin/merge-flow@1`` → ``curio.builtin/merge-flow``). Ids that
 * don't match the versioned ``<pkg>/<template>@<major>`` shape pass through.
 */
export function stripNodeTypeVersion(nodeType: string): string {
    return splitCanonicalNodeType(nodeType)?.unversioned ?? nodeType;
}

/**
 * Canonical type with the manifest version stripped — for ``NodeType`` enum
 * comparisons only. Registry/descriptor lookups need the full versioned id
 * and must keep using ``getFlowNodeCanonicalType``.
 */
export function unversionedFlowNodeType(
    node: Parameters<typeof getFlowNodeCanonicalType>[0],
): string {
    return stripNodeTypeVersion(getFlowNodeCanonicalType(node));
}
