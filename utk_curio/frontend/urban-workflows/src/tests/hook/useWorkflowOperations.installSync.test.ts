import { renderHook, act } from "@testing-library/react";

// ── Mock the hook's heavy collaborators ───────────────────────────────────────
// Keep datasetCatalogApi REAL so notifyDatasetCatalogRefresh exercises the
// production code path.
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
import { AGENT_DOCK_REFRESH_EVENT } from "../../utils/agentsPaletteEvents";

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

let warnSpy: jest.SpyInstance;

beforeEach(() => {
  jest.clearAllMocks();
  (TrillGenerator.generateTrill as jest.Mock).mockReturnValue({ dataflow: { datasets: [] } });
  warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => {
  warnSpy.mockRestore();
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

describe("saveCurrentProject", () => {
  it("re-hydrates the datasets mirror from the saved spec — the backend-owned section wins over a drifted mirror (dev/81)", async () => {
    (projectsApi.create as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [], packages: [] } },
    });
    // The backend carried forward an install this client's mirror never saw.
    (projectsApi.update as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [{ datasetId: "imported.x1" }], packages: [] } },
    });
    const dispatch = jest.spyOn(window, "dispatchEvent");
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    await act(async () => {
      await result.current.ensureProjectId();
    });
    await act(async () => {
      await result.current.saveCurrentProject();
    });

    expect(result.current.dataflowDatasets).toEqual([{ datasetId: "imported.x1" }]);
    // The catalog refresh fan-out fired so open palettes/drawers refetch.
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({ type: DATASET_CATALOG_REFRESH_EVENT }),
    );
    dispatch.mockRestore();
  });

  it("fires the agent-dock refresh after an update save so pruned attachment tiles disappear", async () => {
    // The backend prunes attachments for deleted nodes on save; the dock must
    // reconcile from the persisted spec without a reload.
    (projectsApi.create as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [], packages: [] } },
    });
    (projectsApi.update as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [], packages: [] } },
    });
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));

    // Create pins the project id so the next save takes the UPDATE branch.
    await act(async () => {
      await result.current.ensureProjectId();
    });

    const dispatch = jest.spyOn(window, "dispatchEvent");
    await act(async () => {
      await result.current.saveCurrentProject();
    });

    expect(projectsApi.update).toHaveBeenCalledTimes(1);
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({ type: AGENT_DOCK_REFRESH_EVENT }),
    );
    dispatch.mockRestore();
  });

  it("serializes concurrent saves on a new dataflow into one create + one update (no duplicate projects)", async () => {
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
      const a = result.current.persistDataflowForInstall();
      const b = result.current.persistDataflowForInstall();
      resolveCreate({ id: "proj-1", name: "wf", spec: { dataflow: { datasets: [], packages: [] } } });
      await Promise.all([a, b]);
    });

    expect(projectsApi.create).toHaveBeenCalledTimes(1);
    expect(projectsApi.update).toHaveBeenCalledTimes(1); // the chained second save
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
      await result.current.ensureProjectId();
    });
    await act(async () => {
      await result.current.persistDataflowForInstall();
    });
    expect(projectsApi.create).toHaveBeenCalledTimes(1);
    expect(projectsApi.update).toHaveBeenCalledTimes(1);
  });

  it("warns the user when the save reports datasets it couldn't install", async () => {
    // Vector 3 fix: a computed output the backend silently skipped (e.g. its
    // artifact was missing) now comes back in dataset_install_warnings, and we
    // surface it instead of letting the dataset vanish without a trace.
    (projectsApi.create as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [], packages: [] } },
      dataset_install_warnings: [
        { node_id: "n1", filename: "out.parquet", reason: "output artifact not found at save time" },
      ],
    });
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await act(async () => {
      await result.current.persistDataflowForInstall();
    });
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.stringContaining("couldn't be generated"),
      "warning",
    );
  });

  it("does not warn when there are no install failures", async () => {
    (projectsApi.create as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [], packages: [] } },
      dataset_install_warnings: [],
    });
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await act(async () => {
      await result.current.persistDataflowForInstall();
    });
    expect(mockShowToast).not.toHaveBeenCalled();
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

describe("persistDataflowForInstall - warning scoping (#180)", () => {
  const respondWith = (
    warnings: Array<{ node_id: string; filename: string; reason: string }>,
  ) =>
    (projectsApi.create as jest.Mock).mockResolvedValue({
      id: "proj-1",
      name: "wf",
      spec: { dataflow: { datasets: [], packages: [] } },
      dataset_install_warnings: warnings,
    });

  const STALE = {
    node_id: "n-untouched",
    filename: "stale.parquet",
    reason: "output artifact not found at save time",
  };
  const RAN = {
    node_id: "n-ran",
    filename: "out.parquet",
    reason: "output artifact not found at save time",
  };

  it("does not toast a warning for a node this install-sync did not cover", async () => {
    // The #180 nuisance: buildOutputRefs re-sends refs for EVERY toggle-enabled
    // node, so a save triggered by n-ran carries n-untouched's stale ref too.
    respondWith([STALE]);
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await act(async () => {
      await result.current.persistDataflowForInstall(["n-ran"]);
    });
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it("still logs the filtered-out warning so nothing is silently lost", async () => {
    respondWith([STALE]);
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await act(async () => {
      await result.current.persistDataflowForInstall(["n-ran"]);
    });
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("n-untouched"));
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("stale.parquet"));
  });

  it("still toasts a warning for a node that IS in the pending set", async () => {
    respondWith([RAN]);
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await act(async () => {
      await result.current.persistDataflowForInstall(["n-ran"]);
    });
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.stringContaining("couldn't be generated"),
      "warning",
    );
  });

  it("toasts only the pending subset when one save reports both", async () => {
    respondWith([STALE, RAN]);
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await act(async () => {
      await result.current.persistDataflowForInstall(["n-ran"]);
    });
    expect(mockShowToast).toHaveBeenCalledTimes(1);
    // Singular copy proves the filter ran BEFORE the count, not just before the
    // name list: the plural branch would read "2 datasets couldn't be generated".
    const [message] = (mockShowToast as jest.Mock).mock.calls[0];
    expect(message).toContain('Dataset for "n-ran"');
    expect(message).not.toContain("n-untouched");
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("n-untouched"));
  });

  it("surfaces every warning when no scope is passed (unscoped callers unchanged)", async () => {
    respondWith([STALE, RAN]);
    const { result } = renderHook(() => useWorkflowOperations(makeDeps()));
    await act(async () => {
      await result.current.persistDataflowForInstall();
    });
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.stringContaining("2 datasets couldn't be generated"),
      "warning",
    );
    expect(warnSpy).not.toHaveBeenCalled();
  });
});
