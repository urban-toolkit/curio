/**
 * Where an Autark node runs each source of its data section (autk-grammar
 * 5.5.0's `after: 'compute'`, the owner's design B): a source after compute
 * runs once the node's passes have run, so it reads what a pass kept in
 * autk-db (`writeBack`).
 *
 * - A document with compute passes: the node loads its sources before compute
 *   where it loads its data section (`loadedSources`), and runs those after
 *   compute in the browser after its passes (`sourcesAfterPasses`), which
 *   load the tables of the node's input they read there (`documentTableRefs`).
 * - A document of no compute pass: its sources after compute load with the
 *   others, after them, the order the grammar runs them in, wherever they
 *   stand in `data`, and the code both loaders run asks the grammar's
 *   `dataPhases` first, which refuses an `after` other than 'compute'.
 * - An OpenStreetMap table a pass changes in place and keeps in autk-db is
 *   read row by row, as the grammar reads it (`osmElementTables`).
 *
 * The functions this release adds are read off the module as it is, so a
 * build without them fails each case on its own.
 */
import * as compile from "../../../adapters/node/autkDataCompile";
import { autkNeedsInput, documentTableRefs } from "../../../utils/autkInput";

const { compileDataSpecToAutkDbJs, osmElementTables } = compile;
const { loadedSources, sourcesAfterPasses } = compile as any;

const square = (x: number) => ({
  type: "Feature",
  properties: { zone: x },
  geometry: { type: "Polygon", coordinates: [[[x, 0], [x + 10, 0], [x + 10, 10], [x, 10], [x, 0]]] },
});
const ZONES = {
  type: "geojson", outputTableName: "zones", coordinateFormat: "EPSG:3395",
  geojsonObject: { type: "FeatureCollection", features: [square(0), square(20)] },
};
const PINS = {
  type: "geojson", outputTableName: "pins", coordinateFormat: "EPSG:3395",
  geojsonObject: { type: "FeatureCollection", features: [{ type: "Feature", properties: { p: 1 }, geometry: { type: "Point", coordinates: [5, 5] } }] },
};
/** A join after compute of the pins onto the zones, listed before both. */
const JOIN_AFTER = {
  type: "join", dataRef: "zones", joinDataRef: "pins", groupBy: [{ column: "*", aggregateFn: "count" }], after: "compute",
};
/** A heatmap after compute of the node's first input. */
const HEATMAP_AFTER = {
  type: "heatmap", outputTableName: "heat", joinDataRef: "input_0", near: { distance: 50 }, grid: { rows: 2, columns: 2 },
  after: "compute",
};
const CLUSTERS = { type: "clusters", dataRef: "zones", outputColumnName: "block", writeBack: true };

/** The sources the compiled code loads, in its order: its `__sources`. */
function compiledSources(code: string): any[] {
  const line = code.split("\n").find((row) => row.startsWith("const __sources = "));
  if (!line) throw new Error("the compiled code has no __sources");
  return JSON.parse(line.slice("const __sources = ".length).replace(/;$/, ""));
}

describe("a document with compute passes", () => {
  const document = { data: [JOIN_AFTER, ZONES, HEATMAP_AFTER, PINS], compute: [CLUSTERS], map: { layerRefs: [{ dataRef: "heat" }] } };

  test("loads its sources before compute where it loads its data, and runs those after compute after its passes", () => {
    expect(loadedSources(document)).toEqual([ZONES, PINS]);
    expect(sourcesAfterPasses(document)).toEqual([JOIN_AFTER, HEATMAP_AFTER]);
  });

  test("reads the table of its input a source after compute bins in the browser, and so needs its input", () => {
    const refs = documentTableRefs(document);
    expect(refs).toContain("input_0");
    // The tables its own sources load are not its input's.
    expect(refs).not.toContain("pins");
    expect(autkNeedsInput(document)).toBe(true);
    // One whose source after compute reads only what its own sources load does not.
    expect(autkNeedsInput({ ...document, data: [JOIN_AFTER, ZONES, PINS], map: { layerRefs: [{ dataRef: "zones" }] } }))
      .toBe(false);
  });
});

describe("a document of no compute pass", () => {
  const document = { data: [JOIN_AFTER, ZONES, PINS] };

  test("loads its sources after compute after the others, wherever they stand in data", () => {
    expect(loadedSources(document)).toEqual([ZONES, PINS, JOIN_AFTER]);
    expect(sourcesAfterPasses(document)).toEqual([]);
  });

  test("compiles them in that order, and asks the grammar's dataPhases of the section first", () => {
    const code = compileDataSpecToAutkDbJs(document.data);
    expect(code.split("\n")[1]).toBe("import { createDataAdapter, dataPhases } from '@urban-toolkit/autk-grammar/data';");
    expect(compiledSources(code).map((source) => source.type === "join" ? "join" : source.outputTableName))
      .toEqual(["zones", "pins", "join"]);
    expect(code).toContain("dataPhases({ data: __sources });");
    // The join reads tables its section loads before it, as the grammar runs them.
    expect(code).toContain("const __tableProblem = null;");
  });

  test("a section without after compiles as it does without the grammar's phases", () => {
    const code = compileDataSpecToAutkDbJs([ZONES, PINS]);
    expect(code.split("\n")[1]).toBe("import { createDataAdapter } from '@urban-toolkit/autk-grammar/data';");
    expect(code).not.toContain("dataPhases");
  });
});

describe("an OpenStreetMap table a view reads as elements", () => {
  const osm = { type: "osm", pbfFileUrl: "a.pbf", outputTableName: "fidi", autoLoadLayers: { layers: ["buildings"] } };
  const view = { map: { layerRefs: [{ dataRef: "fidi_buildings", osmElements: true }] } };

  test("is read row by row when a pass changes it in place and keeps it in autk-db, as the grammar reads it", () => {
    const pass = { type: "clusters", dataRef: "fidi_buildings", outputColumnName: "block" };
    expect(osmElementTables({ data: [osm], compute: [{ ...pass, writeBack: true }], ...view })).toEqual([]);
    // A pass that writes a table of its own leaves it as elements.
    expect(osmElementTables({ data: [osm], compute: [{ ...pass, outputTableName: "blocks", writeBack: true }], ...view }))
      .toEqual(["fidi_buildings"]);
  });
});
