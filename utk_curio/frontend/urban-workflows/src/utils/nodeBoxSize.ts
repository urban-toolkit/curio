import {
    DEFAULT_NODE_HEIGHT,
    DEFAULT_NODE_WIDTH,
    MIN_NODE_HEIGHT,
    MIN_NODE_WIDTH,
    MINIMIZED_NODE_HEIGHT,
    MINIMIZED_NODE_WIDTH,
} from "../constants";
import { getFlowNodeCanonicalType } from "./flowNodeCanonicalType";
// Deep import rather than `../registry`, whose barrel pulls in every adapter
// (vega included). This module has to stay a leaf so layout code can use it.
import { tryGetNodeDescriptor } from "../registry/nodeRegistry";

export interface NodeBox {
    width: number;
    height: number;
}

export interface MeasurableNode {
    type?: string | null;
    data?: { nodeType?: string | null; nodeWidth?: unknown; nodeHeight?: unknown } | null;
}

/** `typeof v === "number"` with NaN/Infinity excluded, mirroring the renderer. */
function finiteNumber(value: unknown): number | undefined {
    return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

/**
 * The box a node actually occupies once `NodeContainer` has rendered it.
 *
 * This mirrors `components/styles.tsx` rather than approximating it, because a
 * layout pass that guesses wrong is worse than none: under-estimate and the
 * overlap it was meant to remove comes back the moment the node inflates.
 *
 * Two rules here are easy to get wrong and both matter:
 *
 * 1. A `noContent` template (merge-flow) mounts minimized and bails out of BOTH
 *    resize effects, so its manifest size is its literal footprint -- 50x180,
 *    sub-minimum and staying that way.
 * 2. The mount clamp snaps a sub-minimum size to the DEFAULT, not to the
 *    minimum. A node asking for `nodeWidth: 120` renders at 525, not 200.
 *
 * When no descriptor is registered the answer is 525x350, deliberately. An
 * anonymous shared view registers no packages at all, and a spec can name an
 * uninstalled one; `UnresolvedNode`'s small placeholder shell is a transient
 * that inflates to the default in place as soon as the package arrives.
 * Over-estimating costs a little slack, under-estimating costs the bug.
 */
export function resolveNodeBoxSize(node: MeasurableNode): NodeBox {
    const container = tryGetNodeDescriptor(getFlowNodeCanonicalType(node) as any)
        ?.adapter?.container;
    const data = node?.data ?? undefined;

    if (container?.noContent) {
        return {
            width: finiteNumber(container.nodeWidth) ?? MINIMIZED_NODE_WIDTH,
            height: finiteNumber(container.nodeHeight) ?? MINIMIZED_NODE_HEIGHT,
        };
    }

    const width = finiteNumber(data?.nodeWidth) ?? finiteNumber(container?.nodeWidth);
    const height = finiteNumber(data?.nodeHeight) ?? finiteNumber(container?.nodeHeight);

    return {
        width: width === undefined || width < MIN_NODE_WIDTH ? DEFAULT_NODE_WIDTH : width,
        height: height === undefined || height < MIN_NODE_HEIGHT ? DEFAULT_NODE_HEIGHT : height,
    };
}
