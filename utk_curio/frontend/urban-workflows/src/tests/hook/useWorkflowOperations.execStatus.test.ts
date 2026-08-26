import { renderHook, act } from "@testing-library/react";

// ── Mock the hook's heavy collaborators (same set as installSync.test) ────────
jest.mock("reactflow", () => ({
  useReactFlow: () => ({ getNodes: () => [], getEdges: () => [] }),
  useNodesInitialized: () => false,
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

// dev/70: CodeEditor calls markNodeStale on EVERY keystroke. The marks must be
// idempotent — returning the same state object when the node is already in the
// target status — or each keystroke changes the FlowContext value and re-renders
// every consumer on the canvas.
describe("nodeExecStatus marks", () => {
  it("markNodeStale keeps the same state object when the node is already stale", () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    act(() => result.current.markNodeStale("n1"));
    const afterFirst = result.current.nodeExecStatus;
    expect(afterFirst).toEqual({ n1: "stale" });

    act(() => result.current.markNodeStale("n1"));
    expect(result.current.nodeExecStatus).toBe(afterFirst);
  });

  it("markNodeExecuted keeps the same state object when already executed", () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    act(() => result.current.markNodeExecuted("n1"));
    const afterFirst = result.current.nodeExecStatus;
    expect(afterFirst).toEqual({ n1: "executed" });

    act(() => result.current.markNodeExecuted("n1"));
    expect(result.current.nodeExecStatus).toBe(afterFirst);
  });

  it("still transitions between stale and executed", () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    act(() => result.current.markNodeStale("n1"));
    act(() => result.current.markNodeExecuted("n1"));
    expect(result.current.nodeExecStatus).toEqual({ n1: "executed" });

    act(() => result.current.markNodeStale("n1"));
    expect(result.current.nodeExecStatus).toEqual({ n1: "stale" });
  });
});
