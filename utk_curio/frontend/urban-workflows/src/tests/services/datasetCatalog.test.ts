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
  datasetDisplayTitle,
  datasetSubtitle,
  stripDataFileExtension,
  isGeneratedDataFileName,
  createOsmGroupDragPayload,
  groupDatasetsForPalette,
  nodeLinkedDatasetIds,
  isNodeLinkedToAnyDataset,
  DATASET_DRAG_MIME,
  DatasetCatalogItem,
  type DatasetPaletteGroup,
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

describe("datasetDisplayTitle (clean, user-facing dataset name)", () => {
  test("computed datasets show the producing node's name (title), not the filename", () => {
    expect(
      datasetDisplayTitle(
        makeDataset({
          origin: "computed",
          title: "Data Transformation",
          fileName: "1782498496720 Ef610Da8.Json",
          dirName: "computed.node-x@1",
        }),
      ),
    ).toBe("Data Transformation");
  });

  test("computed datasets with no captured node name (title === fileName) fall back to dirName", () => {
    expect(
      datasetDisplayTitle(
        makeDataset({
          origin: "computed",
          title: "1782498496720 Ef610Da8.Json",
          fileName: "1782498496720 Ef610Da8.Json",
          dirName: "computed.node-x@1",
        }),
      ),
    ).toBe("computed.node-x@1");
  });

  test("computed datasets fall back to dirName (not fileName) when title is blank", () => {
    expect(
      datasetDisplayTitle(
        makeDataset({ origin: "computed", title: "   ", fileName: "My Output", dirName: "computed.node-x@1" }),
      ),
    ).toBe("computed.node-x@1");
  });

  test("namespaced computed dirName falls back to the node-scoped folder, never the dataflow UUID", () => {
    expect(
      datasetDisplayTitle(
        makeDataset({
          origin: "computed",
          title: "1782498496720 Ef610Da8.Json",
          fileName: "1782498496720 Ef610Da8.Json",
          // dirName is dataflow-namespaced: computed.<dataflowId>.<node>@1
          dirName: "computed.c8077fbd-010d-4f6f-b7e2-a99f5df87243.whatif-data@1",
        }),
      ),
    ).toBe("computed.whatif-data@1");
  });

  test("a bare namespaced id (no @N) also drops the dataflow segment (#175)", () => {
    // Dataset IDs never carry @<major> — only dirNames do. The regex must not
    // require it, or the raw namespaced string (with the dataflow UUID) leaks.
    const { displayFolderName } = require("../../services/datasetCatalog/datasetCatalogTypes");
    expect(
      displayFolderName("computed.c8077fbd-010d-4f6f-b7e2-a99f5df87243.whatif-data"),
    ).toBe("computed.whatif-data");
    // Python-twin parity: legacy and non-computed inputs pass through.
    expect(displayFolderName("computed.node-x")).toBe("computed.node-x");
    expect(displayFolderName("imported.xabc@1")).toBe("imported.xabc@1");
  });

  test("a friendly node title is still shown even with a namespaced dirName", () => {
    expect(
      datasetDisplayTitle(
        makeDataset({
          origin: "computed",
          title: "Knowledge Graph",
          fileName: "1782498496720 Ef610Da8.Json",
          dirName: "computed.c8077fbd-010d-4f6f-b7e2-a99f5df87243.whatif-data@1",
        }),
      ),
    ).toBe("Knowledge Graph");
  });

  test("stale hub copy (title LOOKS generated, fileName differs) still falls back to dirName", () => {
    // Browsing from another dataflow surfaces only the published hub row, whose
    // title was captured at publish time and whose fileName is derived from the
    // stored ``.json.zlib`` file — so they don't match byte-for-byte. The title
    // must still never render as the raw filename.
    expect(
      datasetDisplayTitle(
        makeDataset({
          origin: "hub",
          sourceLabel: "Computed",
          title: "1782757759504 31640Bba.Json",
          fileName: "1782757759504 31640Bba.Json.Zlib",
          dirName: "computed.whatif-data@1",
        }),
      ),
    ).toBe("computed.whatif-data@1");
  });

  test("imported / hub / source datasets show their real title", () => {
    expect(
      datasetDisplayTitle(makeDataset({ origin: "imported", title: "Chicago Boundary", dirName: "data.urbanlab.chicago-boundary@1" })),
    ).toBe("Chicago Boundary");
    expect(
      datasetDisplayTitle(makeDataset({ origin: "hub", title: "Census Blocks" })),
    ).toBe("Census Blocks");
  });
});

describe("datasetSubtitle (secondary line under the title)", () => {
  test("computed datasets with a real node-name title show the store folder (dirName)", () => {
    expect(
      datasetSubtitle(
        makeDataset({
          origin: "computed",
          title: "Data Transformation",
          fileName: "1782498496720 Ef610Da8.Json",
          dirName: "computed.node-x@1",
        }),
      ),
    ).toBe("computed.node-x@1");
  });

  test("imported / hub datasets show the store folder", () => {
    expect(
      datasetSubtitle(makeDataset({ origin: "imported", dirName: "data.urbanlab.chicago-boundary@1" })),
    ).toBe("data.urbanlab.chicago-boundary@1");
  });

  test("falls back to the filename (no extension) when dirName would duplicate the title", () => {
    // No node name captured (title === fileName) → datasetDisplayTitle falls back
    // to dirName, so showing dirName again would just echo the title.
    expect(
      datasetSubtitle(
        makeDataset({
          origin: "computed",
          title: "1782498496720 Ef610Da8.Json",
          fileName: "1782498496720 Ef610Da8.Json",
          dirName: "computed.node-x@1",
        }),
      ),
    ).toBe("1782498496720 Ef610Da8");
  });

  test("blank-title computed dataset (title→dirName) also shows the filename subtitle", () => {
    expect(
      datasetSubtitle(
        makeDataset({ origin: "computed", title: "   ", fileName: "My Output.json", dirName: "computed.node-x@1" }),
      ),
    ).toBe("My Output");
  });

  test("returns nullish when there is no store folder yet (line omitted)", () => {
    expect(datasetSubtitle(makeDataset({ origin: "computed", dirName: null }))).toBeNull();
    expect(datasetSubtitle(makeDataset({ origin: "computed" }))).toBeUndefined();
  });

  test("shows the node-scoped folder for a dataflow-namespaced computed dir", () => {
    expect(
      datasetSubtitle(
        makeDataset({
          origin: "computed",
          title: "Knowledge Graph",
          fileName: "1782498496720 Ef610Da8.Json",
          dirName: "computed.c8077fbd-010d-4f6f-b7e2-a99f5df87243.whatif-data@1",
        }),
      ),
    ).toBe("computed.whatif-data@1");
  });
});

describe("isGeneratedDataFileName", () => {
  test("flags epoch-prefixed and data-extension names as generated", () => {
    expect(isGeneratedDataFileName("1782757759504 31640Bba.Json")).toBe(true);
    expect(isGeneratedDataFileName("1782757759504_31640bba")).toBe(true); // epoch prefix
    expect(isGeneratedDataFileName("output.json")).toBe(true);
    expect(isGeneratedDataFileName("data.json.zlib")).toBe(true);
    expect(isGeneratedDataFileName("blocks.parquet")).toBe(true);
  });

  test("treats real human/node names as NOT generated", () => {
    expect(isGeneratedDataFileName("Autark")).toBe(false);
    expect(isGeneratedDataFileName("Data Transformation")).toBe(false);
    expect(isGeneratedDataFileName("Chicago Boundary")).toBe(false);
    expect(isGeneratedDataFileName("")).toBe(false);
    expect(isGeneratedDataFileName(null)).toBe(false);
  });
});

describe("stripDataFileExtension", () => {
  test("strips a trailing .json / .Json case-insensitively", () => {
    expect(stripDataFileExtension("output.json")).toBe("output");
    expect(stripDataFileExtension("1782498496720 Ef610Da8.Json")).toBe("1782498496720 Ef610Da8");
    expect(stripDataFileExtension("data.JSON")).toBe("data");
  });

  test("leaves names without a .json extension untouched (incl. embedded dots)", () => {
    expect(stripDataFileExtension("My Output")).toBe("My Output");
    expect(stripDataFileExtension("v1.2.summary")).toBe("v1.2.summary");
    expect(stripDataFileExtension("blocks.csv")).toBe("blocks.csv");
  });

  test("passes through null / undefined", () => {
    expect(stripDataFileExtension(null)).toBeNull();
    expect(stripDataFileExtension(undefined)).toBeUndefined();
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

describe("nodeLinkedDatasetIds / isNodeLinkedToAnyDataset (highlighting)", () => {
  test("collects datasetSource, datasetRefs, and appliedDatasets ids", () => {
    const data = {
      datasetSource: { datasetId: "osm.x1" },
      datasetRefs: ["loop.points", "loop.lines"],
      appliedDatasets: { "loop.multipolygons": { id: "loop.multipolygons" } },
    };
    expect(new Set(nodeLinkedDatasetIds(data))).toEqual(
      new Set(["osm.x1", "loop.points", "loop.lines", "loop.multipolygons"]),
    );
  });

  test("a group-created node is matched by both the group id and any member id", () => {
    // Node created by dragging the whole group: datasetSource = group id, refs = layers.
    const groupNode = { datasetSource: { datasetId: "osm.x1" }, datasetRefs: ["loop.points", "loop.lines"] };
    expect(isNodeLinkedToAnyDataset(groupNode, ["osm.x1"])).toBe(true); // group parent
    expect(isNodeLinkedToAnyDataset(groupNode, ["loop.points"])).toBe(true); // an individual layer
    expect(isNodeLinkedToAnyDataset(groupNode, ["unrelated"])).toBe(false);
  });

  test("an individual-layer node is matched by that layer id", () => {
    const layerNode = { datasetSource: { datasetId: "loop.lines" }, datasetRefs: ["loop.lines"] };
    expect(isNodeLinkedToAnyDataset(layerNode, ["loop.lines"])).toBe(true);
    expect(isNodeLinkedToAnyDataset(layerNode, ["loop.points"])).toBe(false);
  });

  test("empty/absent linkage never matches", () => {
    expect(nodeLinkedDatasetIds({})).toEqual([]);
    expect(isNodeLinkedToAnyDataset({}, ["x"])).toBe(false);
  });
});

test("dragging an OSM group builds a node that loads all layers via real member refs", () => {
  const members = [
    makeDataset({ id: "loop.points", title: "chicago_loop (points)", origin: "imported", format: "parquet", path: "/store/loop.points@1/data/points.parquet", layerName: "points", groupId: "osm.x1" }),
    makeDataset({ id: "loop.lines", title: "chicago_loop (lines)", origin: "imported", format: "parquet", path: "/store/loop.lines@1/data/lines.parquet", layerName: "lines", groupId: "osm.x1" }),
  ];
  const [group] = groupDatasetsForPalette(members) as [DatasetPaletteGroup];
  const payload = createOsmGroupDragPayload(group);

  // The payload is the full multilayer dataset (osm), carrying the real layers.
  expect(payload.format).toBe("osm");
  expect(payload.datasetId).toBe("osm.x1");
  expect(payload.groupLayers?.map((l) => l.id)).toEqual(["loop.points", "loop.lines"]);

  const options = buildDatasetLoaderNodeOptions(payload, { x: 0, y: 0 });
  // Node references the REAL layer ids — never the synthetic group id — so the
  // saved dataflow.datasets can't gain a phantom ref.
  expect(options.datasetRefs).toEqual(["loop.points", "loop.lines"]);
  expect(Object.keys(options.appliedDatasets)).toEqual(["loop.points", "loop.lines"]);
  expect(options.appliedDatasets["osm.x1"]).toBeUndefined();
  // The loader reads every layer into one `layers` dict (the full import).
  expect(options.code).toContain('layers["points"] = _curio_read_layer("/store/loop.points@1/data/points.parquet")');
  expect(options.code).toContain('layers["lines"] = _curio_read_layer("/store/loop.lines@1/data/lines.parquet")');
  expect(options.code).toContain("return layers");
  // The linkage marker still points at the group for palette↔canvas focus.
  expect(options.datasetSource.datasetId).toBe("osm.x1");
});

test("dropping an OSM group onto a node applies all layer refs, not the group id", () => {
  const members = [
    makeDataset({ id: "loop.points", title: "chicago_loop (points)", format: "parquet", path: "/a.parquet", layerName: "points", groupId: "osm.x9" }),
    makeDataset({ id: "loop.lines", title: "chicago_loop (lines)", format: "parquet", path: "/b.parquet", layerName: "lines", groupId: "osm.x9" }),
  ];
  const [group] = groupDatasetsForPalette(members) as [DatasetPaletteGroup];
  const result = applyDatasetToNodeData({ datasetRefs: ["existing"] }, "", createOsmGroupDragPayload(group));
  expect(result.data.datasetRefs).toEqual(["existing", "loop.points", "loop.lines"]);
  expect(result.data.appliedDatasets["osm.x9"]).toBeUndefined();
  expect(result.data.appliedDatasets["loop.points"]).toBeTruthy();
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

  test("links a fresh account-store save (dirName set, not installed) (#175)", () => {
    // Computed outputs are account-level assets on save — no spec ref, so
    // installed stays false until an explicit Install. The OUTPUT chip must
    // still render for them.
    const items = [
      makeDataset({
        id: "computed.flow-1.node-a",
        dirName: "computed.flow-1.node-a@1",
        producerNodeId: "node-a",
        installed: false,
      }),
    ];
    expect(installedComputedByProducer(items).get("node-a")?.id).toBe("computed.flow-1.node-a");
  });
});
