/**
 * The canvas and the dataflow's Yjs doc kept in step both ways
 * (`providers/flow/useDataflowDoc.ts`), on the REAL FlowProvider and its real
 * load (`useCode().loadTrill`), bound to a doc as the server's first sync
 * leaves one.
 *
 * Each field `TrillGenerator.generateTrill` writes goes both ways: a change
 * another tab makes to it in the doc reaches this canvas, where
 * `generateTrill` writes it back as the doc holds it; and a change made on
 * this canvas reaches the doc. The fields come from `generateTrill` itself,
 * for a node with every setting set, so a field added to it later fails here
 * until it goes both ways.
 */
import React from "react";
import { act, render } from "@testing-library/react";
import { ReactFlow, ReactFlowProvider } from "reactflow";
import * as Y from "yjs";

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
import { DataflowDocContext, type DocBinding } from "../../providers/collab/docContext";
import { DataflowDocProvider } from "../../providers/collab/docProvider";
import { applyDataflow, dataflowToDoc, docToDataflow } from "../../providers/collab/docMapping";
import { buildCodeNode, nodeMetaFromTrill } from "../../hook/codeNodes";
import { METADATA_FIELD_DATA, NODE_FIELD_DATA, trillNodeOf } from "../../providers/flow/useDataflowDoc";
import { setCurrentProject } from "../../registry/projectPackagesStore";
import { TrillGenerator } from "../../TrillGenerator";
import { serverHistory } from "../../providers/history/serverHistory";

const PROJECT = "7c3e0f42-5b9a-4d0e-9c1f-2a8b6d4e1f30";
const TYPE = "curio.builtin/python-computation@1";

/** Each node field's value in another tab's change, and a second one. */
const NODE_SAMPLES: Record<string, [unknown, unknown]> = {
    type: ["curio.builtin/computation-analysis@1", TYPE],
    x: [111, 222],
    y: [333, 444],
    width: [640, 700],
    height: [480, 500],
    minimized: [true, false],
    dashboardPinned: [true, false],
    dashboardX: [5, 6],
    dashboardY: [7, 8],
    dashboardWidth: [300, 320],
    dashboardHeight: [200, 220],
    saveOutputDataset: [true, false],
    content: ["x = 42\n", "x = 43\n"],
    out: ["DATAFRAME", "GEODATAFRAME"],
    in: ["GEODATAFRAME", "DATAFRAME"],
    goal: ["Compute the heat", "Map the heat"],
    title: ["Renamed", "Renamed again"],
};

/** Fields a save writes only beside their partner: the dashboard's place and
 *  size (`generateTrill`, and a load reads them so). A change to one comes
 *  with the other. */
const PARTNERS: Record<string, string> = {
    dashboardX: "dashboardY",
    dashboardY: "dashboardX",
    dashboardWidth: "dashboardHeight",
    dashboardHeight: "dashboardWidth",
};

/** Flags a save writes only when they are on. */
const ONLY_WHEN_ON = new Set(["minimized", "dashboardPinned"]);

/** What a save writes for *field* set to *value*. */
const asSaved = (field: string, value: unknown) => (ONLY_WHEN_ON.has(field) && value === false ? undefined : value);

/** The same for each `metadata` setting. */
const METADATA_SAMPLES: Record<string, [unknown, unknown]> = {
    keywords: [[3, 4], [5]],
    datasetRefs: [["data.utk.parks@1"], ["data.utk.trees@1"]],
    datasetSource: [{ datasetId: "data.utk.parks@1", title: "Parks" }, { datasetId: "data.utk.trees@1", title: "Trees" }],
    datasetWidgets: [
        { data: { id: "data.utk.parks@1", title: "Parks", format: "csv", refs: ["data.utk.parks@1"] } },
        { data: { id: "data.utk.trees@1", title: "Trees", format: "csv", refs: ["data.utk.trees@1"] } },
    ],
    modelRefs: [[{ id: "model.utk.trees@1", name: "Trees" }], [{ id: "model.utk.roofs@1", name: "Roofs" }]],
    appearance: [{ backgroundColor: "#ffefb0" }, { backgroundColor: "#c8e6c9" }],
    spatialJoin: [{ predicate: "within", output: "counts" }, { predicate: "contains" }],
    simpleVis: [{ imageColumn: "image" }, { imageColumn: "photo" }],
    packageTemplateLabel: ["Renamed kind", "Another kind"],
    packageTemplateConfig: [{ description: "configured" }, { description: "configured again" }],
    dataPool: [{ insideChart: "MERGE_AND" }, { betweenCharts: "MERGE_OR" }],
    widgets: [
        [{ name: "rows", type: "number", default: 5, value: 9 }],
        [{ name: "rows", type: "number", default: 5, value: 12 }],
    ],
    copiedFrom: [["origin"], ["origin", "copy"]],
    selections: [
        [{ name: "picked", node: "m", column: "id", ids: [1, 2] }],
        [{ name: "picked", node: "m", column: "id", ids: [3] }],
    ],
};

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
function serverDoc(dataflow: any, canWrite = true): DataflowDocProvider {
    const held = new DataflowDocProvider(PROJECT, { canWrite });
    dataflowToDoc(dataflow, held.doc, "doc-1");
    held.synced = true;
    return held;
}

/** Open the dataflow on a canvas bound to *held*; *docChange* is what
 *  another tab changed in the doc since the file was read. */
async function open(held: DataflowDocProvider, loaded = spec()) {
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
        code.loadTrill(loaded);
    });
    await flush();
    await flush();
}

/** Another tab's change, from the doc's *before* to *after*, as the
 *  provider applies one the server relays. */
async function fromAnotherTab(change: (dataflow: any) => void) {
    const before = docToDataflow(provider.doc);
    const after = JSON.parse(JSON.stringify(before));
    change(after);
    await act(async () => {
        provider.doc.transact(() => applyDataflow(provider.doc, before, after), provider);
    });
    await flush();
}

const docNode = (id = "n") => docToDataflow(provider.doc).nodes.find((n: any) => n.id === id);
const canvasNode = (id = "n") => api.nodes.find((n: any) => n.id === id) as any;

/** What a load builds on the canvas for *node*'s Trill: the data its fields
 *  become there, so a change made on the canvas is made as a load holds it. */
function canvasDataFor(trillNode: any, keys: readonly string[]): Record<string, unknown> {
    const built = buildCodeNode(trillNode.type, nodeMetaFromTrill(trillNode, () => ({ x: 0, y: 0 })), {
        pythonInterpreter: {}, jsInterpreter: {}, outputCallback: null, interactionsCallback: null,
        propagationCallback: null, defaultSaveOutputDataset: false, position: () => ({ x: 0, y: 0 }),
    });
    return Object.fromEntries(keys.filter((k) => k !== "position").map((key) => [key, (built.data as any)[key]]));
}

afterEach(() => {
    provider?.destroy();
    mockShowToast.mockClear();
});

describe("the fields the cases cover are those generateTrill writes", () => {
    test("every node field and every metadata setting", () => {
        const full: any = {
            id: "full", position: { x: 1, y: 2 },
            data: {
                nodeId: "full", nodeType: TYPE, nodeWidth: 1, nodeHeight: 1, minimized: true, dashboardPinned: true,
                dashboardX: 1, dashboardY: 1, dashboardWidth: 1, dashboardHeight: 1, saveOutputDataset: true,
                code: "c", out: "o", in: "i", goal: "g", title: "t",
                keywords: [1], datasetRefs: ["d"], datasetSource: { datasetId: "d" },
                datasetWidgets: { w: { id: "d", title: "d", format: "csv", refs: ["d"] } },
                modelRefs: [{ id: "m", name: "m" }], appearance: { backgroundColor: "#fff" },
                spatialJoin: { predicate: "within" }, simpleVis: { imageColumn: "i" },
                packageTemplateLabel: "l", packageTemplateConfig: { description: "d" },
                dataPool: { insideChart: "MERGE_AND" }, widgets: [{ name: "w", type: "number", default: 1 }],
                copiedFrom: ["c"], selections: [{ name: "s", node: "n", column: "c", ids: [1] }],
            },
        };
        const trill = TrillGenerator.generateTrill([full], [], "f").dataflow.nodes[0];
        const nodeFields = Object.keys(trill).filter((f) => f !== "id" && f !== "metadata").sort();
        expect(Object.keys(NODE_SAMPLES).sort()).toEqual(nodeFields);
        expect(Object.keys(METADATA_SAMPLES).sort()).toEqual(Object.keys(trill.metadata).sort());
        // And the canvas data each becomes is named for the doc's changes.
        expect(Object.keys(NODE_FIELD_DATA).filter((f) => f !== "warnings").sort()).toEqual(nodeFields);
        expect(Object.keys(METADATA_FIELD_DATA).sort()).toEqual(Object.keys(trill.metadata).sort());
    });
});

describe("another tab's change to a node's field reaches this canvas", () => {
    test.each(Object.keys(NODE_SAMPLES).filter((f) => f !== "type"))("%s", async (field) => {
        await open(serverDoc(spec().dataflow));
        const [value] = NODE_SAMPLES[field];
        await fromAnotherTab((df) => {
            df.nodes[0][field] = value;
            const partner = PARTNERS[field];
            if (partner && df.nodes[0][partner] === undefined) df.nodes[0][partner] = NODE_SAMPLES[partner][0];
        });
        expect(trillNodeOf(canvasNode())[field]).toEqual(value);
    });

    test.each(Object.keys(METADATA_SAMPLES))("metadata.%s", async (setting) => {
        await open(serverDoc(spec().dataflow));
        const [value] = METADATA_SAMPLES[setting];
        await fromAnotherTab((df) => {
            df.nodes[0].metadata = { ...(df.nodes[0].metadata ?? {}), [setting]: value };
        });
        expect(trillNodeOf(canvasNode()).metadata?.[setting]).toEqual(value);
    });

    test("type: the node is the other type's", async () => {
        await open(serverDoc(spec().dataflow));
        await fromAnotherTab((df) => {
            df.nodes[0].type = NODE_SAMPLES.type[0];
        });
        expect(canvasNode().data.nodeType).toBe(NODE_SAMPLES.type[0]);
    });
});

describe("a change made on this canvas to a node's field reaches the doc", () => {
    const setOnCanvas = async (trillField: string, value: unknown, metadata = false) => {
        const node = canvasNode();
        if (!metadata && (trillField === "x" || trillField === "y")) {
            const position = { ...node.position, [trillField]: value };
            act(() => api.onNodesChange([{ type: "position", id: "n", position, dragging: false } as any]));
            await flush();
            return;
        }
        const trill = trillNodeOf(node);
        const partner = metadata ? undefined : PARTNERS[trillField];
        const withPartner = partner && trill[partner] === undefined ? { [partner]: NODE_SAMPLES[partner][0] } : {};
        const changed = metadata
            ? { ...trill, metadata: { ...(trill.metadata ?? {}), [trillField]: value } }
            : { ...trill, [trillField]: value, ...withPartner };
        const keys = metadata
            ? METADATA_FIELD_DATA[trillField]
            : [...NODE_FIELD_DATA[trillField], ...(partner ? NODE_FIELD_DATA[partner] : [])];
        act(() => api.updateDataNode("n", { ...node.data, ...canvasDataFor(changed, keys) }));
        await flush();
    };

    test.each(Object.keys(NODE_SAMPLES))("%s", async (field) => {
        await open(serverDoc(spec().dataflow));
        const [, value] = NODE_SAMPLES[field];
        const [first] = NODE_SAMPLES[field];
        // From a value the doc holds to another, so each is a change.
        await setOnCanvas(field, first);
        await setOnCanvas(field, value);
        // The doc holds what a save of this canvas writes.
        expect(trillNodeOf(canvasNode())[field]).toEqual(asSaved(field, value));
        expect(docNode()[field]).toEqual(asSaved(field, value));
    });

    test.each(Object.keys(METADATA_SAMPLES))("metadata.%s", async (setting) => {
        await open(serverDoc(spec().dataflow));
        const [first, value] = METADATA_SAMPLES[setting];
        await setOnCanvas(setting, first, true);
        await setOnCanvas(setting, value, true);
        expect(docNode().metadata?.[setting]).toEqual(value);
    });
});

describe("the dataflow's own fields, connections and scenarios", () => {
    test("another tab's name, goal, description, categories, auto-run and scenarios reach this canvas", async () => {
        await open(serverDoc(spec().dataflow));
        await fromAnotherTab((df) => {
            df.name = "Renamed by Ana";
            df.task = "Find the shade";
            df.description = "Where the trees are";
            df.categories = { city: ["Chicago"] };
            df.autoRun = true;
            df.scenarios = [{ id: "s1", name: "Cool roofs", color: "#4477aa", nodes: ["n"] }];
        });
        expect(api.workflowNameRef.current).toBe("Renamed by Ana");
        expect(api.workflowGoal).toBe("Find the shade");
        expect(api.workflowDescription).toBe("Where the trees are");
        expect(api.workflowCategories).toEqual({ city: ["Chicago"] });
        expect(api.autoRun).toBe(true);
        expect(api.scenarios).toEqual([{ id: "s1", name: "Cool roofs", color: "#4477aa", nodes: ["n"] }]);
    });

    test("this canvas's name, auto-run and scenarios reach the doc, and the server's sections never go from here", async () => {
        await open(serverDoc(spec().dataflow));
        act(() => {
            api.setWorkflowName("Renamed here");
            api.setAutoRun(true);
            api.setScenarios([{ id: "s2", name: "Shade", color: "#228833", nodes: ["m"] }]);
            api.setPackages(["curio.builtin@1", "curio.scout@1"]);
        });
        await flush();
        const df = docToDataflow(provider.doc);
        expect(df.name).toBe("Renamed here");
        expect(df.autoRun).toBe(true);
        expect(df.scenarios).toEqual([{ id: "s2", name: "Shade", color: "#228833", nodes: ["m"] }]);
        expect(df.packages).toEqual(["curio.builtin@1"]);
        expect(df.timestamp).toBe(1);
    });

    test("another tab's connection, and its removal, reach this canvas", async () => {
        const dataflow = spec().dataflow;
        dataflow.edges = [];
        await open(serverDoc(dataflow), { dataflow } as any);
        await fromAnotherTab((df) => {
            df.edges.push({ id: "n-m", source: "n", target: "m", sourceHandle: "out", targetHandle: "in" });
        });
        expect(api.edges.map((e: any) => [e.id, e.source, e.target])).toEqual([["n-m", "n", "m"]]);
        await fromAnotherTab((df) => {
            df.edges = [];
        });
        expect(api.edges).toEqual([]);
    });

    test("a node another tab adds and removes comes and goes, built as a load builds it", async () => {
        await open(serverDoc(spec().dataflow));
        await fromAnotherTab((df) => {
            df.nodes.push({ id: "k", type: TYPE, x: 50, y: 60, content: "z = 1\n" });
        });
        const added = canvasNode("k");
        expect(added.position).toEqual({ x: 50, y: 60 });
        expect(added.data.code).toBe("z = 1\n");
        expect(typeof added.data.outputCallback).toBe("function");
        await fromAnotherTab((df) => {
            df.nodes = df.nodes.filter((n: any) => n.id !== "k");
        });
        expect(canvasNode("k")).toBeUndefined();
    });

    test("this canvas's removal of a node takes it and its connections out of the doc", async () => {
        await open(serverDoc(spec().dataflow));
        act(() => api.applyReviewedRemovals(["m"], ["n-m"]));
        await flush();
        const df = docToDataflow(provider.doc);
        expect(df.nodes.map((n: any) => n.id)).toEqual(["n"]);
        expect(df.edges).toEqual([]);
    });
});

describe("what the canvas changes in place, with no new node", () => {
    test("an editor's own copy of its code never reaches the doc, and a writer's code does", async () => {
        await open(serverDoc(spec().dataflow));
        // What a spec editor floats while it mounts, before its spec lands,
        // and what any editor's copy holds of the code it shows: never the doc's.
        canvasNode().data.code = "{}";
        act(() => api.updateDataNode("m", { ...canvasNode("m").data, title: "A later change" }));
        await flush();
        expect(docNode("m").title).toBe("A later change");
        expect(docNode().content).toBe("x = 1\n");

        // A writer of the node's code (a drop, an agent, a rewrite) sets it as
        // the node's code, which the doc takes.
        act(() => api.updateDefaultCode("n", "x = 2\n"));
        await flush();
        expect(docNode().content).toBe("x = 2\n");
    });

    test("a widget's value set in place reaches the doc when its editor says so", async () => {
        const dataflow: any = spec().dataflow;
        dataflow.nodes[0].metadata = { widgets: [{ name: "rows", type: "number", default: 5, value: 5 }] };
        await open(serverDoc(dataflow), { dataflow } as any);
        const data = canvasNode().data;
        // As the node's Widgets tab sets a value (`NodeEditor.updateWidgets`).
        data.widgets = data.widgets.map((widget: any) => ({ ...widget, value: 9 }));
        act(() => api.dataflowDoc!.noteNodeData("n"));
        await flush();
        expect(docNode().metadata.widgets[0].value).toBe(9);
    });

    test("a node or a connection added twice with one id is on the canvas once", async () => {
        await open(serverDoc(spec().dataflow));
        const node = buildCodeNode(TYPE, nodeMetaFromTrill({ id: "k", type: TYPE, x: 5, y: 5, content: "z = 1\n" }, () => ({ x: 0, y: 0 })), {
            pythonInterpreter: {}, jsInterpreter: {}, outputCallback: null, interactionsCallback: null,
            propagationCallback: null, defaultSaveOutputDataset: false, position: () => ({ x: 0, y: 0 }),
        });
        // The doc's change and an agent's apply, before the canvas renders.
        act(() => {
            api.addNode(node, undefined, false);
            api.addNode({ ...node }, undefined, false);
        });
        await flush();
        expect(api.nodes.filter((n: any) => n.id === "k")).toHaveLength(1);
        const edge = { id: "k-m", source: "k", target: "m", sourceHandle: "out", targetHandle: "in", data: {} };
        act(() => {
            api.onEdgesChange([{ type: "add", item: edge }] as any);
            api.onEdgesChange([{ type: "add", item: { ...edge } }] as any);
        });
        await flush();
        expect(api.edges.filter((e: any) => e.id === "k-m")).toHaveLength(1);
        expect(docToDataflow(provider.doc).nodes.filter((n: any) => n.id === "k")).toHaveLength(1);
    });

    test("a selection tag set in place reaches the doc when its editor says so", async () => {
        const dataflow: any = spec().dataflow;
        dataflow.nodes[0].metadata = { selections: [{ name: "picked", node: "m", column: "id", ids: [1] }] };
        await open(serverDoc(dataflow), { dataflow } as any);
        const data = canvasNode().data;
        data.selections = data.selections.map((tag: any) => ({ ...tag, ids: [1, 2] }));
        act(() => api.dataflowDoc!.noteNodeData("n"));
        await flush();
        expect(docNode().metadata.selections[0].ids).toEqual([1, 2]);
    });
});

describe("binding", () => {
    test("opening a dataflow writes nothing into its doc", async () => {
        const held = serverDoc(spec().dataflow);
        const written: Uint8Array[] = [];
        held.doc.on("update", (update: Uint8Array, origin: unknown) => {
            if (origin !== held) written.push(update);
        });
        await open(held);
        expect(api.nodes.map((n: any) => n.id).sort()).toEqual(["m", "n"]);
        expect(written).toEqual([]);
    });

    test("what another tab typed after the file was read reaches the canvas at the first sync", async () => {
        const live = spec().dataflow;
        live.nodes[0].content = "x = 1\n# typed meanwhile\n";
        await open(serverDoc(live), spec());
        expect(canvasNode().data.code).toBe("x = 1\n# typed meanwhile\n");
    });

    test("what this canvas changed before its doc was there reaches the doc at the bind", async () => {
        // The room joins the tab a moment after the dataflow opens. The canvas
        // took its load only once the doc was there, so a change made before
        // was part of the load the bind compared with, and never reached the
        // doc; no save carries it now.
        const held = serverDoc(spec().dataflow);
        provider = held;
        setCurrentProject(PROJECT, []);
        let joined!: (binding: DocBinding) => void;
        const Room: React.FC<{ children: React.ReactNode }> = ({ children }) => {
            const [binding, setBinding] = React.useState<DocBinding | null>(null);
            joined = setBinding;
            return <DataflowDocContext.Provider value={binding}>{children}</DataflowDocContext.Provider>;
        };
        render(
            <Room>
                <ReactFlowProvider>
                    <FlowProvider>
                        <Bridge />
                    </FlowProvider>
                </ReactFlowProvider>
            </Room>,
        );
        await flush();
        act(() => {
            code.loadTrill(spec());
        });
        await flush();
        await flush();
        act(() => api.updateDataNode("n", { ...canvasNode().data, title: "Named before the doc was there" }));
        await flush();
        expect(docNode().title).toBeUndefined();

        act(() => joined({ provider: held, synced: true }));
        await flush();
        await flush();

        expect(docNode().title).toBe("Named before the doc was there");
        expect(canvasNode().data.title).toBe("Named before the doc was there");
        // Bound now, the canvas holds nothing the doc does not keep.
        expect(api.projectDirty).toBe(false);
    });

    test("a bound canvas's history is the server's: the versions its load recorded go, and its edits record none", async () => {
        await open(serverDoc(spec().dataflow));
        const history = serverHistory();
        expect(history?.projectId).toBe(PROJECT);
        expect(history?.reads()).toBe(true);
        expect(history?.codeOf("n")).toBe("x = 1\n");
        expect(history?.codeOf("gone")).toBeUndefined();
        expect(TrillGenerator.provenanceJSON.nodes).toEqual([]);

        const node = buildCodeNode(TYPE, nodeMetaFromTrill({ id: "k", type: TYPE, x: 5, y: 5, content: "z = 1\n" }, () => ({ x: 0, y: 0 })), {
            pythonInterpreter: {}, jsInterpreter: {}, outputCallback: null, interactionsCallback: null,
            propagationCallback: null, defaultSaveOutputDataset: false, position: () => ({ x: 0, y: 0 }),
        });
        act(() => api.addNode(node, undefined, true));
        await flush();
        expect(docNode("k")).toBeDefined();
        expect(TrillGenerator.provenanceJSON.nodes).toEqual([]);
        expect(history?.codeOf("k")).toBe("z = 1\n");
    });

    test("a load of the bound dataflow binds again, and the versions its replay recorded go", async () => {
        await open(serverDoc(spec().dataflow));
        const first = serverHistory();
        expect(first).not.toBeNull();
        act(() => {
            code.loadTrill(spec());
        });
        await flush();
        await flush();
        const again = serverHistory();
        expect(again).not.toBeNull();
        expect(again).not.toBe(first);
        expect(TrillGenerator.provenanceJSON.nodes).toEqual([]);
    });

    test("a watcher's canvas takes the doc's changes and writes none", async () => {
        const held = serverDoc(spec().dataflow, false);
        await open(held);
        act(() => api.updateDataNode("n", { ...canvasNode().data, title: "A watcher's title" }));
        await flush();
        expect(docNode().title).toBeUndefined();
        await fromAnotherTab((df) => {
            df.nodes[0].goal = "From the owner";
        });
        expect(canvasNode().data.goal).toBe("From the owner");
    });

    test("another tab's drag moves the node live and writes nothing; its drop sets the place", async () => {
        await open(serverDoc(spec().dataflow));
        const written: unknown[] = [];
        provider.doc.on("update", (_u: Uint8Array, origin: unknown) => written.push(origin));
        const other = new (require("y-protocols/awareness").Awareness)(new Y.Doc());
        const relay = () => {
            const { encodeAwarenessUpdate, applyAwarenessUpdate } = require("y-protocols/awareness");
            applyAwarenessUpdate(provider.awareness, encodeAwarenessUpdate(other, [other.clientID]), provider);
        };
        await act(async () => {
            other.setLocalState({ user: { name: "Ana" }, drag: { nodes: { n: { x: 75, y: 90 } } } });
            relay();
        });
        await flush();
        expect(canvasNode().position).toEqual({ x: 75, y: 90 });
        expect(written).toEqual([]);

        await act(async () => {
            other.setLocalState({ user: { name: "Ana" }, drag: null });
            relay();
        });
        await fromAnotherTab((df) => {
            df.nodes[0].x = 80;
            df.nodes[0].y = 95;
        });
        expect(canvasNode().position).toEqual({ x: 80, y: 95 });
        expect(docNode().x).toBe(80);
        other.destroy();
    });

    test("a node another tab removes while this tab edits its code says who, and Put it back adds it again", async () => {
        await open(serverDoc(spec().dataflow));
        act(() => provider.awareness.setLocalStateField("editing", "n"));
        const other = new (require("y-protocols/awareness").Awareness)(new Y.Doc());
        const { encodeAwarenessUpdate, applyAwarenessUpdate } = require("y-protocols/awareness");
        await act(async () => {
            other.setLocalState({ user: { name: "Fabio" }, removed: { nodes: ["n"], at: Date.now() } });
            applyAwarenessUpdate(provider.awareness, encodeAwarenessUpdate(other, [other.clientID]), provider);
        });
        await fromAnotherTab((df) => {
            df.nodes = df.nodes.filter((n: any) => n.id !== "n");
            df.edges = [];
        });
        expect(canvasNode()).toBeUndefined();
        const [message, , options] = mockShowToast.mock.calls.find(([text]) => /removed this node/.test(text)) ?? [];
        expect(message).toBe("Fabio removed this node while you were editing it.");
        expect(options?.action?.label).toBe("Put it back");

        await act(async () => options.action.onClick());
        await flush();
        expect(canvasNode()?.data?.code).toBe("x = 1\n");
        expect(docNode()?.content).toBe("x = 1\n");
        expect(docToDataflow(provider.doc).edges.map((e: any) => [e.source, e.target])).toEqual([["n", "m"]]);
        other.destroy();
    });
});
