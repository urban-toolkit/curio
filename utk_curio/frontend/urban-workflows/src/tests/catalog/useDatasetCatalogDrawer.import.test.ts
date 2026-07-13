import { renderHook, act } from "@testing-library/react";

// ── Mock the drawer hook's collaborators ──────────────────────────────────────
// Keep the datasetCatalog module REAL except for useDatasetCatalog, so the
// production notifyDatasetCatalogRefresh() + DATASET_CATALOG_REFRESH_EVENT are
// exercised end-to-end.
const mockImportDataset = jest.fn();
const mockCatalogReload = jest.fn(async () => {});

jest.mock("../../services/datasetCatalog", () => {
  const actual = jest.requireActual("../../services/datasetCatalog");
  return {
    ...actual,
    useDatasetCatalog: () => ({
      items: [],
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
      "Registered Imported.csv in the data catalog.",
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
        `Registered 3 datasets from ${name} in the data catalog.`,
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

    // Installed each real layer, never the synthetic group id.
    expect(installSpy).toHaveBeenCalledTimes(2);
    const installedIds = installSpy.mock.calls.map((c) => c[1]);
    expect(installedIds).toEqual(["imported.xaaa", "imported.xbbb"]);
    expect(installedIds).not.toContain("osm.xdeadbeef");
    // dataflowDatasets got the real per-layer refs (so a later save won't drop them).
    expect(mockSetDataflowDatasets).toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalledWith(
      "Installed 2 layers from back_bay.",
      "success",
    );

    installSpy.mockRestore();
  });
});
