import type { Node } from "reactflow";
import { getNodesBounds } from "reactflow";

/**
 * How far the dataflow viewport may pan, in flow coordinates.
 *
 * This used to be one static box, `[[-2000,-2000],[6000,6000]]`, which meant a
 * wide graph simply had a region you could not reach: nodes past x=6000 were
 * visible in a fitView and then unreachable the moment you dragged, because
 * interactive pan/zoom goes through d3-zoom's `constrain()` while `fitView` and
 * `setViewport` call `d3Zoom.transform` and bypass it (#234). Getting there was
 * easy - `usePosition` places each palette node at `maxX + 800`, so the ninth
 * one is already outside, and a notebook import strides 700px per level.
 *
 * The clamp itself is not the mistake, and deleting it is not the fix: it was
 * removed once and restored (44365b01), because `minZoom 0.05` with no clamp
 * lets one trackpad gesture carry the dataflow somewhere there is no way back
 * from short of a reload. So the bound stays - it just tracks the work now.
 *
 * The floor is the old static box. The extent is that box UNIONED with the
 * nodes' own bounds, so it can only ever grow: an empty canvas behaves exactly
 * as it did before, and no change can make a previously reachable region
 * unreachable.
 */
export type CanvasExtent = [[number, number], [number, number]];

export const CANVAS_EXTENT_FLOOR: CanvasExtent = [
    [-2000, -2000],
    [6000, 6000],
];

/** Room to overshoot past the outermost node, so an edge node can be centered
 *  rather than jammed against the boundary. */
const PADDING = 2000;

/**
 * Bounds are rounded outward to this grid.
 *
 * React Flow re-applies `translateExtent` through `useStoreUpdater`, whose
 * effect keys on the value's identity - so an extent recomputed from raw node
 * positions would call `d3Zoom.translateExtent()` on every frame of a drag.
 * Quantizing means the numbers stay put until a node crosses a boundary, which
 * lets the caller memoize on them and keep the array identity stable.
 */
const QUANTUM = 1000;

function isFiniteNumber(value: unknown): value is number {
    return typeof value === "number" && Number.isFinite(value);
}

const floorTo = (v: number) => Math.floor(v / QUANTUM) * QUANTUM;
const ceilTo = (v: number) => Math.ceil(v / QUANTUM) * QUANTUM;

/**
 * The pan bound for a given set of nodes.
 *
 * Unmeasured nodes are fine here. React Flow fills `width`/`height` only after
 * it measures the DOM, so `getNodesBounds` can report a zero-area box during a
 * load - but the *positions* are already right, and `PADDING` is far larger
 * than any node, so the result is still a correct (if slightly generous)
 * bound. That is why this does not gate on measurement the way
 * `fitViewWithMenuOffset` has to: a fit that is off by a node's height frames
 * the wrong thing, whereas a bound that is off by a node's height is invisible.
 */
export function computeTranslateExtent(nodes: Node[] | undefined | null): CanvasExtent {
    if (!nodes || nodes.length === 0) return CANVAS_EXTENT_FLOOR;

    const bounds = getNodesBounds(nodes);
    if (
        !bounds ||
        !isFiniteNumber(bounds.x) ||
        !isFiniteNumber(bounds.y) ||
        !isFiniteNumber(bounds.width) ||
        !isFiniteNumber(bounds.height)
    ) {
        // A node with a NaN position would otherwise poison the whole extent
        // and lock panning entirely. The floor is always safe.
        return CANVAS_EXTENT_FLOOR;
    }

    const [[floorMinX, floorMinY], [floorMaxX, floorMaxY]] = CANVAS_EXTENT_FLOOR;

    return [
        [
            Math.min(floorMinX, floorTo(bounds.x - PADDING)),
            Math.min(floorMinY, floorTo(bounds.y - PADDING)),
        ],
        [
            Math.max(floorMaxX, ceilTo(bounds.x + bounds.width + PADDING)),
            Math.max(floorMaxY, ceilTo(bounds.y + bounds.height + PADDING)),
        ],
    ];
}
