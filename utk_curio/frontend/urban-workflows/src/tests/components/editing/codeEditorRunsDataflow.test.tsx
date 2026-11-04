/**
 * A code node's run names the dataflow it is of, by the rule the dataflow's
 * agents follow (`useAgentsDataflowId`): the owner's canvas sends the dataflow
 * it saves, an invited editor's the dataflow its route opened, though the
 * editor's canvas saves none (`loadSharedProject`), and a watcher's sends none.
 * The backend then gives the run that dataflow's datasets and saved outputs,
 * for its owner and its editors alone.
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

let mockFlow: Record<string, unknown> = {};
jest.mock("../../../providers/FlowProvider", () => ({
    useFlowContext: () => ({
        workflowNameRef: { current: "wf" },
        markNodeExecuted: jest.fn(),
        markNodeStale: jest.fn(),
        markNodeErrored: jest.fn(),
        signalNodeExecDone: jest.fn(),
        playNodesUpTo: jest.fn(),
        isDashboardSource: () => false,
        projectId: null,
        viewerMode: "owner",
        defaultSaveOutputDataset: false,
        ...mockFlow,
    }),
}));
jest.mock("../../../providers/ProvenanceProvider", () => ({
    useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
// The tab's role in the dataflow's room: null until the room names it.
let mockRole: string | null = null;
jest.mock("../../../providers/CollaborationProvider", () => ({
    useCollab: () => ({
        connected: false,
        users: [],
        lockedNodes: {},
        role: mockRole,
        onRemote: () => () => undefined,
    }),
}));
jest.mock("../../../utils/palettePackageFactoryDraft", () => ({
    resolveNodeDisplayLabel: () => "Node",
}));
jest.mock("../../../hook/usePackageBackendRun", () => ({
    usePackageBackendRun: () => null,
}));

import CodeEditor from "../../../components/editing/CodeEditor";
import { clearCurrentProject, setCurrentProject } from "../../../registry/projectPackagesStore";

const PYTHON = "curio.builtin/computation-analysis";
const CODE = 'trees = curio_load_data("imported.xstreet-trees")\nreturn trees';
const ALICES = "alices-dataflow";

/** Play the node, as a play delivers its resolved code; the dataflow its run is sent with. */
function dataflowOfItsRun(): unknown {
    const interpretCode = jest.fn();
    const data: any = {
        nodeId: "n1",
        nodeType: PYTHON,
        input: "",
        inputTypes: [],
        outputCallback: jest.fn(),
        pythonInterpreter: { interpretCode },
    };
    const props = (dirty: number) => ({
        setOutputCallback: jest.fn(),
        data,
        output: { code: "exec", content: "" },
        nodeType: PYTHON as any,
        replacedCode: CODE,
        sendCodeToWidgets: jest.fn(),
        replacedCodeDirty: dirty,
        readOnly: false,
        defaultValue: CODE,
        floatCode: jest.fn(),
    });
    const view = render(<CodeEditor {...props(0)} />);
    act(() => {
        view.rerender(<CodeEditor {...props(1)} />);
    });
    expect(interpretCode).toHaveBeenCalledTimes(1);
    // interpretCode(code, resolved code, input, input types, callback, node
    // type, node id, workflow name, provenance, dataflow, ...)
    return interpretCode.mock.calls[0][9];
}

beforeEach(() => {
    jest.clearAllMocks();
    mockFlow = {};
    mockRole = null;
    clearCurrentProject();
});

describe("a code node's run names the dataflow it is of", () => {
    test("on the owner's canvas, the dataflow it saves", () => {
        mockFlow = { projectId: ALICES, viewerMode: "owner" };
        setCurrentProject(ALICES, []);
        expect(dataflowOfItsRun()).toBe(ALICES);
    });

    test("on an invited editor's, the dataflow its route opened", () => {
        mockFlow = { projectId: null, viewerMode: "shared" };
        mockRole = "editor";
        setCurrentProject(ALICES, []);
        expect(dataflowOfItsRun()).toBe(ALICES);
    });

    test("on a watcher's, none", () => {
        mockFlow = { projectId: null, viewerMode: "shared" };
        mockRole = "watcher";
        setCurrentProject(ALICES, []);
        expect(dataflowOfItsRun() ?? null).toBeNull();
    });

    test("on an editor's the room has not named one yet, none", () => {
        mockFlow = { projectId: null, viewerMode: "shared" };
        setCurrentProject(ALICES, []);
        expect(dataflowOfItsRun() ?? null).toBeNull();
    });
});
