/**
 * Does `resolveNodeBoxSize` report the box a node actually renders at?
 *
 * It exists to feed `deoverlapLayout`, and a layout pass that measures wrong is
 * worse than none: under-estimate a node and the overlap it was meant to remove
 * comes straight back the moment the node inflates. So this pins the two rules
 * in `components/styles.tsx` that are easy to read past -- `noContent` templates
 * keeping a sub-minimum footprint, and the mount clamp snapping a too-small size
 * to the DEFAULT rather than to the minimum.
 */
import { faCircle } from "@fortawesome/free-solid-svg-icons";
import { Position } from "reactflow";

import { CURIO_UNIVERSAL_NODE_TYPE, NodeType, SupportedType } from "../../constants";
import { clearPackageNodes, registerNode } from "../../registry/nodeRegistry";
import { ContainerConfig, NodeBehaviorHook, NodeDescriptor } from "../../registry/types";
import { resolveNodeBoxSize } from "../../utils/nodeBoxSize";

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
        // merge-flow. Both resize effects in NodeContainer bail on noContent, so
        // 50x180 is the literal rendered size -- not clamped up to 200x150, and
        // not the 525x350 default.
        registerNode(descriptor("curio.builtin/merge-flow@1", {
            noContent: true,
            nodeWidth: 50,
            nodeHeight: 180,
        }));

        expect(resolveNodeBoxSize(node("curio.builtin/merge-flow@1"))).toEqual({
            width: 50,
            height: 180,
        });
    });

    test("a noContent template with no size falls back to the minimized chip", () => {
        registerNode(descriptor("curio.builtin/chip@1", { noContent: true }));

        expect(resolveNodeBoxSize(node("curio.builtin/chip@1"))).toEqual({
            width: 70,
            height: 40,
        });
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
