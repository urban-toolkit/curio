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
  datasetIdsInCode,
  DATASET_DRAG_MIME,
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  type DatasetFormat,
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
      datasetDisplayTitle(makeDataset({ origin: "imported", title: "Chicago Boundary", dirName: "data.utk.chicago-boundary@1" })),
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
      datasetSubtitle(makeDataset({ origin: "imported", dirName: "data.utk.chicago-boundary@1" })),
    ).toBe("data.utk.chicago-boundary@1");
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

test("buildDatasetLoaderCode loads a CSV with one portable call", () => {
  // Portable form: the sandbox resolves the id and reads the CSV at execution
  // time, so generated code carries no machine-specific absolute path.
  const code = buildDatasetLoaderCode(dataset);
  expect(code).toContain('df = curio_load_data("file-123")');
  expect(code).not.toContain(String(dataset.path));
});

test("buildDatasetLoaderCode includes return statement for CSV", () => {
  const code = buildDatasetLoaderCode(dataset);
  expect(code).toContain("return df");
});

test("buildDatasetLoaderCode loads parquet with one portable call", () => {
  // The sandbox reads it as a GeoDataFrame when it has geometry, so a computed
  // geo dataset reloads with the type the producing node emitted.
  const code = buildDatasetLoaderCode(parquetDataset);
  expect(code).toContain('df = curio_load_data("parquet-456")');
  expect(code).toContain("return df");
});

const jsonDataset: DatasetCatalogItem = {
  id: "computed.dataflow-1.node-a",
  title: "Autark",
  origin: "computed",
  format: "json",
  uri: "curio://datasets/computed.dataflow-1.node-a@1",
  path: "/store/computed.dataflow-1.node-a@1/data/1786466491428_32e01db8.json.zlib",
  consumerNodeIds: [],
  updatedAt: "2026-08-11T00:00:00Z",
  tags: ["json", "computed"],
};

test("buildDatasetLoaderCode loads json with one portable call", () => {
  // Computed dict/list outputs (autk-grammar pool wrappers) are stored as
  // `.json.zlib` with `format: json`; the sandbox decompresses them and still
  // reads plain user-imported .json files.
  const code = buildDatasetLoaderCode(jsonDataset);
  expect(code).toContain('data = curio_load_data("computed.dataflow-1.node-a")');
  expect(code).toContain("return data");
});

test("mergeDatasetLoaderCode is stable on re-apply", () => {
  const first = mergeDatasetLoaderCode("", jsonDataset);
  expect(first.split('curio_load_data("computed.dataflow-1.node-a")')).toHaveLength(2);
  // Re-applying the same dataset must not duplicate the loader block.
  const again = mergeDatasetLoaderCode(first, jsonDataset);
  expect(again).toBe(first);
});

test("a raster's loader names its window, and a loader with one counts as applied", () => {
  const raster = { ...jsonDataset, id: "data.scout.depth", format: "geotiff", title: "Depth" } as never;
  const first = mergeDatasetLoaderCode("", raster);
  expect(first).toContain('src = curio_load_data("data.scout.depth", bounds=None)');
  // The user picks a window; dropping the same dataset again adds no second loader.
  const windowed = first.replace("bounds=None", "bounds=(-90.48, 41.44, -90.46, 41.46)");
  expect(mergeDatasetLoaderCode(windowed, raster)).toBe(windowed);
});

test("buildDatasetLoaderCode loads a bundle with one portable call", () => {
  // The sandbox reads the bundle manifest and returns the parts as a tuple, so
  // it re-detects the same `outputs` envelope the producing node emitted.
  const code = buildDatasetLoaderCode(bundleDataset);
  expect(code).toContain('bundle = curio_load_data("computed.node_x")');
  expect(code).toContain("return bundle");
});

test("buildDatasetLoaderNodeOptions builds a new Data Loading node payload", () => {
  const payload = createDatasetDragPayload(dataset);
  const options = buildDatasetLoaderNodeOptions(payload, { x: 100, y: 200 });
  expect(options.position).toEqual({ x: 100, y: 200 });
  expect(options.datasetRefs).toEqual(["file-123"]);
  expect(options.code).toContain('df = curio_load_data("file-123")');
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
  expect(options.code).toContain('layers["points"] = curio_load_data("loop.points")');
  expect(options.code).toContain('layers["lines"] = curio_load_data("loop.lines")');
  expect(options.code).toContain("return layers");
  // The linkage marker still points at the group for palette↔canvas focus.
  expect(options.datasetSource.datasetId).toBe("osm.x1");
});

test("dragging a Discovery OpenStreetMap group reads its GeoJSON layers as GeoJSON", () => {
  // A Discovery download lands each Autark layer as a GeoJSON file in one osm.x group.
  const members = [
    makeDataset({ id: "golf.buildings", title: "OpenStreetMap, Golf (buildings)", origin: "imported", format: "geojson", path: "/store/golf.buildings@1/data/osm_buildings.geojson", layerName: "buildings", groupId: "osm.x2" }),
    makeDataset({ id: "golf.roads", title: "OpenStreetMap, Golf (roads)", origin: "imported", format: "geojson", path: "/store/golf.roads@1/data/osm_roads.geojson", layerName: "roads", groupId: "osm.x2" }),
  ];
  const [group] = groupDatasetsForPalette(members) as [DatasetPaletteGroup];
  const options = buildDatasetLoaderNodeOptions(createOsmGroupDragPayload(group), { x: 0, y: 0 });

  expect(options.code).toContain('layers["buildings"] = curio_load_data("golf.buildings")');
  expect(options.code).toContain('layers["roads"] = curio_load_data("golf.roads")');
  expect(options.code).not.toContain("read_parquet");
  expect(options.code).toContain("return layers");
});

describe("a layer group's drag payload takes its kind from the group id (#440)", () => {
  function groupOf(groupId: string): DatasetPaletteGroup {
    const members = [
      makeDataset({ id: "imported.parks_parks", title: "parks (parks)", origin: "imported", format: "parquet", path: "/store/imported.parks_parks@1/data/parks.parquet", layerName: "parks", groupId }),
      makeDataset({ id: "imported.parks_trails", title: "parks (trails)", origin: "imported", format: "parquet", path: "/store/imported.parks_trails@1/data/trails.parquet", layerName: "trails", groupId }),
    ];
    const [group] = groupDatasetsForPalette(members) as [DatasetPaletteGroup];
    return group;
  }

  test("a GeoPackage group drops as a GeoPackage dataset, not an OSM PBF", () => {
    const payload = createOsmGroupDragPayload(groupOf("gpkg.x1"));
    expect(payload.format).toBe("gpkg");
    expect(payload.uri).toBe("curio://gpkg/gpkg.x1");

    // The DATASET pill's tooltip reads the format from the node's datasetSource.
    const options = buildDatasetLoaderNodeOptions(payload, { x: 0, y: 0 });
    expect(options.datasetSource.format).toBe("gpkg");
    expect(DATASET_FORMAT_LABEL[options.datasetSource.format]).toBe("GeoPackage");
    // The layers still load through their own ids.
    expect(options.datasetRefs).toEqual(["imported.parks_parks", "imported.parks_trails"]);
    expect(options.code).toContain('layers["parks"] = curio_load_data("imported.parks_parks")');
    expect(options.code).toContain('layers["trails"] = curio_load_data("imported.parks_trails")');
  });

  test("a GTFS feed drops as GTFS, though its tables were downloaded (#608)", () => {
    // A GTFS feed is always a Discovery download; it still says what it is
    // rather than its tables' Parquet, unlike #586's layer groups.
    const discoverySource = { sourceId: "source.curio.direct-url@1", sourceName: "Direct URL" };
    const feed = groupOf("gtfs.x1");
    const downloaded: DatasetPaletteGroup = {
      ...feed,
      members: feed.members.map((m) => ({ ...m, discoverySource })),
    };
    const payload = createOsmGroupDragPayload(downloaded);
    expect(payload.format).toBe("gtfs");
    expect(payload.uri).toBe("curio://gtfs/gtfs.x1");
    const options = buildDatasetLoaderNodeOptions(payload, { x: 0, y: 0 });
    expect(DATASET_FORMAT_LABEL[options.datasetSource.format]).toBe("GTFS");
    // Each table loads through its own id.
    expect(options.datasetRefs).toEqual(["imported.parks_parks", "imported.parks_trails"]);
  });

  test("an OSM group still drops as an OSM PBF dataset", () => {
    const payload = createOsmGroupDragPayload(groupOf("osm.x1"));
    expect(payload.format).toBe("osm");
    expect(payload.uri).toBe("curio://osm/osm.x1");
    const options = buildDatasetLoaderNodeOptions(payload, { x: 0, y: 0 });
    expect(DATASET_FORMAT_LABEL[options.datasetSource.format]).toBe("OSM PBF");
  });

  test("a group of NetCDF variables drops as NetCDF and loads each variable without returning it", () => {
    // One file per variable, as WRF writes them, under one netcdf. group id.
    const members = ["RAIN", "T2"].map((variable) =>
      makeDataset({
        id: `data.test.wrf-${variable.toLowerCase()}`,
        title: `WRF sample (${variable})`,
        origin: "hub",
        format: "netcdf",
        path: `/catalog/data.test.wrf-${variable.toLowerCase()}@1/data/${variable}.nc`,
        layerName: variable,
        groupId: "netcdf.wrf-sample",
      }),
    );
    const [group] = groupDatasetsForPalette(members) as [DatasetPaletteGroup];
    const payload = createOsmGroupDragPayload(group);
    expect(payload.format).toBe("netcdf");
    expect(payload.uri).toBe("curio://netcdf/netcdf.wrf-sample");

    const options = buildDatasetLoaderNodeOptions(payload, { x: 0, y: 0 });
    expect(DATASET_FORMAT_LABEL[options.datasetSource.format]).toBe("NetCDF");
    expect(options.datasetRefs).toEqual(["data.test.wrf-rain", "data.test.wrf-t2"]);
    expect(options.code).toContain('layers["RAIN"] = curio_load_data("data.test.wrf-rain")');
    expect(options.code).toContain('layers["T2"] = curio_load_data("data.test.wrf-t2")');
    // A node's output cannot carry an xarray Dataset, so the node returns nothing.
    expect(options.code).not.toContain("return");
  });
});

describe("a Discovery download's group drops as its layers' format (#586)", () => {
  // The layers of one OpenStreetMap download: GeoJSON, each carrying where it
  // came from, under an osm. group id as a .pbf import's are.
  const discoverySource = { sourceId: "source.openstreetmap.autark@1", sourceName: "OpenStreetMap" };
  const downloaded = (): DatasetPaletteGroup => {
    const members = [
      makeDataset({ id: "imported.xpoints", title: "Points of interest, Loop (points)", origin: "imported", format: "geojson", path: "/store/imported.xpoints@1/data/osm_points.geojson", layerName: "points", groupId: "osm.x1", discoverySource }),
      makeDataset({ id: "imported.xpolygons", title: "Points of interest, Loop (polygons)", origin: "imported", format: "geojson", path: "/store/imported.xpolygons@1/data/osm_polygons.geojson", layerName: "polygons", groupId: "osm.x1", discoverySource }),
    ];
    const [group] = groupDatasetsForPalette(members) as [DatasetPaletteGroup];
    return group;
  };

  test("its payload says GeoJSON and keeps the group's id and uri", () => {
    const payload = createOsmGroupDragPayload(downloaded());
    expect(payload.format).toBe("geojson");
    expect(payload.datasetId).toBe("osm.x1");
    expect(payload.uri).toBe("curio://osm/osm.x1");

    // The DATASET pill reads the format from the node's datasetSource.
    const options = buildDatasetLoaderNodeOptions(payload, { x: 0, y: 0 });
    expect(DATASET_FORMAT_LABEL[options.datasetSource.format]).toBe("GeoJSON");
    // The layers still load through their own ids, read as the GeoJSON they are (#579).
    expect(options.datasetRefs).toEqual(["imported.xpoints", "imported.xpolygons"]);
    expect(options.code).toContain('layers["points"] = curio_load_data("imported.xpoints")');

    // Only when every layer was downloaded: otherwise it is an OSM PBF import.
    const mixed = downloaded();
    mixed.members[1] = { ...mixed.members[1], discoverySource: null };
    expect(createOsmGroupDragPayload(mixed).format).toBe("osm");
  });
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

describe("a layer group card dragged from the Data Catalog drawer (#724)", () => {
  // The drawer lists a layer group as one card (`groupOsm`), shaped as the
  // backend builds it (`build_layer_group_item`): the group's id, title and
  // format, its layers' ids, and its layers.
  function layersOf(groupId: string, format: DatasetFormat): DatasetCatalogItem[] {
    return ["stops", "routes"].map((layer) =>
      makeDataset({
        id: `imported.x${layer}`,
        title: `google_transit (${layer})`,
        origin: "imported",
        format,
        uri: `curio://datasets/imported.x${layer}@1`,
        path: `/store/imported.x${layer}@1/data/${layer}.${format === "netcdf" ? "nc" : "parquet"}`,
        layerName: layer,
        groupId,
      }),
    );
  }

  function drawerCard(groupId: string, members: DatasetCatalogItem[]): DatasetCatalogItem {
    const kind = groupId.split(".")[0] as DatasetFormat;
    return {
      ...makeDataset({
        id: groupId,
        title: "google_transit",
        origin: "imported",
        format: kind,
        uri: `curio://${kind}/${groupId}`,
        path: null,
        groupLayerIds: members.map((member) => member.id),
      }),
      groupLayers: members.map(({ id, title, uri, path, format, layerName }) => ({
        id,
        title,
        uri,
        path,
        format,
        layerName,
      })),
    } as DatasetCatalogItem;
  }

  afterEach(() => endDatasetDrag());

  test.each([
    ["osm.x1", "parquet"],
    ["gpkg.x1", "parquet"],
    ["gtfs.x1", "parquet"],
    ["netcdf.x1", "netcdf"],
  ] as Array<[string, DatasetFormat]>)("a %s card drops as the palette's group row does", (groupId, format) => {
    const members = layersOf(groupId, format);
    // The drawer's drag start (`handleDatasetDragStart`), then the canvas drop.
    beginDatasetDrag(drawerCard(groupId, members));
    const payload = readDatasetDragPayload({ getData: () => "", types: [] } as unknown as DataTransfer);
    expect(payload).not.toBeNull();
    const fromDrawer = buildDatasetLoaderNodeOptions(payload!, { x: 0, y: 0 });

    const [group] = groupDatasetsForPalette(members) as [DatasetPaletteGroup];
    const fromPalette = buildDatasetLoaderNodeOptions(createOsmGroupDragPayload(group), { x: 0, y: 0 });
    expect(fromDrawer).toEqual(fromPalette);
    // The node loads and references each layer, never the group id.
    expect(datasetIdsInCode(fromDrawer.code)).toEqual(["imported.xstops", "imported.xroutes"]);
    expect(fromDrawer.datasetRefs).toEqual(["imported.xstops", "imported.xroutes"]);
    expect(fromDrawer.appliedDatasets[groupId]).toBeUndefined();
  });

  test("dropped onto a node, a card applies its layers, not the group id", () => {
    const card = drawerCard("gtfs.x1", layersOf("gtfs.x1", "parquet"));
    const result = applyDatasetToNodeData({ datasetRefs: ["existing"] }, "", createDatasetDragPayload(card));
    expect(result.data.datasetRefs).toEqual(["existing", "imported.xstops", "imported.xroutes"]);
    expect(result.data.appliedDatasets["gtfs.x1"]).toBeUndefined();
    expect(datasetIdsInCode(result.code)).toEqual(["imported.xstops", "imported.xroutes"]);
  });

  test("a card's loader, when the listing sent none, reads each layer", () => {
    const code = buildDatasetLoaderCode(drawerCard("gpkg.x1", layersOf("gpkg.x1", "parquet")));
    expect(datasetIdsInCode(code)).toEqual(["imported.xstops", "imported.xroutes"]);
    expect(code).toContain("return layers");
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
  expect(result.code).toContain('df = curio_load_data("file-123")');
});

test("mergeDatasetLoaderCode inserts loader before return in existing code", () => {
  const existingCode = "import pandas as pd\n\ndf = old_data\nreturn df";
  const merged = mergeDatasetLoaderCode(existingCode, dataset);
  // loader code should appear before the return
  const loaderPos = merged.indexOf('curio_load_data("file-123")');
  const returnPos = merged.indexOf("return df");
  expect(loaderPos).toBeGreaterThan(-1);
  expect(returnPos).toBeGreaterThan(loaderPos);
});

test("mergeDatasetLoaderCode is a no-op when the id-form loader is already there", () => {
  // Dropping the same dataset onto a node twice must not stack a second loader
  // block. The check matches the emitted curio_load_data("<id>") call, so it
  // keeps working now that snippets no longer embed a literal path.
  const once = mergeDatasetLoaderCode("", dataset);
  expect(once).toContain('curio_load_data("file-123")');

  const twice = mergeDatasetLoaderCode(once, dataset);
  expect(twice).toBe(once.trim());

  const calls = once.split('curio_load_data("file-123")').length - 1;
  expect(twice.split('curio_load_data("file-123")').length - 1).toBe(calls);
});

test("mergeDatasetLoaderCode still recognises a legacy literal-path loader", () => {
  // Nodes generated before id-based resolution embed the absolute path; those
  // must not gain a duplicate block either.
  const legacy = [
    "import pandas as pd",
    "",
    `dataset_path = "${dataset.path}"`,
    "df = pd.read_csv(dataset_path)",
    "return df",
  ].join("\n");

  expect(mergeDatasetLoaderCode(legacy, dataset)).toBe(legacy);
});

test("mergeDatasetLoaderCode on empty code includes return", () => {
  const merged = mergeDatasetLoaderCode("", dataset);
  expect(merged).toContain('df = curio_load_data("file-123")');
  expect(merged).toContain("return df");
});


test("mergeDatasetLoaderCode indents the loader block to match an indented return (B4)", () => {
  const existing = ["if cond:", "    x = compute()", "    return x"].join("\n");
  const merged = mergeDatasetLoaderCode(existing, dataset);
  // No line of the inserted loader may sit at column 0 between the indented
  // code and the indented return — that would be a Python IndentationError.
  expect(merged).toContain('    df = curio_load_data("file-123")');
  expect(merged).toContain("    return df");
  expect(merged).not.toMatch(/\ndf = curio_load_data/);
});

test("mergeDatasetLoaderCode/buildDatasetLoaderCode escape backslashes and quotes in the path (B11)", () => {
  // An UNSAFE id (quote inside) must never reach the generated source as a
  // curio_data_path call — the snippet falls back to the literal path,
  // which must stay a valid Python string literal: backslashes escaped, so no
  // raw `\U`/`\b` escape and the literal isn't terminated early.
  const winDataset = makeDataset({
    id: 'evil"id',
    format: "csv",
    path: "C:\\Users\\me\\data\\blocks.csv",
    uri: "file:///c/blocks.csv",
  });
  const code = buildDatasetLoaderCode(winDataset);
  expect(code).not.toContain("curio_");
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
