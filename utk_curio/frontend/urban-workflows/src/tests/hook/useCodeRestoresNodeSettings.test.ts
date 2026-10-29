/**
 * Do the per-node settings a spec carries reach the node at load?
 *
 * Read as source, the way `deoverlapOnLoad.test.ts` and
 * `loadPathsMarkDirty.test.ts` read `useCode`: the hook cannot be mounted
 * without the whole provider stack. A load reads each spec node with
 * `nodeMetaFromTrill` and builds it with `buildCodeNode` (`hook/codeNodes.ts`),
 * the two a node the dataflow's doc brings to the canvas is made with too.
 *
 * What is pinned is a specific trap. `nodeMetaFromTrill` copies
 * `metadata.spatialJoin` and `metadata.simpleVis` off each spec node into
 * `nodeMeta`, then `buildCodeNode` builds `node.data` from an EXPLICIT list of
 * options. A setting that is read but missing from that list survives every
 * save (TrillGenerator reads `node.data`) and dies on every load. That is how
 * the Spatial Join in example 15 ran with the default `name` property although
 * the file said `zip` (#262), and how a Simple View pinned to one image column
 * (#276) forgot the choice on reopen. A renamed node header
 * (`metadata.packageTemplateLabel`, #412) must take the same path, and so must
 * the rest of the node settings modal's config (`metadata.packageTemplateConfig`,
 * #412), which goes through a converter on the way in, and a Data Pool's
 * conflict modes (`metadata.dataPool`, #581).
 */
import * as fs from "fs";
import * as path from "path";

const USE_CODE = fs.readFileSync(
    path.join(__dirname, "..", "..", "hook", "useCode.ts"),
    "utf-8",
);
const CODE_NODES = fs.readFileSync(
    path.join(__dirname, "..", "..", "hook", "codeNodes.ts"),
    "utf-8",
);

function buildCodeNodeSource(): string {
    const start = CODE_NODES.indexOf("export function buildCodeNode");
    expect(start).toBeGreaterThan(-1);
    const next = CODE_NODES.indexOf("\nexport ", start + 1);
    return CODE_NODES.slice(start, next === -1 ? undefined : next);
}

const RESTORED_KEYS = [
    "spatialJoin", "simpleVis", "packageTemplateLabel", "packageTemplateConfig", "dataPool", "widgets", "copiedFrom",
    "selections",
];

describe("per-node settings survive a load", () => {
    test("a load reads each spec node with nodeMetaFromTrill and builds it with buildCodeNode", () => {
        expect(USE_CODE).toMatch(/nodeMetaFromTrill\(/);
        expect(USE_CODE).toMatch(/buildCodeNode\(/);
    });

    test.each(RESTORED_KEYS)(
        "loadTrill reads metadata.%s off the spec",
        (key) => {
            // Copied as is, or handed to one converter: `nodeMeta.k =
            // node.metadata.k` or `nodeMeta.k = fromSpec(node.metadata.k)`.
            expect(CODE_NODES).toMatch(
                new RegExp(`nodeMeta\\.${key} = (\\w+\\()?node\\.metadata\\.${key}\\b`),
            );
        },
    );

    test.each(RESTORED_KEYS)(
        "generateCodeNode accepts %s and writes it into node.data",
        (key) => {
            const factory = buildCodeNodeSource();
            // Destructured from the options, with the same default shape as
            // its neighbours...
            expect(factory).toMatch(new RegExp(`^\\s*${key} = undefined,\\s*$`, "m"));
            // ...and placed on data, where TrillGenerator reads it back.
            const literal = factory.slice(factory.indexOf("data: {"));
            expect(literal).toMatch(new RegExp(`^\\s*${key},\\s*$`, "m"));
        },
    );

    test("the options type declares each, so a new call site cannot drop them silently", () => {
        const typeStart = CODE_NODES.indexOf("export type CreateCodeNodeOptions");
        const typeEnd = CODE_NODES.indexOf("export interface CodeNodeRuntime", typeStart);
        expect(typeStart).toBeGreaterThan(-1);
        expect(typeEnd).toBeGreaterThan(typeStart);
        const typeBlock = CODE_NODES.slice(typeStart, typeEnd);
        expect(typeBlock).toMatch(/spatialJoin\?: \{ predicate\?: string; output\?: "pairs" \| "counts" \};/);
        expect(typeBlock).toMatch(/simpleVis\?: \{ imageColumn\?: string \};/);
        expect(typeBlock).toMatch(/packageTemplateLabel\?: string;/);
        expect(typeBlock).toMatch(/packageTemplateConfig\?: Partial<CanvasTemplateConfig>;/);
        expect(typeBlock).toMatch(/dataPool\?: \{ insideChart\?: string; betweenCharts\?: string \};/);
        expect(typeBlock).toMatch(/widgets\?: WidgetDef\[\];/);
        expect(typeBlock).toMatch(/copiedFrom\?: string\[\];/);
        expect(typeBlock).toMatch(/selections\?: SelectionTag\[\];/);
    });

    test("a Map Editor node's edits are in its code: an old save's metadata.editFeatures is left out", () => {
        expect(USE_CODE).not.toMatch(/editFeatures/);
        expect(CODE_NODES).not.toMatch(/editFeatures/);
    });
});
