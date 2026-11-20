/**
 * The tables an Autark node reads and writes for autk-grammar 5.3.0's map
 * keys and 5.4.0's compute passes (utils/autkInput):
 *
 * - a map's `terrain` names the raster table its ground rises to, which the
 *   node reads from its input like any table a map draws;
 * - a `windows` pass writes a table of points, one a window, and a `clusters`
 *   pass a row each, in place or under its own name; a node runs neither over
 *   a table with no rows, nor a pass over what one of them would write;
 * - a buildings table a layer with `buildingsZeroHeight` draws keeps no
 *   height for a part that has none, so autk-map draws it at its own random
 *   height; every other buildings table gets the height Curio gives such a part.
 */
jest.mock("../../services/api", () => ({ fetchData: jest.fn(), fetchPreviewData: jest.fn() }));

import { withZeroHeightExports } from "../../adapters/node/autkZeroHeights";
import { autkSourcesFrom, documentTableRefs, passesAtHand, writtenTables } from "../../utils/autkInput";
import type { GrammarFrame, GrammarInput } from "../../utils/grammarInput";

function frame(over: Partial<GrammarFrame>): GrammarFrame {
  return {
    name: null,
    dataType: "geodataframe",
    payload: { type: "FeatureCollection", features: [] },
    schema: null,
    geometryName: "geometry",
    crsName: null,
    fromBundle: false,
    index: 0,
    circle: 0,
    ...over,
  };
}
const read = (...frames: GrammarFrame[]): GrammarInput => ({ frames });

describe("a map's terrain", () => {
  test("names a table the document reads: the raster its ground rises to, in its map's workspace", () => {
    expect(documentTableRefs({ map: { terrain: { dataRef: "heights", band: "band_1" }, layerRefs: [{ dataRef: "zones" }] } }).sort())
      .toEqual(["heights", "zones"]);
    expect(documentTableRefs({ map: { workspace: "east", terrain: { dataRef: "heights" }, layerRefs: [{ dataRef: "zones" }] } }).sort())
      .toEqual(["east/heights", "east/zones"]);
  });

  test("reads an input's raster that only the terrain names, by the input's name", () => {
    const spec = { map: { terrain: { dataRef: "input_0" }, layerRefs: [{ dataRef: "zones" }] } };
    const prepared = autkSourcesFrom(read(frame({ name: "dem", dataType: "raster" as any, payload: "the raster" })), spec);
    expect(prepared.rasters.map((raster) => raster.outputTableName)).toContain("input_0");
  });
});

describe("the tables windows and clusters passes write", () => {
  test("a windows pass writes a table of points under its own name, one a window, not a row each", () => {
    expect(writtenTables({ compute: [{ type: "windows", dataRef: "towers", floors: 3, outputTableName: "windows" }] }))
      .toEqual([{ name: "windows", from: "towers", holdsRows: false, layerType: "points" }]);
    expect(writtenTables({ compute: [{
      type: "windows", workspace: "east", dataRef: "towers", floors: 3, outputTableName: "windows", layerType: "polygons",
    }] })).toEqual([{ name: "windows", from: "towers", holdsRows: false, layerType: "polygons", workspace: "east" }]);
  });

  test("a clusters pass writes a row each, in place or under its own name", () => {
    expect(writtenTables({ compute: [{ type: "clusters", dataRef: "towers", outputColumnName: "block" }] }))
      .toEqual([{ name: "towers", from: "towers", holdsRows: true }]);
    expect(writtenTables({ compute: [{
      type: "clusters", dataRef: "towers", outputColumnName: "block", outputTableName: "blocks", layerType: "polygons",
    }] })).toEqual([{ name: "blocks", from: "towers", holdsRows: true, layerType: "polygons" }]);
  });

  test("a node runs neither over a table with no rows, nor a pass over the table one of them would write", () => {
    const passes = [
      { type: "windows", dataRef: "towers", floors: 3, outputTableName: "windows" },
      { type: "clusters", dataRef: "windows", outputColumnName: "group" },
      { type: "clusters", dataRef: "lines", outputColumnName: "network" },
    ];
    const known = new Set(["towers", "lines", "windows"]);
    expect(passesAtHand(passes, known, new Set(["lines"]))).toEqual([passes[2]]);
    expect(passesAtHand(passes, known, new Set(["towers", "lines"]))).toEqual(passes);
  });
});

describe("buildingsZeroHeight", () => {
  /** A square footprint *at* blocks east. */
  const square = (at: number) => ({
    type: "Polygon", coordinates: [[[at, 0], [at + 0.5, 0], [at + 0.5, 0.5], [at, 0.5], [at, 0]]],
  });
  /** Parts with a height, with none, with a height that holds no number, and with levels only. */
  const PARTS = [{ height: 30 }, {}, { height: null }, { "building:levels": 4 }];
  const towers = () => frame({
    name: "towers",
    layerType: "buildings",
    payload: {
      type: "FeatureCollection",
      features: PARTS.map((properties, at) => ({ type: "Feature", geometry: square(at), properties: { id: at, ...properties } })),
    },
  });
  const HEIGHT_KEYS = ["height", "building:height", "levels", "building:levels"];
  const handed = (spec: any) => autkSourcesFrom(read(towers()), spec)
    .sources.find((source) => source.outputTableName === "towers")!
    .geojsonObject.features.map((feature: any) => feature.properties);

  test("a buildings table a layer with buildingsZeroHeight draws keeps no height for a part that has none", () => {
    const parts = handed({ map: { layerRefs: [{ dataRef: "towers", buildingsZeroHeight: true }] } });
    expect(parts[0].height).toBe(30);
    for (const part of [parts[1], parts[2]]) {
      expect(HEIGHT_KEYS.filter((key) => key in part)).toEqual([]);
    }
    // A part with levels keeps its height, written where autk-map reads it.
    expect(parts[3].height).toBeCloseTo(13.6, 6);
  });

  test("the run's database hands the map such a table with no height key that holds no number, on a building and on its parts", async () => {
    // As autk-db exports a table it keeps column by column: every column on every feature.
    const exported = {
      type: "FeatureCollection",
      features: [
        { type: "Feature", geometry: square(0), properties: { height: 30, levels: null } },
        { type: "Feature", geometry: square(1), properties: { height: null, "building:levels": "" } },
        { type: "Feature", geometry: square(2), properties: { height: null, parts: [{ geometryIndex: 0, height: null }] } },
      ],
    };
    const db = { getCurrentWorkspace: () => "autk", getLayer: jest.fn(async () => exported) };
    const grammar: any = { dataAdapter: { resolveSource: jest.fn(async () => db) } };
    withZeroHeightExports(grammar, new Set(["towers"]));
    const loaded = await grammar.dataAdapter.resolveSource(undefined, { type: "geojson", outputTableName: "towers" });

    const towers = await loaded.getLayer("towers");
    expect(towers.features.map((feature: any) => feature.properties)).toEqual([
      { height: 30 },
      {},
      { parts: [{ geometryIndex: 0 }] },
    ]);
    // Any other table, as autk-db exports it.
    expect(await loaded.getLayer("roads")).toBe(exported);
  });

  test("every other buildings table gives a part without a height the one autk-map draws", () => {
    const parts = handed({ map: { layerRefs: [{ dataRef: "towers" }] } });
    expect(parts.slice(0, 3).map((part: any) => part.height)).toEqual([30, 6, 6]);
    expect(parts[3].height).toBeCloseTo(13.6, 6);
  });
});
