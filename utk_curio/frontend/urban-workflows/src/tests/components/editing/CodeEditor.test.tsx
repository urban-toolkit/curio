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
    // dev/117: the mount's monaco stub grows setModelMarkers so the credential
    // hint's best-effort markers can be asserted; a test may delete it to
    // exercise the "no markers here" path.
    const setModelMarkers = jest.fn();
    const monacoStub: any = {
        KeyMod: { CtrlCmd: 2048 },
        KeyCode: { Enter: 3 },
        MarkerSeverity: { Warning: 4 },
        editor: { setModelMarkers },
    };
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
            props.onMount?.(ref.current, monacoStub);
        }, []);
        return React.createElement("div", { "data-testid": "mock-monaco" });
    };
    return { __esModule: true, default: MockEditor, __editors: editors, __setModelMarkers: setModelMarkers, __monacoStub: monacoStub };
});

const mockMarkNodeStale = jest.fn();
jest.mock("../../../providers/FlowProvider", () => ({
    useFlowContext: () => ({
        workflowNameRef: { current: "wf" },
        markNodeExecuted: jest.fn(),
        markNodeStale: mockMarkNodeStale,
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

const { __editors, __setModelMarkers, __monacoStub } = jest.requireMock("@monaco-editor/react");
const lastEditor = () => __editors[__editors.length - 1];

const SAVED_CODE = "import pandas as pd\ndf = pd.DataFrame()";

function renderCodeEditor(defaultValue: string | undefined, opts: { readOnly?: boolean } = {}) {
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
        readOnly: opts.readOnly ?? false,
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


describe("CodeEditor credential hint (dev/117)", () => {
    const { screen, fireEvent } = require("@testing-library/react");
    const { CREDENTIAL_SCAN_DEBOUNCE_MS } = require("../../../components/editing/CodeEditor");
    const { subscribeConnectionKeysRequests } = require("../../../components/connectionKeys/connectionKeysRequest");
    const VALUE = "AbCdEf0123456789xyzXYZ-_";
    const KEYED = `import requests\nurl = "https://api.census.gov/data"\napi_key = "${VALUE}"\nreturn 1`;
    const hint = () => screen.queryByTestId("credential-hint");

    beforeEach(() => {
        __editors.length = 0;
        __setModelMarkers.mockClear();
        jest.useFakeTimers();
    });
    afterEach(() => {
        jest.useRealTimers();
    });

    test("typing a key shows the bar after the debounce, naming the line; removing it hides the bar", () => {
        renderCodeEditor(SAVED_CODE);
        const editor = lastEditor();
        act(() => { editor.__type(KEYED); });
        expect(hint()).toBeNull(); // not per keystroke
        act(() => { jest.advanceTimersByTime(CREDENTIAL_SCAN_DEBOUNCE_MS); });
        expect(hint()).toHaveTextContent("Line 3 looks like an API key.");
        expect(hint()).toHaveTextContent('curio_secret("<name>")');
        expect(hint()!.textContent).not.toContain(VALUE);
        act(() => { editor.__type(KEYED.replace(`api_key = "${VALUE}"`, 'api_key = curio_secret("census")')); });
        act(() => { jest.advanceTimersByTime(CREDENTIAL_SCAN_DEBOUNCE_MS); });
        expect(hint()).toBeNull();
    });

    test("content that arrives whole is scanned at once, and the markers follow the findings", () => {
        const { setDefaultValue } = renderCodeEditor(SAVED_CODE);
        expect(hint()).toBeNull();
        act(() => { setDefaultValue(KEYED); }); // an external apply — no debounce
        expect(hint()).toHaveTextContent("Line 3 looks like an API key.");
        const [, owner, markers] = __setModelMarkers.mock.calls[__setModelMarkers.mock.calls.length - 1];
        expect(owner).toBe("curio-credential");
        expect(markers).toEqual([expect.objectContaining({ severity: 4, startLineNumber: 3, endLineNumber: 3 })]);
        expect(JSON.stringify(markers)).not.toContain(VALUE);
        act(() => { lastEditor().__type("return 1"); jest.advanceTimersByTime(CREDENTIAL_SCAN_DEBOUNCE_MS); });
        expect(hint()).toBeNull();
        expect(__setModelMarkers.mock.calls[__setModelMarkers.mock.calls.length - 1][2]).toEqual([]);
    });

    test("Dismiss hides the bar for that finding; a different literal shows it again", () => {
        const { setDefaultValue } = renderCodeEditor(KEYED);
        expect(hint()).not.toBeNull();
        fireEvent.click(screen.getByRole("button", { name: "Dismiss this hint" }));
        expect(hint()).toBeNull();
        act(() => { setDefaultValue(KEYED + `\ntoken = "${VALUE}"`); });
        expect(hint()).toHaveTextContent("Lines 3 and 5 look like API keys.");
    });

    test("Save as connection key asks for the settings form with the code's host and a suggested name", () => {
        const seen: unknown[] = [];
        const off = subscribeConnectionKeysRequests((f: unknown) => seen.push(f));
        renderCodeEditor(KEYED);
        fireEvent.click(screen.getByRole("button", { name: "Save this key as a connection key" }));
        expect(seen).toEqual([{ section: "connection-keys", host: "api.census.gov", suggestedName: "census" }]);
        off();
    });

    test("a read-only editor shows the text alone", () => {
        renderCodeEditor(KEYED, { readOnly: true });
        expect(hint()).toHaveTextContent("Line 3 looks like an API key.");
        expect(screen.queryByRole("button", { name: "Save this key as a connection key" })).toBeNull();
        expect(screen.queryByRole("button", { name: "Dismiss this hint" })).toBeNull();
    });

    test("a Monaco without setModelMarkers still gets the bar", () => {
        const saved = __monacoStub.editor;
        delete __monacoStub.editor;
        try {
            renderCodeEditor(KEYED);
            expect(hint()).toHaveTextContent("Line 3 looks like an API key.");
            expect(__setModelMarkers).not.toHaveBeenCalled();
        } finally {
            __monacoStub.editor = saved;
        }
    });

    test("the bar is a polite status region and never blocks: the model keeps the typed code", () => {
        renderCodeEditor(KEYED);
        expect(hint()).toHaveAttribute("role", "status");
        expect(hint()).toHaveAttribute("aria-live", "polite");
        expect(lastEditor().getValue()).toBe(KEYED);
    });
});
