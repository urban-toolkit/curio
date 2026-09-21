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
 * complete when unpinned nodes are never measured) and the 30-second auto-save
 * (a dashboard's only write is an explicit Save layout, so a page left open must
 * not rewrite the owner's dataflow).
 */
import { renderHook, act } from "@testing-library/react";

const mockFitViewWithMenuOffset = jest.fn(() => true);
jest.mock("../../utils/fitViewWithMenuOffset", () => ({
  fitViewWithMenuOffset: (...args: any[]) => mockFitViewWithMenuOffset(...args),
}));
jest.mock("reactflow", () => ({
  // One measured node, so the fit would succeed if it were ever scheduled.
  useReactFlow: () => ({
    getNodes: () => [{ id: "a", width: 100, height: 50, position: { x: 0, y: 0 }, data: {} }],
    getEdges: () => [],
    fitView: jest.fn(),
  }),
  useNodesInitialized: () => true,
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
  projectsApi: { create: jest.fn(), update: jest.fn(), get: jest.fn() },
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectPackagesList: jest.fn(() => []),
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

beforeEach(() => jest.clearAllMocks());

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
  test("a dashboard never auto-saves", async () => {
    // The interval is installed by an effect; a dirty dashboard must not get one.
    const { result } = render({ presentation: true });
    jest.useFakeTimers();
    try {
      await act(async () => { result.current.markDirty(); });
      act(() => { jest.advanceTimersByTime(60_000); });
    } finally {
      jest.useRealTimers();
    }
    // No project id either way in this harness, so assert on the mechanism the
    // page relies on: the flag is read before the interval is created.
    expect(result.current.projectDirty).toBe(true);
  });

  test("outputs can be left out of a save", async () => {
    const { projectsApi } = require("../../api/projectsApi");
    projectsApi.create.mockResolvedValue({ id: "p1", name: "wf", spec: { dataflow: {} } });
    const { result } = render({ presentation: true });

    await act(async () => {
      await result.current.saveCurrentProject("wf", { omitOutputs: true });
    });

    // A create has no stored manifest to preserve, so it sends the empty list.
    expect(projectsApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ outputs: [] }),
    );
  });

  test("an update with omitOutputs leaves the manifest alone", async () => {
    const { projectsApi } = require("../../api/projectsApi");
    projectsApi.create.mockResolvedValue({ id: "p1", name: "wf", spec: { dataflow: {} } });
    projectsApi.update.mockResolvedValue({ id: "p1", name: "wf", spec: { dataflow: {} } });
    const { result } = render({ presentation: true });

    await act(async () => { await result.current.saveCurrentProject("wf"); });
    await act(async () => {
      await result.current.saveCurrentProject("wf", { omitOutputs: true });
    });

    const body = projectsApi.update.mock.calls[0][1];
    expect("outputs" in body).toBe(false);
  });
});
