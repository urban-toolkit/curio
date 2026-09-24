/**
 * Do the per-node settings a spec carries reach the node at load?
 *
 * Read as source, the way `deoverlapOnLoad.test.ts` and
 * `loadPathsMarkDirty.test.ts` read this hook: `useCode` cannot be mounted
 * without the whole provider stack.
 *
 * What is pinned is a specific trap. `loadTrill` copies `metadata.spatialJoin`
 * and `metadata.simpleVis` off each spec node into `nodeMeta`, then hands
 * `nodeMeta` to `generateCodeNode`, which builds `node.data` from an EXPLICIT
 * list of options. A setting that is read in the loop but missing from that
 * list survives every save (TrillGenerator reads `node.data`) and dies on
 * every load. That is how the Spatial Join in example 15 ran with the default
 * `name` property although the file said `zip` (#262), and how a Simple View
 * pinned to one image column (#276) forgot the choice on reopen.
 */
import * as fs from "fs";
import * as path from "path";

const USE_CODE = fs.readFileSync(
    path.join(__dirname, "..", "..", "hook", "useCode.ts"),
    "utf-8",
);

function generateCodeNodeSource(): string {
    const start = USE_CODE.indexOf("const generateCodeNode");
    const end = USE_CODE.indexOf("const createCodeNode", start);
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    return USE_CODE.slice(start, end);
}

describe("per-node settings survive a load", () => {
    test.each(["spatialJoin", "simpleVis"])(
        "loadTrill reads metadata.%s off the spec",
        (key) => {
            expect(USE_CODE).toContain(`nodeMeta.${key} = node.metadata.${key}`);
        },
    );

    test.each(["spatialJoin", "simpleVis"])(
        "generateCodeNode accepts %s and writes it into node.data",
        (key) => {
            const factory = generateCodeNodeSource();
            // Destructured from the options, with the same default shape as
            // its neighbours...
            expect(factory).toMatch(new RegExp(`^\\s*${key} = undefined,\\s*$`, "m"));
            // ...and placed on data, where TrillGenerator reads it back.
            const literal = factory.slice(factory.indexOf("data: {"));
            expect(literal).toMatch(new RegExp(`^\\s*${key},\\s*$`, "m"));
        },
    );

    test("the options type declares both, so a new call site cannot drop them silently", () => {
        const typeStart = USE_CODE.indexOf("CreateCodeNodeOptions");
        const typeEnd = USE_CODE.indexOf("interface IUseCode", typeStart);
        const typeBlock = USE_CODE.slice(typeStart, typeEnd);
        expect(typeBlock).toMatch(/spatialJoin\?: \{ nameProperty\?: string; output\?: "points" \| "polygons" \};/);
        expect(typeBlock).toMatch(/simpleVis\?: \{ imageColumn\?: string \};/);
    });
});
