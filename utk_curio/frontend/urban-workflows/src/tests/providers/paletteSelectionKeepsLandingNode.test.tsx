/**
 * A palette row selects the canvas nodes it names as another tab's node lands
 * on this canvas: the node that lands stays, on the canvas and in the
 * dataflow's doc, and the row's nodes are the selection.
 *
 * Curio's canvas hands React Flow its nodes as props (`nodes=`, no
 * `defaultNodes`). React Flow takes its own copy of them in an effect after
 * each commit, while the canvas writes each commit into the dataflow's doc
 * earlier, in a layout effect of that commit (`useDataflowDoc`). A dataset's
 * row (`focusLinkedNodes`) and a package's row (`PackageTemplateRow`) selected
 * through React Flow's `setNodes`, which hands its updater React Flow's copy
 * and makes what it returns the canvas's whole node list. A click between the
 * two effects, in the commit in which the canvas took another tab's node, found
 * a copy without that node and dropped it, and the next commit wrote its
 * removal into the doc, for everyone.
 *
 * The click is made at that moment every time, in the canvas writer's
 * transaction (origin `canvas`), as `test_agent_queue_e2e.py`'s forcing
 * listener makes a selection there. The harness is `dataflowDocBridge.test.tsx`'s:
 * the REAL FlowProvider and its load, with a React Flow handed the canvas's
 * nodes, bound to a doc as the server's first sync leaves one.
 */
import React from "react";
import { act, render, screen } from "@testing-library/react";
import { ReactFlow, ReactFlowProvider, useReactFlow, type ReactFlowInstance } from "reactflow";
import type { Transaction } from "yjs";
import { faUpload } from "@fortawesome/free-solid-svg-icons";

class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
    (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
    useToastContext: () => ({ showToast: mockShowToast }),
    useOptionalToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../hook/useVega", () => ({
    useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

import FlowProvider, { useFlowContext } from "../../providers/FlowProvider";
import { useCode } from "../../hook/useCode";
import { CANVAS_ORIGIN, DataflowDocContext, type DocBinding } from "../../providers/collab/docContext";
import { DataflowDocProvider } from "../../providers/collab/docProvider";
import { applyDataflow, dataflowToDoc, docToDataflow } from "../../providers/collab/docMapping";
import { setCurrentProject } from "../../registry/projectPackagesStore";
import { DatasetRow } from "../../components/menus/nodes/datasetPalette/DatasetPaletteRows";
import { PackageTemplateRow } from "../../components/menus/nodes/toolsMenuPackagePalette/PackagePaletteRows";
import { getFlowNodeCanonicalType } from "../../utils/flowNodeCanonicalType";
import type { NodeDescriptor } from "../../registry/types";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";

const PROJECT = "3d1f6b2a-8c4e-4f7a-9b0d-5e2c7a1f9d46";
const TYPE = "curio.builtin/python-computation@1";

function spec() {
    return {
        dataflow: {
            name: "Bound", task: "", timestamp: 1, provenance_id: "Bound", packages: ["curio.builtin@1"],
            nodes: [
                { id: "n", type: TYPE, x: 0, y: 0, content: "x = 1\n", out: "DEFAULT", in: "DEFAULT", goal: "",
                  saveOutputDataset: false },
                { id: "m", type: TYPE, x: 600, y: 0, content: "y = 1\n", out: "DEFAULT", in: "DEFAULT", goal: "",
                  saveOutputDataset: false },
            ],
            edges: [{ id: "n-m", source: "n", target: "m", sourceHandle: "out", targetHandle: "in" }],
        },
    };
}

type FlowApi = ReturnType<typeof useFlowContext>;
let api: FlowApi;
let code: ReturnType<typeof useCode>;
let flow: ReactFlowInstance;
let provider: DataflowDocProvider;

/** The canvas, a React Flow handed its nodes as the canvas hands them, and
 *  *row* beside it, as the tool rail's palette is. */
const Bridge: React.FC<{ row: React.ReactNode }> = ({ row }) => {
    api = useFlowContext();
    code = useCode();
    flow = useReactFlow();
    return (
        <div style={{ width: 800, height: 600 }}>
            <ReactFlow nodes={api.nodes} edges={api.edges} onNodesChange={api.onNodesChange} onEdgesChange={api.onEdgesChange} />
            {row}
        </div>
    );
};

async function flush() {
    await act(async () => {
        await Promise.resolve();
    });
}

/** Open the dataflow on a canvas bound to its doc, as the server's first sync
 *  leaves it, with *row* beside the canvas. */
async function open(row: React.ReactNode) {
    provider = new DataflowDocProvider(PROJECT, { canWrite: true });
    dataflowToDoc(spec().dataflow, provider.doc, "doc-1");
    provider.synced = true;
    setCurrentProject(PROJECT, []);
    const binding: DocBinding = { provider, synced: true };
    render(
        <DataflowDocContext.Provider value={binding}>
            <ReactFlowProvider>
                <FlowProvider>
                    <Bridge row={row} />
                </FlowProvider>
            </ReactFlowProvider>
        </DataflowDocContext.Provider>,
    );
    await flush();
    act(() => {
        code.loadTrill(spec());
    });
    await flush();
    await flush();
}

/** What the forcing saw: the nodes the canvas held and React Flow's copy of it
 *  lacked when it clicked, and what the click raised. */
type Forced = { fresh: string[] | null; error: string | null };

/** Click *button* once, in the canvas writer's transaction (origin `canvas`) of
 *  the commit in which the canvas holds a node that React Flow's copy of the
 *  canvas lacks: the doc written, React Flow's effect not run yet. */
function clickAsANodeLands(button: HTMLElement): Forced {
    const forced: Forced = { fresh: null, error: null };
    const doc = provider.doc;
    const onTransaction = (transaction: Transaction) => {
        if (transaction.origin !== CANVAS_ORIGIN) return;
        const inReactFlow = new Set(flow.getNodes().map((node) => node.id));
        const fresh = api.nodes.map((node) => node.id).filter((id) => !inReactFlow.has(id));
        if (fresh.length === 0) return;
        doc.off("afterTransaction", onTransaction);
        forced.fresh = fresh;
        try {
            button.click();
        } catch (error) {
            forced.error = String(error);
        }
    };
    doc.on("afterTransaction", onTransaction);
    return forced;
}

/** Another tab adds the node "c", and the server relays its change. */
async function anotherTabAddsANode() {
    const before = docToDataflow(provider.doc);
    const after = JSON.parse(JSON.stringify(before));
    after.nodes.push({ id: "c", type: TYPE, x: 1200, y: 0, content: "z = 1\n" });
    await act(async () => {
        provider.doc.transact(() => applyDataflow(provider.doc, before, after), provider);
    });
    await flush();
}

const idsOf = (nodes: Array<{ id: string }>) => nodes.map((node) => node.id).sort();

/** The click came as the canvas took "c", and "c" stays on the canvas and in the doc. */
function expectTheNodeThatLandedStays(forced: Forced) {
    if (forced.fresh === null) {
        throw new Error("the forcing missed: the canvas never held a node that React Flow's copy of it lacked");
    }
    expect(forced).toEqual({ fresh: ["c"], error: null });
    expect(idsOf(api.nodes)).toEqual(["c", "m", "n"]);
    expect(idsOf(docToDataflow(provider.doc).nodes)).toEqual(["c", "m", "n"]);
}

afterEach(() => {
    provider?.destroy();
    mockShowToast.mockClear();
});

/** A computed dataset, the output of the node "n". */
const SUMS = {
    id: "computed.sums",
    title: "Sums",
    origin: "computed",
    format: "csv",
    uri: "curio://datasets/computed.sums",
    consumerNodeIds: [],
    updatedAt: "2026-07-14T00:00:00Z",
    tags: [],
    installed: true,
    producerNodeId: "n",
} as unknown as DatasetCatalogItem;

/** The package palette's row for the type of the canvas's nodes. */
const PACKAGE_ROW = "Python on this canvas";
const RowOfTheCanvasType: React.FC = () => {
    const { nodes } = useFlowContext();
    const desc = {
        id: nodes.length > 0 ? getFlowNodeCanonicalType(nodes[0]) : "",
        label: PACKAGE_ROW,
        description: "",
        icon: faUpload,
        category: "computation",
    };
    return <PackageTemplateRow desc={desc as unknown as NodeDescriptor} />;
};

describe("a palette row selects its nodes as another tab's node lands on the canvas", () => {
    test("a dataset's row: the node that lands stays, and the dataset's node is the selection", async () => {
        await open(<DatasetRow dataset={SUMS} />);
        const row = document.querySelector<HTMLElement>(`[data-dataset-id="${SUMS.id}"] button`);
        expect(row).not.toBeNull();
        const forced = clickAsANodeLands(row!);

        await anotherTabAddsANode();

        expectTheNodeThatLandedStays(forced);
        expect(idsOf(api.nodes.filter((node) => node.selected))).toEqual(["n"]);
    });

    test("a package's row: the node that lands stays, and the row's nodes are the selection", async () => {
        await open(<RowOfTheCanvasType />);
        const row = screen.getByText(PACKAGE_ROW).closest("button");
        expect(row).not.toBeNull();
        const forced = clickAsANodeLands(row!);

        await anotherTabAddsANode();

        expectTheNodeThatLandedStays(forced);
        expect(idsOf(api.nodes.filter((node) => node.selected))).toEqual(["m", "n"]);
    });
});
