import {
  applyDatasetToNodeData,
  beginDatasetDrag,
  buildDatasetLoaderCode,
  buildDatasetLoaderNodeOptions,
  createDatasetDragPayload,
  endDatasetDrag,
  readDatasetDragPayload,
  isUserInstalledDataset,
  isDatasetPaletteNode,
  getDatasetSourceId,
  installedComputedByProducer,
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

test("buildDatasetLoaderNodeOptions stamps the datasetSource linkage marker", () => {
  const options = buildDatasetLoaderNodeOptions(dataset, { x: 0, y: 0 });
  expect(options.datasetSource).toEqual({
    datasetId: "file-123",
    title: "Blocks",
    format: "csv",
    origin: "imported",
  });
});

test("createDatasetDragPayload carries origin so the linkage survives a drag", () => {
  expect(createDatasetDragPayload(dataset).origin).toBe("imported");
  const options = buildDatasetLoaderNodeOptions(createDatasetDragPayload(dataset), { x: 0, y: 0 });
  expect(options.datasetSource.origin).toBe("imported");
});

test("isDatasetPaletteNode / getDatasetSourceId reflect the marker", () => {
  const paletteNode = buildDatasetLoaderNodeOptions(dataset, { x: 0, y: 0 });
  expect(isDatasetPaletteNode(paletteNode)).toBe(true);
  expect(getDatasetSourceId(paletteNode)).toBe("file-123");

  // A plain code node that merely references a dataset is NOT a palette node.
  const applied = applyDatasetToNodeData(
    { nodeId: "n", nodeType: NodeType.DATA_LOADING },
    "print('x')",
    createDatasetDragPayload(dataset),
  );
  expect(isDatasetPaletteNode(applied.data)).toBe(false);
  expect(getDatasetSourceId(applied.data)).toBeNull();
  expect(isDatasetPaletteNode(undefined)).toBe(false);
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


test("mergeDatasetLoaderCode indents the loader block to match an indented return (B4)", () => {
  const existing = ["if cond:", "    x = compute()", "    return x"].join("\n");
  const merged = mergeDatasetLoaderCode(existing, dataset);
  // No line of the inserted loader may sit at column 0 between the indented
  // code and the indented return — that would be a Python IndentationError.
  expect(merged).toContain("    df = pd.read_csv(dataset_path)");
  expect(merged).toContain("    return df");
  expect(merged).not.toMatch(/\ndf = pd\.read_csv/);
});

test("mergeDatasetLoaderCode/buildDatasetLoaderCode escape backslashes and quotes in the path (B11)", () => {
  const winDataset = makeDataset({
    format: "csv",
    path: "C:\\Users\\me\\data\\blocks.csv",
    uri: "file:///c/blocks.csv",
  });
  const code = buildDatasetLoaderCode(winDataset);
  // The path must be a valid Python string literal: backslashes escaped, so no
  // raw `\U`/`\b` escape and the literal isn't terminated early.
  expect(code).toContain('dataset_path = "C:\\\\Users\\\\me\\\\data\\\\blocks.csv"');
});

test("datasetProvenanceLabel is origin-based, not format-based (B14)", () => {
  const { datasetProvenanceLabel } = require("../../services/datasetCatalog/datasetCatalogTypes");
  // An imported parquet must read "Imported", not "Computed".
  expect(datasetProvenanceLabel("imported", "parquet")).toBe("Imported");
  expect(datasetProvenanceLabel("hub", "parquet")).toBe("Imported");
  // A computed dataset stays "Computed".
  expect(datasetProvenanceLabel("computed", "parquet")).toBe("Computed");
  expect(datasetProvenanceLabel("computed", "csv")).toBe("Computed");
});

describe("installedComputedByProducer (producer↔palette linkage)", () => {
  test("maps producerNodeId → installed computed dataset", () => {
    const items = [
      makeDataset({ id: "computed.node-a", producerNodeId: "node-a", installed: true }),
      makeDataset({ id: "computed.node-b", producerNodeId: "node-b", installed: true }),
    ];
    const map = installedComputedByProducer(items);
    expect(map.get("node-a")?.id).toBe("computed.node-a");
    expect(map.get("node-b")?.id).toBe("computed.node-b");
    expect(map.size).toBe(2);
  });

  test("excludes non-installed, non-computed, and producer-less items", () => {
    const items = [
      makeDataset({ id: "computed.live", producerNodeId: "node-x", installed: false }),
      makeDataset({ id: "imported.file", origin: "imported", producerNodeId: "node-y", installed: true }),
      makeDataset({ id: "computed.orphan", producerNodeId: null, installed: true }),
    ];
    expect(installedComputedByProducer(items).size).toBe(0);
  });

  test("first match wins when a node produced several (recent-sorted) items", () => {
    const items = [
      makeDataset({ id: "computed.recent", producerNodeId: "node-a", installed: true }),
      makeDataset({ id: "computed.older", producerNodeId: "node-a", installed: true }),
    ];
    expect(installedComputedByProducer(items).get("node-a")?.id).toBe("computed.recent");
  });
});
