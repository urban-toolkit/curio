/**
 * #442: a dataset dropped onto an existing node gets a DATASET pill, and the
 * node keeps saving its own output.
 *
 * On main the pill rendered only for `isDatasetPaletteNode(data) &&
 * data.datasetSource` (components/styles.tsx). The drop-onto-node path writes
 * neither, which the first test pins, so the node showed no pill.
 */
import {
  applyDatasetToNodeData,
  droppedDatasetSource,
  isDatasetPaletteNode,
} from "../../services/datasetCatalog/datasetApplication";
import { resolveSaveOutputDataset } from "../../utils/saveOutputDataset";

const CHICAGO = {
  datasetId: "data.utk.chicago-boundary@1",
  title: "Chicago boundary",
  format: "geojson",
  origin: "hub",
} as any;
const ZIPS = {
  datasetId: "data.utk.chicago-zips@1",
  title: "Chicago ZIP codes",
  format: "geojson",
  origin: "hub",
} as any;

const pythonNode = {
  nodeId: "n1",
  nodeType: "curio.builtin/computation-analysis@1",
  code: "return arg\n",
  saveOutputDataset: true,
};

test("a dataset dropped onto a Python node gives it a pill and leaves saving on", () => {
  const { data } = applyDatasetToNodeData(pythonNode, pythonNode.code, CHICAGO);

  // The drop does not make it a palette node; that is what keeps saving on.
  expect(data.datasetSource).toBeUndefined();
  expect(isDatasetPaletteNode(data)).toBe(false);
  expect(resolveSaveOutputDataset(data)).toBe(true);

  expect(droppedDatasetSource(data)).toEqual({
    datasetId: "data.utk.chicago-boundary@1",
    title: "Chicago boundary",
    format: "geojson",
    origin: "imported",
  });
});

test("after a reload only the ids are left, and the catalog names the dataset", () => {
  const reloaded = { ...pythonNode, datasetRefs: ["data.utk.chicago-boundary@1"] };
  const lookup = (id: string) =>
    id === CHICAGO.datasetId
      ? { datasetId: id, title: "Chicago boundary", format: "geojson", origin: "hub" } as any
      : undefined;

  expect(droppedDatasetSource(reloaded, lookup)).toMatchObject({
    title: "Chicago boundary",
    format: "geojson",
    origin: "hub",
  });
  // Nothing to name it with: the id stands in.
  expect(droppedDatasetSource(reloaded)?.title).toBe("data.utk.chicago-boundary@1");
});

test("a node reading two datasets names the first and counts the other", () => {
  const once = applyDatasetToNodeData(pythonNode, pythonNode.code, CHICAGO);
  const twice = applyDatasetToNodeData(once.data, once.code, ZIPS);

  expect(droppedDatasetSource(twice.data)?.title).toBe("Chicago boundary +1");
});

test("a palette-created node keeps its own pill, and a node with no dataset gets none", () => {
  const paletteNode = { ...pythonNode, datasetSource: CHICAGO, datasetRefs: [CHICAGO.datasetId] };
  expect(droppedDatasetSource(paletteNode)).toBeNull();
  expect(droppedDatasetSource(pythonNode)).toBeNull();
});
