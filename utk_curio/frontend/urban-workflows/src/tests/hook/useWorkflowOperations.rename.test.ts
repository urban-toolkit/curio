import { renderHook, act } from "@testing-library/react";

// Same collaborator mocks as installSync.test.ts — this suite exercises the same
// save path, just the name that rides on it.
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

/**
 * `setWorkflowName` is threaded in from FlowProvider, so the fake has to write
 * `workflowNameRef` too — that ref is what the spec serializer reads, and the
 * whole bug is the two drifting apart.
 */
const makeDeps = () => {
  const workflowNameRef = { current: "Loaded name" };
  return {
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
    setWorkflowName: jest.fn((n: string) => {
      workflowNameRef.current = n;
    }),
    workflowNameRef,
    setWorkflowDescription: jest.fn(),
    workflowDescriptionRef: { current: "" },
    onEdgesDelete: jest.fn(),
    onNodesDelete: jest.fn(),
    onNodesChange: jest.fn(),
    onConnect: jest.fn(),
    addNode: jest.fn(),
    defaultSaveOutputDataset: false,
  } as any;
};

/** Put the hook in the state the bug needs: a project loaded from the server. */
async function loadedProject(result: any, name = "Loaded name") {
  (projectsApi.get as jest.Mock).mockResolvedValue({
    project: { id: "proj-1", name, updated_at: null },
    spec: { dataflow: { nodes: [], edges: [] } },
    outputs: [],
  });
  await act(async () => {
    await result.current.loadProject("proj-1");
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  (projectsApi.update as jest.Mock).mockResolvedValue({
    id: "proj-1",
    name: "Server name",
    spec: { dataflow: { datasets: [], packages: [] } },
  });
});

describe("renameDataflow", () => {
  it("makes the next save send the NEW name, not the load-time one", async () => {
    // #230 itself. `saveCurrentProject` reads `projectName`, which only
    // `loadProject` ever set, so a rename that touched `workflowName` alone was
    // overruled by the stale value and the Projects card never moved.
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await loadedProject(result);

    act(() => {
      result.current.renameDataflow("New name");
    });
    await act(async () => {
      await result.current.saveCurrentProject();
    });

    expect(projectsApi.update).toHaveBeenCalledWith(
      "proj-1",
      expect.objectContaining({ name: "New name" }),
    );
  });

  it("marks the dataflow dirty, so the save indicator and autosave notice", async () => {
    // Nothing said a rename diverged from disk. That went unseen only because
    // the phantom dirty flag of #229 was masking it; with that fixed, a rename
    // that did not mark dirty would read as already-saved.
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await loadedProject(result);
    expect(result.current.projectDirty).toBe(false);

    act(() => {
      result.current.renameDataflow("New name");
    });

    expect(result.current.projectDirty).toBe(true);
  });

  it("refuses a blank entry and changes nothing", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await loadedProject(result);

    let accepted: boolean | undefined;
    act(() => {
      accepted = result.current.renameDataflow("   ");
    });

    expect(accepted).toBe(false);
    expect(result.current.projectDirty).toBe(false);

    await act(async () => {
      await result.current.saveCurrentProject();
    });
    expect(projectsApi.update).toHaveBeenCalledWith(
      "proj-1",
      expect.objectContaining({ name: "Loaded name" }),
    );
  });

  it("trims the committed name", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await loadedProject(result);

    act(() => {
      result.current.renameDataflow("  Padded  ");
    });
    await act(async () => {
      await result.current.saveCurrentProject();
    });

    expect(projectsApi.update).toHaveBeenCalledWith(
      "proj-1",
      expect.objectContaining({ name: "Padded" }),
    );
  });
});

describe("saveCurrentProject", () => {
  it("re-pins the client's name to whatever the server stored", async () => {
    // The create branch always did this; the update branch could only drift.
    // Observable through the NEXT save, which must carry the server's name.
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await loadedProject(result);

    await act(async () => {
      await result.current.saveCurrentProject();
    });
    await act(async () => {
      await result.current.saveCurrentProject();
    });

    expect(projectsApi.update).toHaveBeenLastCalledWith(
      "proj-1",
      expect.objectContaining({ name: "Server name" }),
    );
  });
});
