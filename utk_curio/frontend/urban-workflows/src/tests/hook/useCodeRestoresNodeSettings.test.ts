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
 * pinned to one image column (#276) forgot the choice on reopen. A renamed
 * node header (`metadata.packageTemplateLabel`, #412) must take the same path,
 * and so must the rest of the node settings modal's config
 * (`metadata.packageTemplateConfig`, #412), which goes through a converter on
 * the way in, and a Data Pool's conflict modes (`metadata.dataPool`, #581).
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

const RESTORED_KEYS = [
    "spatialJoin", "simpleVis", "packageTemplateLabel", "packageTemplateConfig", "dataPool", "widgets", "copiedFrom",
    "selections",
    // #662: an Edit Features node's edit list.
    "editFeatures",
];

describe("per-node settings survive a load", () => {
    test.each(RESTORED_KEYS)(
        "loadTrill reads metadata.%s off the spec",
        (key) => {
            // Copied as is, or handed to one converter: `nodeMeta.k =
            // node.metadata.k` or `nodeMeta.k = fromSpec(node.metadata.k)`.
            expect(USE_CODE).toMatch(
                new RegExp(`nodeMeta\\.${key} = (\\w+\\()?node\\.metadata\\.${key}\\b`),
            );
        },
    );

    test.each(RESTORED_KEYS)(
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

    test("the options type declares each, so a new call site cannot drop them silently", () => {
        const typeStart = USE_CODE.indexOf("CreateCodeNodeOptions");
        const typeEnd = USE_CODE.indexOf("interface IUseCode", typeStart);
        const typeBlock = USE_CODE.slice(typeStart, typeEnd);
        expect(typeBlock).toMatch(/spatialJoin\?: \{ nameProperty\?: string; output\?: "points" \| "polygons" \};/);
        expect(typeBlock).toMatch(/simpleVis\?: \{ imageColumn\?: string \};/);
        expect(typeBlock).toMatch(/packageTemplateLabel\?: string;/);
        expect(typeBlock).toMatch(/packageTemplateConfig\?: Partial<CanvasTemplateConfig>;/);
        expect(typeBlock).toMatch(/dataPool\?: \{ insideChart\?: string; betweenCharts\?: string \};/);
        expect(typeBlock).toMatch(/widgets\?: WidgetDef\[\];/);
        expect(typeBlock).toMatch(/copiedFrom\?: string\[\];/);
        expect(typeBlock).toMatch(/selections\?: SelectionTag\[\];/);
        expect(typeBlock).toMatch(/editFeatures\?: EditFeaturesSettings;/);
    });
});

describe("a minimized node comes back minimized", () => {
    // Top-level on the spec node, as `width` and `height` are, not in metadata.
    test("loadTrill reads minimized off the spec node", () => {
        expect(USE_CODE).toMatch(/if\(node\.minimized === true\)\s*nodeMeta\.minimized = true;/);
    });

    test("generateCodeNode accepts minimized and writes it into node.data", () => {
        const factory = generateCodeNodeSource();
        expect(factory).toMatch(/^\s*minimized = undefined,\s*$/m);
        expect(factory.slice(factory.indexOf("data: {"))).toMatch(/^\s*minimized,\s*$/m);
    });
});

describe("a controls-only node comes back controls-only", () => {
    test("loadTrill reads controlsOnly off the spec node", () => {
        expect(USE_CODE).toMatch(/if\(node\.controlsOnly === true\)\s*nodeMeta\.controlsOnly = true;/);
        expect(USE_CODE).toMatch(/nodeMeta\.controlsOnlyWidth = node\.controlsOnlyWidth;/);
        expect(USE_CODE).toMatch(/nodeMeta\.controlsOnlyHeight = node\.controlsOnlyHeight;/);
        expect(USE_CODE).toMatch(/if\(node\.dashboardControlsOnly === true\)\s*nodeMeta\.dashboardControlsOnly = true;/);
        expect(USE_CODE).toMatch(/if\(node\.dashboardSeparateWidgets === true\)\s*nodeMeta\.dashboardSeparateWidgets = true;/);
        expect(USE_CODE).toMatch(/nodeMeta\.dashboardWidgetLayout = node\.dashboardWidgetLayout;/);
    });

    test("generateCodeNode accepts controlsOnly and writes it into node.data", () => {
        const factory = generateCodeNodeSource();
        expect(factory).toMatch(/^\s*controlsOnly = undefined,\s*$/m);
        expect(factory.slice(factory.indexOf("data: {"))).toMatch(/^\s*controlsOnly,\s*$/m);
    });
});
