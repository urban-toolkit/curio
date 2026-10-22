/**
 * What a chip's hover shows of an input (readInputPreview): the one
 * `/get-preview` read the header already makes, kept as the kind of value the
 * input holds, its columns and their dtypes, its first rows, how many rows it
 * has, and, for a GeoDataFrame, its coordinate system and geometry type. The
 * header's lists are a view of the same read (readInputColumns). And what the
 * node that feeds each input says of its output: not run, stale or failed.
 */
const mockFetchPreviewData = jest.fn();
jest.mock("../../services/api", () => ({
  fetchData: jest.fn(),
  fetchPreviewData: (...args: any[]) => mockFetchPreviewData(...args),
}));

import {
  inputSourcesFor,
  readInputColumns,
  readInputPreview,
  type PreviewTable,
} from "../../utils/references/inputScope";
import { POOL_INPUT, SUMMARY_REF, SUMMARY_TUPLE } from "../_support/chipPreviewFixtures";

const fc = (type: string, rows: Array<Record<string, unknown>>) => ({
  type: "FeatureCollection",
  features: rows.map((properties) => ({ type: "Feature", geometry: { type, coordinates: [] }, properties })),
});

/** The table *preview* holds, when it holds one frame. */
function tableOf(preview: Awaited<ReturnType<typeof readInputPreview>>): PreviewTable {
  expect(preview.kind).toBe("frame");
  return (preview as { kind: "frame"; table: PreviewTable }).table;
}

beforeEach(() => mockFetchPreviewData.mockReset());

describe("readInputPreview", () => {
  test("example 26's Summarize: a tuple of two tables, each with its columns, dtypes, rows and total", async () => {
    mockFetchPreviewData.mockResolvedValue(SUMMARY_TUPLE);
    const preview = await readInputPreview(SUMMARY_REF);
    // One read, the one the header makes.
    expect(mockFetchPreviewData).toHaveBeenCalledTimes(1);
    expect(mockFetchPreviewData).toHaveBeenCalledWith("several-summary-artifact");
    expect(preview.kind).toBe("tuple");
    if (preview.kind !== "tuple") return;
    expect(preview.size).toBe(2);
    expect(preview.parts).toHaveLength(2);
    const [means, peaks] = preview.parts.map((part) => (part as { table: PreviewTable }).table);
    expect(means).toMatchObject({
      frameType: "dataframe",
      columns: ["sensor", "pm25_mean"],
      dtypes: { sensor: "str", pm25_mean: "float64" },
      rows: [
        { sensor: "sensor_A", pm25_mean: 8.041667 },
        { sensor: "sensor_B", pm25_mean: 10.041667 },
        { sensor: "sensor_C", pm25_mean: 12.041667 },
      ],
      totalRows: 3,
      readRows: 3,
    });
    expect(peaks).toMatchObject({
      columns: ["sensor", "pm25_peak"],
      dtypes: { sensor: "str", pm25_peak: "float64" },
      rows: [
        { sensor: "sensor_A", pm25_peak: 11 },
        { sensor: "sensor_B", pm25_peak: 13 },
        { sensor: "sensor_C", pm25_peak: 15 },
      ],
      totalRows: 3,
    });
  });

  test("a tuple holding a table and a number keeps the number as a value of its own", async () => {
    mockFetchPreviewData.mockResolvedValue({
      dataType: "outputs",
      data: [SUMMARY_TUPLE.data[0], { dataType: "int", data: 3 }],
    });
    const preview = await readInputPreview({ path: "art", dataType: "outputs" });
    expect(preview.kind).toBe("tuple");
    if (preview.kind !== "tuple") return;
    expect(preview.size).toBe(2);
    expect((preview.parts[0] as { table: PreviewTable }).table.columns).toEqual(["sensor", "pm25_mean"]);
    expect(preview.parts[1]).toEqual({ value: 3, dataType: "int" });
  });

  test("interaction-vega's pool: inline rows, no fetch, the first 5 kept with the total, the CRS and the geometry type", async () => {
    const table = tableOf(await readInputPreview(POOL_INPUT));
    expect(mockFetchPreviewData).not.toHaveBeenCalled();
    expect(table).toMatchObject({
      frameType: "geodataframe",
      // The pool's own flag on each row is no column of the table it hands on.
      columns: ["geometry", "accessibility", "neighborhood_name"],
      dtypes: { geometry: "geometry", accessibility: "float64", neighborhood_name: "str" },
      totalRows: 79,
      readRows: 79,
      crs: "EPSG:3395",
      geometryType: "MultiPolygon",
    });
    // A geometry is its type.
    expect(table.rows).toEqual([
      { geometry: "MultiPolygon", accessibility: 0.3124, neighborhood_name: "Adams" },
      { geometry: "MultiPolygon", accessibility: 0.3807, neighborhood_name: "Wallingford" },
      { geometry: "MultiPolygon", accessibility: 0.3982, neighborhood_name: "Green Lake" },
      { geometry: "MultiPolygon", accessibility: 0.0194, neighborhood_name: "Sand Point" },
      { geometry: "MultiPolygon", accessibility: 0.711, neighborhood_name: "Windermere" },
    ]);
    // Each column's summary covers every row read: a number's range, text's distinct values.
    expect(table.summaries.accessibility).toEqual({ empty: 0, min: 0, max: 1 });
    expect(table.summaries.neighborhood_name.empty).toBe(0);
    expect(table.summaries.neighborhood_name.distinct).toHaveLength(79);
  });

  test("a table cut to its 100-row preview says how many rows it has, and its summaries cover the 100 read", async () => {
    const zips = Array.from({ length: 100 }, (_, i) => String(60601 + (i % 10)));
    const pop = Array.from({ length: 100 }, (_, i) => (i < 2 ? null : i * 1.5));
    mockFetchPreviewData.mockResolvedValue({
      dataType: "dataframe",
      data: { zip: zips, pop },
      schema: { zip: "str", pop: "float64" },
      preview: true,
      previewRows: 100,
      totalRows: 2500,
    });
    const table = tableOf(await readInputPreview({ path: "art", dataType: "dataframe" }));
    expect(table).toMatchObject({ frameType: "dataframe", totalRows: 2500, readRows: 100 });
    expect(table.rows).toHaveLength(5);
    expect(table.rows[0]).toEqual({ zip: "60601", pop: null });
    expect(table.summaries.pop).toEqual({ empty: 2, min: 3, max: 148.5 });
    expect(table.summaries.zip.distinct).toHaveLength(10);
    expect(table.crs).toBeUndefined();
  });

  test("an input carrying named layers: each layer's columns, rows, feature count and geometry type", async () => {
    mockFetchPreviewData.mockResolvedValue({
      dataType: "list",
      data: [
        { dataType: "dict", data: { name: "table_osm_roads", type: "roads",
          geojson: fc("LineString", [{ highway: "primary" }, { highway: "residential" }, { highway: "primary" }, { highway: null }]) } },
        { dataType: "dict", data: { name: "table_osm_buildings", type: "buildings",
          geojson: fc("Polygon", [{ height: 9 }, { height: 12.5 }]) } },
      ],
    });
    const preview = await readInputPreview({ path: "art", dataType: "list" });
    expect(preview.kind).toBe("layers");
    if (preview.kind !== "layers") return;
    expect(preview.layers.map((layer) => layer.name)).toEqual(["table_osm_roads", "table_osm_buildings"]);
    expect(preview.layers[0].table).toMatchObject({
      frameType: "geodataframe",
      columns: ["highway"],
      totalRows: 4,
      geometryType: "LineString",
      rows: [{ highway: "primary" }, { highway: "residential" }, { highway: "primary" }, { highway: null }],
    });
    expect(preview.layers[0].table.summaries.highway).toEqual({ empty: 1, distinct: ["primary", "residential"] });
    expect(preview.layers[1].table).toMatchObject({ columns: ["height"], totalRows: 2, geometryType: "Polygon" });
  });

  test("a value shows itself, from one read", async () => {
    mockFetchPreviewData.mockResolvedValue({ dataType: "float", data: 2.5 });
    expect(await readInputPreview({ path: "v", dataType: "float" })).toEqual({ kind: "value", dataType: "float", value: 2.5 });
    expect(mockFetchPreviewData).toHaveBeenCalledTimes(1);
    // A value inline needs no read.
    mockFetchPreviewData.mockReset();
    expect(await readInputPreview({ dataType: "str", data: "winter" })).toEqual({ kind: "value", dataType: "str", value: "winter" });
    expect(mockFetchPreviewData).not.toHaveBeenCalled();
  });

  test("a raster is not read", async () => {
    expect(await readInputPreview({ path: "r", dataType: "raster" })).toEqual({ kind: "raster" });
    expect(mockFetchPreviewData).not.toHaveBeenCalled();
  });

  test("a JSON list or dict shows its first items", async () => {
    mockFetchPreviewData.mockResolvedValue({
      dataType: "list",
      data: Array.from({ length: 12 }, (_, i) => ({ dataType: "int", data: i * 10 })),
    });
    expect(await readInputPreview({ path: "l", dataType: "list" })).toEqual({
      kind: "json",
      shape: "list",
      total: 12,
      items: [0, 10, 20, 30, 40].map((value, i) => ({ key: String(i), value })),
    });
    mockFetchPreviewData.mockResolvedValue({ dataType: "dict", data: { season: "winter", hours: 6 } });
    expect(await readInputPreview({ path: "d", dataType: "dict" })).toEqual({
      kind: "json",
      shape: "dict",
      total: 2,
      items: [{ key: "season", value: "winter" }, { key: "hours", value: 6 }],
    });
  });

  test("nothing has arrived: empty, and nothing is read", async () => {
    expect(await readInputPreview("")).toEqual({ kind: "empty" });
    expect(await readInputPreview(null)).toEqual({ kind: "empty" });
    expect(mockFetchPreviewData).not.toHaveBeenCalled();
  });

  test("a read that fails throws, as the header's read does, so its caller can say so", async () => {
    mockFetchPreviewData.mockRejectedValue(new Error("Failed to fetch preview"));
    await expect(readInputPreview({ path: "gone", dataType: "dataframe" })).rejects.toThrow("Failed to fetch preview");
  });
});

describe("readInputColumns, a view of the same read", () => {
  test("a table: its columns and dtypes, as before", async () => {
    mockFetchPreviewData.mockResolvedValue({
      dataType: "dataframe", data: { zip: ["a"], pop: [1] }, schema: { zip: "str", pop: "int64" },
    });
    expect(await readInputColumns({ path: "art", dataType: "dataframe" }))
      .toEqual({ columns: ["zip", "pop"], dtypes: { zip: "str", pop: "int64" } });
    expect(mockFetchPreviewData).toHaveBeenCalledTimes(1);
  });

  test("an inline GeoDataFrame: its columns from its schema", async () => {
    expect(await readInputColumns(POOL_INPUT)).toEqual({
      columns: ["geometry", "accessibility", "neighborhood_name"],
      dtypes: { geometry: "geometry", accessibility: "float64", neighborhood_name: "str" },
    });
  });

  test("example 26's tuple holds 2 values", async () => {
    mockFetchPreviewData.mockResolvedValue(SUMMARY_TUPLE);
    expect(await readInputColumns(SUMMARY_REF)).toEqual({ columns: [], dtypes: {}, layers: [], tuple: 2 });
  });

  test("a value, a raster and a JSON list have no columns", async () => {
    mockFetchPreviewData.mockResolvedValue({ dataType: "int", data: 3 });
    expect(await readInputColumns({ path: "v", dataType: "int" })).toEqual({ columns: [], dtypes: {} });
    expect(await readInputColumns({ path: "r", dataType: "raster" })).toEqual({ columns: [], dtypes: {} });
    mockFetchPreviewData.mockResolvedValue({ dataType: "list", data: [{ dataType: "int", data: 1 }] });
    expect(await readInputColumns({ path: "l", dataType: "list" })).toEqual({ columns: [], dtypes: {} });
  });
});

describe("inputSourcesFor: the node that feeds each input, and its output's state", () => {
  const edges = [
    { id: "e0", source: "stations", target: "join", sourceHandle: "out", targetHandle: "in" },
    { id: "e1", source: "summary", target: "join", sourceHandle: "out", targetHandle: "in_1" },
    { id: "e2", source: "zips", target: "join", sourceHandle: "out", targetHandle: "in_2" },
  ];
  const nodes = [
    { id: "stations", data: { title: "Stations", nodeType: "loading" } },
    { id: "summary", data: { title: "Summarize", nodeType: "python" } },
    { id: "zips", data: { nodeType: "pool" } },
  ];
  const typeOf = (data: any) => ({ loading: "Data Loading", python: "Python Computation", pool: "Data Pool" } as any)[data.nodeType];

  test("its title, its type when that differs, and whether it ran", () => {
    const values: Record<number, unknown> = { 0: { path: "a" }, 1: { path: "b" }, 2: { path: "c" } };
    const sources = inputSourcesFor("join", edges, nodes, (slot) => values[slot], typeOf, {
      stations: "executed", summary: "stale", zips: "executed",
    });
    expect(sources).toEqual({
      0: { title: "Stations", type: "Data Loading", status: "done" },
      1: { title: "Summarize", type: "Python Computation", status: "stale" },
      // A node with no title is named by its type, once.
      2: { title: "Data Pool", status: "done" },
    });
  });

  test("an input with no value is not run, and a node that failed says so whatever it holds", () => {
    const values: Record<number, unknown> = { 0: "", 1: { path: "b" }, 2: undefined };
    const sources = inputSourcesFor("join", edges, nodes, (slot) => values[slot], typeOf, { summary: "errored" });
    expect(sources[0].status).toBe("not-run");
    expect(sources[1].status).toBe("errored");
    expect(sources[2].status).toBe("not-run");
  });
});
