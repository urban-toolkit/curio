/**
 * The tables an Autark node reads and writes for autk-grammar 5.3.0's map
 * keys and 5.4.0's compute passes (utils/autkInput):
 *
 * - a map's `terrain` names the raster table its ground rises to, which the
 *   node reads from its input like any table a map draws;
 * - a `windows` pass writes a table of points, one a window, and a `clusters`
 *   pass a row each, in place or under its own name; a node runs neither over
 *   a table with no rows, nor a pass over what one of them would write.
 */
jest.mock("../../services/api", () => ({ fetchData: jest.fn(), fetchPreviewData: jest.fn() }));

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
