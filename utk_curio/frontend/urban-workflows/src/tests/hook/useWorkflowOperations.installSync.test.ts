import { renderHook, act } from "@testing-library/react";

// ── Mock the hook's heavy collaborators ───────────────────────────────────────
// Keep datasetCatalogApi REAL so buildInstalledDatasetRef / upsertDataflowDatasetRef /
// notifyDatasetCatalogRefresh exercise the production code paths.
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
import { projectsApi } from "../../api/projectsApi";
import { TrillGenerator } from "../../TrillGenerator";
import { DATASET_CATALOG_REFRESH_EVENT } from "../../services/datasetCatalog/datasetCatalogApi";

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

beforeEach(() => {
  jest.clearAllMocks();
  (TrillGenerator.generateTrill as jest.Mock).mockReturnValue({ dataflow: { datasets: [] } });
});

describe("ensureProjectId", () => {
  it("creates+saves the project once for a brand-new dataflow and returns its id", async () => {
    (projectsApi.create as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [], packages: [] } },
    });
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    let id: string | null = null;
    await act(async () => {
      id = await result.current.ensureProjectId();
    });

    expect(id).toBe("proj-1");
    expect(projectsApi.create).toHaveBeenCalledTimes(1);

    // Project now exists: a second call short-circuits without another create.
    let id2: string | null = null;
    await act(async () => {
      id2 = await result.current.ensureProjectId();
    });
    expect(id2).toBe("proj-1");
    expect(projectsApi.create).toHaveBeenCalledTimes(1);
  });

  it("de-dupes concurrent callers so two rapid installs create only one project", async () => {
    let resolveCreate: (v: any) => void = () => {};
    (projectsApi.create as jest.Mock).mockImplementation(
      () =>
        new Promise((res) => {
          resolveCreate = res;
        }),
    );
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    let p1: Promise<string | null>, p2: Promise<string | null>;
    act(() => {
      p1 = result.current.ensureProjectId();
      p2 = result.current.ensureProjectId();
    });
    // Both observed the in-flight save; only one POST went out.
    expect(projectsApi.create).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveCreate({ id: "proj-1", name: "wf", spec: { dataflow: { packages: [] } } });
      await Promise.all([p1, p2]);
    });
    await expect(p1!).resolves.toBe("proj-1");
    await expect(p2!).resolves.toBe("proj-1");
    expect(projectsApi.create).toHaveBeenCalledTimes(1);
  });

  it("toasts and returns null when the save fails", async () => {
    (projectsApi.create as jest.Mock).mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    let id: string | null = "unset" as any;
    await act(async () => {
      id = await result.current.ensureProjectId();
    });
    expect(id).toBeNull();
    expect(mockShowToast).toHaveBeenCalledWith("nope", "error");
  });
});

describe("persistInstalledDataset", () => {
  it("creates the project for a new dataflow and serializes the dataset ref into the saved spec", async () => {
    (projectsApi.create as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [{ datasetId: "computed.n1@1" }], packages: [] } },
    });
    const dispatch = jest.spyOn(window, "dispatchEvent");
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    await act(async () => {
      await result.current.persistInstalledDataset({
        id: "computed.n1@1",
        dirName: "computed.n1@1",
        producerNodeId: "n1",
      });
    });

    expect(projectsApi.create).toHaveBeenCalledTimes(1);

    // Race-fix proof: saveCurrentProject reads dataflowDatasetsRef.current, which
    // persistInstalledDataset updates SYNCHRONOUSLY before awaiting the save — so
    // the ref reaches generateTrill (arg index 6) even though setState hasn't flushed.
    const calls = (TrillGenerator.generateTrill as jest.Mock).mock.calls;
    const datasetsArg = calls[calls.length - 1][6];
    expect(datasetsArg).toEqual(
      expect.arrayContaining([expect.objectContaining({ datasetId: "computed.n1@1" })]),
    );

    // The catalog refresh fan-out fired so open palettes/drawers refetch.
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({ type: DATASET_CATALOG_REFRESH_EVENT }),
    );
    dispatch.mockRestore();
  });

  it("updates (not re-creates) an already-saved project so the UI resyncs from the saved spec", async () => {
    // Regression: removing datasets then re-running the flow on an EXISTING project
    // must reach the same persisted+visible state as a manual save. persistInstalledDataset
    // now always saves — create the first time, UPDATE thereafter — so syncDatasetsFromSavedSpec
    // refreshes the catalog without the user clicking the disk icon.
    (projectsApi.create as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [{ datasetId: "computed.n1@1" }], packages: [] } },
    });
    (projectsApi.update as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [{ datasetId: "computed.n2@1" }], packages: [] } },
    });
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    // First install creates the project.
    await act(async () => {
      await result.current.persistInstalledDataset({ id: "computed.n1@1", dirName: "computed.n1@1" });
    });
    expect(projectsApi.create).toHaveBeenCalledTimes(1);

    // Second install (e.g. re-run after removal) on the now-saved project: no second
    // create, but a real UPDATE that round-trips the persisted spec.
    await act(async () => {
      await result.current.persistInstalledDataset({ id: "computed.n2@1", dirName: "computed.n2@1" });
    });
    expect(projectsApi.create).toHaveBeenCalledTimes(1);
    expect(projectsApi.update).toHaveBeenCalledTimes(1);
    expect((projectsApi.update as jest.Mock).mock.calls[0][0]).toBe("proj-1");
  });

  it("serializes concurrent installs on a new dataflow into one create + one update (no duplicate projects)", async () => {
    // Two producing nodes finishing back-to-back must not both POST a create.
    let resolveCreate: (v: any) => void = () => {};
    (projectsApi.create as jest.Mock).mockImplementation(
      () => new Promise((res) => { resolveCreate = res; }),
    );
    (projectsApi.update as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [], packages: [] } },
    });
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    await act(async () => {
      const a = result.current.persistInstalledDataset({ id: "computed.n1@1", dirName: "computed.n1@1" });
      const b = result.current.persistInstalledDataset({ id: "computed.n2@1", dirName: "computed.n2@1" });
      resolveCreate({ id: "proj-1", name: "wf", spec: { dataflow: { datasets: [], packages: [] } } });
      await Promise.all([a, b]);
    });

    expect(projectsApi.create).toHaveBeenCalledTimes(1);
    expect(projectsApi.update).toHaveBeenCalledTimes(1); // the chained second save
  });

  it("is a no-op for a missing or partial payload", async () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await act(async () => {
      await result.current.persistInstalledDataset(null);
      await result.current.persistInstalledDataset({ id: "x" } as any); // no dirName
    });
    expect(projectsApi.create).not.toHaveBeenCalled();
  });
});

describe("persistDataflowForInstall (no execution-time install payload)", () => {
  it("creates the project the first time so the save-time install surfaces", async () => {
    (projectsApi.create as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [], packages: [] } },
    });
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await act(async () => {
      await result.current.persistDataflowForInstall();
    });
    expect(projectsApi.create).toHaveBeenCalledTimes(1);
  });

  it("updates an already-saved project (same save the disk icon performs)", async () => {
    (projectsApi.create as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [], packages: [] } },
    });
    (projectsApi.update as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [{ datasetId: "computed.n1@1" }], packages: [] } },
    });
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    // Establish the project, then a second producing run with no install payload.
    await act(async () => {
      await result.current.persistInstalledDataset({ id: "computed.n0@1", dirName: "computed.n0@1" });
    });
    await act(async () => {
      await result.current.persistDataflowForInstall();
    });
    expect(projectsApi.create).toHaveBeenCalledTimes(1);
    expect(projectsApi.update).toHaveBeenCalledTimes(1);
  });
});

describe("pendingInstalls store", () => {
  it("begins and clears an install placeholder", () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    act(() => {
      result.current.beginPendingInstall({ key: "n1", producerNodeId: "n1", label: "Node 1" });
    });
    expect(result.current.pendingInstalls).toHaveLength(1);
    expect(result.current.pendingInstalls[0]).toMatchObject({ key: "n1", label: "Node 1" });
    act(() => {
      result.current.endPendingInstall("n1");
    });
    expect(result.current.pendingInstalls).toHaveLength(0);
  });

  it("is idempotent per key — a re-run replaces rather than duplicates", () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    act(() => {
      result.current.beginPendingInstall({ key: "n1", producerNodeId: "n1", label: "first" });
      result.current.beginPendingInstall({ key: "n1", producerNodeId: "n1", label: "second" });
    });
    expect(result.current.pendingInstalls).toHaveLength(1);
    expect(result.current.pendingInstalls[0].label).toBe("second");
  });

  it("tracks multiple concurrent installs independently", () => {
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    act(() => {
      result.current.beginPendingInstall({ key: "n1", producerNodeId: "n1", label: "A" });
      result.current.beginPendingInstall({ key: "n2", producerNodeId: "n2", label: "B" });
    });
    expect(result.current.pendingInstalls.map((p) => p.key).sort()).toEqual(["n1", "n2"]);
    act(() => result.current.endPendingInstall("n1"));
    expect(result.current.pendingInstalls.map((p) => p.key)).toEqual(["n2"]);
  });

  it("auto-clears a placeholder after the safety timeout (no permanent spinner)", () => {
    jest.useFakeTimers();
    try {
      const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
      act(() => {
        result.current.beginPendingInstall({ key: "n1", producerNodeId: "n1", label: "stuck" });
      });
      expect(result.current.pendingInstalls).toHaveLength(1);
      act(() => {
        jest.advanceTimersByTime(600_000);
      });
      expect(result.current.pendingInstalls).toHaveLength(0);
    } finally {
      jest.useRealTimers();
    }
  });
});
