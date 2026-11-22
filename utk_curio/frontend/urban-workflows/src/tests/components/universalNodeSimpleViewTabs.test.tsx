/**
 * Simple View on the canvas, as the shipped manifest declares it
 * (packages/curio.builtin@1) and the registry's own conversion makes it
 * (`registerPackageTemplates`), drawn by UniversalNode with its real editor
 * and behavior.
 *
 * - It opens on what it shows: its cards, or why it shows nothing yet.
 * - Its Widgets tab holds one field, Time column: the column its player's
 *   range names in the views linked to it, t_s until set. A value typed
 *   there is the node's, and the tab stays where it is.
 * - Its header has no Play, run status or Save output toggle. NodeContainer
 *   draws those three only for a node that hands it a send-code callback
 *   (`sendCodeToWidgets`), and Simple View hands it none.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { act, fireEvent, render } from "@testing-library/react";

// vega ships ESM Jest's default transform skips; nothing here draws a chart.
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

// The parts of React Flow that need its store; the rest stays real. The view
// is wired to a node above it.
jest.mock("reactflow", () => ({
  ...jest.requireActual("reactflow"),
  Handle: () => null,
  useEdges: () => [{ id: "up->view", source: "up", target: "view", sourceHandle: "out", targetHandle: "in" }],
  useUpdateNodeInternals: () => () => undefined,
}));
// Each set of props the node hands its container, its header's send-code
// callback among them.
const mockContainers: any[] = [];
jest.mock("../../components/styles", () => ({
  NodeContainer: (props: any) => {
    mockContainers.push(props);
    return <div data-testid="node-container">{props.children}</div>;
  },
}));
jest.mock("../../components/DescriptionModal", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/OutputIcon", () => ({ OutputIcon: () => null }));
jest.mock("../../components/edges/InputIcon", () => ({ InputIcon: () => null }));
jest.mock("../../components/UnresolvedNode", () => ({ UnresolvedNode: () => null }));
jest.mock("../../components/agents/attach/NodeAgentBadges", () => ({ NodeAgentBadges: () => null }));
jest.mock("../../components/nodes/NodeOutcomeStrip", () => ({ NodeOutcomeStrip: () => null }));
jest.mock("../../registry/registryReadiness", () => ({
  isRegistryReady: () => true,
  subscribeToRegistryReady: () => () => undefined,
}));
// The node's state, with the send-code callback its editor registers kept as
// the canvas keeps it: a callback registered here reaches the header.
jest.mock("../../hook/useNodeState", () => {
  const React = require("react");
  return {
    useNodeState: (data: any) => {
      const [output, setOutput] = React.useState(data.output ?? { code: "", content: "" });
      const [sendCode, setSendCode] = React.useState(undefined);
      return {
        output,
        setOutput,
        code: data.code ?? "",
        setCode: () => undefined,
        sendCode,
        setSendCodeCallback: (fn: any) => setSendCode(() => fn),
        templateData: {},
        user: null,
        promptDescription: () => undefined,
        closeDescription: () => undefined,
        showDescriptionModal: false,
      };
    },
  };
});
jest.mock("../../hook/useSelectionViews", () => ({
  ...jest.requireActual("../../hook/useSelectionViews"),
  useSelectionViews: () => [],
}));
// The flow around the view, set per test and read on every render.
let mockFlow: Record<string, unknown> = {};
jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => mockFlow }));
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: () => undefined }),
}));
jest.mock("../../providers/ToastProvider", () => ({ useToastContext: () => ({ showToast: () => undefined }) }));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({
    connected: false,
    users: [],
    lockedNodes: {},
    onRemote: () => () => undefined,
  }),
}));
jest.mock("../../services/api", () => ({ fetchData: jest.fn() }));
jest.mock("../../utils/backendUrl", () => ({ backendUrl: () => "http://backend.test" }));
jest.mock("../../utils/authApi", () => ({
  ...jest.requireActual("../../utils/authApi"),
  getToken: () => "tok-123",
  apiFetch: jest.fn(() => Promise.resolve({ url: "/api/media/link-1", expiresIn: 600 })),
}));
jest.mock("@monaco-editor/react", () => ({
  __esModule: true,
  default: () => <textarea data-testid="monaco" readOnly />,
}));

// The behavior and icon registries are filled before packagesClient pulls in
// the adapters, in the order packagesClient.test.ts uses.
import "../../registry/builtinBehaviors";
import "../../registry/iconRegistry";
import { registerPackageTemplates } from "../../registry/packagesClient";
import { clearPackageNodes } from "../../registry/nodeRegistry";
import UniversalNode from "../../components/UniversalNode";

/** The built-in templates as packages/curio.builtin@1/manifest.json declares them. */
const MANIFEST = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../../../../../../packages/curio.builtin@1/manifest.json"), "utf8"),
);
const SHIPPED = MANIFEST.templates.find((template: any) => template.id === "vis-simple");
const TYPE = "curio.builtin/vis-simple@1";

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
    id: TYPE,
    templateId: "vis-simple",
  }],
};

const VIEW = "view";

/** A video's row as a collection hands it over, column by column. */
const VIDEOS = {
  dataType: "dataframe",
  data: {
    thumbnail: { 0: "https://example.test/poster.png" },
    kind: { 0: "video" },
    dataset_id: { 0: "imported.xc1@1" },
    file_id: { 0: "walkmp4fffffffffff" },
    name: { 0: "walk.mp4" },
  },
};

function viewData(extra: Record<string, unknown> = {}) {
  return {
    nodeId: VIEW,
    nodeType: TYPE,
    input: "",
    outputCallback: () => undefined,
    interactionsCallback: () => undefined,
    ...extra,
  };
}

/** What the canvas holds of the node: updateDataNode gives it new data. */
let mockSetData: ((data: any) => void) | null = null;
function Canvas({ initial }: { initial: any }) {
  const [data, setData] = React.useState(initial);
  mockSetData = setData;
  return <UniversalNode data={data} isConnectable />;
}

/** Lets the promises and timers the node started run. */
async function settle() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

async function mount(data: any) {
  let utils: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<Canvas initial={data} />);
  });
  await settle();
  return utils!;
}

/** Whether *element* shows: in no tab pane, or in the active one. */
function shown(element: Element | null): boolean {
  if (element === null) return false;
  const pane = element.closest(".tab-pane");
  return pane === null || pane.classList.contains("active");
}

/** A tab of the node, by its event key, as the e2e helpers find it. */
function tabOf(container: HTMLElement, key: string): HTMLElement {
  const tab = container.querySelector<HTMLElement>(`.nav-link[data-rr-ui-event-key="${key}"]`);
  if (!tab) throw new Error(`the Simple View has no ${key} tab`);
  return tab;
}

/** The one pane Bootstrap marks active. */
function activePane(container: HTMLElement): HTMLElement {
  const pane = container.querySelector<HTMLElement>(".tab-pane.active");
  if (!pane) throw new Error("no active pane rendered");
  return pane;
}

const timeColumnField = (root: ParentNode) => root.querySelector<HTMLInputElement>('input[aria-label="Time column"]');

/** The node data the last write gave the canvas. */
const written = () => {
  const calls = (mockFlow.updateDataNode as jest.Mock).mock.calls;
  return calls.length ? calls[calls.length - 1][1] : undefined;
};

beforeAll(() => {
  (globalThis as any).ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  clearPackageNodes();
  registerPackageTemplates([LISTING]);
});

beforeEach(() => {
  mockContainers.length = 0;
  mockFlow = {
    nodes: [
      { id: "up", type: "__curioUniversalNode", data: { nodeId: "up", nodeType: "curio.builtin/python-computation" } },
      { id: VIEW, type: "__curioUniversalNode", data: { nodeId: VIEW, nodeType: TYPE } },
    ],
    edges: [{ id: "up->view", source: "up", target: VIEW, sourceHandle: "out", targetHandle: "in" }],
    scenarios: [],
    nodeExecStatus: {},
    dashboardOn: false,
    dashboardStopped: null,
    projectId: "p1",
    isRunActive: false,
    serverRunActive: false,
    workflowNameRef: { current: "wf" },
    updateDataNode: jest.fn((_nodeId: string, data: any) => mockSetData?.(data)),
    signalNodeExecDone: () => undefined,
    playNodesUpTo: () => undefined,
    markDirty: () => undefined,
    markNodeStale: () => undefined,
    markNodeErrored: () => undefined,
    markNodeExecuted: () => undefined,
    requestAutoRun: () => undefined,
    isDashboardSource: () => false,
    clearSelectionTagsOf: () => undefined,
  };
});

describe("a Simple View on the canvas", () => {
  test("opens on its cards", async () => {
    const { container } = await mount(viewData({ input: VIDEOS }));

    const cards = container.querySelector(`#imageBox_content_${VIEW}`);
    expect(cards).not.toBeNull();
    expect(shown(cards)).toBe(true);
  });

  test("opens on why it shows nothing, while nothing has reached it", async () => {
    const { container } = await mount(viewData());

    const empty = container.querySelector("[data-curio-node-empty]");
    expect(empty).not.toBeNull();
    expect(shown(empty)).toBe(true);
  });

  test("hands its header no send-code callback, so it draws no Play, run status or Save output toggle", async () => {
    await mount(viewData({ input: VIDEOS }));

    expect(mockContainers.length).toBeGreaterThan(0);
    expect(mockContainers[mockContainers.length - 1].sendCodeToWidgets).toBeUndefined();
  });

  test("holds one field on its Widgets tab, Time column, t_s until set", async () => {
    const { container } = await mount(viewData({ input: VIDEOS }));

    fireEvent.click(tabOf(container, "widgets"));

    const pane = activePane(container);
    const field = timeColumnField(pane);
    expect(field).not.toBeNull();
    expect(field!.value).toBe("t_s");
    expect(pane.querySelectorAll("input")).toHaveLength(1);
  });

  test("keeps a Time column typed there as the node's own, and stays on its Widgets tab", async () => {
    const { container } = await mount(viewData({ input: VIDEOS, widgets: SHIPPED.widgets }));

    fireEvent.click(tabOf(container, "widgets"));
    const field = timeColumnField(activePane(container))!;
    // Each its own step, as a person types and then leaves the field: the
    // field shows what was typed before it is left.
    fireEvent.change(field, { target: { value: "walked_s" } });
    expect(field.value).toBe("walked_s");
    fireEvent.blur(field);
    await settle();

    const widgets = written()?.widgets ?? [];
    expect(widgets.filter((widget: any) => widget.name === "time_column")).toEqual([
      { name: "time_column", type: "text", label: "Time column", default: "t_s", value: "walked_s" },
    ]);
    // The write gave the node new data, and its editor stayed on the field.
    const pane = activePane(container);
    expect(timeColumnField(pane)).not.toBeNull();
    expect(timeColumnField(pane)!.value).toBe("walked_s");
  });
});
