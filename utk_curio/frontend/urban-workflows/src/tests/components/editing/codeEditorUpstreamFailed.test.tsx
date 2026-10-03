/**
 * A code node whose input comes from a failed node is not sent to the sandbox
 * (#603), and every way a code node's run can fail is reported the same way.
 *
 * #603: a Python Computation node fed by a Data Loading node that had just
 * failed still went to the sandbox with no input, and came back with
 * "This node received no input but its code references `arg`", a message
 * about wiring. The node now asks the question a chart or a Data Pool already
 * asks (hook/useGrammarInputState): did a node wired into me fail? If so it
 * says so, by name, and does not run.
 *
 * The other cases pin the failure report itself. A run that fails marks the
 * node errored (so the nodes it feeds can tell) and tells the runner it failed
 * (so the runner stops below it). Two branches did only part of that.
 */
import React from "react";
import { render, act } from "@testing-library/react";

jest.mock("@monaco-editor/react", () => {
    const React: typeof import("react") = require("react");
    const MockEditor = (props: any) => {
        React.useEffect(() => {
            props.onMount?.(
                {
                    getModel: () => null,
                    getValue: () => props.defaultValue ?? "",
                    setValue: () => {},
                    onDidBlurEditorText: () => {},
                    addAction: () => ({ dispose: () => {} }),
                    executeEdits: () => true,
                    pushUndoStop: () => {},
                    getPosition: () => ({ lineNumber: 1, column: 1 }),
                    setPosition: () => {},
                },
                { KeyMod: { CtrlCmd: 2048 }, KeyCode: { Enter: 3 } },
            );
        }, []);
        return React.createElement("div", { "data-testid": "mock-monaco" });
    };
    return { __esModule: true, default: MockEditor };
});

const mockMarkNodeErrored = jest.fn();
const mockSignalNodeExecDone = jest.fn();
let mockFlow: Record<string, unknown> = {};
jest.mock("../../../providers/FlowProvider", () => ({
    useFlowContext: () => ({
        workflowNameRef: { current: "wf" },
        markNodeExecuted: jest.fn(),
        markNodeStale: jest.fn(),
        markNodeErrored: mockMarkNodeErrored,
        signalNodeExecDone: mockSignalNodeExecDone,
        playNodesUpTo: jest.fn(),
        isDashboardSource: () => false,
        projectId: null,
        defaultSaveOutputDataset: false,
        ...mockFlow,
    }),
}));
jest.mock("../../../providers/ProvenanceProvider", () => ({
    useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
jest.mock("../../../providers/CollaborationProvider", () => ({
    useCollab: () => ({
        enabled: false,
        connected: false,
        users: [],
        proposals: [],
        currentUserId: null,
        lockedNodes: {},
        onRemote: () => () => undefined,
        requestCodeChange: jest.fn(),
        approveCodeChange: jest.fn(),
        rejectCodeChange: jest.fn(),
    }),
}));
jest.mock("../../../utils/palettePackageFactoryDraft", () => ({
    resolveNodeDisplayLabel: (data: any) => data?.packageTemplateLabel ?? "Node",
}));
let mockBackendRun: any = null;
jest.mock("../../../hook/usePackageBackendRun", () => ({
    usePackageBackendRun: () => mockBackendRun,
}));

import CodeEditor from "../../../components/editing/CodeEditor";

const PYTHON = "curio.builtin/computation-analysis";
const CODE = "sp = arg['sp_units']\nreturn sp";

/** The upstream node, failed: wired into n1 and marked errored. */
function upstreamFailed() {
    mockFlow = {
        edges: [{ id: "up->n1", source: "up", target: "n1" }],
        nodeExecStatus: { up: "errored" },
        nodes: [{ id: "up", data: { nodeId: "up", nodeType: "curio.builtin/data-loading", packageTemplateLabel: "Load parcels" } }],
    };
}

/** Mount, then deliver the resolved code the way a play does. */
function play({ replacedCode = CODE, result }: { replacedCode?: string; result?: any } = {}) {
    const setOutputCallback = jest.fn();
    const interpretCode = jest.fn((...args: any[]) => {
        if (result) args[4](result);
    });
    const data = {
        nodeId: "n1",
        nodeType: PYTHON,
        input: "",
        inputTypes: [],
        outputCallback: jest.fn(),
        pythonInterpreter: { interpretCode },
    };
    const props = (dirty: boolean) => ({
        setOutputCallback,
        data,
        output: { code: "exec", content: "" },
        nodeType: PYTHON as any,
        replacedCode,
        sendCodeToWidgets: jest.fn(),
        replacedCodeDirty: dirty,
        readOnly: false,
        defaultValue: CODE,
        floatCode: jest.fn(),
    });
    const view = render(<CodeEditor {...props(false)} />);
    act(() => {
        view.rerender(<CodeEditor {...props(true)} />);
    });
    return { setOutputCallback, interpretCode };
}

beforeEach(() => {
    jest.clearAllMocks();
    mockFlow = {};
    mockBackendRun = null;
});

describe("a code node fed by a failed node (#603)", () => {
    test("is not sent to the sandbox", () => {
        upstreamFailed();
        const { interpretCode } = play();
        expect(interpretCode).not.toHaveBeenCalled();
    });

    test("says which node feeding it failed, instead of a wiring message", () => {
        upstreamFailed();
        const { setOutputCallback } = play();
        const shown = setOutputCallback.mock.calls.map((c) => c[0]);
        const reason = shown.find((o: any) => o?.code === "error");
        expect(reason).toBeDefined();
        expect(reason.content).toContain("The node feeding this one");
        expect(reason.content).toContain("Load parcels");
        expect(reason.content).not.toContain("received no input");
    });

    test("reports itself failed, so the runner stops below it too", () => {
        upstreamFailed();
        play();
        expect(mockMarkNodeErrored).toHaveBeenCalledWith("n1");
        expect(mockSignalNodeExecDone).toHaveBeenCalledWith("n1", { failed: true });
    });

    test("an upstream that ran is no reason to stop", () => {
        mockFlow = {
            edges: [{ id: "up->n1", source: "up", target: "n1" }],
            nodeExecStatus: { up: "executed" },
        };
        const { interpretCode } = play();
        expect(interpretCode).toHaveBeenCalledTimes(1);
    });
});

describe("every failed run is reported the same way", () => {
    test("a sandbox failure tells the runner it failed", () => {
        play({ result: { output: { path: "" }, stdout: [], stderr: "Traceback (most recent call last):\nRuntimeError: boom" } });
        expect(mockMarkNodeErrored).toHaveBeenCalledWith("n1");
        expect(mockSignalNodeExecDone).toHaveBeenCalledWith("n1", { failed: true });
    });

    test("an empty editor is a failure the runner hears about", () => {
        const { setOutputCallback } = play({ replacedCode: "" });
        expect(setOutputCallback).toHaveBeenCalledWith({ code: "error", content: "No code to execute" });
        expect(mockMarkNodeErrored).toHaveBeenCalledWith("n1");
        expect(mockSignalNodeExecDone).toHaveBeenCalledWith("n1", { failed: true });
    });

    test("a package backend failure marks the node errored", async () => {
        mockBackendRun = jest.fn().mockResolvedValue({ ok: false, content: "HandlerError: boom" });
        const { setOutputCallback } = play();
        await act(async () => {
            await Promise.resolve();
            await Promise.resolve();
        });
        expect(setOutputCallback).toHaveBeenCalledWith({ code: "error", content: "HandlerError: boom" });
        expect(mockMarkNodeErrored).toHaveBeenCalledWith("n1");
        expect(mockSignalNodeExecDone).toHaveBeenCalledWith("n1", { failed: true });
    });
});
