import React from "react";
import { render, act } from "@testing-library/react";

// Fake Monaco: uncontrolled model owned by the fake editor; onChange is fired
// by the __type test helper the way real typing would.
jest.mock("@monaco-editor/react", () => {
    // Typed: a jest.mock factory cannot close over the import above, so it
    // re-requires - and an unannotated require() is untyped, which makes
    // React.useRef<any>() a "type arguments on an untyped call" error.
    const React: typeof import("react") = require("react");
    const editors: any[] = [];
    function makeEditor(initial: string) {
        let value = initial;
        let position = { lineNumber: 1, column: 1 };
        const model = {
            getFullModelRange: () => ({ range: "full" }),
            validatePosition: (p: any) => p,
        };
        const editor: any = {
            getModel: () => model,
            getValue: () => value,
            setValue: (v: string) => { value = v; },
            getPosition: () => position,
            setPosition: (p: any) => { position = p; },
            executeEdits: jest.fn((_s: string, edits: any[]) => {
                value = edits[0].text;
                position = { lineNumber: 9999, column: 9999 };
                return true;
            }),
            pushUndoStop: () => {},
            onDidBlurEditorText: () => {},
            // Ctrl/Cmd+Enter registers through addAction on mount (#223).
            // Captured so a test can assert the binding, and present at all so
            // the mount does not run against a fake missing half the API.
            __actions: [] as any[],
            addAction(action: any) {
                editor.__actions.push(action);
                return { dispose: () => {} };
            },
            __type(v: string, pos = { lineNumber: 2, column: 3 }) {
                value = v;
                position = pos;
                editor.props?.onChange?.(v, {});
            },
            __position: () => position,
        };
        return editor;
    }
    const MockEditor = (props: any) => {
        const ref = React.useRef<any>(null);
        if (!ref.current) {
            ref.current = makeEditor(props.defaultValue ?? props.value ?? "");
            editors.push(ref.current);
        }
        ref.current.props = props;
        React.useEffect(() => {
            props.onMount?.(ref.current, {
                KeyMod: { CtrlCmd: 2048 },
                KeyCode: { Enter: 3 },
            });
        }, []);
        return React.createElement("div", { "data-testid": "mock-monaco" });
    };
    return { __esModule: true, default: MockEditor, __editors: editors };
});

const mockMarkNodeStale = jest.fn();
const mockPlayNodesUpTo = jest.fn();
jest.mock("../../../providers/FlowProvider", () => ({
    useFlowContext: () => ({
        workflowNameRef: { current: "wf" },
        markNodeExecuted: jest.fn(),
        markNodeStale: mockMarkNodeStale,
        playNodesUpTo: mockPlayNodesUpTo,
        signalNodeExecDone: jest.fn(),
        projectId: null,
        defaultSaveOutputDataset: false,
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
jest.mock("../../../utils/saveOutputDataset", () => ({
    resolveSaveOutputDataset: () => false,
}));
jest.mock("../../../utils/palettePackageFactoryDraft", () => ({
    resolveNodeDisplayLabel: () => "Node",
}));

import CodeEditor from "../../../components/editing/CodeEditor";

const { __editors } = jest.requireMock("@monaco-editor/react");
const lastEditor = () => __editors[__editors.length - 1];

const SAVED_CODE = "import pandas as pd\ndf = pd.DataFrame()";

function renderCodeEditor(defaultValue: string | undefined) {
    const sendCodeToWidgets = jest.fn();
    const floatCode = jest.fn();
    const props = (dv: string | undefined) => ({
        setOutputCallback: jest.fn(),
        data: { nodeId: "n1", input: "", inputTypes: [], outputCallback: jest.fn() },
        output: { code: "", content: "" },
        nodeType: "curio.builtin/python-computation@1" as any,
        replacedCode: "",
        sendCodeToWidgets,
        replacedCodeDirty: false,
        readOnly: false,
        defaultValue: dv,
        floatCode,
    });
    const view = render(<CodeEditor {...props(defaultValue)} />);
    return {
        sendCodeToWidgets,
        floatCode,
        setDefaultValue: (dv: string | undefined) =>
            view.rerender(<CodeEditor {...props(dv)} />),
        rerenderSame: () => view.rerender(<CodeEditor {...props(defaultValue)} />),
    };
}

describe("CodeEditor content sync (dev/70)", () => {
    beforeEach(() => {
        __editors.length = 0;
        mockMarkNodeStale.mockClear();
    });

    test("loads defaultValue into the editor and resolves widget markers", () => {
        const { sendCodeToWidgets } = renderCodeEditor(SAVED_CODE);
        expect(lastEditor().getValue()).toBe(SAVED_CODE);
        expect(sendCodeToWidgets).toHaveBeenCalledWith(SAVED_CODE);
    });

    test("an undefined defaultValue leaves the editor empty (fresh palette node)", () => {
        const { sendCodeToWidgets } = renderCodeEditor(undefined);
        expect(lastEditor().getValue()).toBe("");
        expect(lastEditor().executeEdits).not.toHaveBeenCalled();
        expect(sendCodeToWidgets).not.toHaveBeenCalled();
    });

    test("regression: typing is never rewritten by re-renders with the same defaultValue", () => {
        const { rerenderSame, floatCode } = renderCodeEditor(SAVED_CODE);
        const editor = lastEditor();
        const initialApplies = editor.executeEdits.mock.calls.length;

        act(() => { editor.__type(SAVED_CODE + "\nprint(1)", { lineNumber: 3, column: 9 }); });
        rerenderSame(); // e.g. a context-driven canvas re-render mid-typing
        rerenderSame();

        // No further programmatic writes: content and cursor stay the user's.
        expect(editor.executeEdits.mock.calls.length).toBe(initialApplies);
        expect(editor.getValue()).toBe(SAVED_CODE + "\nprint(1)");
        expect(editor.__position()).toEqual({ lineNumber: 3, column: 9 });
        expect(floatCode).toHaveBeenCalledWith(SAVED_CODE + "\nprint(1)");
    });

    test("regression: defaultValue flipping to undefined and back never clobbers edits", () => {
        const { setDefaultValue } = renderCodeEditor(SAVED_CODE);
        const editor = lastEditor();

        act(() => { editor.__type("user code", { lineNumber: 1, column: 10 }); });
        setDefaultValue(undefined);
        setDefaultValue(SAVED_CODE);

        expect(editor.getValue()).toBe("user code");
    });

    test("a genuinely new external value (dataset drop / LLM apply) replaces content", () => {
        const { setDefaultValue, sendCodeToWidgets } = renderCodeEditor(SAVED_CODE);
        const editor = lastEditor();

        act(() => { editor.__type("user code"); });
        const external = "df = load_dataset('census')";
        setDefaultValue(external);

        expect(editor.getValue()).toBe(external);
        expect(sendCodeToWidgets).toHaveBeenCalledWith(external);
    });

    test("typing marks the node stale", () => {
        renderCodeEditor(SAVED_CODE);
        const editor = lastEditor();
        act(() => { editor.__type("x = 1"); });
        expect(mockMarkNodeStale).toHaveBeenCalledWith("n1");
    });
});

/**
 * #354: the editor half of Ctrl/Cmd+Enter was registered on mount and nothing
 * ever checked it. The fake above has recorded ``__actions`` since #223 with a
 * comment saying "so a test can assert the binding" - and no test read it.
 */
describe("the run-node shortcut is bound to the editor (#223)", () => {
    test("registers the action on mount", () => {
        renderCodeEditor(SAVED_CODE);
        const action = lastEditor().__actions.find((a: any) => a.id === "curio.runNode");
        expect(action).toBeDefined();
        expect(action.label).toBe("Run this node");
    });

    test("binds it to Ctrl/Cmd+Enter", () => {
        // CtrlCmd | Enter, from the KeyMod/KeyCode values the fake supplies on
        // mount. A keybinding that drifts off this chord is the regression.
        renderCodeEditor(SAVED_CODE);
        const action = lastEditor().__actions.find((a: any) => a.id === "curio.runNode");
        expect(action.keybindings).toEqual([2048 | 3]);
    });

    test("running it plays this node", () => {
        renderCodeEditor(SAVED_CODE);
        const action = lastEditor().__actions.find((a: any) => a.id === "curio.runNode");
        act(() => { action.run(); });
        expect(mockPlayNodesUpTo).toHaveBeenCalledWith("n1");
    });
});
