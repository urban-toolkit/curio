import {
  applyDatasetToNodeData,
  buildDatasetLoaderCode,
  createDatasetDragPayload,
  DATASET_DRAG_MIME,
  DatasetCatalogItem,
} from "../../services/datasetCatalog";
import { NodeType } from "../../constants";

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

test("buildDatasetLoaderCode creates CSV imports and loader", () => {
  expect(buildDatasetLoaderCode(dataset)).toContain("import pandas as pd");
  expect(buildDatasetLoaderCode(dataset)).toContain('dataset_path = "/tmp/blocks.csv"');
  expect(buildDatasetLoaderCode(dataset)).toContain("pd.read_csv(dataset_path)");
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
