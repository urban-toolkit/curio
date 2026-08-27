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
 * The reader each format must reach for. Keyed by the full `DatasetFormat`
 * union, so adding a format to the type without adding it here is a TypeScript
 * error rather than a silently uncovered case.
 */
const READERS: Record<DatasetFormat, string | null> = {
  csv: "pd.read_csv",
  geojson: "gpd.read_file",
  shp: "gpd.read_file",
  json: "json.loads",
  parquet: "gpd.read_parquet",
  geotiff: "rasterio.open",
  bundle: "_curio_load_bundle",
  // `osm` has no snippetForFormat branch by design: an OSM group is loaded
  // through osmGroupLoaderSnippet, which needs the group's layer list rather
  // than a single path. Asserted explicitly below rather than dropped, so the
  // exception stays visible.
  osm: null,
};

function snippetFor(format: DatasetFormat) {
  return getDatasetLoaderSnippet({
    id: "data.urbanlab.example",
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

  it.each(covered)("addresses %s by dataset id, not by path", (format) => {
    const snippet = snippetFor(format);
    expect(snippet.code).toContain(
      'curio_dataset_path("data.urbanlab.example")',
    );
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
    expect(snippet.code).not.toContain("curio_dataset_path");
  });

  it("routes osm through the group loader instead of a single-path branch", () => {
    // Documents the one deliberate gap in the switch. If a future change gives
    // `osm` its own branch, this expectation is what will notice.
    const snippet = snippetFor("osm");
    expect(snippet.returnVariable).toBeNull();
  });

  it("builds runnable node code with imports and a return", () => {
    const code = buildDatasetLoaderCode({
      id: "data.cityofchicago.green-roofs",
      format: "csv",
      path: "/tmp/green-roofs.csv",
    } as never);
    expect(code).toContain("import pandas as pd");
    expect(code).toContain(
      'dataset_path = curio_dataset_path("data.cityofchicago.green-roofs")',
    );
    expect(code).toContain("df = pd.read_csv(dataset_path)");
    expect(code.trimEnd().endsWith("return df")).toBe(true);
  });

  it("prefers a backend-supplied snippet over the local generator", () => {
    // Hub catalog rows always carry the backend's `loaderSnippet`, which is the
    // authoritative one (the Python generator restores parquet's JSON-encoded
    // object columns from the .decode.json sidecar; this TS twin does not).
    const snippet = getDatasetLoaderSnippet({
      id: "data.urbanlab.example",
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
