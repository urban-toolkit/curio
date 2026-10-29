/**
 * What a load does differently when the tree is a dashboard.
 *
 * The dashboard's layout is applied at LOAD time, inside `loadParsedTrill`,
 * rather than by the page afterwards. Two reasons, and both are invisible from
 * the page: the loader is fire-and-forget so a page has no "it finished" signal
 * to transform against, and a transform re-applied on every render would fight
 * React Flow over `position` on each frame of a tile drag.
 *
 * The other half is what must NOT happen there: the canvas fit (it cannot
 * complete when unpinned nodes are never measured) and any save on its own (a
 * dashboard's only write is an explicit Save layout, so a page left open must
 * not rewrite the owner's dataflow). Save layout writes where the tiles sit
 * and how large they are, and nothing else.
 */
import { renderHook, act } from "@testing-library/react";

const mockFitViewWithMenuOffset = jest.fn((..._args: any[]) => true);
jest.mock("../../utils/fitViewWithMenuOffset", () => ({
  fitViewWithMenuOffset: (...args: any[]) => mockFitViewWithMenuOffset(...args),
}));
// One measured node, so the fit would succeed if it were ever scheduled.
const MEASURED = [{ id: "a", width: 100, height: 50, position: { x: 0, y: 0 }, data: {} }];
let mockFlowNodes: any[] = MEASURED;
jest.mock("reactflow", () => ({
  useReactFlow: () => ({
    getNodes: () => mockFlowNodes,
    getEdges: () => [],
    fitView: jest.fn(),
  }),
  useNodesInitialized: () => true,
}));
// The package registry has loaded, so the fit has nothing to wait for
// (useWorkflowOperations.loadFit.test.ts covers the wait).
jest.mock("../../registry/registryReadiness", () => ({
  isRegistryReady: () => true,
  subscribeToRegistryReady: () => () => {},
}));
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ getAllNodeProvenance: () => ({}) }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ user: null, enableUserAuth: false }),
}));
jest.mock("../../api/projectsApi", () => ({
  projectsApi: { create: jest.fn(), update: jest.fn(), get: jest.fn(), saveLayout: jest.fn() },
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectPackagesList: jest.fn(() => []),
  // No routed dataflow and nothing loading: saves take their id from the
  // hook's own state, as they do once a load has landed.
  getCurrentProjectId: jest.fn(() => undefined),
  whenProjectSettled: jest.fn(async () => {}),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  subscribe: jest.fn(() => jest.fn()),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";

// The canvas schedules its fit through requestAnimationFrame, which jsdom backs
// with a real timer. Run it inline so "did the fit get scheduled" is decided by
// the code rather than by how long the test waits.
(global as any).requestAnimationFrame = (cb: FrameRequestCallback) => {
  cb(0);
  return 0;
};
(global as any).cancelAnimationFrame = () => {};

const CHART = "curio.builtin/vis-vega@1";
const PRODUCER = "curio.builtin/computation-analysis@1";

const makeNode = (id: string, nodeType: string, data: Record<string, unknown> = {}) => ({
  id,
  type: "__curioUniversalNode",
  position: { x: 40, y: 60 },
  data: { nodeId: id, nodeType, input: "", ...data },
});

const makeEdge = (source: string, target: string) => ({
  id: `reactflow__edge-${source}out-${target}in`,
  source,
  target,
  sourceHandle: "out",
  targetHandle: "in",
});

const NODES = () => [
  makeNode("py", PRODUCER),
  makeNode("chart", CHART, { dashboardPinned: true }),
];
const EDGES = () => [makeEdge("py", "chart")];

function makeDeps(over: Record<string, unknown> = {}) {
  return {
    nodes: [],
    edges: [],
    setNodes: jest.fn((u: any) => (typeof u === "function" ? u([]) : u)),
    setEdges: jest.fn(),
    setOutputs: jest.fn(),
    outputsRef: { current: [] },
    setInteractions: jest.fn(),
    setDashboardPins: jest.fn(),
    setWorkflowName: jest.fn(),
    workflowNameRef: { current: "wf" },
    setWorkflowDescription: jest.fn(),
    workflowDescriptionRef: { current: "" },
    onEdgesDelete: jest.fn(),
    onNodesDelete: jest.fn(),
    onNodesChange: jest.fn(),
    onConnect: jest.fn(),
    addNode: jest.fn(),
    defaultSaveOutputDataset: false,
    ...over,
  } as any;
}

function render(over: Record<string, unknown> = {}) {
  const deps = makeDeps(over);
  const rendered = renderHook(() => useWorkflowOperations(deps));
  return { ...rendered, deps };
}

async function load(api: any, nodes: any[], edges: any[]) {
  await act(async () => {
    await api.loadParsedTrill("wf", "", nodes, edges, false, false, [], "", []);
    // The fit is scheduled from an effect keyed on state the load sets.
    await Promise.resolve();
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockFlowNodes = MEASURED;
});

describe("a dashboard load", () => {
  test("the nodes arrive laid out as tiles", async () => {
    const { result, deps } = render({ presentation: true });

    await load(result.current, NODES(), EDGES());

    const added = deps.addNode.mock.calls.map((call: any[]) => call[0]);
    const chart = added.find((n: any) => n.id === "chart");
    const producer = added.find((n: any) => n.id === "py");
    // The pinned node is a tile: visible, draggable by its title band.
    expect(chart.style).toBeUndefined();
    expect(chart.dragHandle).toBe(".curio-dashboard-tile-handle");
    // The producer is hidden but still added, so its behaviour hook can run.
    expect(producer.style.display).toBe("none");
    expect(added).toHaveLength(2);
    // And the canvas coordinates are preserved for whatever saves next.
    expect(chart.data.workflowPosition).toEqual({ x: 40, y: 60 });
  });

  test("the edges are replayed hidden", async () => {
    const { result, deps } = render({ presentation: true });

    await load(result.current, NODES(), EDGES());

    const replayed = deps.onConnect.mock.calls.map((call: any[]) => call[0]);
    expect(replayed).toHaveLength(1);
    expect(replayed[0].hidden).toBe(true);
  });

  test("the canvas fit is never scheduled", async () => {
    const { result } = render({ presentation: true });

    await load(result.current, NODES(), EDGES());

    // It could not succeed anyway: a hidden node is never measured, so the
    // helper would retry twenty times and then force a degenerate fit.
    expect(mockFitViewWithMenuOffset).not.toHaveBeenCalled();
  });

  test("pins still come off the spec", async () => {
    const { result, deps } = render({ presentation: true });

    await load(result.current, NODES(), EDGES());

    expect(deps.setDashboardPins).toHaveBeenCalledWith({ chart: true });
  });
});

describe("a canvas load is unchanged", () => {
  test("the nodes arrive as authored", async () => {
    const { result, deps } = render();

    await load(result.current, NODES(), EDGES());

    const added = deps.addNode.mock.calls.map((call: any[]) => call[0]);
    expect(added.every((n: any) => n.style === undefined)).toBe(true);
    expect(added.every((n: any) => n.dragHandle === undefined)).toBe(true);
    // Nothing stamps workflowPosition on the canvas; the dashboard owns that key.
    expect(added.every((n: any) => n.data.workflowPosition === undefined)).toBe(true);
  });

  test("the edges are visible and the fit runs", async () => {
    const { result, deps } = render();

    await load(result.current, NODES(), EDGES());

    expect(deps.onConnect.mock.calls[0][0].hidden).toBeUndefined();
    expect(mockFitViewWithMenuOffset).toHaveBeenCalled();
  });
});

describe("saving", () => {
  test("a dashboard never saves on its own", async () => {
    const { projectsApi } = require("../../api/projectsApi");
    const { result } = render({ presentation: true });
    jest.useFakeTimers();
    try {
      await act(async () => { result.current.markDirty(); });
      act(() => { jest.advanceTimersByTime(60_000); });
    } finally {
      jest.useRealTimers();
    }
    // Its unsaved layout stays the page's until Save layout.
    expect(result.current.projectDirty).toBe(true);
    expect(projectsApi.update).not.toHaveBeenCalled();
    expect(projectsApi.create).not.toHaveBeenCalled();
    expect(projectsApi.saveLayout).not.toHaveBeenCalled();
  });

  test("Save layout sends each pinned tile's place and size, and nothing else", async () => {
    // Not the dataflow, nor its outputs, nor a value a viewer tried on a
    // control (#1117): those are never the layout's.
    const { projectsApi } = require("../../api/projectsApi");
    projectsApi.get.mockResolvedValue({
      project: { id: "p1", name: "wf", updated_at: null },
      spec: { dataflow: { nodes: [], edges: [] } },
      outputs: [],
    });
    projectsApi.saveLayout.mockResolvedValue({ saved: true });
    mockFlowNodes = [
      makeNode("chart", CHART, {
        dashboardPinned: true, dashboardX: 400, dashboardY: 80, dashboardWidth: 640, dashboardHeight: 360,
        widgets: [{ name: "year", type: "select", value: "a value tried here" }],
      }),
      // Not a tile, though it holds a place: its place is not the page's.
      makeNode("py", PRODUCER, { dashboardX: 1, dashboardY: 2 }),
      // A tile with no saved place yet sends none.
      makeNode("fresh", CHART, { dashboardPinned: true }),
    ];
    const { result } = render({ presentation: true });
    await act(async () => { await result.current.loadProject("p1"); });
    act(() => { result.current.markDirty(); });

    await act(async () => { await result.current.saveDashboardLayout(); });

    expect(projectsApi.saveLayout).toHaveBeenCalledTimes(1);
    expect(projectsApi.saveLayout).toHaveBeenCalledWith("p1", {
      chart: { dashboardX: 400, dashboardY: 80, dashboardWidth: 640, dashboardHeight: 360 },
    });
    expect(projectsApi.update).not.toHaveBeenCalled();
    expect(projectsApi.create).not.toHaveBeenCalled();
    // The layout is kept: leaving the page asks nothing.
    expect(result.current.projectDirty).toBe(false);
  });
});
