import { renderHook, act } from "@testing-library/react";

// ── Mock the drawer hook's collaborators ──────────────────────────────────────
// Keep the datasetCatalog module REAL except for useDatasetCatalog, so the
// production notifyDatasetCatalogRefresh() + DATASET_CATALOG_REFRESH_EVENT are
// exercised end-to-end.
const mockImportDataset = jest.fn();
const mockCatalogReload = jest.fn(async () => {});
let mockCatalogItems: unknown[] = [];

jest.mock("../../services/datasetCatalog", () => {
  const actual = jest.requireActual("../../services/datasetCatalog");
  return {
    ...actual,
    useDatasetCatalog: () => ({
      items: mockCatalogItems,
      facets: { origin: {} },
      loading: false,
      refreshing: false,
      error: null,
      reload: mockCatalogReload,
      install: jest.fn(),
      uninstall: jest.fn(),
      importDataset: mockImportDataset,
    }),
  };
});

const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

const mockSetDataflowDatasets = jest.fn();
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: "flow-1",
    ensureProjectId: jest.fn(async () => "flow-1"),
    setDataflowDatasets: mockSetDataflowDatasets,
    outputs: [],
    nodes: [],
    defaultSaveOutputDataset: false,
    pendingInstalls: [],
    beginPendingInstall: jest.fn(),
    endPendingInstall: jest.fn(),
  }),
}));

jest.mock("../../utils/saveOutputDataset", () => ({
  buildSaveableLiveOutputs: jest.fn(() => []),
}));

import { useDatasetCatalogDrawer } from "../../components/datasets/catalog/useDatasetCatalogDrawer";
import {
  DATASET_CATALOG_REFRESH_EVENT,
  datasetCatalogApi,
} from "../../services/datasetCatalog";

describe("useDatasetCatalogDrawer.onPickImport", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockCatalogItems = [];
  });

  it("registers a standalone catalog item and fans out a refresh without attaching to the dataflow", async () => {
    mockImportDataset.mockResolvedValueOnce({
      id: "imported-1",
      title: "Imported.csv",
      origin: "imported",
      format: "csv",
    });
    const refreshSpy = jest.fn();
    window.addEventListener(DATASET_CATALOG_REFRESH_EVENT, refreshSpy);

    const file = new File(["a,b\n1,2"], "Imported.csv", { type: "text/csv" });
    const { result } = renderHook(() => useDatasetCatalogDrawer(true));

    await act(async () => {
      await result.current.onPickImport(file);
    });

    expect(mockImportDataset).toHaveBeenCalledWith(file);
    // Register-only: import must NOT attach the dataset to the open dataflow.
    expect(mockSetDataflowDatasets).not.toHaveBeenCalled();
    expect(refreshSpy).toHaveBeenCalledTimes(1);
    expect(mockShowToast).toHaveBeenCalledWith(
      "Registered Imported.csv in the Data Catalog.",
      "success",
    );

    window.removeEventListener(DATASET_CATALOG_REFRESH_EVENT, refreshSpy);
  });

  it("does not fan out a refresh when the import fails", async () => {
    mockImportDataset.mockRejectedValueOnce(new Error("boom"));
    const refreshSpy = jest.fn();
    window.addEventListener(DATASET_CATALOG_REFRESH_EVENT, refreshSpy);

    const file = new File(["x"], "bad.csv", { type: "text/csv" });
    const { result } = renderHook(() => useDatasetCatalogDrawer(true));

    await act(async () => {
      await result.current.onPickImport(file);
    });

    expect(refreshSpy).not.toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalledWith("boom", "error");

    window.removeEventListener(DATASET_CATALOG_REFRESH_EVENT, refreshSpy);
  });

  it.each(["chicago.pbf", "chicago.osm.pbf", "CHICAGO.OSM.PBF"])(
    "sends OSM PBF (%s) through the importer and reports the per-layer count",
    async (name) => {
      mockImportDataset.mockResolvedValueOnce({
        id: "imported-osm",
        title: `${name} (points)`,
        origin: "imported",
        format: "parquet",
        importedDatasetCount: 3,
      });
      const refreshSpy = jest.fn();
      window.addEventListener(DATASET_CATALOG_REFRESH_EVENT, refreshSpy);

      const file = new File(["<binary>"], name, { type: "application/octet-stream" });
      const { result } = renderHook(() => useDatasetCatalogDrawer(true));

      await act(async () => {
        await result.current.onPickImport(file);
      });

      // .pbf is a real importable format now (backend converts it to one
      // GeoParquet dataset per OSM layer).
      expect(mockImportDataset).toHaveBeenCalledWith(file);
      expect(refreshSpy).toHaveBeenCalledTimes(1);
      expect(mockShowToast).toHaveBeenCalledWith(
        `Registered 3 datasets from ${name} in the Data Catalog.`,
        "success",
      );

      window.removeEventListener(DATASET_CATALOG_REFRESH_EVENT, refreshSpy);
    },
  );
});

describe("useDatasetCatalogDrawer.onInstall (OSM group)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockCatalogReload.mockResolvedValue(undefined);
    mockCatalogItems = [];
  });

  it("installs each member layer (not the synthetic group id) and records real refs", async () => {
    const installSpy = jest
      .spyOn(datasetCatalogApi, "installToDataflow")
      .mockImplementation(async (_flow, datasetId) => ({
        id: datasetId,
        title: datasetId,
        origin: "imported",
        format: "parquet",
        dirName: `${datasetId}@1`,
        uri: `curio://datasets/${datasetId}@1`,
        consumerNodeIds: [],
        tags: [],
        updatedAt: "2026-01-01T00:00:00Z",
        installed: true,
      }) as never);

    const group = {
      id: "osm.xdeadbeef",
      title: "back_bay",
      origin: "imported" as const,
      format: "osm" as const,
      uri: "curio://osm/osm.xdeadbeef",
      consumerNodeIds: [],
      tags: ["osm", "bundle"],
      updatedAt: "2026-01-01T00:00:00Z",
      groupLayerIds: ["imported.xaaa", "imported.xbbb"],
    };

    const { result } = renderHook(() => useDatasetCatalogDrawer(true));
    await act(async () => {
      await result.current.onInstall(group as never);
    });

    // Added each real layer, never the synthetic group id.
    expect(installSpy).toHaveBeenCalledTimes(2);
    const installedIds = installSpy.mock.calls.map((c) => c[1]);
    expect(installedIds).toEqual(["imported.xaaa", "imported.xbbb"]);
    expect(installedIds).not.toContain("osm.xdeadbeef");
    // dataflowDatasets got the real per-layer refs (so a later save won't drop them).
    expect(mockSetDataflowDatasets).toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalledWith(
      "Added 2 layers from back_bay to this dataflow.",
      "success",
    );

    installSpy.mockRestore();
  });
});

describe("useDatasetCatalogDrawer refresh flow (#178)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockCatalogReload.mockResolvedValue(undefined);
    mockCatalogItems = [];
  });

  it("reloads the catalog exactly ONCE per action (self-listener answers the event)", async () => {
    const installSpy = jest
      .spyOn(datasetCatalogApi, "installToDataflow")
      .mockResolvedValue({
        id: "imported.xaaa",
        title: "One",
        origin: "imported",
        format: "csv",
        dirName: "imported.xaaa@1",
        uri: "curio://datasets/imported.xaaa@1",
        consumerNodeIds: [],
        tags: [],
        updatedAt: "2026-01-01T00:00:00Z",
        installed: true,
      } as never);
    const refreshSpy = jest.fn();
    window.addEventListener(DATASET_CATALOG_REFRESH_EVENT, refreshSpy);

    const dataset = {
      id: "imported.xaaa",
      title: "One",
      origin: "imported" as const,
      format: "csv" as const,
      consumerNodeIds: [],
      tags: [],
      updatedAt: "2026-01-01T00:00:00Z",
    };
    const { result } = renderHook(() => useDatasetCatalogDrawer(true));
    await act(async () => {
      await result.current.onInstall(dataset as never);
    });

    // One event dispatched; the hook's own listener performed the single
    // bust-cache reload — no direct reload from the handler.
    expect(refreshSpy).toHaveBeenCalledTimes(1);
    expect(mockCatalogReload).toHaveBeenCalledTimes(1);
    expect(mockCatalogReload).toHaveBeenCalledWith({ bustCache: true });

    window.removeEventListener(DATASET_CATALOG_REFRESH_EVENT, refreshSpy);
    installSpy.mockRestore();
  });
});

describe("useDatasetCatalogDrawer.onDelete confirm dialog (#177)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockCatalogReload.mockResolvedValue(undefined);
    mockCatalogItems = [];
  });

  const dataset = {
    id: "computed.flow-1.n1",
    title: "Knowledge Graph",
    origin: "computed" as const,
    format: "json" as const,
    dirName: "computed.flow-1.n1@1",
    producerNodeId: "n1",
    consumerNodeIds: [],
    consumerNodeCount: 5,
    tags: [],
    updatedAt: "2026-01-01T00:00:00Z",
  };

  it("warns with the affected-DATAFLOW count from /usage, not consumerNodeCount", async () => {
    const usageSpy = jest.spyOn(datasetCatalogApi, "datasetUsage").mockResolvedValue([
      { dataflowId: "a", dataflowName: "A", nodeCount: 0, nodes: [] },
      { dataflowId: "b", dataflowName: "B", nodeCount: 2, nodes: [] },
      { dataflowId: "c", dataflowName: "C", nodeCount: 0, nodes: [] },
    ] as never);
    const deleteSpy = jest
      .spyOn(datasetCatalogApi, "deleteDataset")
      .mockResolvedValue({ id: dataset.id, deleted: true, removedFrom: ["a", "b", "c"] });
    let confirmMessage = "";
    const confirmSpy = jest.spyOn(window, "confirm").mockImplementation((msg) => {
      confirmMessage = String(msg);
      return true;
    });

    const { result } = renderHook(() => useDatasetCatalogDrawer(true));
    await act(async () => {
      await result.current.onDelete(dataset as never);
    });

    expect(usageSpy).toHaveBeenCalledWith(dataset.id);
    expect(confirmMessage).toContain("used in 3 data flows");
    expect(confirmMessage).toContain("consumed by 2 nodes");
    // The old wording keyed on consumerNodeCount is gone.
    expect(confirmMessage).not.toContain("referenced by 5 nodes");
    expect(deleteSpy).toHaveBeenCalledWith(dataset.id);

    confirmSpy.mockRestore();
    usageSpy.mockRestore();
    deleteSpy.mockRestore();
  });

  it("falls back to the node-count wording when the usage lookup fails", async () => {
    const usageSpy = jest
      .spyOn(datasetCatalogApi, "datasetUsage")
      .mockRejectedValue(new Error("offline"));
    const deleteSpy = jest
      .spyOn(datasetCatalogApi, "deleteDataset")
      .mockResolvedValue({ id: dataset.id, deleted: true, removedFrom: [] });
    let confirmMessage = "";
    const confirmSpy = jest.spyOn(window, "confirm").mockImplementation((msg) => {
      confirmMessage = String(msg);
      return true;
    });

    const { result } = renderHook(() => useDatasetCatalogDrawer(true));
    await act(async () => {
      await result.current.onDelete(dataset as never);
    });

    expect(confirmMessage).toContain("referenced by 5 nodes");

    confirmSpy.mockRestore();
    usageSpy.mockRestore();
    deleteSpy.mockRestore();
  });

  it("reports a partial delete honestly and keeps the row (#173)", async () => {
    // The backend verifies the rmtree actually emptied the directory and
    // reports `deleted: false` with the survivors in `failedDirs` when a locked
    // file keeps it alive. The row must stay visible and the toast must be an
    // error: claiming success here strands a dataset the user thinks is gone.
    const usageSpy = jest.spyOn(datasetCatalogApi, "datasetUsage").mockResolvedValue([]);
    const deleteSpy = jest.spyOn(datasetCatalogApi, "deleteDataset").mockResolvedValue({
      id: dataset.id,
      deleted: false,
      removedFrom: [],
      failedDirs: ["computed.flow-1.n1@1"],
    } as never);
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);

    const { result } = renderHook(() => useDatasetCatalogDrawer(true));
    await act(async () => {
      await result.current.onDelete(dataset as never);
    });

    expect(deleteSpy).toHaveBeenCalledWith(dataset.id);
    const [message, level] = mockShowToast.mock.calls.at(-1)!;
    expect(level).toBe("error");
    expect(String(message)).toContain("Could not fully delete");
    expect(String(message)).toContain(dataset.title);
    // No success toast slipped out alongside it.
    expect(mockShowToast).not.toHaveBeenCalledWith(
      expect.stringContaining("Deleted "),
      "success",
    );

    confirmSpy.mockRestore();
    usageSpy.mockRestore();
    deleteSpy.mockRestore();
  });

  it("still reloads the catalog after a partial delete", async () => {
    // Refs were stripped even though the directory survived, so the listing is
    // stale either way and must be refetched.
    const usageSpy = jest.spyOn(datasetCatalogApi, "datasetUsage").mockResolvedValue([]);
    const deleteSpy = jest.spyOn(datasetCatalogApi, "deleteDataset").mockResolvedValue({
      id: dataset.id,
      deleted: false,
      removedFrom: [],
      failedDirs: ["computed.flow-1.n1@1"],
    } as never);
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);

    const { result } = renderHook(() => useDatasetCatalogDrawer(true));
    await act(async () => {
      await result.current.onDelete(dataset as never);
    });

    expect(mockCatalogReload).toHaveBeenCalledWith({ bustCache: true });

    confirmSpy.mockRestore();
    usageSpy.mockRestore();
    deleteSpy.mockRestore();
  });

  it("does not delete when the dialog is dismissed", async () => {
    const usageSpy = jest.spyOn(datasetCatalogApi, "datasetUsage").mockResolvedValue([]);
    const deleteSpy = jest.spyOn(datasetCatalogApi, "deleteDataset");
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(false);

    const { result } = renderHook(() => useDatasetCatalogDrawer(true));
    await act(async () => {
      await result.current.onDelete(dataset as never);
    });

    expect(deleteSpy).not.toHaveBeenCalled();

    confirmSpy.mockRestore();
    usageSpy.mockRestore();
    deleteSpy.mockRestore();
  });
});

describe("useDatasetCatalogDrawer visible items (account-level computed)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockCatalogItems = [];
  });

  const persistedComputed = {
    id: "computed.flow-1.n1",
    title: "Knowledge Graph",
    origin: "computed" as const,
    format: "json" as const,
    // A persisted account-store dataset has a real store folder.
    dirName: "computed.flow-1.n1@1",
    uri: "curio://datasets/computed.flow-1.n1@1",
    producerNodeId: "n1",
    consumerNodeIds: [],
    tags: ["computed", "json"],
    updatedAt: "2026-01-01T00:00:00Z",
    installed: false,
  };
  const ephemeralLiveOutput = {
    id: "computed.flow-1.n2",
    title: "1790000000000 Deadbeef.Json",
    origin: "computed" as const,
    format: "json" as const,
    // Session-only live output: no store folder yet.
    uri: "curio://outputs/1790000000000_deadbeef.json",
    path: "1790000000000_deadbeef.json",
    producerNodeId: "n2",
    consumerNodeIds: [],
    tags: ["computed", "json"],
    updatedAt: "2026-01-01T00:00:00Z",
    installed: false,
  };

  it("shows a persisted-but-not-installed computed dataset and drops the ephemeral live output", () => {
    mockCatalogItems = [persistedComputed, ephemeralLiveOutput];
    const { result } = renderHook(() => useDatasetCatalogDrawer(true));

    act(() => result.current.setTab("computed"));

    const shownIds = result.current.items.map((i) => i.id);
    expect(shownIds).toContain("computed.flow-1.n1"); // account-level asset, available
    expect(shownIds).not.toContain("computed.flow-1.n2"); // ephemeral, dropped
    // The persisted computed dataset is shown as available, not installed.
    const shown = result.current.items.find((i) => i.id === "computed.flow-1.n1");
    expect(shown?.installed).not.toBe(true);
    expect(result.current.tabComputedCount).toBe(1);
  });
});
