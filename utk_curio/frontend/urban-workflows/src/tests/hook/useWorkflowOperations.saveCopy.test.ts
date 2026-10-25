/**
 * Save a copy names the dataflow it copies (`copy_of`), so the new dataflow
 * gets that dataflow's saved outputs from its owner's Data Catalog, whichever
 * account owns it, rather than from the store, which keeps them only so long
 * and lets no other account read them.
 */
import { renderHook, act } from "@testing-library/react";

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
  useUserContext: () => ({
    user: { id: 2, username: "ada", name: "Ada", email: null, profile_image: null, type: null, is_guest: false },
    enableUserAuth: true,
  }),
}));
jest.mock("../../api/projectsApi", () => ({
  projectsApi: { create: jest.fn(), update: jest.fn(), get: jest.fn() },
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
  ...jest.requireActual("../../registry/projectPackagesStore"),
  getCurrentProjectPackagesList: jest.fn(() => []),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  subscribe: jest.fn(() => jest.fn()),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";
import { projectsApi } from "../../api/projectsApi";
import { TrillGenerator } from "../../TrillGenerator";

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

const SOURCE = "3f2b8c1e-5d4a-4c3b-9a2e-1f0e9d8c7b6a";

beforeEach(() => {
  jest.clearAllMocks();
  (TrillGenerator.generateTrill as jest.Mock).mockReturnValue({ dataflow: { datasets: [] } });
  (projectsApi.create as jest.Mock).mockResolvedValue({
    id: "proj-copy",
    name: "wf (copy)",
    spec: { dataflow: { datasets: [], packages: [] } },
    spec_revision: 1,
  });
});

it("names the dataflow it copies", async () => {
  const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

  await act(async () => {
    await result.current.saveAsNewProject("wf (copy)", SOURCE);
  });

  expect(projectsApi.create).toHaveBeenCalledTimes(1);
  expect(projectsApi.create).toHaveBeenCalledWith(expect.objectContaining({ name: "wf (copy)", copy_of: SOURCE }));
  expect(result.current.projectId).toBe("proj-copy");
});

it("names none when it copies no dataflow", async () => {
  const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

  await act(async () => {
    await result.current.saveAsNewProject("wf (copy)");
  });

  expect(projectsApi.create).toHaveBeenCalledTimes(1);
  expect((projectsApi.create as jest.Mock).mock.calls[0][0]).not.toHaveProperty("copy_of");
});
