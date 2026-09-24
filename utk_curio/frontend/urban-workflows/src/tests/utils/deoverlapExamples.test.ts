/**
 * Do the shipped examples and the runtime pass agree?
 *
 * Two halves fixed the same problem from opposite ends, and they have to meet
 * cleanly. `scripts/tidy_example_layout.py` rewrote `docs/examples/*.json` into
 * a layered layout with an 80px gutter; `deoverlapNodes` is the safety net that
 * separates whatever else reaches the canvas, at an 8px collision floor.
 *
 * That means the pass must be a NO-OP on every shipped example. If it ever
 * starts moving one, either an example was hand-edited into a collision or the
 * gutter was raised past what the offline layout produces -- and every gallery
 * project would then be relayouted on open, silently diverging from the file on
 * disk the first time anyone saved.
 *
 * The second test is the other direction: fed a genuinely overlapping spec, the
 * pass has to fix it. Coordinates there are the real ones example 04 shipped
 * with before the relayout, whose two Data Transformation nodes overlapped by
 * 521x32.
 */
import * as fs from "fs";
import * as path from "path";

import { deoverlapNodes } from "../../utils/deoverlapLayout";

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..", "..");
const EXAMPLES_DIR = path.join(REPO_ROOT, "docs", "examples");
const BUILTIN_MANIFEST = path.join(
    REPO_ROOT, "packages", "curio.builtin@1", "manifest.json",
);

/**
 * Node sizes straight from the package manifest, so this test measures what the
 * app measures without needing the registry booted.
 */
function manifestSizes(): Record<string, { width: number; height: number }> {
    const manifest = JSON.parse(fs.readFileSync(BUILTIN_MANIFEST, "utf-8"));
    const sizes: Record<string, { width: number; height: number }> = {};
    for (const template of manifest.templates ?? []) {
        const style = template.containerStyle ?? {};
        sizes[`curio.builtin/${template.id}`] = {
            width: typeof style.nodeWidth === "number" ? style.nodeWidth : 525,
            height: typeof style.nodeHeight === "number" ? style.nodeHeight : 350,
        };
    }
    return sizes;
}

const SIZES = manifestSizes();

function measure(node: any) {
    const data = node?.data ?? {};
    if (typeof data.nodeWidth === "number" && typeof data.nodeHeight === "number") {
        return { width: data.nodeWidth, height: data.nodeHeight };
    }
    const base = SIZES[String(data.nodeType).split("@")[0]] ?? { width: 525, height: 350 };
    return {
        width: typeof data.nodeWidth === "number" ? data.nodeWidth : base.width,
        height: typeof data.nodeHeight === "number" ? data.nodeHeight : base.height,
    };
}

/** A spec's nodes shaped the way `loadTrill` hands them to the pass. */
function toFlowNodes(spec: any) {
    return spec.dataflow.nodes.map((n: any) => ({
        id: n.id,
        position: { x: n.x, y: n.y },
        data: {
            nodeType: n.type,
            ...(typeof n.width === "number" ? { nodeWidth: n.width } : {}),
            ...(typeof n.height === "number" ? { nodeHeight: n.height } : {}),
        },
    }));
}

const exampleFiles = fs
    .readdirSync(EXAMPLES_DIR)
    .filter((name) => /^\d\d-.*\.json$/.test(name))
    .sort();

describe("the shipped examples need no de-overlapping", () => {
    test("there are examples to check", () => {
        expect(exampleFiles.length).toBeGreaterThan(0);
    });

    test.each(exampleFiles)("%s loads unchanged", (name) => {
        const spec = JSON.parse(fs.readFileSync(path.join(EXAMPLES_DIR, name), "utf-8"));
        const nodes = toFlowNodes(spec);

        // `toBe`: the pass returns the very same array when it finds nothing to
        // do, so this is the strongest possible statement that it stayed out of
        // the way.
        expect(deoverlapNodes(nodes, { measure })).toBe(nodes);
    });
});

describe("a genuinely overlapping spec is repaired", () => {
    test("separates the pair example 04 used to ship with", () => {
        const nodes = [
            { id: "2704287e", position: { x: 1200, y: 1518 }, data: { nodeType: "curio.builtin/data-transformation" } },
            { id: "f4cb8452", position: { x: 1204, y: 1836 }, data: { nodeType: "curio.builtin/data-transformation" } },
        ];

        const result = deoverlapNodes(nodes, { measure });

        expect(result).not.toBe(nodes);
        const [a, b] = result.map((n: any) => n.position);
        const gapY = Math.max(a.y - (b.y + 350), b.y - (a.y + 350));
        const gapX = Math.max(a.x - (b.x + 525), b.x - (a.x + 525));
        expect(gapX >= 8 || gapY >= 8).toBe(true);
    });
});
