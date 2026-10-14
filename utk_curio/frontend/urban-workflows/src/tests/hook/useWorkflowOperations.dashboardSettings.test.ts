/**
 * The dashboard's own settings (`dataflow.dashboard`) in the flow state: a
 * load restores where the Run button stands, a move makes the dataflow dirty,
 * and a save writes it.
 */
import { renderHook, act } from "@testing-library/react";

let mockCanvasNodes: any[] = [];
jest.mock("reactflow", () => ({
  useReactFlow: () => ({ getNodes: () => mockCanvasNodes, getEdges: () => [] }),
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
jest.mock("../../utils/saveOutputDataset", () => ({
  buildSaveableLiveOutputs: jest.fn(() => []),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectPackagesList: jest.fn(() => []),
  getCurrentProjectId: jest.fn(() => undefined),
  whenProjectSettled: jest.fn(async () => {}),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  subscribe: jest.fn(() => jest.fn()),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";
import { TrillGenerator } from "../../TrillGenerator";
import { projectsApi } from "../../api/projectsApi";

const makeNode = (id: string) => ({
  id,
  type: "curioUniversalNode",
  position: { x: 0, y: 0 },
  data: { nodeId: id, nodeType: "curio.builtin/data-loading@1", input: "" },
});

const makeDeps = () =>
  ({
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
  }) as any;

const NODES = [makeNode("a")];
const PLACED = { runButton: { x: 640, y: -20 } };

beforeEach(() => {
  jest.clearAllMocks();
  TrillGenerator.reset();
  mockCanvasNodes = [];
  (projectsApi.create as jest.Mock).mockResolvedValue({
    id: "proj-1",
    name: "wf",
    spec: { dataflow: { datasets: [], packages: [] } },
  });
});

async function saved(result: any) {
  await act(async () => {
    await result.current.saveCurrentProject();
  });
  return (projectsApi.create as jest.Mock).mock.calls[0][0].spec.dataflow;
}

test("a load restores where the Run button stands, without dirtying the dataflow", async () => {
  const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
  await act(async () => {
    await result.current.loadParsedTrill("wf", "", NODES, [], false, false, [], "", [], {}, [], PLACED);
  });
  expect(result.current.dashboardSettings).toEqual(PLACED);
  expect(result.current.projectDirty).toBe(false);
});

test("a load without settings clears them, and an absent argument keeps them", async () => {
  const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
  await act(async () => {
    await result.current.loadParsedTrill("wf", "", NODES, [], false, false, [], "", [], {}, [], PLACED);
  });
  await act(async () => {
    await result.current.loadParsedTrill("wf", "", NODES, [], false, false, [], "", [], {}, []);
  });
  expect(result.current.dashboardSettings).toEqual(PLACED);
  await act(async () => {
    await result.current.loadParsedTrill("wf", "", NODES, [], false, false, [], "", [], {}, [], null);
  });
  expect(result.current.dashboardSettings).toEqual({});
});

test("moving or resizing the Run button dirties the dataflow, and a save writes its place and size", async () => {
  mockCanvasNodes = NODES;
  const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
  act(() => {
    result.current.setDashboardRunButton({ x: 10, y: 20, width: 80, height: 50 });
  });
  expect(result.current.projectDirty).toBe(true);
  expect((await saved(result)).dashboard).toEqual({ runButton: { x: 10, y: 20, width: 80, height: 50 } });
});

test("a dataflow whose Run button was never placed saves no settings", async () => {
  mockCanvasNodes = NODES;
  const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
  expect((await saved(result)).dashboard).toBeUndefined();
});
