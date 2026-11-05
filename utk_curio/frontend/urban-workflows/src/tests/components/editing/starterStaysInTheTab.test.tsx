/**
 * A starter is not an edit. A Vega-Lite chart or an Autark map whose input
 * arrives with an empty editor gets a starter chosen in this tab from that
 * input (`hook/useStarterSpec`). Its editor shows it, but the dataflow's doc
 * does not take it as the node's spec until someone edits it
 * (`useYMonacoBinding`); otherwise the server's copy holds the starter, and
 * Solve keeps it as a person's edit and drops its own spec. Nor is the spec
 * editor's empty `{}` the node's spec. A chart template's own starter is the
 * node's spec, as before.
 *
 * The real GrammarEditor, bound to a node of the dataflow's doc. y-monaco is
 * stubbed with what it does here: the doc's text goes into the editor when
 * it binds, each change of the editor goes into the doc, as typing does, and
 * each change of the doc into the editor.
 */
import React from "react";
import { act, render, waitFor } from "@testing-library/react";
import * as Y from "yjs";

// One Monaco editor and its model: content written into it, by `executeEdits`
// or `setValue`, and typing tell the model's listeners and the editor's
// `onChange`, as Monaco's do.
jest.mock("@monaco-editor/react", () => {
    const React: typeof import("react") = require("react");
    const editors: any[] = [];
    // Loosely typed: a jest.mock factory may name nothing outside itself, and
    // babel takes a parameter's name in a type annotation for such a name.
    function makeEditor(initial: string) {
        let value = initial;
        const listeners = new Set<any>();
        const editor: any = {};
        const changed = () => {
            listeners.forEach((listener) => listener({ changes: [] }));
            editor.props?.onChange?.(value, {});
        };
        const model = {
            getValue: () => value,
            setValue: (next: string) => {
                value = next;
                changed();
            },
            getFullModelRange: () => ({ range: "full" }),
            validatePosition: (position: any) => position,
            onDidChangeContent: (listener: any) => {
                listeners.add(listener);
                return { dispose: () => listeners.delete(listener) };
            },
        };
        Object.assign(editor, {
            getModel: () => model,
            getValue: () => value,
            setValue: (next: string) => model.setValue(next),
            getPosition: () => ({ lineNumber: 1, column: 1 }),
            setPosition: () => undefined,
            executeEdits: (_source: string, edits: any[]) => {
                value = edits[0].text;
                changed();
                return true;
            },
            pushUndoStop: () => undefined,
            onDidFocusEditorText: () => ({ dispose: () => undefined }),
            onDidBlurEditorText: () => ({ dispose: () => undefined }),
            hasTextFocus: () => false,
            /** A person types until the editor holds *next*. */
            type(next: string) {
                value = next;
                changed();
            },
        });
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
            props.onMount?.(ref.current, { languages: { json: { jsonDefaults: { setDiagnosticsOptions: () => undefined } } } });
        }, []);
        return React.createElement("div", { "data-testid": "mock-monaco" });
    };
    return { __esModule: true, default: MockEditor, __editors: editors };
});

const mockBindings: Array<{ destroyed: boolean }> = [];
jest.mock("y-monaco", () => ({
    MonacoBinding: class {
        destroyed = false;
        private busy = false;
        private readonly ytext: any;
        private readonly observer: any;
        private readonly listener: any;
        constructor(ytext: any, model: any) {
            this.ytext = ytext;
            const shown = ytext.toString();
            if (model.getValue() !== shown) model.setValue(shown);
            this.observer = () => {
                if (this.busy) return;
                this.busy = true;
                try {
                    model.setValue(ytext.toString());
                } finally {
                    this.busy = false;
                }
            };
            ytext.observe(this.observer);
            this.listener = model.onDidChangeContent(() => {
                if (this.busy) return;
                this.busy = true;
                try {
                    const typed = model.getValue();
                    ytext.doc.transact(() => {
                        ytext.delete(0, ytext.length);
                        ytext.insert(0, typed);
                    }, this);
                } finally {
                    this.busy = false;
                }
            });
            mockBindings.push(this);
        }
        destroy() {
            this.destroyed = true;
            this.ytext.unobserve(this.observer);
            this.listener.dispose();
        }
    },
}));

// The editor reads playNodesUpTo for its run chord; FlowProvider pulls in the
// registry and vega, which do not load under jsdom.
jest.mock("../../../providers/FlowProvider", () => ({
    useFlowContext: () => ({ playNodesUpTo: jest.fn(), dashboardOn: false }),
}));
jest.mock("../../../providers/CollaborationProvider", () => ({
    useCollab: () => ({ connected: false, users: [], lockedNodes: {}, onRemote: () => () => undefined }),
}));

import GrammarEditor from "../../../components/editing/GrammarEditor";
import { DataflowDocContext } from "../../../providers/collab/docContext";
import { DataflowDocProvider } from "../../../providers/collab/docProvider";
import { dataflowToDoc, replaceText } from "../../../providers/collab/docMapping";

const { __editors } = jest.requireMock("@monaco-editor/react");
const editor = () => __editors[__editors.length - 1];

/** The starter a chart chose from its input, an edit of it, and the spec Solve wrote. */
const STARTER = '{\n  "mark": "geoshape",\n  "encoding": {"shape": {"field": "geometry", "type": "geojson"}}\n}';
const EDITED = STARTER.replace("geoshape", "point");
const SOLVED = '{\n  "mark": "bar",\n  "encoding": {"x": {"field": "name", "type": "nominal"}}\n}';
/** A chart template's own starter, which is the node's spec. */
const TEMPLATE = '{\n  "mark": "line"\n}';

let providers: DataflowDocProvider[] = [];

/** A dataflow's doc holding the chart "chart" with *fields*: `content` for a
 *  planned node's empty spec, none for a node just dropped. */
function docWith(fields: Record<string, unknown>): DataflowDocProvider {
    const provider = new DataflowDocProvider("project-starter", { canWrite: true });
    dataflowToDoc({
        name: "Starters",
        nodes: [{ id: "chart", type: "curio.builtin/vis-vega", x: 0, y: 0, ...fields }],
        edges: [],
    }, provider.doc, "doc-starter");
    provider.synced = true;
    providers.push(provider);
    return provider;
}

/** The chart's spec in the doc, or null when it has none. */
function specIn(provider: DataflowDocProvider): string | null {
    const node = provider.doc.getMap("nodes").get("chart") as Y.Map<unknown>;
    const text = node.get("content");
    return text instanceof Y.Text ? text.toString() : null;
}

/** The server writes *spec* into the chart, as Solve does: into the copy it
 *  holds, which the tab's doc then takes as a remote change. */
function serverWrites(provider: DataflowDocProvider, spec: string) {
    const server = new Y.Doc();
    Y.applyUpdate(server, Y.encodeStateAsUpdate(provider.doc));
    const seen = Y.encodeStateVector(provider.doc);
    const node = server.getMap("nodes").get("chart") as Y.Map<unknown>;
    server.transact(() => {
        const text = node.get("content");
        if (text instanceof Y.Text) replaceText(text, spec);
        else node.set("content", new Y.Text(spec));
    });
    act(() => Y.applyUpdate(provider.doc, Y.encodeStateAsUpdate(server, seen), "server"));
}

/** What the editor is handed: its content, and whether it is a starter. */
type Handed = { defaultValue?: string; starter?: string };

/** The chart's spec editor, bound to *provider*'s doc, handed *first*. */
function chartEditor(provider: DataflowDocProvider, first: Handed) {
    // Loosely typed: the props are the editor's whatever its version.
    const props = (handed: Handed): any => ({
        output: { code: "", content: "" },
        nodeId: "chart",
        applyGrammar: jest.fn(),
        replacedCode: "",
        sendCodeToWidgets: jest.fn(),
        replacedCodeDirty: 0,
        floatCode: jest.fn(),
        readOnly: false,
        ...handed,
    });
    const tree = (handed: Handed) => (
        <DataflowDocContext.Provider value={{ provider, synced: true }}>
            <GrammarEditor {...props(handed)} />
        </DataflowDocContext.Provider>
    );
    const view = render(tree(first));
    return { hand: (next: Handed) => view.rerender(tree(next)) };
}

/** Let a bind that waits on y-monaco's import end. */
async function settle() {
    for (let i = 0; i < 5; i++) {
        await act(async () => {
            await Promise.resolve();
        });
    }
}

beforeEach(() => {
    mockBindings.length = 0;
});

afterEach(() => {
    providers.forEach((provider) => provider.destroy());
    providers = [];
});

describe("a planned chart, whose doc holds its empty spec", () => {
    async function handedItsStarter() {
        const provider = docWith({ content: "" });
        const chart = chartEditor(provider, { defaultValue: "" });
        await waitFor(() => expect(mockBindings).toHaveLength(1));
        chart.hand({ defaultValue: STARTER, starter: STARTER });
        await waitFor(() => expect(editor().getValue()).toBe(STARTER));
        await settle();
        return provider;
    }

    test("shows the starter it chose from its input, and the doc keeps the spec empty", async () => {
        const provider = await handedItsStarter();

        expect(editor().getValue()).toBe(STARTER);
        expect(specIn(provider)).toBe("");
    });

    test("shows the spec Solve writes into the doc in the starter's place, whole", async () => {
        const provider = await handedItsStarter();
        expect(specIn(provider)).toBe("");

        serverWrites(provider, SOLVED);

        await waitFor(() => expect(editor().getValue()).toBe(SOLVED));
        expect(specIn(provider)).toBe(SOLVED);
    });

    test("writes the starter as edited into the doc at the first edit, and every edit after", async () => {
        const provider = await handedItsStarter();
        expect(specIn(provider)).toBe("");

        act(() => editor().type(EDITED));
        await waitFor(() => expect(specIn(provider)).toBe(EDITED));
        await settle();
        act(() => editor().type(SOLVED));

        await waitFor(() => expect(specIn(provider)).toBe(SOLVED));
        expect(editor().getValue()).toBe(SOLVED);
    });
});

describe("a chart just dropped, whose doc holds no spec", () => {
    test("leaves its empty spec and its starter out of the doc, and writes its first edit", async () => {
        const provider = docWith({});
        const chart = chartEditor(provider, {});
        await settle();
        expect(editor().getValue()).toBe("{}");
        expect(specIn(provider)).toBeNull();

        chart.hand({ defaultValue: STARTER, starter: STARTER });
        await waitFor(() => expect(editor().getValue()).toBe(STARTER));
        await settle();
        expect(specIn(provider)).toBeNull();

        act(() => editor().type(EDITED));
        await waitFor(() => expect(specIn(provider)).toBe(EDITED));
    });

    test("takes a chart template's own starter as its spec, as before", async () => {
        const provider = docWith({});
        chartEditor(provider, { defaultValue: TEMPLATE });

        await waitFor(() => expect(specIn(provider)).toBe(TEMPLATE));
        expect(editor().getValue()).toBe(TEMPLATE);
    });
});
