/**
 * A widget's value that another tab, or an agent's change the server wrote,
 * brings through the dataflow's doc (`providers/flow/useDataflowDoc.ts`), on
 * the REAL FlowProvider bound to a doc as the server's first sync leaves one.
 *
 * - Simple View's Time column, the one widget of a template with neither code
 *   nor a spec, names the column its player's range is on: it changes no
 *   output, so a view that is current stays current, as it does when a person
 *   sets it in the view's own field.
 * - A code node's widget, which its code reads, still leaves the node out of
 *   date.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { act, render } from "@testing-library/react";
import { ReactFlow, ReactFlowProvider } from "reactflow";

class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
    (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

jest.mock("../../providers/ToastProvider", () => ({
    useToastContext: () => ({ showToast: jest.fn() }),
    useOptionalToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../hook/useVega", () => ({
    useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

// The behavior and icon registries are filled before packagesClient pulls in
// the adapters, in the order packagesClient.test.ts uses.
import "../../registry/builtinBehaviors";
import "../../registry/iconRegistry";
import { registerPackageTemplates } from "../../registry/packagesClient";
import { clearPackageNodes } from "../../registry/nodeRegistry";
import FlowProvider, { useFlowContext } from "../../providers/FlowProvider";
import { useCode } from "../../hook/useCode";
import { DataflowDocContext, type DocBinding } from "../../providers/collab/docContext";
import { DataflowDocProvider } from "../../providers/collab/docProvider";
import { applyDataflow, dataflowToDoc, docToDataflow } from "../../providers/collab/docMapping";
import { trillNodeOf } from "../../providers/flow/useDataflowDoc";
import { setCurrentProject } from "../../registry/projectPackagesStore";

const PROJECT = "3f1c2b8e-7d4a-4c5e-9b1f-6a2d8e4c0b71";
const CODE = "curio.builtin/python-computation@1";
const VIEW = "curio.builtin/vis-simple@1";

/** The built-in templates as packages/curio.builtin@1/manifest.json declares them. */
const MANIFEST = JSON.parse(
    fs.readFileSync(path.resolve(__dirname, "../../../../../../packages/curio.builtin@1/manifest.json"), "utf8"),
);
const SHIPPED = MANIFEST.templates.find((template: any) => template.id === "vis-simple");

/** The built-in package with its Simple View, as the package listing hands it to the registry. */
const LISTING: any = {
    packageId: "curio.builtin",
    major: 1,
    version: MANIFEST.version ?? "1.0.0",
    name: MANIFEST.name ?? "Curio",
    publisher: "Curio",
    description: "",
    license: "MIT",
    permissions: [],
    lineage: null,
    templates: [{
        icon: null,
        grammarId: null,
        badge: null,
        source: null,
        containerStyle: null,
        hasProvenance: null,
        ...SHIPPED,
        id: VIEW,
        templateId: "vis-simple",
    }],
};

/** The Time column widget as the shipped template declares it. */
const TIME_COLUMN = { name: "time_column", type: "text", label: "Time column", default: "t_s" };

/** A table of objects, read by a code node's widget, played beside the walk in a Simple View. */
function spec() {
    return {
        dataflow: {
            name: "Walk", task: "", timestamp: 1, provenance_id: "Walk", packages: ["curio.builtin@1"],
            nodes: [
                { id: "objects", type: CODE, x: 0, y: 0, content: "return [!! rows !!]\n", out: "DEFAULT", in: "DEFAULT",
                  goal: "", saveOutputDataset: false,
                  metadata: { widgets: [{ name: "rows", type: "number", default: 5 }] } },
                { id: "walk", type: VIEW, x: 600, y: 0, content: "", out: "DEFAULT", in: "DEFAULT", goal: "",
                  saveOutputDataset: false },
            ],
            edges: [{ id: "objects-walk", source: "objects", target: "walk", sourceHandle: "out", targetHandle: "in" }],
        },
    };
}

type FlowApi = ReturnType<typeof useFlowContext>;
let api: FlowApi;
let code: ReturnType<typeof useCode>;
let provider: DataflowDocProvider;

const Bridge: React.FC = () => {
    api = useFlowContext();
    code = useCode();
    return (
        <div style={{ width: 800, height: 600 }}>
            <ReactFlow nodes={api.nodes} edges={api.edges} onNodesChange={api.onNodesChange} onEdgesChange={api.onEdgesChange} />
        </div>
    );
};

async function flush() {
    await act(async () => {
        await Promise.resolve();
    });
}

/** The doc another tab and the server hold, as the first sync leaves it. */
function serverDoc(dataflow: any): DataflowDocProvider {
    const held = new DataflowDocProvider(PROJECT, { canWrite: true });
    dataflowToDoc(dataflow, held.doc, "doc-1");
    held.synced = true;
    return held;
}

/** Open the dataflow on a canvas bound to *held*. */
async function open(held: DataflowDocProvider) {
    provider = held;
    setCurrentProject(PROJECT, []);
    const binding: DocBinding = { provider: held, synced: true };
    render(
        <DataflowDocContext.Provider value={binding}>
            <ReactFlowProvider>
                <FlowProvider>
                    <Bridge />
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

/** A change from outside this tab, from the doc's *before* to *after*, as
 *  the provider applies one the server relays: another tab's, or an agent's
 *  change the server wrote. */
async function fromOutside(change: (dataflow: any) => void) {
    const before = docToDataflow(provider.doc);
    const after = JSON.parse(JSON.stringify(before));
    change(after);
    await act(async () => {
        provider.doc.transact(() => applyDataflow(provider.doc, before, after), provider);
    });
    await flush();
}

const canvasNode = (id: string) => api.nodes.find((n: any) => n.id === id) as any;
const trillWidgets = (id: string) => trillNodeOf(canvasNode(id)).metadata?.widgets;

beforeAll(() => {
    clearPackageNodes();
    registerPackageTemplates([LISTING]);
});

afterAll(() => {
    clearPackageNodes();
});

afterEach(() => {
    provider?.destroy();
});

describe("a widget's value the dataflow's doc brings", () => {
    test("a Simple View's Time column reaches the view and leaves it current: it changes no output", async () => {
        await open(serverDoc(spec().dataflow));
        // The view is current, as a run that showed its input leaves it. The
        // load left it out of date: it replays each saved connection as a new
        // one (`onConnect`), and a new input does leave its target out of date.
        act(() => api.markNodeExecuted("walk"));
        expect(api.nodeExecStatus.walk).toBe("executed");

        await fromOutside((df) => {
            const walk = df.nodes.find((n: any) => n.id === "walk");
            walk.metadata = { ...(walk.metadata ?? {}), widgets: [{ ...TIME_COLUMN, value: "walked_s" }] };
        });

        expect(trillWidgets("walk")).toEqual([{ ...TIME_COLUMN, value: "walked_s" }]);
        expect(api.nodeExecStatus.walk).not.toBe("stale");
    });

    test("a code node's widget leaves it out of date: its code reads it", async () => {
        await open(serverDoc(spec().dataflow));

        await fromOutside((df) => {
            df.nodes.find((n: any) => n.id === "objects").metadata.widgets[0].value = 9;
        });

        expect(trillWidgets("objects")).toEqual([{ name: "rows", type: "number", default: 5, value: 9 }]);
        expect(api.nodeExecStatus.objects).toBe("stale");
    });
});
