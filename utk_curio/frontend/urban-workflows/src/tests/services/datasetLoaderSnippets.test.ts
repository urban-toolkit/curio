/**
 * Every DatasetFormat must generate a loader that actually loads something.
 *
 * `snippetForFormat` ends in a fallthrough that emits `dataset_path = ...` and
 * nothing else, with `returnVariable: null`. A format that reaches it produces a
 * Data Loading node which assigns a path, reads no file and returns no value -
 * no error, just a node that silently does nothing. Since the format union and
 * the switch are maintained separately, that is one forgotten branch away.
 *
 * The Data Catalog migration made this reachable in a new way: the examples now
 * ship `parquet` and `geotiff` datasets, so two formats that previously had no
 * committed data behind them are on the critical path.
 */
import {
  buildDatasetLoaderCode,
  getDatasetLoaderSnippet,
} from "../../services/datasetCatalog/datasetLoaderSnippets";
import type { DatasetFormat } from "../../services/datasetCatalog/datasetCatalogTypes";

/**
 * The call each format's loader makes when the dataset has an id: the sandbox
 * reads the dataset by its format. Keyed by the full `DatasetFormat` union, so
 * adding a format to the type without adding it here is a TypeScript error
 * rather than a silently uncovered case.
 */
const READERS: Record<DatasetFormat, string | null> = {
  csv: "curio_load_data",
  geojson: "curio_load_data",
  shp: "curio_load_data",
  json: "curio_load_data",
  parquet: "curio_load_data",
  geotiff: "curio_load_data",
  bundle: "curio_load_data",
  // `osm` has no snippetForFormat branch by design: an OSM group is loaded
  // through osmGroupLoaderSnippet, which needs the group's layer list rather
  // than a single path. Asserted explicitly below rather than dropped, so the
  // exception stays visible.
  osm: null,
  // Same exception, same reason: a GeoPackage group is a set of per-layer
  // parquet datasets, so there is no single path to generate for. Each member
  // is an ordinary `parquet` dataset and takes that branch.
  gpkg: null,
  // A collection's index, with a readable path for every file, which only the
  // sandbox's `curio_load_collection` can resolve.
  collection: "curio_load_collection",
};

/** The reader an id-less loader (a legacy literal path) spells out per format. */
const LITERAL_READERS: Partial<Record<DatasetFormat, string>> = {
  csv: "pd.read_csv",
  geojson: "gpd.read_file",
  shp: "gpd.read_file",
  json: "json.loads",
  parquet: "gpd.read_parquet",
  geotiff: "rasterio.open",
  bundle: "_curio_load_bundle",
  collection: "pd.read_parquet",
};

function snippetFor(format: DatasetFormat) {
  return getDatasetLoaderSnippet({
    id: "data.utk.example",
    format,
    path: "/tmp/example-file",
  } as never);
}

describe("snippetForFormat", () => {
  const covered = (Object.keys(READERS) as DatasetFormat[]).filter(
    (format) => READERS[format] !== null,
  );

  it.each(covered)("emits a real reader for %s", (format) => {
    const snippet = snippetFor(format);
    expect(snippet.code).toContain(READERS[format] as string);
    // The fallthrough's tell: a path and no return value.
    expect(snippet.returnVariable).toBeTruthy();
  });

  it.each(covered)("emits a real reader for %s without an id", (format) => {
    const snippet = getDatasetLoaderSnippet({ format, path: "/tmp/example-file" } as never);
    expect(snippet.code).toContain(LITERAL_READERS[format] as string);
    expect(snippet.returnVariable).toBeTruthy();
  });

  it.each(covered)("addresses %s by dataset id, not by path", (format) => {
    const snippet = snippetFor(format);
    const call = format === "collection" ? "curio_load_collection" : "curio_load_data";
    expect(snippet.code).toContain(`${call}("data.utk.example")`);
    // A machine-specific absolute path in generated code is what the portable
    // id call exists to avoid; it must not appear when an id is available.
    expect(snippet.code).not.toContain("/tmp/example-file");
  });

  it("falls back to the literal path when the dataset has no usable id", () => {
    const snippet = getDatasetLoaderSnippet({
      format: "csv",
      path: "/tmp/example-file",
    } as never);
    expect(snippet.code).toContain('"/tmp/example-file"');
    expect(snippet.code).not.toContain("curio_");
  });

  it("routes osm through the group loader instead of a single-path branch", () => {
    // Documents the one deliberate gap in the switch. If a future change gives
    // `osm` its own branch, this expectation is what will notice.
    const snippet = snippetFor("osm");
    expect(snippet.returnVariable).toBeNull();
  });

  it("builds runnable node code: one load call and a return", () => {
    const code = buildDatasetLoaderCode({
      id: "data.cityofchicago.green-roofs",
      format: "csv",
      path: "/tmp/green-roofs.csv",
    } as never);
    expect(code).toBe('df = curio_load_data("data.cityofchicago.green-roofs")\nreturn df');
  });

  it("loads a collection the way the backend's generator does", () => {
    const code = buildDatasetLoaderCode({
      id: "imported.xabc@1",
      format: "collection",
      path: "/tmp/index.parquet",
    } as never);
    expect(code).toBe('collection = curio_load_collection("imported.xabc@1")\nreturn collection');
  });

  it("names a Discovery download's Autark layer the way the backend's generator does", () => {
    const osm = {
      id: "imported.osm-buildings@1",
      format: "geojson",
      path: "/tmp/osm_buildings.geojson",
      layerName: "buildings",
      discoverySource: { sourceId: "source.osm.openstreetmap@1", resourceId: "buildings" },
    };
    // With an id the layer travels to the sandbox with the dataset's format
    // (the backend's execution_format), so the code is the one load call.
    expect(buildDatasetLoaderCode(osm as never)).toBe(
      'gdf = curio_load_data("imported.osm-buildings@1")\nreturn gdf',
    );
    // Without an id the literal-path loader names the layer itself.
    const idless = { ...osm, id: undefined };
    expect(buildDatasetLoaderCode(idless as never)).toContain('gdf.metadata = {"layerType": "buildings"}');
    // A GeoPackage layer called "buildings" is not a Discovery download, and a
    // Discovery layer that is not one of Autark's is not typed.
    for (const other of [{ ...idless, discoverySource: null }, { ...idless, layerName: "map-features" }]) {
      expect(buildDatasetLoaderCode(other as never)).not.toContain("gdf.metadata");
    }
  });

  it("names the Autark layer of a Discovery GeoParquet download too", () => {
    const overture = {
      id: "imported.overture-buildings@1",
      format: "parquet",
      path: "/tmp/overture_buildings.parquet",
      layerName: "buildings",
      discoverySource: { sourceId: "source.overture.maps@1", resourceId: "buildings" },
    };
    // With an id the layer travels to the sandbox with the dataset's format,
    // so the code is the one load call.
    expect(buildDatasetLoaderCode(overture as never)).toBe(
      'df = curio_load_data("imported.overture-buildings@1")\nreturn df',
    );
    // Without an id the literal-path loader names the layer itself.
    const idless = { ...overture, id: undefined };
    const code = buildDatasetLoaderCode(idless as never);
    expect(code).toContain("df = gpd.read_parquet(dataset_path)");
    expect(code).toContain('    df = pd.read_parquet(dataset_path)\ndf.metadata = {"layerType": "buildings"}\n');
    expect(code.trimEnd().endsWith("return df")).toBe(true);
    for (const other of [{ ...idless, discoverySource: null }, { ...idless, layerName: "places" }]) {
      expect(buildDatasetLoaderCode(other as never)).not.toContain("df.metadata");
    }
  });

  it("prefers a backend-supplied snippet over the local generator", () => {
    // Hub catalog rows always carry the backend's `loaderSnippet`, which is the
    // authoritative one.
    const snippet = getDatasetLoaderSnippet({
      id: "data.utk.example",
      format: "parquet",
      path: "/tmp/example.parquet",
      loaderSnippet: {
        language: "python",
        imports: ["import pandas as pd"],
        pathVariable: "dataset_path",
        code: "dataset_path = 'from-backend'",
        returnVariable: "df",
      },
    } as never);
    expect(snippet.code).toBe("dataset_path = 'from-backend'");
  });
});
