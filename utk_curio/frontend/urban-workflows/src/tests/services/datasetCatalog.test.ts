import {
  applyDatasetToNodeData,
  beginDatasetDrag,
  buildDatasetLoaderCode,
  buildDatasetLoaderNodeOptions,
  createDatasetDragPayload,
  endDatasetDrag,
  readDatasetDragPayload,
  isUserInstalledDataset,
  DATASET_DRAG_MIME,
  DatasetCatalogItem,
} from "../../services/datasetCatalog";
import { mergeDatasetLoaderCode } from "../../services/datasetCatalog/datasetLoaderSnippets";
import { NodeType } from "../../constants";

function makeDataset(overrides: Partial<DatasetCatalogItem>): DatasetCatalogItem {
  return {
    id: "computed.node-x",
    title: "Node Output",
    origin: "computed",
    format: "parquet",
    uri: "curio://datasets/computed.node-x@1",
    path: "/store/computed.node-x@1/data/out.parquet",
    consumerNodeIds: [],
    updatedAt: "2026-06-18T00:00:00Z",
    tags: ["computed"],
    ...overrides,
  } as DatasetCatalogItem;
}

describe("isUserInstalledDataset (palette 'Installed datasets' filter)", () => {
  test("includes an installed computed dataset", () => {
    expect(isUserInstalledDataset(makeDataset({ installed: true }))).toBe(true);
  });

  test("still includes it after it is published to the Data Catalog (issue #140)", () => {
    // Publishing does not uninstall the local copy, so it must remain in the
    // palette's installed list.
    expect(
      isUserInstalledDataset(makeDataset({ installed: true, publishedToHub: true })),
    ).toBe(true);
  });

  test("excludes ephemeral live outputs / browsable entries (installed falsy)", () => {
    expect(isUserInstalledDataset(makeDataset({ installed: false }))).toBe(false);
    expect(isUserInstalledDataset(makeDataset({}))).toBe(false);
  });
});

const dataset: DatasetCatalogItem = {
  id: "file-123",
  title: "Blocks",
  description: "Test blocks",
  origin: "imported",
  format: "csv",
  uri: "file:///tmp/blocks.csv",
  path: "/tmp/blocks.csv",
  consumerNodeIds: [],
  updatedAt: "2026-05-29T00:00:00Z",
  sourceLabel: "Workspace data",
  tags: ["csv"],
};

const parquetDataset: DatasetCatalogItem = {
  id: "parquet-456",
  title: "Output Data",
  origin: "computed",
  format: "parquet",
  uri: "curio://outputs/output.parquet",
  path: "/tmp/output.parquet",
  consumerNodeIds: [],
  updatedAt: "2026-06-01T00:00:00Z",
  tags: ["parquet"],
};

const bundleDataset: DatasetCatalogItem = {
  id: "computed.node_x",
  title: "Node output (3 parts)",
  origin: "computed",
  format: "bundle",
  uri: "curio://datasets/computed.node_x@1",
  path: "/data/computed.node_x@1/data/bundle.json",
  consumerNodeIds: [],
  updatedAt: "2026-06-10T00:00:00Z",
  tags: ["bundle", "computed"],
};

test("buildDatasetLoaderCode creates CSV imports and loader", () => {
  expect(buildDatasetLoaderCode(dataset)).toContain("import pandas as pd");
  expect(buildDatasetLoaderCode(dataset)).toContain('dataset_path = "/tmp/blocks.csv"');
  expect(buildDatasetLoaderCode(dataset)).toContain("pd.read_csv(dataset_path)");
});

test("buildDatasetLoaderCode includes return statement for CSV", () => {
  const code = buildDatasetLoaderCode(dataset);
  expect(code).toContain("return df");
});

test("buildDatasetLoaderCode reads parquet as a GeoDataFrame first, then falls back", () => {
  const code = buildDatasetLoaderCode(parquetDataset);
  // GeoParquet-aware read so a computed geo dataset reloads with the same
  // (geo)dataframe type/schema the producing node emitted.
  expect(code).toContain("import geopandas as gpd");
  expect(code).toContain("gpd.read_parquet(dataset_path)");
  expect(code).toContain("pd.read_parquet(dataset_path)");
  expect(code).toContain("return df");
});

test("buildDatasetLoaderCode rebuilds a bundle into a tuple of parts", () => {
  const code = buildDatasetLoaderCode(bundleDataset);
  // Reads the bundle manifest and returns the parts as a tuple so the sandbox
  // re-detects the same `outputs` envelope the producing node emitted.
  expect(code).toContain('bundle_path = "/data/computed.node_x@1/data/bundle.json"');
  expect(code).toContain("spec.get(\"parts\", [])");
  expect(code).toContain("gpd.read_parquet(file_path)");
  expect(code).toContain("return tuple(items)");
  expect(code).toContain("return bundle");
});

test("buildDatasetLoaderNodeOptions builds a new Data Loading node payload", () => {
  const payload = createDatasetDragPayload(dataset);
  const options = buildDatasetLoaderNodeOptions(payload, { x: 100, y: 200 });
  expect(options.position).toEqual({ x: 100, y: 200 });
  expect(options.datasetRefs).toEqual(["file-123"]);
  expect(options.code).toContain("pd.read_csv(dataset_path)");
  expect(options.appliedDatasets["file-123"]).toMatchObject({
    id: "file-123",
    title: "Blocks",
    format: "csv",
  });
});

test("readDatasetDragPayload uses active drag session when getData is empty", () => {
  beginDatasetDrag(dataset);
  const payload = readDatasetDragPayload({ getData: () => "", types: [] } as unknown as DataTransfer);
  expect(payload?.datasetId).toBe("file-123");
  endDatasetDrag();
});

test("createDatasetDragPayload preserves decoupled dataset identity", () => {
  const payload = createDatasetDragPayload(dataset);
  expect(DATASET_DRAG_MIME).toBe("application/x-curio-dataset");
  expect(payload).toMatchObject({
    datasetId: "file-123",
    title: "Blocks",
    format: "csv",
  });
});

test("applyDatasetToNodeData records refs and merges loader code", () => {
  const result = applyDatasetToNodeData(
    { nodeId: "node-1", nodeType: NodeType.DATA_LOADING, datasetRefs: [] },
    "print('hello')",
    createDatasetDragPayload(dataset),
  );

  expect(result.data.datasetRefs).toEqual(["file-123"]);
  expect(result.code).toContain("print('hello')");
  expect(result.code).toContain("pd.read_csv(dataset_path)");
});

test("mergeDatasetLoaderCode inserts loader before return in existing code", () => {
  const existingCode = "import pandas as pd\n\ndf = old_data\nreturn df";
  const merged = mergeDatasetLoaderCode(existingCode, dataset);
  // loader code should appear before the return
  const loaderPos = merged.indexOf("pd.read_csv");
  const returnPos = merged.indexOf("return df");
  expect(loaderPos).toBeGreaterThan(-1);
  expect(returnPos).toBeGreaterThan(loaderPos);
});

test("mergeDatasetLoaderCode on empty code includes return", () => {
  const merged = mergeDatasetLoaderCode("", dataset);
  expect(merged).toContain("pd.read_csv(dataset_path)");
  expect(merged).toContain("return df");
});

