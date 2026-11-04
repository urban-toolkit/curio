/**
 * Does `resolveNodeBoxSize` report the box a node actually renders at?
 *
 * It exists to feed `deoverlapLayout`, and a layout pass that measures wrong is
 * worse than none: under-estimate a node and the overlap it was meant to remove
 * comes straight back the moment the node inflates. So this pins the rules in
 * `components/styles.tsx` that are easy to read past -- `noContent` templates
 * keeping a sub-minimum footprint, the mount clamp snapping a too-small size
 * to the DEFAULT rather than to the minimum, and a node saved minimized
 * mounting as its chip.
 */
import { faCircle } from "@fortawesome/free-solid-svg-icons";
import { Position } from "reactflow";

import { CURIO_UNIVERSAL_NODE_TYPE, NodeType, SupportedType } from "../../constants";
import { clearPackageNodes, registerNode } from "../../registry/nodeRegistry";
import { ContainerConfig, NodeBehaviorHook, NodeDescriptor } from "../../registry/types";
import * as fs from "fs";
import * as path from "path";

import { clampNodeBox, minimizedChipBox, resolveNodeBoxSize } from "../../utils/nodeBoxSize";

const noopBehavior: NodeBehaviorHook = () => ({});

function descriptor(id: string, container: ContainerConfig): NodeDescriptor {
    return {
        id: id as NodeType,
        category: "data",
        label: id,
        icon: faCircle,
        inputPorts: [],
        outputPorts: [{ types: [SupportedType.DATAFRAME] }],
        editor: "code",
        inPalette: true,
        paletteOrder: 1,
        description: "",
        hasCode: true,
        hasWidgets: false,
        hasGrammar: false,
        adapter: {
            handles: [{ id: "out", type: "source", position: Position.Right }],
            editor: { code: true, grammar: false, widgets: false },
            container,
            useNodeBehavior: noopBehavior,
        },
    };
}

/** A node exactly as `loadTrill`/the palette build them: one React Flow type,
 *  the real dispatcher id in `data.nodeType`. */
function node(nodeType: string, data: Record<string, unknown> = {}) {
    return { type: CURIO_UNIVERSAL_NODE_TYPE, data: { nodeType, ...data } };
}

describe("resolveNodeBoxSize", () => {
    afterEach(() => {
        clearPackageNodes();
    });

    test("an unregistered node type measures as the default box", () => {
        // The anonymous shared view registers no packages at all, and a spec can
        // name an uninstalled one. 525x350 over-estimates a placeholder shell on
        // purpose: that shell inflates to exactly this the moment it resolves.
        expect(resolveNodeBoxSize(node("some.package/never-installed@1"))).toEqual({
            width: 525,
            height: 350,
        });
    });

    test("a template size is used when the template sets one", () => {
        registerNode(descriptor("curio.builtin/spatial-join@1", {
            nodeWidth: 280,
            nodeHeight: 170,
        }));

        expect(resolveNodeBoxSize(node("curio.builtin/spatial-join@1"))).toEqual({
            width: 280,
            height: 170,
        });
    });

    test("a noContent template keeps its sub-minimum footprint", () => {
        // A package template that declares a 50x180 icon-only chip. Both resize
        // effects in NodeContainer bail on noContent, so 50x180 is the literal
        // rendered size -- not clamped up to 200x150, and not the 525x350
        // default. `source: "package"` so afterEach's clearPackageNodes drops it.
        registerNode({
            ...descriptor("acme.test/icon-chip@1", {
                noContent: true,
                nodeWidth: 50,
                nodeHeight: 180,
            }),
            source: "package",
        });

        expect(resolveNodeBoxSize(node("acme.test/icon-chip@1"))).toEqual({
            width: 50,
            height: 180,
        });
    });

    test("a noContent template with no size falls back to the minimized chip", () => {
        registerNode(descriptor("curio.builtin/chip@1", { noContent: true }));

        expect(resolveNodeBoxSize(node("curio.builtin/chip@1"))).toEqual({
            width: 250,
            height: 40,
        });
    });

    // A node saved minimized opens as its chip, its icon and title, so the
    // load's layout pass measures the chip: chips laid out close together stay
    // where they were, and chips the chip's width makes overlap are moved apart.
    test("a node saved minimized measures as its chip, whatever size it opens back to", () => {
        registerNode(descriptor("curio.builtin/vis-vega@1", {}));

        expect(
            resolveNodeBoxSize(
                node("curio.builtin/vis-vega@1", { nodeWidth: 640, nodeHeight: 480, minimized: true }),
            ),
        ).toEqual({ width: 250, height: 40 });
    });

    // #1235: a chip's handle resizes the chip alone, so a longer title shows.
    test("a resized chip measures at its own size, not the size it opens back to", () => {
        registerNode(descriptor("curio.builtin/vis-vega@1", {}));

        expect(
            resolveNodeBoxSize(
                node("curio.builtin/vis-vega@1", {
                    nodeWidth: 640, nodeHeight: 480, minimized: true, minimizedWidth: 180, minimizedHeight: 72,
                }),
            ),
        ).toEqual({ width: 180, height: 72 });
        // Open, it is the size it opens back to.
        expect(
            resolveNodeBoxSize(
                node("curio.builtin/vis-vega@1", { nodeWidth: 640, nodeHeight: 480, minimizedWidth: 180, minimizedHeight: 72 }),
            ),
        ).toEqual({ width: 640, height: 480 });
    });

    test("the node's own size overrides the template's", () => {
        registerNode(descriptor("curio.builtin/spatial-join@1", {
            nodeWidth: 280,
            nodeHeight: 170,
        }));

        expect(
            resolveNodeBoxSize(
                node("curio.builtin/spatial-join@1", { nodeWidth: 640, nodeHeight: 900 }),
            ),
        ).toEqual({ width: 640, height: 900 });
    });

    test("a sub-minimum size snaps to the DEFAULT, not to the minimum", () => {
        // The rule worth pinning: styles.tsx's mount effect reads
        // `nodeWidth < MIN_NODE_WIDTH` and then sets 525, not 200. Measuring such
        // a node as 200 wide would leave 325px of it lying over its neighbour.
        registerNode(descriptor("curio.builtin/vis-vega@1", {}));

        expect(
            resolveNodeBoxSize(
                node("curio.builtin/vis-vega@1", { nodeWidth: 120, nodeHeight: 60 }),
            ),
        ).toEqual({ width: 525, height: 350 });
    });

    test("an unversioned type resolves to the registered @1 descriptor", () => {
        registerNode(descriptor("curio.builtin/spatial-join@1", {
            nodeWidth: 280,
            nodeHeight: 170,
        }));

        // Saved specs mix versioned and unversioned forms (#169).
        expect(resolveNodeBoxSize(node("curio.builtin/spatial-join"))).toEqual({
            width: 280,
            height: 170,
        });
    });

    test("a non-numeric or non-finite size is ignored", () => {
        registerNode(descriptor("curio.builtin/vis-vega@1", {}));

        expect(
            resolveNodeBoxSize(
                node("curio.builtin/vis-vega@1", { nodeWidth: NaN, nodeHeight: "700" }),
            ),
        ).toEqual({ width: 525, height: 350 });
    });

    test("a node with no data at all still measures", () => {
        expect(resolveNodeBoxSize({ type: CURIO_UNIVERSAL_NODE_TYPE })).toEqual({
            width: 525,
            height: 350,
        });
    });
});

describe("clampNodeBox", () => {
    test("no size, or one under the minimum, is the default box", () => {
        expect(clampNodeBox(undefined, undefined)).toEqual({ width: 525, height: 350 });
        expect(clampNodeBox(120, 40)).toEqual({ width: 525, height: 350 });
        expect(clampNodeBox(NaN, "700")).toEqual({ width: 525, height: 350 });
    });

    test("a size at or over the minimum is kept", () => {
        expect(clampNodeBox(280, 170)).toEqual({ width: 280, height: 170 });
        expect(clampNodeBox(900, 600)).toEqual({ width: 900, height: 600 });
    });

    // #683: NodeContainer started from the size asked for, undefined for most
    // built-ins, and reached the default only in a mount effect. The canvas's
    // load fit could measure that narrow first render, so the grown nodes ended
    // past the window's edge. Its size state must start from the clamp.
    test("NodeContainer's first render is already the clamped size", () => {
        const source = fs.readFileSync(
            path.resolve(__dirname, "../../components/styles.tsx"),
            "utf8",
        );
        const widthAt = source.indexOf("const [currentNodeWidth, setCurrentNodeWidth]");
        const heightAt = source.indexOf("const [currentNodeHeight, setCurrentNodeHeight]");
        const minimizedAt = source.indexOf("const setMinimized = ");
        expect([widthAt, heightAt, minimizedAt].every((at) => at >= 0)).toBe(true);
        expect(source.slice(widthAt, heightAt)).toContain("clampNodeBox(nodeWidth, nodeHeight).width");
        expect(source.slice(heightAt, minimizedAt)).toContain("clampNodeBox(nodeWidth, nodeHeight).height");
    });
});

describe("minimizedChipBox", () => {
    test("a chip never resized is 250x40", () => {
        expect(minimizedChipBox(undefined)).toEqual({ width: 250, height: 40 });
        expect(minimizedChipBox({ minimizedWidth: NaN, minimizedHeight: "90" })).toEqual({ width: 250, height: 40 });
    });

    test("a resized chip keeps its size, no smaller than the least chip", () => {
        expect(minimizedChipBox({ minimizedWidth: 300, minimizedHeight: 64 })).toEqual({ width: 300, height: 64 });
        expect(minimizedChipBox({ minimizedWidth: 50, minimizedHeight: 10 })).toEqual({ width: 120, height: 40 });
    });
});

// #1235: dragging a folded node's corner sized the hidden card, read as 0x0,
// and the release saved 0x0 as the size it opens back to. The handle now sizes
// the chip and keeps the chip's size in its own fields.
describe("a folded node's corner handle", () => {
    const source = fs.readFileSync(path.resolve(__dirname, "../../components/styles.tsx"), "utf8");
    const keepChip = source.slice(source.indexOf("const keepChipSize = "), source.indexOf("const keepBoxSize = "));

    test("sizes the chip, and keeps its size apart from the size the node opens back to", () => {
        expect(source).toContain("box={shownMinimized ? chipRef : resizableRef}");
        expect(source).toContain("onResizeEnd={shownMinimized ? keepChipSize : keepBoxSize}");
        expect(keepChip).toContain("minimizedWidth: width, minimizedHeight: height");
        expect(keepChip).not.toContain("nodeWidth");
    });

    test("opening a node clamps the size it opens back to, so an old 0x0 opens at the default", () => {
        const opens = source.match(/const opened = clampNodeBox\(nodeWidth, nodeHeight\);/g) ?? [];
        expect(opens).toHaveLength(2);
    });
});
