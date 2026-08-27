import { renderHook, act } from "@testing-library/react";

// ── Mock the hook's heavy collaborators (installSync harness) ─────────────────
const mockGetNodes = jest.fn(() => [] as Array<{ id: string }>);
const mockGetEdges = jest.fn(() => [] as Array<{ id: string; source: string; target: string }>);
jest.mock("reactflow", () => ({
  useReactFlow: () => ({ getNodes: mockGetNodes, getEdges: mockGetEdges }),
  useNodesInitialized: () => false,
}));
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ getAllNodeProvenance: () => ({}) }),
}));
const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ user: null, enableUserAuth: false }),
}));
jest.mock("../../api/projectsApi", () => ({
  projectsApi: { create: jest.fn(), update: jest.fn() },
}));
jest.mock("../../TrillGenerator", () => ({
  TrillGenerator: {
    generateTrill: jest.fn(() => ({ dataflow: { datasets: [] } })),
    getSerializableDataflowProvenance: jest.fn(() => ({})),
    reset: jest.fn(),
  },
}));
jest.mock("../../utils/saveOutputDataset", () => ({
  buildSaveableLiveOutputs: jest.fn(() => []),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectPackagesList: jest.fn(() => []),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  subscribe: jest.fn(() => jest.fn()),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";

const makeDeps = () =>
  ({
    nodes: [],
    edges: [],
    setNodes: jest.fn(),
    setEdges: jest.fn(),
    setOutputs: jest.fn(),
    outputsRef: { current: [] },
    setInteractions: jest.fn(),
    setDashboardPins: jest.fn(),
    setPositionsInDashboard: jest.fn(),
    setPositionsInWorkflow: jest.fn(),
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
  }) as any;

const LIVE_NODES = [{ id: "old-loader" }, { id: "cleaner" }, { id: "survivor" }];
const LIVE_EDGES = [
  { id: "edge-1", source: "old-loader", target: "cleaner" },
  { id: "edge-2", source: "cleaner", target: "survivor" },
];

beforeEach(() => {
  jest.clearAllMocks();
  mockGetNodes.mockReturnValue(LIVE_NODES);
  mockGetEdges.mockReturnValue(LIVE_EDGES);
});

describe("applyReviewedRemovals (dev/62 — reviewed plan removals bypass the manual guard)", () => {
  it("removes connected victims AND their edges in one call, with NO warning toast", () => {
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));

    act(() => {
      result.current.applyReviewedRemovals(
        ["old-loader", "cleaner"],
        ["edge-1", "edge-2"],
      );
    });

    // The user's exact failure: applyRemoveChanges refused connected nodes
    // with a toast per victim. The reviewed path never warns.
    expect(mockShowToast).not.toHaveBeenCalled();
    // Manual-parity bookkeeping for the edges (collab, provenance, input
    // reset) and the state filter.
    expect(deps.onEdgesDelete).toHaveBeenCalledWith(LIVE_EDGES);
    const edgeFilter = deps.setEdges.mock.calls[0][0];
    expect(edgeFilter(LIVE_EDGES)).toEqual([]);
    // The victims leave through the canvas change machinery.
    const changes = [
      { id: "old-loader", type: "remove" },
      { id: "cleaner", type: "remove" },
    ];
    expect(deps.onNodesDelete).toHaveBeenCalledWith(changes);
    expect(deps.onNodesChange).toHaveBeenCalledWith(changes);
  });

  it("already-absent nodes and edges are a no-op", () => {
    mockGetNodes.mockReturnValue([{ id: "survivor" }]);
    mockGetEdges.mockReturnValue([]);
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));

    act(() => {
      result.current.applyReviewedRemovals(["old-loader"], ["edge-1"]);
    });

    expect(deps.onEdgesDelete).not.toHaveBeenCalled();
    expect(deps.setEdges).not.toHaveBeenCalled();
    expect(deps.onNodesDelete).not.toHaveBeenCalled();
    expect(deps.onNodesChange).not.toHaveBeenCalled();
  });

  it("unlisted elements survive the state filters", () => {
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));

    act(() => {
      result.current.applyReviewedRemovals(["old-loader"], ["edge-1"]);
    });

    expect(deps.onEdgesDelete).toHaveBeenCalledWith([LIVE_EDGES[0]]);
    const edgeFilter = deps.setEdges.mock.calls[0][0];
    expect(edgeFilter(LIVE_EDGES)).toEqual([LIVE_EDGES[1]]);
    expect(deps.onNodesChange).toHaveBeenCalledWith([
      { id: "old-loader", type: "remove" },
    ]);
  });

  it("the manual guard is byte-identical: applyRemoveChanges still refuses connected nodes", () => {
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));

    act(() => {
      result.current.applyRemoveChanges([{ id: "old-loader", type: "remove" }]);
    });

    expect(mockShowToast).toHaveBeenCalledWith(
      "Connected boxes cannot be removed. Remove the edges first by selecting it and pressing Delete or Backspace.",
      "warning",
    );
    expect(deps.onNodesChange).toHaveBeenCalledWith([]);
  });
});
