import React from "react";
import { render, act } from "@testing-library/react";

// Fake Monaco: uncontrolled model owned by the fake editor; onChange is fired
// by the __type test helper the way real typing would. executeEdits replaces
// the whole content (what the hook uses for external applies).
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
            __type(v: string) {
                value = v;
                editor.props?.onChange?.(v, {});
            },
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
                languages: { json: { jsonDefaults: { setDiagnosticsOptions: () => {} } } },
            });
        }, []);
        return React.createElement("div", { "data-testid": "mock-monaco" });
    };
    return { __esModule: true, default: MockEditor, __editors: editors };
});

// The editor reads playNodesUpTo for the Ctrl/Cmd+Enter binding (#223), and
// FlowProvider pulls in the registry -> adapters -> vega chain, which does not
// load under jsdom. Same stub pattern the other suites that touch it use.
jest.mock("../../../providers/FlowProvider", () => ({
    useFlowContext: () => ({ playNodesUpTo: jest.fn() }),
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

import GrammarEditor from "../../../components/editing/GrammarEditor";

const { __editors } = jest.requireMock("@monaco-editor/react");
const lastEditor = () => __editors[__editors.length - 1];

const DEFAULT_SPEC = '{\n  "map": { "layerRefs": [] }\n}';

function renderGrammarEditor(defaultValue: string | undefined, floatCode = jest.fn()) {
    const props = (dv: string | undefined) => ({
        output: { code: "", content: "" },
        nodeId: "n1",
        applyGrammar: jest.fn(),
        schema: undefined,
        replacedCode: "",
        sendCodeToWidgets: jest.fn(),
        replacedCodeDirty: false,
        defaultValue: dv,
        floatCode,
        readOnly: false,
    });
    const view = render(<GrammarEditor {...props(defaultValue)} />);
    return {
        floatCode,
        setDefaultValue: (dv: string | undefined) =>
            view.rerender(<GrammarEditor {...props(dv)} />),
    };
}

describe("GrammarEditor content sync (dev/70)", () => {
    beforeEach(() => { __editors.length = 0; });

    test("loads the external spec into the editor once", () => {
        renderGrammarEditor(DEFAULT_SPEC);
        expect(lastEditor().getValue()).toBe(DEFAULT_SPEC);
        expect(lastEditor().executeEdits).toHaveBeenCalledTimes(1);
    });

    test("regression: defaultValue flipping spec→undefined→spec never resets typed content", () => {
        const { floatCode, setDefaultValue } = renderGrammarEditor(DEFAULT_SPEC);
        const editor = lastEditor();

        act(() => { editor.__type('{"user": "edited"}'); });
        expect(editor.getValue()).toBe('{"user": "edited"}');

        // The oscillation the old data.code-derived override produced.
        setDefaultValue(undefined);
        setDefaultValue(DEFAULT_SPEC);
        setDefaultValue(undefined);

        expect(editor.getValue()).toBe('{"user": "edited"}');
        // floatCode saw only strings — never the undefined that used to poison
        // nodeState.code / data.code.
        for (const call of floatCode.mock.calls) {
            expect(typeof call[0]).toBe("string");
        }
    });

    // These two also carry what tests/components/grammarEditorUndefinedGuard.test.tsx
    // used to assert ("adopts a real defaultValue that arrives after mount" and
    // "an undefined defaultValue does not wipe the editor", #157). That file mocked
    // Monaco as a plain textarea driven by a `value` prop, which stopped matching
    // the editor once content started flowing through useMonacoExternalValue; the
    // fake editor here exercises the real path instead.
    test("a genuinely new external value still replaces the content", () => {
        const { floatCode, setDefaultValue } = renderGrammarEditor(DEFAULT_SPEC);
        const editor = lastEditor();

        act(() => { editor.__type('{"user": "edited"}'); });
        const external = '{"plot": {}}';
        setDefaultValue(external);

        expect(editor.getValue()).toBe(external);
        expect(floatCode).toHaveBeenCalledWith(external);
    });

    test("typing floats every keystroke to nodeState.code", () => {
        const { floatCode } = renderGrammarEditor(DEFAULT_SPEC);
        const editor = lastEditor();

        act(() => { editor.__type('{"a":1}'); });
        act(() => { editor.__type('{"a":12}'); });

        expect(floatCode).toHaveBeenCalledWith('{"a":1}');
        expect(floatCode).toHaveBeenCalledWith('{"a":12}');
    });
});
