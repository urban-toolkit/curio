/**
 * dev/124 — the canvas declares what it has seen when it saves.
 *
 * The server refuses a save that would delete a node, an edge or a node's code
 * written since the client loaded — an agent apply, a Solve wave, an install —
 * but only when the client says which revision it is working from. These tests
 * are about that declaration: it is captured at the two points that sync, and
 * it is sent.
 */
import { renderHook, act } from "@testing-library/react";

jest.mock("reactflow", () => ({
  useReactFlow: () => ({ getNodes: () => [], getEdges: () => [] }),
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

const loadResponse = (specRevision: number) => ({
  project: {
    id: "proj-1",
    name: "wf",
    updated_at: "2026-09-10T00:00:00",
    spec_revision: specRevision,
  },
  spec: { dataflow: { nodes: [], edges: [], packages: [], datasets: [] } },
  outputs: [],
});

let warnSpy: jest.SpyInstance;

beforeEach(() => {
  jest.clearAllMocks();
  (TrillGenerator.generateTrill as jest.Mock).mockReturnValue({
    dataflow: { datasets: [] },
  });
  warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => warnSpy.mockRestore());

describe("the basis a save declares", () => {
  it("is the revision the project was loaded at", async () => {
    (projectsApi.get as jest.Mock).mockResolvedValue(loadResponse(7));
    (projectsApi.update as jest.Mock).mockResolvedValue({
      id: "proj-1", name: "wf", spec: { dataflow: {} }, spec_revision: 8,
    });
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    await act(async () => {
      await result.current.loadProject("proj-1");
    });
    await act(async () => {
      await result.current.saveCurrentProject();
    });

    expect(projectsApi.update).toHaveBeenCalledWith(
      "proj-1",
      expect.objectContaining({ baseRevision: 7 }),
    );
  });

  it("moves to what the save itself returned, so the next save is current", async () => {
    (projectsApi.get as jest.Mock).mockResolvedValue(loadResponse(7));
    (projectsApi.update as jest.Mock).mockResolvedValue({
      id: "proj-1", name: "wf", spec: { dataflow: {} }, spec_revision: 8,
    });
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    await act(async () => {
      await result.current.loadProject("proj-1");
    });
    await act(async () => {
      await result.current.saveCurrentProject();
      await result.current.saveCurrentProject();
    });

    expect((projectsApi.update as jest.Mock).mock.calls[1][1]).toEqual(
      expect.objectContaining({ baseRevision: 8 }),
    );
  });

  it("is established by the first save of a brand-new dataflow", async () => {
    (projectsApi.create as jest.Mock).mockResolvedValue({
      id: "proj-new", name: "wf",
      spec: { dataflow: { datasets: [], packages: [] } },
      spec_revision: 1,
    });
    (projectsApi.update as jest.Mock).mockResolvedValue({
      id: "proj-new", name: "wf", spec: { dataflow: {} }, spec_revision: 2,
    });
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    await act(async () => {
      await result.current.saveCurrentProject();
    });
    expect(projectsApi.create).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.saveCurrentProject();
    });
    expect(projectsApi.update).toHaveBeenCalledWith(
      "proj-new",
      expect.objectContaining({ baseRevision: 1 }),
    );
  });

  it("is omitted entirely when the canvas has never synced", async () => {
    /* No opinion is a real answer: the server then does not check, which is
       what keeps scripts and older clients working. */
    (projectsApi.create as jest.Mock).mockResolvedValue({
      id: "proj-new", name: "wf",
      spec: { dataflow: { datasets: [], packages: [] } },
    });
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    await act(async () => {
      await result.current.saveCurrentProject();
    });
    const body = (projectsApi.create as jest.Mock).mock.calls[0][0];
    expect(body).not.toHaveProperty("baseRevision");
  });

  it("surfaces the server's refusal to the person who saved", async () => {
    const refusal: any = new Error(
      "This dataflow changed on the server since you opened it — saving now " +
        "would delete 6 nodes that your canvas does not have. Reload the " +
        "project to see the current dataflow, then make your change again.",
    );
    refusal.status = 409;
    (projectsApi.get as jest.Mock).mockResolvedValue(loadResponse(3));
    (projectsApi.update as jest.Mock).mockRejectedValue(refusal);
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    await act(async () => {
      await result.current.loadProject("proj-1");
    });
    await act(async () => {
      await result.current.persistDataflowForInstall();
    });

    expect(mockShowToast).toHaveBeenCalledWith(
      expect.stringContaining("would delete 6 nodes"),
      "error",
    );
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.stringContaining("Reload the project"),
      "error",
    );
  });
});
