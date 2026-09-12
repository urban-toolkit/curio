/**
 * Does `deoverlapNodes` hold the three properties the load path depends on?
 *
 * It runs on every dataflow that reaches the canvas, so the bar is higher than
 * "usually separates things":
 *
 *  - **Idempotent by reference.** A clean layout must come back as the SAME
 *    array. Opening a project has to be a read, and a pass that returned a fresh
 *    array of fresh nodes every time would defeat that at the first identity
 *    check downstream.
 *  - **Deterministic.** Two clients loading the same spec must agree, or
 *    collaboration broadcasts a layout one peer never computed.
 *  - **Terminating.** A degenerate spec (twenty nodes at the origin) must not
 *    hang the app.
 *
 * The gutter of 8 is measured rather than chosen -- see the constant's comment.
 * `measure` is injected throughout so none of this needs the node registry.
 */
import {
    MAX_COLUMN_DROP,
    NODE_GUTTER_X,
    NODE_GUTTER_Y,
    deoverlapNodes,
} from "../../utils/deoverlapLayout";

const BOX = { width: 100, height: 50 };
const measure = () => BOX;

function node(id: string, x: number, y: number) {
    return { id, position: { x, y }, data: { nodeType: "test" } };
}

function boxesOf(nodes: any[], size = BOX) {
    return nodes
        .filter((n) => typeof n.position?.x === "number")
        .map((n) => ({ x: n.position.x, y: n.position.y, w: size.width, h: size.height }));
}

function separated(boxes: any[], gx = NODE_GUTTER_X, gy = NODE_GUTTER_Y): boolean {
    for (let i = 0; i < boxes.length; i++) {
        for (let j = i + 1; j < boxes.length; j++) {
            const a = boxes[i];
            const b = boxes[j];
            const gapX = Math.max(a.x - (b.x + b.w), b.x - (a.x + a.w));
            const gapY = Math.max(a.y - (b.y + b.h), b.y - (a.y + a.h));
            if (gapX < gx && gapY < gy) return false;
        }
    }
    return true;
}

function positionMap(nodes: any[]) {
    return Object.fromEntries(nodes.map((n) => [n.id, `${n.position?.x},${n.position?.y}`]));
}

describe("deoverlapNodes", () => {
    describe("idempotence", () => {
        test("a clean layout comes back as the same array", () => {
            const input = [node("a", 0, 0), node("b", 500, 0), node("c", 0, 500)];

            // `toBe`, not `toEqual`: identity is the guarantee, so that opening a
            // tidy project cannot be mistaken for an edit.
            expect(deoverlapNodes(input, { measure })).toBe(input);
        });

        test("a pair sitting at exactly the gutter is already clean", () => {
            const input = [node("a", 0, 0), node("b", 100 + NODE_GUTTER_X, 0)];

            expect(deoverlapNodes(input, { measure })).toBe(input);
        });

        test("running it twice changes nothing the second time", () => {
            const once = deoverlapNodes(
                [node("a", 0, 0), node("b", 10, 10), node("c", 20, 20)],
                { measure },
            );

            expect(deoverlapNodes(once, { measure })).toBe(once);
        });

        test("fractional coordinates survive a second pass", () => {
            // 04 carries y values like 1234.3. Rounding away from the obstacle
            // can only widen a gap, so the second pass must find nothing to do.
            const once = deoverlapNodes(
                [node("a", 0.4, 0.7), node("b", 10.2, 10.9), node("c", 20.1, 20.3)],
                { measure },
            );

            expect(deoverlapNodes(once, { measure })).toBe(once);
        });

        test("an unmoved node inside a dirty layout keeps its identity", () => {
            const input = [node("a", 0, 0), node("b", 10, 10), node("far", 4000, 4000)];
            const result = deoverlapNodes(input, { measure });

            expect(result).not.toBe(input);
            expect(result[2]).toBe(input[2]);
        });
    });

    describe("determinism", () => {
        test("a permuted input gives an identical layout", () => {
            const base = [
                node("a", 0, 0),
                node("b", 10, 10),
                node("c", 20, 20),
                node("d", 30, 30),
                node("e", 5, 25),
            ];
            const expected = positionMap(deoverlapNodes(base, { measure }));

            // Fixed rotations rather than a shuffle: a flaky test here would be
            // worse than no test.
            for (let shift = 1; shift < base.length; shift++) {
                const rotated = [...base.slice(shift), ...base.slice(0, shift)];
                expect(positionMap(deoverlapNodes(rotated, { measure }))).toEqual(expected);
            }
        });

        test("reversing the input gives an identical layout", () => {
            const base = [node("a", 0, 0), node("b", 10, 10), node("c", 20, 20)];
            const forward = positionMap(deoverlapNodes(base, { measure }));

            expect(positionMap(deoverlapNodes([...base].reverse(), { measure }))).toEqual(
                forward,
            );
        });
    });

    describe("separation", () => {
        test("one pass clears the gutter for every pair", () => {
            const input = [
                node("a", 0, 0),
                node("b", 5, 5),
                node("c", 10, 10),
                node("d", 15, 15),
                node("e", 20, 20),
            ];

            expect(separated(boxesOf(deoverlapNodes(input, { measure })))).toBe(true);
        });

        test("nodes of different sizes are separated on their real boxes", () => {
            const sizes: Record<string, { width: number; height: number }> = {
                wide: { width: 525, height: 350 },
                tall: { width: 100, height: 1600 },
                sliver: { width: 50, height: 180 },
            };
            const input = [node("wide", 0, 0), node("tall", 10, 10), node("sliver", 20, 20)];
            const result = deoverlapNodes(input, {
                measure: (n: any) => sizes[n.id],
            });

            const boxes = result.map((n: any) => ({
                x: n.position.x,
                y: n.position.y,
                w: sizes[n.id].width,
                h: sizes[n.id].height,
            }));
            expect(separated(boxes)).toBe(true);
        });

        test("twenty coincident nodes resolve, and spill sideways", () => {
            // Default-sized boxes, so the column genuinely runs out of room:
            // 20 x (350 + 8) is 7160, well past the cap.
            const full = { width: 525, height: 350 };
            const input = Array.from({ length: 20 }, (_, i) => node(`n${i}`, 0, 0));
            const result = deoverlapNodes(input, { measure: () => full });

            expect(separated(boxesOf(result, full))).toBe(true);
            // The cap is what stops this becoming one unscrollable ribbon.
            const ys = result.map((n: any) => n.position.y);
            expect(Math.max(...ys) - Math.min(...ys)).toBeLessThanOrEqual(MAX_COLUMN_DROP);
            expect(new Set(result.map((n: any) => n.position.x)).size).toBeGreaterThan(1);
        });

        test("a short stack stays in one column", () => {
            // The flip side of the cap: it must not fire when there is room.
            const input = Array.from({ length: 6 }, (_, i) => node(`n${i}`, 0, 0));
            const result = deoverlapNodes(input, { measure });

            expect(separated(boxesOf(result))).toBe(true);
            expect(new Set(result.map((n: any) => n.position.x)).size).toBe(1);
        });
    });

    describe("degenerate input", () => {
        test("an empty array is returned as-is", () => {
            const input: any[] = [];
            expect(deoverlapNodes(input, { measure })).toBe(input);
        });

        test("a single node is returned as-is", () => {
            const input = [node("only", 0, 0)];
            expect(deoverlapNodes(input, { measure })).toBe(input);
        });

        test("a node with no usable position is passed through untouched", () => {
            // Parking it at the origin would shove every real node aside.
            const input: any[] = [
                node("a", 0, 0),
                node("b", 10, 10),
                { id: "nowhere", data: { nodeType: "test" } },
                { id: "nan", position: { x: NaN, y: 0 }, data: { nodeType: "test" } },
            ];
            const result = deoverlapNodes(input, { measure });

            expect(result[2]).toBe(input[2]);
            expect(result[3]).toBe(input[3]);
        });

        test("only `position` is written", () => {
            const input = [node("a", 0, 0), node("b", 10, 10)];
            const result = deoverlapNodes(input, { measure });

            // `data.workflowPosition` belongs to dashboard mode; writing it here
            // would pin what TrillGenerator persists for the rest of time.
            expect(result[1].data).toBe(input[1].data);
            expect((result[1] as any).data.workflowPosition).toBeUndefined();
        });
    });

    test("the gutter constants are the measured ones", () => {
        // 0/1/8 each flag exactly the specs that are genuinely broken; 12 starts
        // flagging 03's deliberate 10px gap and 16 Interaction_Vega_Simple's 14px
        // horizontal ones. Raising these relayouts arrangements someone chose.
        expect(NODE_GUTTER_X).toBe(8);
        expect(NODE_GUTTER_Y).toBe(8);
    });
});
