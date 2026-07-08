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
  OSM_PBF_IMPORT_MESSAGE,
} from "../../services/datasetCatalog";

describe("useDatasetCatalogDrawer.onPickImport", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("fans out a catalog-refresh event so other surfaces update without a reload", async () => {
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
    expect(mockSetDataflowDatasets).toHaveBeenCalled();
    expect(refreshSpy).toHaveBeenCalledTimes(1);
    expect(mockShowToast).toHaveBeenCalledWith("Imported Imported.csv.", "success");

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
    "redirects OSM PBF imports (%s) to the Autark node without hitting the importer",
    async (name) => {
      const refreshSpy = jest.fn();
      window.addEventListener(DATASET_CATALOG_REFRESH_EVENT, refreshSpy);

      const file = new File(["<binary>"], name, { type: "application/octet-stream" });
      const { result } = renderHook(() => useDatasetCatalogDrawer(true));

      await act(async () => {
        await result.current.onPickImport(file);
      });

      expect(mockImportDataset).not.toHaveBeenCalled();
      expect(refreshSpy).not.toHaveBeenCalled();
      expect(mockShowToast).toHaveBeenCalledWith(OSM_PBF_IMPORT_MESSAGE, "warning");

      window.removeEventListener(DATASET_CATALOG_REFRESH_EVENT, refreshSpy);
    },
  );
});
