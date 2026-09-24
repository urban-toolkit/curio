import { MeasurableNode, NodeBox, resolveNodeBoxSize } from "./nodeBoxSize";

/**
 * Minimum clear space between two node boxes, in canvas units.
 *
 * 8 is measured, not picked. Running the conflict predicate over every dataflow
 * shipped in the repo, a gutter of 0, 1 or 8 flags exactly the specs that are
 * genuinely broken and nothing else; at 12 it starts flagging
 * `03-vega-lite-linked-temporal-charts`, whose 10px vertical gap is deliberate,
 * and at 16 `dataflows/Interaction_Vega_Simple`, whose 14px horizontal gaps are
 * too. 8 is the largest value that never relayouts a deliberate arrangement.
 *
 * This is a collision floor, NOT an authoring stride. `NotebookConvertor`'s
 * 700/450 and `dashboardLayout`'s spacing describe how to lay a graph out from
 * scratch; reusing either here would rewrite canvases that are perfectly fine.
 */
export const NODE_GUTTER_X = 8;
export const NODE_GUTTER_Y = 8;

/**
 * How far a node may be pushed down before it spills sideways instead.
 *
 * Roughly six default rows. Mirrors `NotebookConvertor.MAX_ROWS_PER_LEVEL` and
 * its reason: without a cap, a spec with twenty coincident nodes becomes one
 * 9000px column nobody scrolls through.
 */
export const MAX_COLUMN_DROP = 2100;

interface Box {
    x: number;
    y: number;
    w: number;
    h: number;
}

export interface DeoverlapOptions {
    gutterX?: number;
    gutterY?: number;
    /** Injectable so tests (and callers with their own sizing) need no registry. */
    measure?: (node: MeasurableNode) => NodeBox;
}

type PositionedNode = MeasurableNode & {
    id?: unknown;
    position?: { x?: unknown; y?: unknown } | null;
};

function gapX(a: Box, b: Box): number {
    return Math.max(a.x - (b.x + b.w), b.x - (a.x + a.w));
}

function gapY(a: Box, b: Box): number {
    return Math.max(a.y - (b.y + b.h), b.y - (a.y + a.h));
}

/**
 * Two boxes conflict when NEITHER axis clears its gutter.
 *
 * Strictly less-than on both, so a pair sitting at exactly the gutter is already
 * clean. That is the hinge the idempotence guarantee turns on.
 */
function conflicts(a: Box, b: Box, gutterX: number, gutterY: number): boolean {
    return gapX(a, b) < gutterX && gapY(a, b) < gutterY;
}

/**
 * Separate overlapping nodes, moving as little as possible.
 *
 * Nothing in the app corrects node positions: `loadTrill` copies a spec's `x`/`y`
 * straight onto the canvas, so a legacy file, a hand-edited spec or a dataflow
 * saved before a node grew renders with its boxes on top of each other. This is
 * the safety net for that.
 *
 * Three properties it has to have, and how each is obtained:
 *
 * - **Idempotent.** A layout with no conflicts returns the SAME ARRAY, by
 *   reference. That is a fast path rather than a comparison after the fact, so
 *   "clean input is untouched" is true by construction. Phase 2 leaves the
 *   result pairwise conflict-free, so a second call short-circuits in phase 1.
 * - **Deterministic.** The only ordering is a total sort on `(x, y, id)`; a
 *   permuted input gives an identical output. No randomness, no dependence on
 *   array order or object key order.
 * - **Terminating.** Nodes are only ever pushed down or right, so every push
 *   strictly increases `x + y`, and the reachable coordinates are finite over
 *   the placed set. A node settles in at most `2n + 2` pushes; the step budget
 *   below is belt and braces, not the mechanism.
 *
 * Rejected alternatives: a rectangle-collision relaxation is not idempotent in
 * the strong sense (float residue from half-pushes, three mutually overlapping
 * boxes oscillate, the fixed point depends on the iteration count), and column
 * snapping destroys deliberate offsets -- which is exactly what a safety net
 * must not do.
 *
 * Only `position` is written. Never `data.workflowPosition`: that key is set by
 * dashboard mode alone, and its mere presence changes which coordinate
 * `TrillGenerator` persists.
 */
export function deoverlapNodes<T extends PositionedNode>(
    nodes: T[],
    options: DeoverlapOptions = {},
): T[] {
    const {
        gutterX = NODE_GUTTER_X,
        gutterY = NODE_GUTTER_Y,
        measure = resolveNodeBoxSize,
    } = options;

    if (!Array.isArray(nodes) || nodes.length < 2) return nodes;

    const boxes: (Box | null)[] = nodes.map((node) => {
        const position = node?.position;
        const x = position?.x;
        const y = position?.y;
        // A node with no usable position is passed through untouched rather than
        // parked at the origin, where it would shove everything else aside.
        if (typeof x !== "number" || !Number.isFinite(x)) return null;
        if (typeof y !== "number" || !Number.isFinite(y)) return null;
        const { width, height } = measure(node);
        return { x, y, w: width, h: height };
    });

    const live: number[] = [];
    boxes.forEach((box, index) => {
        if (box) live.push(index);
    });

    // Phase 1 -- detect. The idempotence guarantee lives here.
    let violated = false;
    outer: for (let a = 0; a < live.length; a++) {
        for (let b = a + 1; b < live.length; b++) {
            if (conflicts(boxes[live[a]]!, boxes[live[b]]!, gutterX, gutterY)) {
                violated = true;
                break outer;
            }
        }
    }
    if (!violated) return nodes;

    // Phase 2 -- resolve, in a canonical order so the result cannot depend on
    // how the caller happened to build the array.
    const order = [...live].sort((i, j) => {
        const a = boxes[i]!;
        const b = boxes[j]!;
        return (
            a.x - b.x ||
            a.y - b.y ||
            String(nodes[i]?.id ?? i).localeCompare(String(nodes[j]?.id ?? j))
        );
    });

    const placed: Box[] = [];
    const resolved: (Box | undefined)[] = new Array(nodes.length);
    const budget = 4 * live.length + 8;

    for (const index of order) {
        const home = boxes[index]!;
        const box: Box = { ...home };
        let steps = 0;

        for (;;) {
            const obstacle = placed.find((other) => conflicts(box, other, gutterX, gutterY));
            if (!obstacle || steps++ >= budget) break;

            // Round away from the obstacle: that can only ever widen the gap, so
            // a fractional authored coordinate does not re-trigger next time.
            const downY = Math.ceil(obstacle.y + obstacle.h + gutterY);
            const rightX = Math.ceil(obstacle.x + obstacle.w + gutterX);
            const costDown = downY - box.y;
            const costRight = rightX - box.x;

            // Ties go down: default boxes are wider than tall, so a coincident
            // cluster fans into a column, which is how a dataflow reads.
            if (downY - home.y <= MAX_COLUMN_DROP && costDown <= costRight) {
                box.y = downY;
            } else {
                box.x = rightX;
            }
        }

        placed.push(box);
        resolved[index] = box;
    }

    return nodes.map((node, index) => {
        const box = resolved[index];
        const home = boxes[index];
        // An unmoved node keeps its object identity, not just its numbers.
        if (!box || !home || (box.x === home.x && box.y === home.y)) return node;
        return { ...node, position: { ...(node.position ?? {}), x: box.x, y: box.y } };
    });
}
