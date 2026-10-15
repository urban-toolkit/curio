/**
 * A loader's type and source are read from its code
 * (plans/data-loading-expressive-preview-memo.md, section 3.1).
 */
import { buildDatasetLoaderCode } from "../../services/datasetCatalog/datasetLoaderSnippets";
import type { DatasetFormat } from "../../services/datasetCatalog/datasetCatalogTypes";
import {
  artifactDataType,
  detectLoaderProfile,
  formatOfPath,
  hasLoaderCode,
  LOADER_SCAN_CHARS,
  needsTypeProbe,
  shortenPath,
  stripPythonComments,
  urlHost,
} from "../../services/datasetCatalog/loaderProfile";

const catalogItem = (id: string, format: DatasetFormat) =>
  ({ id, datasetId: id, title: `Title of ${id}`, format, origin: "imported" }) as any;

describe("catalog loaders, as the Data Catalog writes them", () => {
  // Every format the catalog generates a loader for: the generator and the
  // detector cannot drift apart without this failing.
  const formats: DatasetFormat[] = ["csv", "geojson", "parquet", "geotiff", "netcdf", "json", "shp", "gpkg"];

  it.each(formats)("a %s dataset reads as that format, from the Data Catalog", (format) => {
    const id = `data.test.${format}-set`;
    const code = buildDatasetLoaderCode(catalogItem(id, format));
    const profile = detectLoaderProfile(code, {
      lookupDataset: (lookupId) => (lookupId === id ? { title: "Chicago community areas", format } : undefined),
    });
    expect(profile.sources[0]).toMatchObject({ kind: "catalog", address: id, datasetId: id, title: "Chicago community areas" });
    expect(profile.dataType).toBe(format);
    expect(profile.typeEvidence).toBe("catalog");
  });

  it("names the dataset by its id while nothing knows it, and claims no type", () => {
    const code = buildDatasetLoaderCode(catalogItem("data.utk.chicago-community-areas", "geojson"));
    const profile = detectLoaderProfile(code);
    expect(profile.sources[0]).toMatchObject({ kind: "catalog", address: "data.utk.chicago-community-areas" });
    expect(profile.sources[0].title).toBeUndefined();
    expect(profile.dataType).toBe("unknown");
  });

  it("does not count a catalog id as a file, even when it ends like one", () => {
    const profile = detectLoaderProfile('gdf = curio_load_data("data.test.rivers.json")');
    expect(profile.sources).toHaveLength(1);
    expect(profile.sources[0].kind).toBe("catalog");
  });
});

describe("files on disk", () => {
  it("reads the file name and the format from a reader's literal path", () => {
    const profile = detectLoaderProfile('import pandas as pd\ndf = pd.read_csv("/data/chicago/taxi_trips_2024.csv")\nreturn df');
    expect(profile.sources).toEqual([{ kind: "disk", address: "/data/chicago/taxi_trips_2024.csv", dataType: "csv" }]);
    expect(profile.dataType).toBe("csv");
  });

  it.each([
    ["rasterio.open('lst/niteroi.tif')", "geotiff"],
    ["xr.open_dataset('wrf_t2_2023.nc')", "netcdf"],
    ["gpd.read_file('parcels.gpkg')", "gpkg"],
    ["gpd.read_file('roads.shp')", "shp"],
    ["pd.read_parquet('permits.parquet')", "parquet"],
    ["path = 'chicago_loop.osm.pbf'", "osm"],
  ])("%s reads as %s", (line, format) => {
    expect(detectLoaderProfile(line).dataType).toBe(format);
  });

  it("keeps a path with no extension as a file, typed by its reader", () => {
    const profile = detectLoaderProfile('df = pd.read_csv("exports/latest")');
    expect(profile.sources[0]).toMatchObject({ kind: "disk", address: "exports/latest" });
    expect(profile.dataType).toBe("csv");
  });

  it("keeps the literal part of a path built at run time", () => {
    const profile = detectLoaderProfile("import os\ndf = pd.read_csv(os.path.join(base, f'{city}.csv'))");
    expect(profile.sources[0]).toEqual({ kind: "disk", address: "{city}.csv", dataType: "csv" });
  });

  it("says the path is built in code when the reader gets no literal at all", () => {
    const profile = detectLoaderProfile("df = pd.read_csv(os.path.join(base, name))");
    expect(profile.sources[0]).toEqual({ kind: "disk", address: "" });
    expect(profile.dataType).toBe("csv");
  });
});

describe("external APIs", () => {
  it("shows only the host, never the path, the query or credentials", () => {
    const code =
      'import requests\nr = requests.get("https://user:pw@data.cityofchicago.org/resource/spqx-js37.json?$$app_token=SECRET&key=abc")\nreturn pd.DataFrame(r.json())';
    const profile = detectLoaderProfile(code);
    expect(profile.sources).toEqual([{ kind: "api", address: "data.cityofchicago.org", dataType: "json" }]);
    expect(JSON.stringify(profile)).not.toMatch(/SECRET|abc|pw|resource/);
  });

  it("reads the portal of a Socrata client", () => {
    const profile = detectLoaderProfile('client = Socrata("data.cityofchicago.org", None)\nrows = client.get("x")');
    expect(profile.sources[0]).toEqual({ kind: "api", address: "data.cityofchicago.org" });
  });

  it("takes the type from what the API returns, not from the API", () => {
    const profile = detectLoaderProfile('rows = requests.get(url).json()\nreturn pd.DataFrame(rows)');
    expect(profile.sources[0]).toEqual({ kind: "api", address: "" });
    expect(profile.dataType).toBe("json");
  });

  it("notes a saved connection key, which keeps the loader from a background run", () => {
    const profile = detectLoaderProfile('key = curio_secret("census")\nr = requests.get("https://api.census.gov/data", params={"key": key})');
    expect(profile.usesSecret).toBe(true);
    expect(profile.sources[0].address).toBe("api.census.gov");
    expect(needsTypeProbe(profile)).toBe(false);
  });

  it("treats a remote file read by pandas as an API", () => {
    const profile = detectLoaderProfile('df = pd.read_csv("https://example.org/files/stops.csv")');
    expect(profile.sources[0]).toEqual({ kind: "api", address: "example.org", dataType: "csv" });
  });
});

describe("data defined in code", () => {
  it.each([
    "df = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})\nreturn df",
    "gdf = gpd.GeoDataFrame([{'name': 'x'}], geometry=[Point(0, 0)])",
    "return [{'a': 1}]",
  ])("%s is defined in code", (code) => {
    expect(detectLoaderProfile(code).sources[0].kind).toBe("inline");
  });

  it("does not call a frame built from a read file 'defined in code'", () => {
    const profile = detectLoaderProfile('rows = pd.read_csv("a.csv")\ndf = pd.DataFrame({"x": rows.x})');
    expect(profile.sources.map((s) => s.kind)).toEqual(["disk"]);
  });
});

describe("the rest", () => {
  it("is empty for empty code or code that is only comments", () => {
    expect(detectLoaderProfile("").sources).toEqual([]);
    expect(detectLoaderProfile("   \n# load something here\n").sources).toEqual([]);
    expect(hasLoaderCode("# nothing yet")).toBe(false);
    expect(hasLoaderCode('x = "# not a comment"')).toBe(true);
  });

  it("calls a loader it cannot read a custom loader, and claims no type", () => {
    const profile = detectLoaderProfile("x = build_everything()\nreturn x");
    expect(profile.sources).toEqual([{ kind: "unknown", address: "" }]);
    expect(profile.dataType).toBe("unknown");
    expect(profile.typeEvidence).toBe("none");
  });

  it("ignores commented-out sources", () => {
    const profile = detectLoaderProfile('# df = pd.read_csv("old.csv")\ndf = pd.read_parquet("new.parquet")');
    expect(profile.sources.map((s) => s.address)).toEqual(["new.parquet"]);
  });

  it("lists several sources in the order the code reads them, and counts the other types", () => {
    const code = 'a = curio_load_data("data.x.areas")\nb = pd.read_csv("counts.csv")';
    const profile = detectLoaderProfile(code, { lookupDataset: () => ({ title: "Areas", format: "geojson" }) });
    expect(profile.sources.map((s) => s.kind)).toEqual(["catalog", "disk"]);
    expect(profile.dataType).toBe("geojson");
    expect(profile.extraTypes).toBe(1);
  });

  it("reads only the head of a huge loader, and never probes it", () => {
    const code = "x = 1\n" + "#".repeat(LOADER_SCAN_CHARS) + '\ndf = pd.read_csv("late.csv")';
    const profile = detectLoaderProfile(code);
    expect(profile.truncated).toBe(true);
    expect(profile.sources[0].kind).toBe("unknown");
    expect(needsTypeProbe(profile)).toBe(false);
  });
});

describe("evidence beyond the code, strongest first", () => {
  const silent = "x = build_everything()\nreturn x";

  it("takes this tab's last run before the journal, the ports and a probe", () => {
    const profile = detectLoaderProfile(silent, {
      runDataType: "geodataframe",
      journalDataType: "raster",
      portTypes: ["DATAFRAME"],
      probeDataType: "dataframe",
    });
    expect(profile).toMatchObject({ dataType: "geodataframe", typeEvidence: "run" });
  });

  it("falls to the journal, then to one declared port type, then to a probe", () => {
    expect(detectLoaderProfile(silent, { journalDataType: "raster", portTypes: ["DATAFRAME"] })).toMatchObject({
      dataType: "raster",
      typeEvidence: "journal",
    });
    expect(detectLoaderProfile(silent, { portTypes: ["RASTER"], probeDataType: "dataframe" })).toMatchObject({
      dataType: "raster",
      typeEvidence: "ports",
    });
    expect(detectLoaderProfile(silent, { portTypes: ["RASTER", "DATAFRAME"], probeDataType: "dataframe" })).toMatchObject({
      dataType: "dataframe",
      typeEvidence: "probe",
    });
  });

  it("lets what the code reads outrank a stale run of other code", () => {
    expect(detectLoaderProfile('df = pd.read_csv("a.csv")', { runDataType: "geodataframe" }).dataType).toBe("csv");
  });

  it("ignores run types that say nothing about a loader", () => {
    expect(detectLoaderProfile(silent, { runDataType: "str" }).dataType).toBe("unknown");
    expect(detectLoaderProfile(silent, { runDataType: "outputs" }).dataType).toBe("unknown");
  });

  it("asks for a probe only when every piece of evidence is silent", () => {
    expect(needsTypeProbe(detectLoaderProfile(silent))).toBe(true);
    expect(needsTypeProbe(detectLoaderProfile(silent, { journalDataType: "dataframe" }))).toBe(false);
    expect(needsTypeProbe(detectLoaderProfile(""))).toBe(false);
  });
});

describe("helpers", () => {
  it("urlHost keeps only the host", () => {
    expect(urlHost("https://u:p@Data.Example.org:8080/a/b?c=d#e")).toBe("data.example.org");
    expect(urlHost("not a url")).toBeNull();
  });

  it("formatOfPath ignores the query", () => {
    expect(formatOfPath("https://x.org/a.geojson?limit=5")).toBe("geojson");
    expect(formatOfPath("archive.zip")).toBeUndefined();
  });

  it("stripPythonComments keeps a # inside a string", () => {
    expect(stripPythonComments('a = "x#y"  # note')).toBe('a = "x#y"  ');
  });

  it("shortenPath elides the middle and keeps the file name", () => {
    const short = shortenPath("/Users/someone/projects/curio/datasets/chicago/very/deep/taxi_trips_2024.csv", 40);
    expect(short.endsWith("/taxi_trips_2024.csv")).toBe(true);
    expect(short.length).toBeLessThanOrEqual(40);
  });

  it("artifactDataType reads an artifact object or its JSON", () => {
    expect(artifactDataType({ path: "a", dataType: "raster" })).toBe("raster");
    expect(artifactDataType('{"path":"a","dataType":"dataframe"}')).toBe("dataframe");
    expect(artifactDataType("Saved to file: a")).toBeNull();
    expect(artifactDataType(null)).toBeNull();
  });
});
