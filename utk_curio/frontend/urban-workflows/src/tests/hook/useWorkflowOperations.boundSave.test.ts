/**
 * What a save sends of the dataflow's history. A canvas bound to the
 * dataflow's doc sends its outputs and nothing of the history, which the
 * server keeps; a canvas bound to no doc carries the history it recorded, for
 * the server to import when the dataflow has none of its own yet.
 */
import { renderHook, act } from "@testing-library/react";

jest.mock("reactflow", () => ({
  useReactFlow: () => ({ getNodes: () => [], getEdges: () => [] }),
  useNodesInitialized: () => false,
}));
const mockEntries = { n1: [{ id: 1, parentId: null, code: "x = 1", inputs: [], outputs: [], startTime: "", endTime: "" }] };
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ getAllNodeProvenance: () => mockEntries }),
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
const mockVersions = { id: "wf", latest: "wf_1", graph: { nodes: [{ id: "wf_1" }], edges: [] }, versions: { wf_1: {} } };
jest.mock("../../TrillGenerator", () => ({
  TrillGenerator: {
    generateTrill: jest.fn(() => ({ dataflow: { datasets: [] } })),
    getSerializableDataflowProvenance: jest.fn(() => mockVersions),
    reset: jest.fn(),
  },
}));
jest.mock("../../utils/saveOutputDataset", () => ({
  buildSaveableLiveOutputs: jest.fn(() => []),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  ...jest.requireActual("../../registry/projectPackagesStore"),
  getCurrentProjectPackagesList: jest.fn(() => []),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  subscribe: jest.fn(() => jest.fn()),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";
import { projectsApi } from "../../api/projectsApi";
import { TrillGenerator } from "../../TrillGenerator";

const makeDeps = (bound: boolean) =>
  ({
    nodes: [],
    edges: [],
    setNodes: jest.fn(),
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
    docBridgeRef: { current: { bound: () => bound, whenKept: jest.fn().mockResolvedValue(true) } },
  }) as any;

const loaded = {
  project: { id: "proj-1", name: "wf", updated_at: "2026-10-28T00:00:00", spec_revision: 3 },
  spec: { dataflow: { nodes: [], edges: [], packages: [], datasets: [] } },
  outputs: [],
};
const answer = { id: "proj-1", name: "wf", spec: { dataflow: {} }, spec_revision: 4 };

beforeEach(() => {
  jest.clearAllMocks();
  (TrillGenerator.generateTrill as jest.Mock).mockReturnValue({ dataflow: { datasets: [] } });
  (projectsApi.get as jest.Mock).mockResolvedValue(loaded);
  (projectsApi.update as jest.Mock).mockResolvedValue(answer);
});

test("a bound canvas's save sends its outputs, after its changes are kept, and nothing of the history", async () => {
  const deps = makeDeps(true);
  const { result } = renderHook(() => useWorkflowOperations(deps));
  await act(async () => {
    await result.current.loadProject("proj-1");
  });
  await act(async () => {
    await result.current.saveCurrentProject();
  });
  expect(deps.docBridgeRef.current.whenKept).toHaveBeenCalled();
  const [id, body] = (projectsApi.update as jest.Mock).mock.calls[0];
  expect(id).toBe("proj-1");
  expect(body).toHaveProperty("outputs");
  expect(body).not.toHaveProperty("spec");
  expect(body).not.toHaveProperty("history");
  expect(JSON.stringify(body)).not.toMatch(/nodeProvenance|dataflowProvenance/);
});

test("a canvas bound to no doc carries the history it recorded in the spec it saves", async () => {
  const { result } = renderHook(() => useWorkflowOperations(makeDeps(false)));
  await act(async () => {
    await result.current.loadProject("proj-1");
  });
  await act(async () => {
    await result.current.saveCurrentProject();
  });
  const [, body] = (projectsApi.update as jest.Mock).mock.calls[0];
  expect(body.spec.nodeProvenance).toEqual(mockEntries);
  expect(body.spec.dataflowProvenance).toEqual(mockVersions);
});
