/**
 * A node shows what an agent writes into it while the agent writes it, in
 * every tab: its code or spec, or its Widgets tab for a widget's value, with
 * the changed lines or widgets marked for a moment as they land. A setting
 * turns no tab. When the agent is done, the node shows the tab it had, its
 * Widgets tab when it opens on its controls; a tab a person picked before, or
 * while the agent wrote, stays. The notebook view's cells turn the same way.
 * The node's lock chip shows the agent's glyph in its tint, and says on hover
 * who is editing and who asked; a tab of the shared guest account's names it
 * by its number.
 *
 * The room is the real CollaborationProvider on a fake socket, as
 * collabRoles.test.tsx has it, and the agent reaches this tab as the server
 * sends it (step 14.2):
 * - its awareness state, on the doc's `yjs` messages: its `user` names it
 *   (`agent`), `editing` is the node it is writing and `writes` what it writes
 *   there, whether it holds the node's lock or writes under its asker's;
 * - its lock, the room's soft lock named after it, with `agent` and `writes`,
 *   by `node_locked` and `node_unlocked`.
 *
 * Each node is UniversalNode with its real NodeEditor. The lines are marked
 * where y-monaco takes a change into the editor (`useYMonacoBinding`), with
 * y-monaco stubbed as in yMonacoUndoPerEditor.test.tsx.
 *
 * A canvas no doc binds (a hosted guest's example) has no awareness: there a
 * run's `change` events say what the agent wrote, as its state in the room
 * said it (`writing`), and reach the node through the same bridge every run's
 * stream calls (`bridgeLandedChangeEvent`).
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as Y from "yjs";
import * as encoding from "lib0/encoding";
import * as awarenessProtocol from "y-protocols/awareness";

// vega ships ESM Jest's default transform skips; nothing here draws a chart.
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

const mockIo = jest.fn();
jest.mock("socket.io-client", () => ({
  io: (...args: unknown[]) => mockIo(...args),
}));
jest.mock("../../utils/backendUrl", () => ({
  backendUrl: () => "http://localhost:5002",
}));
jest.mock("../../utils/authApi", () => {
  const actual = jest.requireActual("../../utils/authApi");
  return {
    ...actual,
    getToken: () => "tok",
    authApi: { ...actual.authApi, getPublicConfig: () => Promise.resolve({ collab_namespace: "/collab" }) },
  };
});
jest.mock("../../registry/projectPackagesStore", () => ({
  ...jest.requireActual("../../registry/projectPackagesStore"),
  getCurrentProjectId: () => "project-1",
  subscribe: () => () => undefined,
}));

// The parts of React Flow that need its store; the rest stays real.
jest.mock("reactflow", () => ({
  ...jest.requireActual("reactflow"),
  Handle: () => null,
  useEdges: () => [],
  useUpdateNodeInternals: () => () => undefined,
}));
jest.mock("../../components/styles", () => ({
  NodeContainer: ({ children }: any) => <div>{children}</div>,
}));
jest.mock("../../components/DescriptionModal", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/OutputIcon", () => ({ OutputIcon: () => null }));
jest.mock("../../components/edges/InputIcon", () => ({ InputIcon: () => null }));
jest.mock("../../components/UnresolvedNode", () => ({ UnresolvedNode: () => null }));
jest.mock("../../components/agents/attach/NodeAgentBadges", () => ({ NodeAgentBadges: () => null }));
jest.mock("../../components/nodes/NodeOutcomeStrip", () => ({ NodeOutcomeStrip: () => null }));

// Three templates as the shipped manifest declares their tabs: Data Loading
// opens on its controls, a Python node on its code, and a Vega-Lite chart on
// its spec, with an Output tab.
jest.mock("../../registry/nodeRegistry", () => {
  const adapter = (outputId?: (nodeId: string) => string) => ({
    handles: [],
    editor: outputId ? { outputId } : {},
    container: { nodeWidth: 525, nodeHeight: 350 },
    useNodeBehavior: () => ({}),
  });
  const descriptors: Record<string, unknown> = {
    "curio.builtin/data-loading": {
      id: "curio.builtin/data-loading", hasCode: true, hasGrammar: false, hasWidgets: true,
      opensOnControls: true, adapter: adapter(),
    },
    "curio.builtin/computation-analysis": {
      id: "curio.builtin/computation-analysis", hasCode: true, hasGrammar: false, hasWidgets: true,
      adapter: adapter(),
    },
    "curio.builtin/vis-vega": {
      id: "curio.builtin/vis-vega", hasCode: false, hasGrammar: true, hasWidgets: true,
      adapter: adapter((nodeId) => `vega-${nodeId}`),
    },
  };
  return {
    ...jest.requireActual("../../registry/nodeRegistry"),
    getNodeDescriptor: (nodeType: string) => descriptors[nodeType],
    tryGetNodeDescriptor: (nodeType: string) => descriptors[nodeType],
    subscribeToRegistry: () => () => undefined,
  };
});
jest.mock("../../registry/registryReadiness", () => ({
  isRegistryReady: () => true,
  subscribeToRegistryReady: () => () => undefined,
}));
jest.mock("../../hook/useNodeState", () => ({
  useNodeState: (data: any) => ({
    output: { code: "", content: "" },
    setOutput: () => undefined,
    code: data.defaultCode ?? "",
    setCode: () => undefined,
    sendCode: undefined,
    setSendCodeCallback: () => undefined,
    templateData: {},
    user: null,
    promptDescription: () => undefined,
    closeDescription: () => undefined,
    showDescriptionModal: false,
  }),
}));
jest.mock("../../hook/useSelectionViews", () => ({
  ...jest.requireActual("../../hook/useSelectionViews"),
  useSelectionViews: () => [],
}));
const mockFlow = {
  dashboardOn: false,
  nodes: [] as unknown[],
  edges: [] as unknown[],
  signalNodeExecDone: () => undefined,
  isRunActive: false,
  serverRunActive: false,
  markDirty: () => undefined,
  markNodeStale: () => undefined,
  requestAutoRun: () => undefined,
  workflowNameRef: { current: "Agents in the room" },
  isDashboardSource: () => false,
  markNodeExecuted: () => undefined,
  markNodeErrored: () => undefined,
  playNodesUpTo: () => undefined,
};
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => mockFlow,
}));
jest.mock("@monaco-editor/react", () => ({
  __esModule: true,
  default: () => <textarea data-testid="monaco" readOnly />,
}));
const mockBindings: Array<{ ytext: unknown }> = [];
jest.mock("y-monaco", () => ({
  MonacoBinding: class {
    ytext: unknown;
    constructor(ytext: unknown) {
      this.ytext = ytext;
      mockBindings.push(this);
    }
    destroy() {}
  },
}));

import { CollaborationProvider } from "../../providers/CollaborationProvider";
import UniversalNode from "../../components/UniversalNode";
import { NotebookViewContext } from "../../providers/flow/notebookViewContext";
import { DataflowDocContext } from "../../providers/collab/docContext";
import { DataflowDocProvider } from "../../providers/collab/docProvider";
import { DOC_EVENT, dataflowToDoc, replaceText } from "../../providers/collab/docMapping";
import { useYMonacoBinding } from "../../components/editing/useYMonacoBinding";
import { TooltipLayer } from "../../components/tooltip/TooltipLayer";
import { setTooltipTimings } from "../../components/tooltip/tooltipStore";
import { bridgeLandedChangeEvent } from "../../services/agents/agentEvents";
import type { WidgetDef } from "../../utils/widgets/widgetModel";

type Handler = (payload?: any) => void;
interface FakeSocket {
  handlers: Record<string, Handler[]>;
  emits: Array<{ event: string; payload: any; ack?: (answer: any) => void }>;
}
let sockets: FakeSocket[] = [];

function fakeSocket(): FakeSocket & Record<string, unknown> {
  const fake: any = {
    handlers: {},
    emits: [],
    connected: true,
    on(event: string, handler: Handler) {
      fake.handlers[event] = fake.handlers[event] || [];
      fake.handlers[event].push(handler);
    },
    off(event: string, handler: Handler) {
      fake.handlers[event] = (fake.handlers[event] || []).filter((h: Handler) => h !== handler);
    },
    emit(event: string, payload: any, ack?: (answer: any) => void) {
      fake.emits.push({ event, payload, ack });
    },
    removeAllListeners: jest.fn(),
    disconnect: jest.fn(),
  };
  return fake;
}

function fire(socket: FakeSocket, event: string, payload?: any) {
  act(() => {
    for (const handler of socket.handlers[event] ?? []) handler(payload);
  });
}

// This tab is Ben's, an editor. Ana owns the dataflow and asked the agent.
const ANA = { user_id: 7, username: "ana", name: "Ana", participant_id: "p-ana", role: "owner" };
const BEN = { user_id: 9, username: "ben", name: "Ben", participant_id: "p-ben", role: "editor" };
const ANAS_LOCK = { user_id: 7, username: "ana", name: "Ana", participant_id: "p-ana", since: 1 };

/** The Node Builder as the server names it, in its lock and in its awareness
 *  state's `user`. */
const NODE_BUILDER = {
  user_id: null,
  username: null,
  name: "Node Builder",
  participant_id: "agent-7f3a",
  agent: {
    attachmentId: "att-node-builder",
    coord: "agent.curio.node-builder@1",
    category: "node",
    askedBy: { account: "ana", name: "Ana" },
  },
};

type Writes = "code" | "spec" | "widgets" | "settings";

/** The Node Builder's lock: the room's soft lock, named after it, with
 *  `agent` and what it `writes`. */
function agentLock(writes: Writes) {
  return { ...NODE_BUILDER, since: 1, writes };
}

/** The Node Builder's peer in the dataflow's doc, as the server runs it. */
let agentPeer: awarenessProtocol.Awareness | null = null;

/** The server sends the Node Builder's awareness state: it is writing
 *  *editing*, a node or the nodes one action writes at once, *writes* there,
 *  or nothing (null). */
function agentWrites(socket: FakeSocket, editing: string | string[] | null, writes: Writes | null = null) {
  agentPeer = agentPeer ?? new awarenessProtocol.Awareness(new Y.Doc());
  agentPeer.setLocalState({ user: NODE_BUILDER, skills: ["node-functions"], editing, writes });
  const encoder = encoding.createEncoder();
  encoding.writeVarUint(encoder, 1);
  encoding.writeVarUint8Array(encoder, awarenessProtocol.encodeAwarenessUpdate(agentPeer, [agentPeer.clientID]));
  fire(socket, DOC_EVENT, { projectId: "project-1", message: encoding.toUint8Array(encoder) });
}

const DATA: WidgetDef = { name: "data", type: "dataset", label: "Data", default: "" };
const ROWS: WidgetDef = {
  name: "rows", type: "choice", label: "Rows", default: "three",
  options: { choices: ["three", "five"], display: "radio" },
};
const LIMIT: WidgetDef = { name: "limit", type: "number", label: "Limit", default: 10 };

const LOADER = {
  nodeId: "loader", nodeType: "curio.builtin/data-loading",
  defaultCode: "data = curio_load_data([!! data !!])\nreturn data", widgets: [DATA],
};
const PYTHON = {
  nodeId: "rows", nodeType: "curio.builtin/computation-analysis",
  defaultCode: "n = [!! rows !!]\nreturn input_0[:n]", widgets: [ROWS, LIMIT],
};
const CHART = {
  nodeId: "chart", nodeType: "curio.builtin/vis-vega",
  defaultCode: '{"mark": "bar"}', widgets: [ROWS],
};

function Node({ data }: { data: Record<string, unknown> }) {
  return (
    <div data-testid={`node-${data.nodeId}`} style={{ position: "relative" }}>
      <UniversalNode data={data} isConnectable />
    </div>
  );
}

/** *children* in the room, joined as Ben's tab; *locks* are the room's at the
 *  join, and *notebook* draws them as notebook cells. */
async function inTheRoom(
  children: React.ReactNode,
  options: { locks?: Record<string, unknown>; notebook?: boolean } = {},
) {
  const tree = (inner: React.ReactNode) => (
    <CollaborationProvider>
      {options.notebook ? (
        <NotebookViewContext.Provider value={{ on: true, laneX: new Map(), cellWidth: 1065, reveal: () => true }}>
          {inner}
        </NotebookViewContext.Provider>
      ) : inner}
    </CollaborationProvider>
  );
  const view = render(tree(children));
  await waitFor(() => expect(sockets).toHaveLength(1));
  const socket = sockets[0];
  fire(socket, "connect");
  const join = socket.emits.find((e) => e.event === "join_session");
  expect(join).toBeDefined();
  act(() => join!.ack!({
    ok: true,
    participant_id: "p-ben",
    role: "editor",
    snapshot: { users: [ANA, BEN], locks: options.locks ?? {}, activity: [] },
  }));
  return { socket, again: (next: React.ReactNode) => view.rerender(tree(next)) };
}

const nodeBox = (nodeId: string) => screen.getByTestId(`node-${nodeId}`);
/** The tab the node shows, by its key, as its active pill says. */
const tabShown = (nodeId: string) =>
  nodeBox(nodeId).querySelector(".nav-link.active")?.getAttribute("data-rr-ui-event-key") ?? null;
/** The pane the node shows. */
function paneShown(nodeId: string): HTMLElement {
  const pane = nodeBox(nodeId).querySelector<HTMLElement>(".tab-pane.active");
  if (!pane) throw new Error(`${nodeId} shows no pane`);
  return pane;
}
/** A person's click on one of the node's tabs. */
function pick(nodeId: string, key: string) {
  const tab = nodeBox(nodeId).querySelector<HTMLElement>(`.nav-link[data-rr-ui-event-key="${key}"]`);
  if (!tab) throw new Error(`${nodeId} has no ${key} tab`);
  fireEvent.click(tab);
}
const lockChip = (nodeId: string) => nodeBox(nodeId).querySelector<HTMLElement>(".collab-lock-chip");
/** The widgets whose rows are marked as an agent's change. */
const markedWidgets = (nodeId: string) =>
  Array.from(nodeBox(nodeId).querySelectorAll<HTMLElement>("[data-widget-row][data-agent-change]"))
    .map((row) => row.getAttribute("data-widget-row"));

beforeEach(() => {
  sockets = [];
  mockBindings.length = 0;
  mockIo.mockReset();
  mockIo.mockImplementation(() => {
    const socket = fakeSocket();
    sockets.push(socket);
    return socket;
  });
});

afterEach(() => {
  jest.useRealTimers();
  agentPeer?.destroy();
  agentPeer = null;
});

describe("while an agent writes a node", () => {
  test("a node that opens on its controls shows its code while the agent writes it, then its Widgets tab again", async () => {
    const { socket } = await inTheRoom(<Node data={LOADER} />);
    expect(tabShown("loader")).toBe("widgets");
    expect(paneShown("loader").querySelector("[data-widget-controls]")).not.toBeNull();

    agentWrites(socket, "loader", "code");
    expect(tabShown("loader")).toBe("code");
    expect(within(paneShown("loader")).queryByTestId("monaco")).not.toBeNull();

    agentWrites(socket, null);
    expect(tabShown("loader")).toBe("widgets");
    expect(paneShown("loader").querySelector("[data-widget-controls]")).not.toBeNull();
  });

  test("the view follows the agent's awareness when it writes under its asker's lock, with no lock of its own", async () => {
    // Ana has the node open, so the node keeps her lock while her agent writes it.
    const { socket } = await inTheRoom(<Node data={LOADER} />, { locks: { loader: ANAS_LOCK } });
    expect(tabShown("loader")).toBe("widgets");

    agentWrites(socket, "loader", "code");
    expect(tabShown("loader")).toBe("code");
    // The chip is still the lock's: Ana's.
    expect(lockChip("loader")?.getAttribute("data-tooltip")).toBe("Editing: Ana");

    agentWrites(socket, null);
    expect(tabShown("loader")).toBe("widgets");
  });

  test("an action that writes two nodes at once turns both, and both go back after", async () => {
    const SECOND_LOADER = { ...LOADER, nodeId: "loader-2" };
    const { socket } = await inTheRoom(<><Node data={LOADER} /><Node data={SECOND_LOADER} /></>);
    expect([tabShown("loader"), tabShown("loader-2")]).toEqual(["widgets", "widgets"]);

    // A batch Solve's wave names every node it writes.
    agentWrites(socket, ["loader", "loader-2"], "code");
    expect([tabShown("loader"), tabShown("loader-2")]).toEqual(["code", "code"]);

    agentWrites(socket, null);
    expect([tabShown("loader"), tabShown("loader-2")]).toEqual(["widgets", "widgets"]);
  });

  test("a tab a person picked before the agent wrote is the one the node goes back to", async () => {
    const { socket } = await inTheRoom(<><Node data={LOADER} /><Node data={PYTHON} /></>);
    // Ben picked the loader's code, and the Python node's Widgets tab.
    pick("loader", "code");
    pick("rows", "widgets");

    agentWrites(socket, "loader", "code");
    expect(tabShown("loader")).toBe("code");
    agentWrites(socket, "rows", "code");
    expect(tabShown("rows")).toBe("code");
    agentWrites(socket, null);

    // Each is back on Ben's pick, not on the tab it opens on.
    expect(tabShown("loader")).toBe("code");
    expect(tabShown("rows")).toBe("widgets");
  });

  test("a tab a person picks while the agent writes the node shows at once, and stays", async () => {
    const { socket } = await inTheRoom(<Node data={CHART} />);
    pick("chart", "output");

    agentWrites(socket, "chart", "spec");
    expect(tabShown("chart")).toBe("grammar");
    expect(within(paneShown("chart")).queryByTestId("monaco")).not.toBeNull();

    pick("chart", "widgets");
    expect(tabShown("chart")).toBe("widgets");

    agentWrites(socket, null);
    // Ben's pick, not the Output tab the node had before the agent wrote.
    expect(tabShown("chart")).toBe("widgets");
  });

  test("a notebook cell turns to what the agent writes, and back, the same way", async () => {
    const { socket } = await inTheRoom(<Node data={CHART} />, { notebook: true });
    expect(tabShown("chart")).toBe("grammar");

    agentWrites(socket, "chart", "widgets");
    expect(tabShown("chart")).toBe("widgets");

    agentWrites(socket, null);
    expect(tabShown("chart")).toBe("grammar");
  });
});

describe("what the agent changed, marked as it lands", () => {
  test("an agent's widget values show on the Widgets tab, the changed widget marked in the agent's tint", async () => {
    const { socket, again } = await inTheRoom(<><Node data={PYTHON} /><Node data={LOADER} /></>);
    expect(tabShown("rows")).toBe("code");

    agentWrites(socket, "rows", "widgets");
    expect(tabShown("rows")).toBe("widgets");
    expect(markedWidgets("rows")).toEqual([]);

    // The value lands through the dataflow's doc: the node's data holds new widgets.
    const rowsSet = { ...PYTHON, widgets: [{ ...ROWS, value: "five" }, LIMIT] };
    again(<><Node data={rowsSet} /><Node data={LOADER} /></>);
    expect(markedWidgets("rows")).toEqual(["rows"]);
    const row = nodeBox("rows").querySelector<HTMLElement>('[data-widget-row="rows"]');
    expect(row?.className).toContain("curio-agent-change curio-agent-change--node");

    // A node that shows only its controls marks its control's row the same way.
    agentWrites(socket, "loader", "widgets");
    expect(tabShown("loader")).toBe("widgets");
    again(<><Node data={rowsSet} /><Node data={{ ...LOADER, widgets: [{ ...DATA, value: "imported.trees" }] }} /></>);
    expect(markedWidgets("loader")).toEqual(["data"]);
    expect(paneShown("loader").querySelector('[data-widget-controls] [data-widget-row="data"][data-agent-change]'))
      .not.toBeNull();
  });

  test("the marks go after a moment", async () => {
    const { socket, again } = await inTheRoom(<Node data={PYTHON} />);
    agentWrites(socket, "rows", "widgets");
    jest.useFakeTimers();

    again(<Node data={{ ...PYTHON, widgets: [{ ...ROWS, value: "five" }, LIMIT] }} />);
    expect(markedWidgets("rows")).toEqual(["rows"]);

    // A second and a half (AGENT_MARK_MS).
    act(() => {
      jest.advanceTimersByTime(1000);
    });
    expect(markedWidgets("rows")).toEqual(["rows"]);
    act(() => {
      jest.advanceTimersByTime(1000);
    });
    expect(markedWidgets("rows")).toEqual([]);
    jest.useRealTimers();
  });

  test("an agent's code lands with its lines marked for a moment, as decorations with a class and no hover that never reach the doc", async () => {
    const CODE = "n = 3\nrows = input_0[:n]\nreturn rows\n";
    const AGENTS = "n = 3\nrows = input_0.head(n)\nreturn rows\n";
    const BASELINE = { current: CODE };
    const MONACO = { KeyMod: { CtrlCmd: 2048, Shift: 1024 }, KeyCode: { KeyZ: 56, KeyY: 55 } };
    const decorations = { set: jest.fn(), clear: jest.fn() };
    const model = { getValue: () => CODE, onDidChangeContent: () => ({ dispose() {} }) };
    const editor = {
      getModel: () => model,
      addAction: () => ({ dispose() {} }),
      onDidFocusEditorText: () => ({ dispose() {} }),
      onDidBlurEditorText: () => ({ dispose() {} }),
      hasTextFocus: () => false,
      trigger: jest.fn(),
      createDecorationsCollection: jest.fn(() => decorations),
    };
    const Bound = () => {
      useYMonacoBinding(editor, MONACO, "rows", { canWrite: true, baselineRef: BASELINE });
      return null;
    };
    const provider = new DataflowDocProvider("project-1", { canWrite: true });
    dataflowToDoc({
      name: "",
      nodes: [{ id: "rows", type: "curio.builtin/computation-analysis", x: 0, y: 0, content: CODE }],
      edges: [],
    }, provider.doc, "doc-1");
    provider.synced = true;
    const text = () => (provider.doc.getMap("nodes").get("rows") as Y.Map<unknown>).get("content") as Y.Text;
    /** The server writes *code* into the node, as it writes an agent's change. */
    const serverWrites = (code: string) => {
      const server = new Y.Doc();
      Y.applyUpdate(server, Y.encodeStateAsUpdate(provider.doc));
      const updates: Uint8Array[] = [];
      server.on("update", (update: Uint8Array) => updates.push(update));
      const content = (server.getMap("nodes").get("rows") as Y.Map<unknown>).get("content") as Y.Text;
      server.transact(() => replaceText(content, code));
      for (const update of updates) Y.applyUpdate(provider.doc, update, provider);
    };

    const { socket } = await inTheRoom(
      <DataflowDocContext.Provider value={{ provider, synced: true }}>
        <Bound />
      </DataflowDocContext.Provider>,
    );
    await waitFor(() => expect(mockBindings).toHaveLength(1));
    agentWrites(socket, "rows", "code");
    jest.useFakeTimers();

    act(() => serverWrites(AGENTS));
    // The line it rewrote, in the agent's tint, and nothing a hover shows.
    expect(decorations.set).toHaveBeenCalledTimes(1);
    expect(decorations.set).toHaveBeenLastCalledWith([{
      range: { startLineNumber: 2, startColumn: 1, endLineNumber: 2, endColumn: 1 },
      options: { isWholeLine: true, className: "curio-agent-change curio-agent-change--node" },
    }]);
    // The doc holds the agent's code and nothing of the marks.
    expect(text().toString()).toBe(AGENTS);

    // Ben's own typing meanwhile is not the agent's.
    act(() => provider.doc.transact(() => text().insert(0, "# Ben\n"), mockBindings[0]));
    expect(decorations.set).toHaveBeenCalledTimes(1);

    act(() => {
      jest.advanceTimersByTime(1000);
    });
    expect(decorations.clear).not.toHaveBeenCalled();
    act(() => {
      jest.advanceTimersByTime(1000);
    });
    expect(decorations.clear).toHaveBeenCalled();
    jest.useRealTimers();

    // Once the agent is done, someone else's change is marked no more.
    agentWrites(socket, null);
    act(() => serverWrites(`${text().toString()}# Ana\n`));
    expect(decorations.set).toHaveBeenCalledTimes(1);
    provider.destroy();
  });
});

describe("what the agent changed, marked until it lets go of the node", () => {
  test("a widget it set is marked no more once the agent lets go, before the moment ends", async () => {
    const { socket, again } = await inTheRoom(<Node data={PYTHON} />);
    agentWrites(socket, "rows", "widgets");
    again(<Node data={{ ...PYTHON, widgets: [{ ...ROWS, value: "five" }, LIMIT] }} />);
    expect(markedWidgets("rows")).toEqual(["rows"]);

    // The agent's second after its write is over: what shows after its reply
    // is the node as it is.
    agentWrites(socket, null);
    expect(markedWidgets("rows")).toEqual([]);
  });

  test("lines it wrote are marked no more once the agent lets go, before the moment ends", async () => {
    const CODE = "n = 3\nrows = input_0[:n]\nreturn rows\n";
    const AGENTS = "n = 3\nrows = input_0.head(n)\nreturn rows\n";
    const MONACO = { KeyMod: { CtrlCmd: 2048, Shift: 1024 }, KeyCode: { KeyZ: 56, KeyY: 55 } };
    const decorations = { set: jest.fn(), clear: jest.fn() };
    const model = { getValue: () => CODE, onDidChangeContent: () => ({ dispose() {} }) };
    const editor = {
      getModel: () => model,
      addAction: () => ({ dispose() {} }),
      onDidFocusEditorText: () => ({ dispose() {} }),
      onDidBlurEditorText: () => ({ dispose() {} }),
      hasTextFocus: () => false,
      trigger: jest.fn(),
      createDecorationsCollection: jest.fn(() => decorations),
    };
    const Bound = () => {
      useYMonacoBinding(editor, MONACO, "rows", { canWrite: true, baselineRef: { current: CODE } });
      return null;
    };
    const provider = new DataflowDocProvider("project-1", { canWrite: true });
    dataflowToDoc({
      name: "",
      nodes: [{ id: "rows", type: "curio.builtin/computation-analysis", x: 0, y: 0, content: CODE }],
      edges: [],
    }, provider.doc, "doc-1");
    provider.synced = true;
    /** The server writes *code* into the node, as it writes an agent's change. */
    const serverWrites = (code: string) => {
      const server = new Y.Doc();
      Y.applyUpdate(server, Y.encodeStateAsUpdate(provider.doc));
      const updates: Uint8Array[] = [];
      server.on("update", (update: Uint8Array) => updates.push(update));
      const content = (server.getMap("nodes").get("rows") as Y.Map<unknown>).get("content") as Y.Text;
      server.transact(() => replaceText(content, code));
      for (const update of updates) Y.applyUpdate(provider.doc, update, provider);
    };

    const { socket } = await inTheRoom(
      <DataflowDocContext.Provider value={{ provider, synced: true }}>
        <Bound />
      </DataflowDocContext.Provider>,
    );
    await waitFor(() => expect(mockBindings).toHaveLength(1));
    agentWrites(socket, "rows", "code");
    act(() => serverWrites(AGENTS));
    expect(decorations.set).toHaveBeenCalledTimes(1);
    expect(decorations.clear).not.toHaveBeenCalled();

    agentWrites(socket, null);
    expect(decorations.clear).toHaveBeenCalled();
    provider.destroy();
  });
});

describe("the node's lock chip", () => {
  test("an agent's shows its glyph in its tint, turns no tab for a setting, and says on hover who is editing and who asked", async () => {
    const restore = setTooltipTimings({ show: 0 });
    try {
      const { socket } = await inTheRoom(
        <>
          <TooltipLayer />
          <Node data={PYTHON} />
          <Node data={LOADER} />
        </>,
        { locks: { loader: ANAS_LOCK } },
      );
      fire(socket, "node_locked", { nodeId: "rows", lock: agentLock("settings") });
      agentWrites(socket, "rows", "settings");

      const chip = lockChip("rows");
      expect(chip).not.toBeNull();
      expect(chip!.getAttribute("data-tooltip")).toBe("Editing: Node Builder (asked by Ana)");
      // The Node Builder's category glyph, in the node category's tint, in
      // place of letters a username would give.
      expect(chip!.querySelector('svg[data-icon="circle-nodes"]')).not.toBeNull();
      expect(chip!.className).toContain("tint_node");
      expect(chip!.textContent).toBe("");
      // A setting turns no tab.
      expect(tabShown("rows")).toBe("code");

      await userEvent.hover(chip!);
      expect(await screen.findByRole("tooltip")).toHaveTextContent(/^Editing: Node Builder \(asked by Ana\)$/);

      // A person's lock keeps their chip: their letters, and their name.
      const anas = lockChip("loader");
      expect(anas?.textContent).toBe("AN");
      expect(anas?.getAttribute("data-tooltip")).toBe("Editing: Ana");
    } finally {
      restore();
    }
  });

  test("a person's goes when they leave the room, with the locks the server released", async () => {
    const carasLock = { user_id: 11, username: "cara", name: "Cara", participant_id: "p-cara", since: 2 };
    const { socket } = await inTheRoom(
      <><Node data={PYTHON} /><Node data={LOADER} /></>,
      { locks: { rows: ANAS_LOCK, loader: ANAS_LOCK } },
    );
    expect(lockChip("rows")?.getAttribute("data-tooltip")).toBe("Editing: Ana");

    // The server released both as Ana left, and Cara took the loader before
    // the leave reached this tab.
    fire(socket, "node_locked", { nodeId: "loader", lock: carasLock });
    fire(socket, "user_left", {
      user_id: 7, username: "ana", participant_id: "p-ana", released_locks: ["rows", "loader"], users: [BEN],
    });

    expect(lockChip("rows")).toBeNull();
    expect(lockChip("loader")?.getAttribute("data-tooltip")).toBe("Editing: Cara");
  });

  test("a tab of the shared guest account's names it by its number, as its chip in the dock does", async () => {
    // Every guest signs in to the one shared guest account, so the room
    // numbers its tabs, and a lock carries the number of the tab that holds it.
    const guestsLock = {
      user_id: 3, username: "guest_shared", name: "Shared Guest", participant_id: "p-guest-2", since: 1, guest_number: 2,
    };
    await inTheRoom(<><Node data={PYTHON} /><Node data={LOADER} /></>, { locks: { rows: guestsLock, loader: ANAS_LOCK } });

    expect([lockChip("rows")?.getAttribute("data-tooltip"), lockChip("rows")?.textContent]).toEqual([
      "Editing: Shared Guest 2", "S2",
    ]);
    // An account's lock keeps its letters and its name.
    expect([lockChip("loader")?.getAttribute("data-tooltip"), lockChip("loader")?.textContent]).toEqual([
      "Editing: Ana", "AN",
    ]);
  });
});

describe("on a canvas no doc binds, from a run's change events", () => {
  // A node of its own, so a hold this suite leaves behind turns no other test's.
  const GUESTS_LOADER = { ...LOADER, nodeId: "guests-loader" };

  /** A run's `change` event for the Node Builder's code in *nodeId*, as the
   *  server streams it: its canvas mutation, and what its state in the room
   *  said while it wrote. */
  function codeChange(nodeId: string) {
    return {
      changeId: "change-1",
      attachmentId: "att-node-builder",
      tool: "node.content.write",
      canvas: { kind: "node-content-applied", nodeId, content: "data = 1\nreturn data", agent: "Node Builder" },
      writing: { user: NODE_BUILDER, editing: nodeId, writes: "code" },
    };
  }

  test("a node that opens on its controls shows its code from the moment an agent's change lands, then its Widgets tab again", async () => {
    // A hosted guest's example: the canvas is in no room, so no doc binds it.
    render(<CollaborationProvider><Node data={GUESTS_LOADER} /></CollaborationProvider>);
    await waitFor(() => expect(sockets).toHaveLength(1));
    expect(tabShown("guests-loader")).toBe("widgets");
    jest.useFakeTimers();

    act(() => {
      bridgeLandedChangeEvent("change", codeChange("guests-loader"));
    });
    expect(tabShown("guests-loader")).toBe("code");
    expect(within(paneShown("guests-loader")).queryByTestId("monaco")).not.toBeNull();

    // The second the server keeps a node after its write, as the room's tabs see it.
    act(() => {
      jest.advanceTimersByTime(999);
    });
    expect(tabShown("guests-loader")).toBe("code");
    act(() => {
      jest.advanceTimersByTime(1);
    });
    expect(tabShown("guests-loader")).toBe("widgets");
    expect(paneShown("guests-loader").querySelector("[data-widget-controls]")).not.toBeNull();
  });

  test("a canvas the doc binds takes what agents write from the doc's awareness alone", async () => {
    await inTheRoom(<Node data={GUESTS_LOADER} />);
    expect(tabShown("guests-loader")).toBe("widgets");

    // The change event comes after the agent let go of the node: the
    // awareness said what it wrote while it wrote it.
    act(() => {
      bridgeLandedChangeEvent("change", codeChange("guests-loader"));
    });
    expect(tabShown("guests-loader")).toBe("widgets");
  });
});
