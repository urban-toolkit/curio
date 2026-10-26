/**
 * A file from the computer, dropped on the canvas or on a node, or picked
 * with a dataset widget's Choose file: imported into the Data Catalog as
 * Import dataset imports it, added to the open dataflow as Add to project adds
 * it, then handed on as the card it now is (useDataFileImport).
 */
import { act, renderHook } from "@testing-library/react";

const mockEnsureProjectId = jest.fn();
const mockSetDataflowDatasets = jest.fn();
const mockShowToast = jest.fn();
let mockHostedGuest = false;

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    ensureProjectId: mockEnsureProjectId,
    setDataflowDatasets: mockSetDataflowDatasets,
  }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../components/apiSettings/useHostedGuest", () => ({
  ...jest.requireActual("../../components/apiSettings/useHostedGuest"),
  useHostedGuest: () => mockHostedGuest,
}));
jest.mock("../../services/datasetCatalog", () => ({
  ...jest.requireActual("../../services/datasetCatalog"),
  datasetCatalogApi: {
    importDataset: jest.fn(),
    getDataset: jest.fn(),
    installToDataflow: jest.fn(),
  },
}));

import { notImportableMessage, useDataFileImport } from "../../components/datasets/useDataFileImport";
import { datasetCatalogApi } from "../../services/datasetCatalog";

const mockApi = datasetCatalogApi as unknown as Record<"importDataset" | "getDataset" | "installToDataflow", jest.Mock>;

function item(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    title: id,
    origin: "imported",
    format: "csv",
    uri: `curio://datasets/${id}@1`,
    path: `/store/${id}@1/data/file.csv`,
    consumerNodeIds: [],
    updatedAt: "2026-10-26T00:00:00Z",
    tags: [],
    ...overrides,
  };
}

const csv = () => new File(["id,height\n1,10\n"], "trees.csv", { type: "text/csv" });

async function importing(files: File[]) {
  const { result } = renderHook(() => useDataFileImport());
  let out: unknown;
  await act(async () => {
    out = await result.current(files);
  });
  return out as { datasetId: string; groupLayers?: { id: string }[] } | null;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockHostedGuest = false;
  mockEnsureProjectId.mockResolvedValue("df-1");
  mockApi.installToDataflow.mockImplementation(async (_df: string, id: string) => item(id));
});

test("a file is imported into the dataflow's account, added to the dataflow, and handed on as its card", async () => {
  mockApi.importDataset.mockResolvedValue(item("imported.xtrees", { title: "trees" }));

  const dataset = await importing([csv()]);

  expect(mockApi.importDataset).toHaveBeenCalledWith(expect.any(File), { dataflowId: "df-1" });
  expect(mockApi.installToDataflow).toHaveBeenCalledWith(
    "df-1", "imported.xtrees", expect.objectContaining({ id: "imported.xtrees" }), undefined,
  );
  expect(mockSetDataflowDatasets).toHaveBeenCalled();
  expect(dataset).toMatchObject({ datasetId: "imported.xtrees", title: "trees" });
  expect(mockShowToast).toHaveBeenCalledWith("Importing trees.csv into the Data Catalog...", "info");
});

test("a file of several layers is handed on as its group, each layer added to the dataflow", async () => {
  mockApi.importDataset.mockResolvedValue(item("imported.xbuildings", { groupId: "osm.x1a2b3c4d", format: "parquet" }));
  const layers = ["buildings", "roads"].map((layer) => ({
    id: `imported.x${layer}`,
    title: `manhattan (${layer})`,
    uri: `curio://datasets/imported.x${layer}@1`,
    path: `/store/imported.x${layer}@1/data/${layer}.parquet`,
    format: "parquet",
    layerName: layer,
  }));
  mockApi.getDataset.mockResolvedValue(
    item("osm.x1a2b3c4d", {
      title: "manhattan",
      format: "osm",
      path: null,
      groupLayerIds: layers.map((layer) => layer.id),
      groupLayers: layers,
    }),
  );

  const dataset = await importing([new File(["pbf"], "manhattan.osm.pbf")]);

  expect(mockApi.getDataset).toHaveBeenCalledWith("osm.x1a2b3c4d", { dataflowId: "df-1" });
  expect(mockApi.installToDataflow.mock.calls.map((call) => call[1])).toEqual([
    "imported.xbuildings",
    "imported.xroads",
  ]);
  expect(dataset?.datasetId).toBe("osm.x1a2b3c4d");
  expect(dataset?.groupLayers?.map((layer) => layer.id)).toEqual(["imported.xbuildings", "imported.xroads"]);
});

test("one file at a time", async () => {
  const dataset = await importing([csv(), csv()]);

  expect(dataset).toBeNull();
  expect(mockApi.importDataset).not.toHaveBeenCalled();
  expect(mockShowToast).toHaveBeenCalledWith("Drop one file at a time.", "warning");
});

test("a file Import dataset does not take is refused before anything is sent", async () => {
  const dataset = await importing([new File(["x"], "budget.xlsx")]);

  expect(dataset).toBeNull();
  expect(mockEnsureProjectId).not.toHaveBeenCalled();
  expect(mockApi.importDataset).not.toHaveBeenCalled();
  expect(mockShowToast).toHaveBeenCalledWith(notImportableMessage("budget.xlsx"), "error");
});

test("a lone shapefile goes to the import, which says how to zip it", async () => {
  mockApi.importDataset.mockRejectedValue(new Error("A shapefile cannot be read from roads.shp alone."));

  const dataset = await importing([new File(["shp"], "roads.shp")]);

  expect(dataset).toBeNull();
  expect(mockApi.importDataset).toHaveBeenCalled();
  expect(mockShowToast).toHaveBeenCalledWith("A shapefile cannot be read from roads.shp alone.", "error");
});

test("a hosted guest on a dataflow it never saved is told to sign in, and nothing is imported", async () => {
  mockHostedGuest = true;
  mockEnsureProjectId.mockResolvedValue(null);

  const dataset = await importing([csv()]);

  expect(dataset).toBeNull();
  expect(mockApi.importDataset).not.toHaveBeenCalled();
  expect(mockShowToast).toHaveBeenCalledWith("Sign in to add datasets.", "warning");
});
