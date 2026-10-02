/**
 * The Autark node's input, read the way the Vega-Lite node reads its own, as
 * the tables an Autark document names.
 */
const mockFetchData = jest.fn();
jest.mock("../../services/api", () => ({
  fetchData: (...args: any[]) => mockFetchData(...args),
  fetchPreviewData: jest.fn(),
}));

import {
  autkNeedsInput,
  autkSourcesFrom,
  documentTableRefs,
  loadableSource,
  ownTableNames,
  inputRow,
  prepareAutkInput,
  tablePositions,
} from "../../utils/autkInput";
import type { GrammarFrame, GrammarInput } from "../../utils/grammarInput";

const point = (x: number, y: number) => ({ type: "Point", coordinates: [x, y] });
const fc = (geoms: any[], crs?: string) => ({
  type: "FeatureCollection",
  ...(crs ? { crs: { properties: { name: crs } } } : {}),
  features: geoms.map((geometry, i) => ({ type: "Feature", geometry, properties: { value: i } })),
});

function frame(over: Partial<GrammarFrame>): GrammarFrame {
  return {
    name: null,
    dataType: "geodataframe",
    payload: fc([point(1, 1)]),
    schema: null,
    geometryName: "geometry",
    crsName: null,
    fromBundle: false,
    index: 0,
    ...over,
  };
}
const read = (...frames: GrammarFrame[]): GrammarInput => ({ frames });
const MAP_ON = (...refs: string[]) => ({ map: { layerRefs: refs.map((dataRef) => ({ dataRef })) } });

describe("documentTableRefs", () => {
  test("maps, plots and compute blocks, as objects or arrays", () => {
    const spec = {
      map: [{ layerRefs: [{ dataRef: "a" }] }, { layerRefs: [{ dataRef: "b" }] }],
      plot: { dataRef: "c", mapRef: "a" },
      compute: [{
        dataRef: "d",
        uniforms: { k: { fromFeature: { layer: "e", path: "x" } }, n: 1 },
        uniformMatrices: { m: { fromFeature: { layer: "f", path: "y" } } },
      }],
    };
    expect(documentTableRefs(spec).sort()).toEqual(["a", "b", "c", "d", "e", "f"]);
  });
});

describe("autkNeedsInput", () => {
  const osm = { type: "osm", outputTableName: "t", autoLoadLayers: { layers: ["roads"] }, queryArea: {} };

  test("a document drawing what its own data section loads needs nothing", () => {
    expect(autkNeedsInput({ data: [osm], ...MAP_ON("t_roads") })).toBe(false);
    expect(autkNeedsInput({ data: [osm] })).toBe(false);
  });

  test("a document naming a table it does not create reads its input", () => {
    expect(autkNeedsInput(MAP_ON("upstream"))).toBe(true);
    expect(autkNeedsInput({ data: [osm], ...MAP_ON("t_roads", "table_osm_water") })).toBe(true);
  });

  test("a compute-only document works on what arrives", () => {
    expect(autkNeedsInput({ compute: [{ dataRef: "x", wglsFunction: "" }] })).toBe(true);
  });

  test("a heatmap's table is the document's own", () => {
    const heat = { type: "heatmap", outputTableName: "h", tableJoinName: "t_roads", near: {}, grid: {} };
    expect(ownTableNames({ data: [osm, heat] }).sort()).toEqual(["h", "t_roads"]);
    expect(autkNeedsInput({ data: [osm, heat], ...MAP_ON("h") })).toBe(false);
  });
});

describe("autkSourcesFrom", () => {
  test("an empty layer an Autark data node stored comes back with no feature list: a table with no rows", () => {
    // What /get hands back for a layer the load found empty, e.g. a PBF area
    // with no water. The render drops it as it drops any empty table.
    const empty = { type: "FeatureCollection", features: null };
    const prepared = autkSourcesFrom(
      read(
        frame({ name: "table_osm_roads", fromBundle: true, index: 0, payload: fc([point(1, 1), point(2, 2)]) }),
        frame({ name: "table_osm_water", fromBundle: true, index: 1, payload: empty }),
      ),
      MAP_ON("table_osm_roads", "table_osm_water"),
    );
    expect(prepared.tables).toEqual(["table_osm_roads", "table_osm_water"]);
    expect(prepared.rowsIn).toBe(2);
    expect(prepared.inputProblem).toBeUndefined();
    expect(loadableSource(prepared.sources[1]).order).toEqual({ load: null, map: null });
  });

  test("a single frame is the table `upstream`, in the CRS it declares", () => {
    const prepared = autkSourcesFrom(
      read(frame({ payload: fc([point(1, 1)], "urn:ogc:def:crs:EPSG::32632") })),
      MAP_ON("upstream"),
    );
    expect(prepared.sources.map((s) => [s.outputTableName, s.coordinateFormat])).toEqual([
      ["upstream", "EPSG:32632"],
    ]);
    expect(prepared.rowsIn).toBe(1);
  });

  test("a named frame keeps its name; `upstream` is added only when the document reads it", () => {
    const named = read(frame({ name: "census" }));
    expect(autkSourcesFrom(named, MAP_ON("census")).sources.map((s) => s.outputTableName))
      .toEqual(["census"]);
    expect(autkSourcesFrom(named, MAP_ON("upstream")).sources.map((s) => s.outputTableName))
      .toEqual(["upstream", "census"]);
    expect(autkSourcesFrom(named, MAP_ON("upstream"), { alias: false }).sources.map((s) => s.outputTableName))
      .toEqual(["census"]);
  });

  test("several layers keep their own names: `upstream` names none of them (#483)", () => {
    // USAGE: "Several layers keep their own names". The alias used to point
    // `upstream` at layer 0 as well, which no doc said.
    const layers = read(
      frame({ name: "parks", fromBundle: true, index: 0 }),
      frame({ fromBundle: true, index: 1 }),
    );
    expect(autkSourcesFrom(layers, MAP_ON("upstream")).tables).toEqual(["parks", "upstream_1"]);
  });

  test("a bundle's unnamed layers are named by position, and keep their layer type", () => {
    const prepared = autkSourcesFrom(
      read(
        frame({ name: "table_osm_roads", layerType: "roads", fromBundle: true, index: 0 }),
        frame({ fromBundle: true, index: 1 }),
      ),
      MAP_ON("table_osm_roads"),
    );
    expect(prepared.sources.map((s) => [s.outputTableName, s.layerType])).toEqual([
      ["table_osm_roads", "roads"],
      ["upstream_1", undefined],
    ]);
  });

  test("a buildings table gets heights autk-map can read, one feature per row", () => {
    // A GeoDataFrame gives every row every column: a building tagged only with
    // building:levels arrives with height null, and autk-map would cull it.
    const rows = [
      { height: 30, "building:levels": null },
      { height: null, "building:levels": 8 },
      { height: null, "building:levels": null },
    ];
    const payload = {
      type: "FeatureCollection",
      features: rows.map((properties) => ({ type: "Feature", geometry: point(1, 1), properties })),
    };
    const prepared = autkSourcesFrom(read(frame({ layerType: "buildings", payload })), MAP_ON("upstream"));
    expect(prepared.sources.map((s) => [s.outputTableName, s.layerType])).toEqual([["upstream", "buildings"]]);
    const features = prepared.sources[0].geojsonObject.features as any[];
    expect(features.map((f) => f.properties.height)).toEqual([30, 8 * 3.4, 6]);
    // The first already reads right, so it is the same feature; the input is not changed.
    expect(features[0]).toBe(payload.features[0]);
    expect(payload.features.map((f) => f.properties.height)).toEqual([30, null, null]);
  });

  test("any other table is passed on as it came", () => {
    const payload = {
      type: "FeatureCollection",
      features: [{ type: "Feature", geometry: point(1, 1), properties: { height: null, "building:levels": 8 } }],
    };
    for (const layerType of [undefined, "polygons"]) {
      const prepared = autkSourcesFrom(read(frame({ layerType, payload })), MAP_ON("upstream"));
      expect(prepared.sources[0].geojsonObject).toBe(payload);
    }
  });

  test("a DataFrame with one geometry column becomes a FeatureCollection, every row in place", () => {
    const prepared = autkSourcesFrom(
      read(frame({
        dataType: "dataframe",
        geometryName: null,
        payload: { zone: ["n", "s", "e"], where: [point(0, 0), null, point(2, 2)] },
      })),
      MAP_ON("upstream"),
    );
    const features = prepared.sources[0].geojsonObject.features as any[];
    expect(features.map((f) => f.geometry)).toEqual([point(0, 0), null, point(2, 2)]);
    expect(features.map((f) => f.properties)).toEqual([{ zone: "n" }, { zone: "s" }, { zone: "e" }]);
    expect(prepared.inputProblem).toBeUndefined();
  });

  test("a DataFrame with no geometry column is refused the way Vega refuses a geoshape", () => {
    const prepared = autkSourcesFrom(
      read(frame({ dataType: "dataframe", geometryName: null, payload: { zone: ["n"], pop: [3] } })),
      MAP_ON("upstream"),
    );
    expect(prepared).toMatchObject({
      sources: [],
      unusable: ["upstream"],
      emptyReason: "geometry-unresolved",
      detail: "upstream has no geometry column, so there is nothing to draw. Return a GeoDataFrame.",
    });
    expect(prepared.inputProblem).toBe(prepared.detail);
  });

  test("a DataFrame with several geometry columns names them", () => {
    const prepared = autkSourcesFrom(
      read(frame({
        dataType: "dataframe",
        geometryName: null,
        payload: { a: [point(0, 0)], b: [point(1, 1)] },
      })),
      MAP_ON("upstream"),
    );
    expect(prepared.emptyReason).toBe("geometry-ambiguous");
    expect(prepared.detail).toContain("(a, b)");
  });

  test("a frame with no geometry in any row cannot be drawn", () => {
    const prepared = autkSourcesFrom(read(frame({ payload: fc([null, null]) })), MAP_ON("upstream"));
    expect(prepared.unusable).toEqual(["upstream"]);
    expect(prepared.detail).toBe("No row of upstream has a geometry, so there is nothing to draw.");
  });

  test("what draws is drawn; what does not is named", () => {
    const prepared = autkSourcesFrom(
      {
        frames: [
          frame({ name: "roads", fromBundle: true, index: 0 }),
          frame({ name: "stats", dataType: "dataframe", geometryName: null, payload: { n: [1] }, fromBundle: true, index: 1 }),
        ],
        skipped: ["raster at position 2"],
      },
      MAP_ON("roads", "stats"),
    );
    expect(prepared.sources.map((s) => s.outputTableName)).toEqual(["roads"]);
    expect(prepared.unusable).toEqual(["stats"]);
    expect(prepared.emptyReason).toBeUndefined();
    expect(prepared.inputProblem).toBe(
      "stats has no geometry column, so there is nothing to draw. Return a GeoDataFrame. "
      + "Left out: raster at position 2.",
    );
  });

  test("a refused input is the table `upstream`, unusable, with the refusal as its reason", () => {
    const prepared = autkSourcesFrom(
      { frames: [], emptyReason: "input-type-rejected", detail: "raster is not a valid input type for the Autark node." },
      MAP_ON("upstream"),
    );
    expect(prepared).toMatchObject({
      unusable: ["upstream"],
      emptyReason: "input-type-rejected",
      inputProblem: "raster is not a valid input type for the Autark node.",
    });
  });
});

describe("loadableSource", () => {
  const source = (geoms: any[]) => ({
    type: "geojson" as const,
    geojsonObject: fc(geoms) as any,
    outputTableName: "upstream",
    coordinateFormat: "EPSG:4326",
  });

  test("a first feature without geometry trades places with the first that has one", () => {
    const { source: loaded, order } = loadableSource(source([null, null, point(2, 2), point(3, 3)]));
    expect((loaded.geojsonObject.features as any[]).map((f) => f.properties.value)).toEqual([2, 1, 0, 3]);
    // The table holds rows 2, 1, 0, 3; a map draws only 2 and 3.
    expect(order).toEqual({ load: [2, 1, 0, 3], map: [2, 3] });
  });

  test("a map pick and a highlight name the input's rows, not positions in what was drawn", () => {
    const { order } = loadableSource(source([point(0, 0), null, point(2, 2)]));
    expect(order).toEqual({ load: null, map: [0, 2] });
    // The second thing the map drew is input row 2...
    expect(inputRow(1, order.map)).toBe(2);
    // ...and a highlight on rows 1 and 2 lights map position 1 (row 1 is not drawn).
    expect(tablePositions([1, 2], order.map)).toEqual([1]);
    // A plot reads the table as loaded, so its positions are the rows.
    expect(inputRow(1, order.load)).toBe(1);
    expect(tablePositions([1, 2], order.load)).toEqual([1, 2]);
  });

  test("a table with geometry everywhere is left alone", () => {
    const plain = source([point(0, 0), point(1, 1)]);
    expect(loadableSource(plain)).toEqual({ source: plain, order: { load: null, map: null } });
  });
});

test("prepareAutkInput reads the input through the shared reader", async () => {
  mockFetchData.mockResolvedValue({ dataType: "geodataframe", data: fc([point(1, 1)]) });
  const prepared = await prepareAutkInput({ path: "art", dataType: "geodataframe" }, MAP_ON("upstream"));
  expect(mockFetchData).toHaveBeenCalledWith("art");
  expect(prepared.tables).toEqual(["upstream"]);
});
