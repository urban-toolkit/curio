/**
 * Two scenarios of one set dragged in one after the other (#662): the shared
 * outcome that lands with the second reads every input it has, with nothing
 * run. One input is the second scenario's own node, whose saved output the
 * second drop restores; the other is the first scenario's, a node of the
 * set's copy already on the canvas, whose saved output the first drop
 * restored, handed over along the outcome's new edge.
 *
 * The real FlowProvider, ProjectLoader, useCode and `useScenarioDrop` run, on
 * a dataflow opened at its address; the projects API and the Scenario
 * Catalog's routes are mocked, the routes answering as the server plans and
 * copies a drop. Each drop asks them with the scenarios the set's copy here
 * holds (`present`), and every id it picks is a new one, as uuid's are.
 */
import React from "react";
import { act, render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Position, ReactFlow, ReactFlowProvider } from "reactflow";
import { faCircle } from "@fortawesome/free-solid-svg-icons";

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
const mockGetProject = jest.fn();
const mockGetCopyPlan = jest.fn();
const mockCopyInto = jest.fn();

// A new id each time, as uuid gives them. The stub the suites share answers
// one id always: the second drop's copies would take the first one's id,
// which the canvas holds already, and none of them would be added.
jest.mock("uuid", () => {
  let calls = 0;
  return { v4: () => `00000000-0000-4000-8000-${String(++calls).padStart(12, "0")}` };
});

jest.mock("../../api/projectsApi", () => {
  const actual = jest.requireActual("../../api/projectsApi");
  return {
    ...actual,
    projectsApi: { ...actual.projectsApi, get: (...args: any[]) => mockGetProject(...args) },
  };
});

jest.mock("../../services/runs/runsApi", () => {
  const actual = jest.requireActual("../../services/runs/runsApi");
  return {
    ...actual,
    runsApi: { ...actual.runsApi, listForProject: () => Promise.resolve([]) },
  };
});

jest.mock("../../services/scenarioCatalog/scenarioCatalogApi", () => ({
  scenarioCatalogApi: {
    getCopyPlan: (...args: any[]) => mockGetCopyPlan(...args),
    copyInto: (...args: any[]) => mockCopyInto(...args),
  },
}));

jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: () => Promise.resolve(),
}));

jest.mock("../../providers/packages/useEnsureWorkflowDeps", () => ({
  useEnsureWorkflowDeps: () => () => {},
}));

jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({
    lockedNodes: {},
    lockNode: jest.fn(),
    unlockNode: jest.fn(),
    onRemote: jest.fn(),
  }),
}));

// The canvas here binds to no doc of the dataflow, so a drop takes the open
// dataflow's id as it is: it would otherwise wait out the bind each time.
jest.mock("../../providers/FlowProvider", () => {
  const actual = jest.requireActual("../../providers/FlowProvider");
  return {
    __esModule: true,
    ...actual,
    default: actual.default,
    useFlowContext: () => {
      const flow = actual.useFlowContext();
      return { ...flow, ensureProjectId: async () => flow.projectId };
    },
  };
});

jest.mock("../../components/apiSettings/useHostedGuest", () => ({
  ...jest.requireActual("../../components/apiSettings/useHostedGuest"),
  useHostedGuest: () => false,
}));

// The scenario commands open the Scenario Catalog drawer, whose provider this
// suite does not mount.
jest.mock("../../providers/scenarioCatalog/scenarioCatalogDrawerContext", () => ({
  useScenarioCatalogDrawer: () => ({
    openScenarioCatalogDrawer: jest.fn(),
    closeScenarioCatalogDrawer: jest.fn(),
    isScenarioCatalogDrawerOpen: false,
  }),
}));

jest.mock("../../hook/useVega", () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

import FlowProvider, { useFlowContext } from "../../providers/FlowProvider";
import { ProjectLoader } from "../../components/ProjectLoader";
import { useScenarioDrop } from "../../components/scenarios/useScenarioDrop";
import { NodeType, SupportedType } from "../../constants";
import { registerNode } from "../../registry/nodeRegistry";
import type { NodeDescriptor } from "../../registry/types";
import { inputSlotOf } from "../../utils/inputSlots";

const PROJECT_ID = "6a1d2c3b-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const SOURCE = "p-heights";
/** Python Computation: one input port that grows a circle per edge. */
const COMPUTATION = "curio.builtin/python-computation@1";

beforeAll(() => {
  const descriptor: NodeDescriptor = {
    id: COMPUTATION as NodeType,
    category: "computation",
    label: "Python Computation",
    icon: faCircle,
    inputPorts: [{ types: [SupportedType.DATAFRAME], cardinality: "[1,n]" }],
    outputPorts: [{ types: [SupportedType.DATAFRAME] }],
    editor: "code",
    inPalette: true,
    description: "",
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    adapter: {
      handles: [
        { id: "in", type: "target", position: Position.Left },
        { id: "out", type: "source", position: Position.Right },
      ],
      editor: { code: true, grammar: false, widgets: false },
      container: {},
      useNodeBehavior: () => ({}),
    },
  };
  registerNode(descriptor);
});

const python = (id: string, x: number, y: number, content = "return input_0") => ({
  id, type: COMPUTATION, x, y, content, in: "DEFAULT", out: "DEFAULT", goal: "", metadata: { keywords: [] },
});

const SET = { id: "hs", name: "Heights" };
const PROJECT = { id: SOURCE, name: "Heights" };

/** The server's plan of a drop of "Doubled" first: its own node, whose saved
 *  output it shows as its last node; "compare" waits for "Tripled". */
const FIRST = {
  scenario: { id: "s-double", name: "Doubled", color: "#e86a3c", description: "" },
  set: SET,
  project: PROJECT,
  nodes: ["double"],
  last: [{ nodeId: "double", sources: ["double"] }],
  context: [],
  shared: [],
  outcomes: ["compare"],
  dataflow: { nodes: [python("double", 0, 0, "return 2")], edges: [] },
  packages: [],
  toRun: [],
  problems: [],
};

/** Then "Tripled", with "Doubled" in the copy: "compare", which saves nothing
 *  here, lands, reading "double" on its first circle and "triple" on its
 *  second. */
const SECOND = {
  scenario: { id: "s-triple", name: "Tripled", color: "#2f8f4a", description: "" },
  set: SET,
  project: PROJECT,
  nodes: ["triple"],
  last: [{ nodeId: "triple", sources: ["triple"] }],
  context: [],
  shared: [{ nodeId: "compare", label: "Compare", scenarios: ["s-triple", "s-double"], sources: [] }],
  outcomes: ["compare"],
  dataflow: {
    nodes: [python("triple", 0, 400, "return 3"), python("compare", 700, 200, "return input_0")],
    edges: [
      { id: "e-double-compare", source: "double", target: "compare", sourceHandle: "out", targetHandle: "in_0" },
      { id: "e-triple-compare", source: "triple", target: "compare", sourceHandle: "out", targetHandle: "in_1" },
    ],
  },
  packages: [],
  toRun: [],
  problems: [],
};

/** Each saved output of the source as the nodes below its copy take it in. */
const frame = (source: string) => ({ path: `art_${source}`, dataType: "dataframe" });

const payload = (scenarioId: string, name: string) => ({
  projectId: SOURCE, scenarioId, name, setId: SET.id, setName: SET.name,
});

type FlowApi = ReturnType<typeof useFlowContext>;
let api: FlowApi;
let drop: ReturnType<typeof useScenarioDrop>;

const Bridge: React.FC = () => {
  api = useFlowContext();
  drop = useScenarioDrop();
  return (
    <div style={{ width: 800, height: 600 }}>
      <ReactFlow nodes={api.nodes} edges={api.edges} onNodesChange={api.onNodesChange} onEdgesChange={api.onEdgesChange} />
    </div>
  );
};

function open() {
  render(
    <MemoryRouter initialEntries={[`/dataflow/${PROJECT_ID}`]}>
      <Routes>
        <Route
          path="/dataflow/:id"
          element={
            <ReactFlowProvider>
              <FlowProvider>
                <ProjectLoader>
                  <Bridge />
                </ProjectLoader>
              </FlowProvider>
            </ReactFlowProvider>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

async function wait(ms: number) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

/** Drag the scenario in, as the canvas does on a drop, and let what it
 *  restores go down (a tick after the load). */
async function dragIn(scenarioId: string, name: string, at: { x: number; y: number }) {
  let added: unknown;
  await act(async () => {
    added = await drop(payload(scenarioId, name), at);
  });
  await wait(50);
  expect(added).not.toBeNull();
}

const copyOf = (original: string) =>
  api.nodes.find((n) => (n.data?.copiedFrom as string[] | undefined)?.at(-1) === original);

beforeEach(() => {
  mockGetProject.mockResolvedValue({
    project: { id: PROJECT_ID, name: "Elsewhere", spec_revision: 1, updated_at: "2026-11-04T09:00:00Z", categories: {} },
    spec: { dataflow: { name: "Elsewhere", task: "", description: "", packages: [], datasets: [], nodes: [], edges: [] } },
    outputs: [],
  });
  mockGetCopyPlan.mockImplementation(async (dragged: { scenarioId: string }) =>
    dragged.scenarioId === "s-double" ? FIRST : SECOND,
  );
  // The server copies each saved output asked for to the copy named, and
  // restores it under the copy's id.
  mockCopyInto.mockImplementation(async (_dragged: unknown, _target: string, _present: unknown, outputs: { source: string; node: string }[]) => ({
    packages: [],
    added: [],
    datasets: {},
    outputs: outputs.map((o) => ({ node_id: o.node, filename: `art_${o.source}`, data_type: "dataframe" })),
  }));
});

afterEach(() => {
  jest.clearAllMocks();
});

describe("a shared outcome landing with the second scenario of a set", () => {
  test("reads both scenarios' outputs, the earlier copy's handed over along its new edge, with nothing run", async () => {
    open();
    await waitFor(() => expect(api.projectId).toBe(PROJECT_ID), { timeout: 5000 });

    await dragIn("s-double", "Doubled", { x: 0, y: 0 });
    // Planned with nothing of the set here yet.
    expect(mockGetCopyPlan).toHaveBeenLastCalledWith(expect.objectContaining({ scenarioId: "s-double" }), PROJECT_ID, []);
    // The first scenario's own node shows its saved output; the outcome waits.
    expect(copyOf("double")).toBeDefined();
    expect(copyOf("compare")).toBeUndefined();

    await dragIn("s-triple", "Tripled", { x: 0, y: 400 });
    // Planned and copied with "Doubled" in the set's copy here: only its own
    // node's saved output is copied, and "compare" reads its inputs.
    expect(mockGetCopyPlan).toHaveBeenLastCalledWith(
      expect.objectContaining({ scenarioId: "s-triple" }), PROJECT_ID, ["s-double"],
    );
    expect(mockCopyInto).toHaveBeenLastCalledWith(
      expect.objectContaining({ scenarioId: "s-triple" }), PROJECT_ID, ["s-double"],
      [{ source: "triple", node: copyOf("triple")!.id }],
    );
    const compare = copyOf("compare");
    expect(compare).toBeDefined();
    const circles = api.edges
      .filter((e) => e.target === compare!.id)
      .map((e) => [e.source, inputSlotOf(e.targetHandle)] as [string, number])
      .sort((a, b) => a[1] - b[1]);
    expect(circles).toEqual([
      [copyOf("double")!.id, 0],
      [copyOf("triple")!.id, 1],
    ]);
    // Both circles hold their scenario's output, read as one value in circle
    // order: never the second scenario's alone.
    expect(compare!.data.inputSlots?.slice(0, 2)).toEqual([frame("double"), frame("triple")]);
    expect(compare!.data.input).toEqual({ dataType: "outputs", data: [frame("double"), frame("triple")] });
    expect(mockShowToast).not.toHaveBeenCalledWith(expect.anything(), "error");
  });
});
