/**
 * What a node's input references can name (#662): its wired circles, named
 * after the nodes that feed them, with what each holds.
 */
const mockFetchPreviewData = jest.fn();
jest.mock("../../services/api", () => ({
  fetchData: jest.fn(),
  fetchPreviewData: (...args: any[]) => mockFetchPreviewData(...args),
}));

import { inputScopeFor, inputValueKey, readInputColumns } from "../../utils/references/inputScope";

const edges = [
  { source: "roads", target: "t", sourceHandle: "out", targetHandle: "in" },
  { source: "parcels", target: "t", sourceHandle: "out", targetHandle: "in_1" },
  { source: "chart", target: "t", sourceHandle: "in/out", targetHandle: "in/out" },
  { source: "roads", target: "other", sourceHandle: "out", targetHandle: "in" },
];
const nodes = [
  { id: "roads", data: { label: "Roads" } },
  { id: "parcels", data: { label: "Parcels" } },
];
const labelOf = (data: any) => data.label ?? null;

describe("inputScopeFor", () => {
  test("one entry per wired circle, named after its node, with its data type", () => {
    const values: Record<number, unknown> = { 0: { path: "a", dataType: "geodataframe" }, 1: "" };
    const scope = inputScopeFor("t", edges, nodes, (slot) => values[slot], labelOf, () => undefined);
    expect(scope).toEqual([
      { slot: 0, label: "Roads", dataType: "geodataframe" },
      // Nothing has arrived on circle 1, so there are no columns to read.
      { slot: 1, label: "Parcels", columns: null },
    ]);
  });

  test("columns already read ride along", () => {
    const read = { columns: ["length"], dtypes: { length: "float64" } };
    const scope = inputScopeFor(
      "t", edges, nodes, () => ({ path: "a" }), labelOf, (value: any) => (value?.path === "a" ? read : undefined),
    );
    expect(scope[0].columns).toEqual(["length"]);
    expect(scope[0].dtypes).toEqual({ length: "float64" });
  });

  test("a node with no edge has no inputs", () => {
    expect(inputScopeFor("lonely", edges, nodes, () => undefined, labelOf, () => undefined)).toEqual([]);
  });

  test("the layers an input carries ride along", () => {
    const read = { columns: [], dtypes: {}, layers: [{ name: "roads", columns: ["highway"], dtypes: {} }] };
    const scope = inputScopeFor("t", edges, nodes, () => ({ path: "a" }), labelOf, () => read);
    expect(scope[0].layers).toEqual([{ name: "roads", columns: ["highway"], dtypes: {} }]);
  });
});

describe("readInputColumns (#662)", () => {
  const fc = (properties: Record<string, unknown>) => ({
    type: "FeatureCollection",
    features: [{ type: "Feature", geometry: { type: "Point", coordinates: [0, 0] }, properties }],
  });

  beforeEach(() => mockFetchPreviewData.mockReset());

  test("a table's columns come from its preview's schema, with their dtypes", async () => {
    mockFetchPreviewData.mockResolvedValue({
      dataType: "dataframe", data: { zip: ["a"], pop: [1] }, schema: { zip: "str", pop: "int64" },
    });
    expect(await readInputColumns({ path: "art", dataType: "dataframe" }))
      .toEqual({ columns: ["zip", "pop"], dtypes: { zip: "str", pop: "int64" } });
    expect(mockFetchPreviewData).toHaveBeenCalledWith("art");
  });

  test("an input carrying several named layers lists each with its own columns", async () => {
    mockFetchPreviewData.mockResolvedValue({
      dataType: "list",
      data: [
        { dataType: "dict", data: { name: "table_osm_roads", type: "roads", geojson: fc({ highway: "primary" }) } },
        { dataType: "dict", data: { name: "table_osm_buildings", type: "buildings", geojson: fc({ height: 9 }) } },
      ],
    });
    expect(await readInputColumns({ path: "art", dataType: "list" })).toEqual({
      columns: [],
      dtypes: {},
      layers: [
        { name: "table_osm_roads", columns: ["highway"], dtypes: {} },
        { name: "table_osm_buildings", columns: ["height"], dtypes: {} },
      ],
    });
  });
});

describe("inputValueKey", () => {
  test("an artifact is known by its path, an inline value by nothing", () => {
    expect(inputValueKey({ path: "abc", dataType: "dataframe" })).toBe("path:abc");
    expect(inputValueKey({ filename: "f.parquet" })).toBe("filename:f.parquet");
    expect(inputValueKey({ data: { a: [1] }, dataType: "dataframe" })).toBeNull();
    expect(inputValueKey("")).toBeNull();
  });
});
