/**
 * The categories the canvas title shows follow the dataflow's changes, on the
 * REAL FlowProvider bound to a doc that syncs with the server: no tab saves
 * the dataflow any more, whose answer carried them, so every tab bound to the
 * doc asks the server again (`GET /api/projects/<id>/categories`).
 *
 * - after a burst of this tab's edits, once the server has them and changes
 *   have been quiet for 3 seconds: one request;
 * - after a change another tab made, in the owner's tab and a watcher's: one;
 * - when a run on the server ends: one, at once;
 * - none while changes keep coming, then one once they stop.
 *
 * The requests are counted where they leave the page (`fetch`), so a checkout
 * that never asks fails each case at its own count.
 */
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
// The dataflow's owner, signed in: its runs go to the server.
jest.mock("../../providers/UserProvider", () => ({
    useUserContext: () => ({
        user: { id: 1, username: "ana", name: "Ana", is_guest: false },
        enableUserAuth: true,
        skipProjectPage: false,
    }),
}));
jest.mock("../../services/runs/runsApi", () => {
    const actual = jest.requireActual("../../services/runs/runsApi");
    return {
        ...actual,
        runsApi: {
            start: jest.fn(),
            get: jest.fn(),
            listForProject: jest.fn(),
            cancel: jest.fn(),
            reportStep: jest.fn(),
            follow: jest.fn(),
        },
    };
});

import FlowProvider, { useFlowContext } from "../../providers/FlowProvider";
import { useCode } from "../../hook/useCode";
import { DataflowDocContext, type DocBinding } from "../../providers/collab/docContext";
import { DataflowDocProvider } from "../../providers/collab/docProvider";
import { applyDataflow, dataflowToDoc, docToDataflow } from "../../providers/collab/docMapping";
import { setCurrentProject } from "../../registry/projectPackagesStore";
import { runsApi } from "../../services/runs/runsApi";
import type { Run, RunEvent, RunStep } from "../../services/runs/runsApi";

const PROJECT = "5b0d7e21-3c4a-4f8e-9a6b-1d2c3e4f5a6b";
const TYPE = "curio.builtin/python-computation@1";
const CATEGORIES_PATH = `/api/projects/${PROJECT}/categories`;
/** What the server answers the categories are. */
const ANSWERED = { source: null, auto: { tags: ["Pandas"], data_type: ["Tables"] }, hand: {} };

const runs = runsApi as jest.Mocked<typeof runsApi>;
const realImmediate: (done: () => void) => void = jest.requireActual("timers").setImmediate;

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

/** The room's socket as the server answers it: each sync starts at once, and
 *  each change is answered at once, or held until `answer` while `holding`. */
class ServerSocket {
    connected = true;
    holding = false;
    private unanswered: Array<() => void> = [];
    private handlers: Record<string, Array<(payload: any) => void>> = {};

    on(event: string, handler: (payload: any) => void) {
        (this.handlers[event] ??= []).push(handler);
    }

    off(event: string, handler: (payload: any) => void) {
        this.handlers[event] = (this.handlers[event] ?? []).filter((h) => h !== handler);
    }

    emit(_event: string, payload: any, ack?: (answer: any) => void) {
        if (!ack) return;
        const bytes: Uint8Array = payload.message;
        // A sync's step 1 starts the tab's sync; anything else is a change.
        if (bytes[0] === 0 && bytes[1] === 0) {
            ack({ ok: true, docId: "doc-1" });
        } else if (this.holding) {
            this.unanswered.push(() => ack({ ok: true, kept: {} }));
        } else {
            ack({ ok: true, kept: {} });
        }
    }

    /** The server has the changes it held. */
    answer() {
        const unanswered = this.unanswered;
        this.unanswered = [];
        this.holding = false;
        unanswered.forEach((ack) => ack());
    }

    /** How many changes wait for the server's answer. */
    waiting() {
        return this.unanswered.length;
    }
}

type FlowApi = ReturnType<typeof useFlowContext>;
let api: FlowApi;
let code: ReturnType<typeof useCode>;
let provider: DataflowDocProvider;
let socket: ServerSocket;

const Bridge: React.FC = () => {
    api = useFlowContext();
    code = useCode();
    return (
        <div style={{ width: 800, height: 600 }}>
            <ReactFlow nodes={api.nodes} edges={api.edges} onNodesChange={api.onNodesChange} onEdgesChange={api.onEdgesChange} />
        </div>
    );
};

const fetchMock = jest.fn(async (url: unknown) => ({
    ok: true,
    status: 200,
    json: async () => (String(url).endsWith(CATEGORIES_PATH) ? { categories: ANSWERED } : {}),
}));

/** How many times the page asked for the dataflow's categories. */
const asked = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith(CATEGORIES_PATH)).length;

/** Let every answer the page waits for land. */
async function settle() {
    for (let turn = 0; turn < 3; turn++) {
        await act(async () => {
            await new Promise<void>((resolve) => realImmediate(resolve));
        });
    }
}

/** *ms* pass on the page's clock. */
async function pass(ms: number) {
    await act(async () => {
        await jest.advanceTimersByTimeAsync(ms);
    });
    await settle();
}

/** Open the dataflow on a canvas bound to its doc, synced on the socket, and
 *  let what the opening does settle. Answers how many times it asked. */
async function open(canWrite = true): Promise<number> {
    // The page's clock is the test's from the start: what the opening waits
    // for passes below, before anything is counted.
    jest.useFakeTimers({ doNotFake: ["queueMicrotask", "nextTick"] });
    provider = new DataflowDocProvider(PROJECT, { canWrite });
    // The doc as the server's first sync leaves it.
    provider.doc.transact(() => dataflowToDoc(spec().dataflow, provider.doc, "doc-1"), provider);
    socket = new ServerSocket();
    provider.attach(socket);
    setCurrentProject(PROJECT, []);
    const binding: DocBinding = { provider, synced: true };
    render(
        <DataflowDocContext.Provider value={binding}>
            <ReactFlowProvider>
                <FlowProvider>
                    <Bridge />
                </FlowProvider>
            </ReactFlowProvider>
        </DataflowDocContext.Provider>,
    );
    await settle();
    act(() => {
        code.loadTrill(spec());
    });
    await settle();
    await pass(5000);
    return asked();
}

/** This tab's own edit of node n's code. */
async function editHere(text: string) {
    act(() => api.updateDefaultCode("n", text));
    await settle();
}

/** Another tab's change, as the provider applies one the server relays. */
async function fromAnotherTab(change: (dataflow: any) => void) {
    const before = docToDataflow(provider.doc);
    const after = JSON.parse(JSON.stringify(before));
    change(after);
    await act(async () => {
        provider.doc.transact(() => applyDataflow(provider.doc, before, after), provider);
    });
    await settle();
}

const docCode = () => docToDataflow(provider.doc).nodes.find((n: any) => n.id === "n")?.content;

beforeEach(() => {
    fetchMock.mockClear();
    (global as any).fetch = fetchMock;
});

afterEach(() => {
    jest.useRealTimers();
    provider?.destroy();
    mockShowToast.mockClear();
});

test("a burst of this tab's edits asks once, after the server has them and they stop for 3 seconds", async () => {
    const before = await open();
    socket.holding = true;

    for (let edit = 1; edit <= 5; edit++) {
        await editHere(`import pandas as pd\nx = ${edit}\n`);
        await pass(200);
    }
    expect(docCode()).toBe("import pandas as pd\nx = 5\n");
    expect(socket.waiting()).toBeGreaterThan(0);

    // Quiet for 3 seconds, but the server does not have the edits yet.
    await pass(3000);
    expect(asked() - before).toBe(0);

    act(() => socket.answer());
    await settle();
    expect(asked() - before).toBe(1);
    expect(api.serverCategories).toEqual(ANSWERED);

    await pass(10000);
    expect(asked() - before).toBe(1);
});

test.each([
    ["the owner's", true],
    ["a watcher's", false],
])("a change another tab made asks once in %s tab, 3 seconds after it", async (_who, canWrite) => {
    const before = await open(canWrite);

    await fromAnotherTab((df) => {
        df.nodes[0].content = "import pandas as pd\n";
    });
    expect(docCode()).toBe("import pandas as pd\n");

    await pass(2800);
    expect(asked() - before).toBe(0);
    await pass(400);
    expect(asked() - before).toBe(1);
    expect(api.serverCategories).toEqual(ANSWERED);

    await pass(10000);
    expect(asked() - before).toBe(1);
});

function step(nodeId: string, fields: Partial<RunStep> = {}): RunStep {
    return {
        nodeId, label: nodeId, nodeType: TYPE, level: 0,
        role: "run", status: "pending", startedAt: null, finishedAt: null, durationMs: null,
        outputPath: null, outputType: null, installedDatasetId: null, codeSha256: null,
        stdoutTail: null, stderrTail: null, skipReason: null, ...fields,
    };
}

function run(id: string, steps: RunStep[], fields: Partial<Run> = {}): Run {
    return {
        id, projectId: PROJECT, projectName: "Bound", trigger: "all", targetNodeId: null,
        wholeDataflow: true, rerunOf: null, specRevision: 3, status: "queued",
        createdAt: null, startedAt: null, finishedAt: null,
        counts: { ok: 0, failed: 0, skipped: 0, waiting: 0 }, error: null, live: true,
        steps, ...fields,
    };
}

test("a run on the server that ends asks once, at once", async () => {
    const before = await open();
    let emit: (event: RunEvent) => void = () => {};
    runs.follow.mockImplementation((_runId, onEvent, signal) => {
        emit = (event) => act(() => onEvent(event));
        return new Promise<void>((resolve) => signal?.addEventListener("abort", () => resolve()));
    });
    runs.listForProject.mockResolvedValue([run("r1", [], { status: "running" })]);
    runs.get.mockResolvedValue(run("r1", [step("n", { status: "running" })], { status: "running" }));
    await act(async () => {
        await api.attachLatestRun(PROJECT);
    });
    await settle();
    expect(api.serverRunActive).toBe(true);
    expect(asked() - before).toBe(0);

    emit({ kind: "run_finished", status: "succeeded", ok: 1, failed: 0, skipped: 0, waiting: 0 });
    await settle();
    expect(asked() - before).toBe(1);
    expect(api.serverCategories).toEqual(ANSWERED);

    await pass(10000);
    expect(asked() - before).toBe(1);
});

test("edits that keep coming ask nothing until they stop, then once", async () => {
    const before = await open();

    for (let edit = 1; edit <= 10; edit++) {
        await editHere(`import pandas as pd\nx = ${edit}\n`);
        await pass(1000);
        expect(asked() - before).toBe(0);
    }
    expect(docCode()).toBe("import pandas as pd\nx = 10\n");

    await pass(1800);
    expect(asked() - before).toBe(0);
    await pass(400);
    expect(asked() - before).toBe(1);
    expect(api.serverCategories).toEqual(ANSWERED);
});
