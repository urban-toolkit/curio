/**
 * What the Map Editor node reads off a layer (#662, `layerModel.ts`): the
 * geometry its features have, the properties a new feature is asked for, the
 * id it takes, the forms' values, and the features as the log leaves them,
 * shapes included; and the corners the edit map handles (`toRings`).
 */
import {
  editedFeatures,
  formProblems,
  formValues,
  geometryKinds,
  inferProperties,
  mainKind,
  nextId,
} from "../../utils/editFeatures/layerModel";
import { applyEdits } from "../../utils/editFeatures/applyEdits";
import { normalizeEdit, normalizeEditFeatures, type FeatureEdit } from "../../utils/editFeatures/editFeatures";
import { toRings } from "../../utils/editFeatures/geometryRings";

const line = (coords: number[][]) => ({ type: "LineString", coordinates: coords });
const roads = {
  type: "FeatureCollection",
  features: [
    { geometry: line([[0, 0], [1, 0]]), properties: { osm_id: 1, highway: "service", oneway: "yes", maxspeed: null, lanes: 2 } },
    { geometry: line([[0, 1], [1, 1]]), properties: { osm_id: 2, highway: "service", oneway: null, maxspeed: "30 mph", lanes: 1 } },
    { geometry: line([[0, 2], [1, 2]]), properties: { osm_id: 3, highway: "secondary", oneway: "yes", maxspeed: null, lanes: 3 } },
    { geometry: { type: "Point", coordinates: [5, 5] }, properties: { osm_id: 4, highway: "service", oneway: "no", maxspeed: null, lanes: 1 } },
  ],
};

describe("a layer's geometry", () => {
  test("is counted by kind, most first, multi-geometries with their kind", () => {
    expect(geometryKinds(roads)).toEqual([{ kind: "lines", count: 3 }, { kind: "points", count: 1 }]);
    expect(mainKind(roads)).toBe("lines");
    expect(mainKind({ features: [{ geometry: { type: "MultiPolygon", coordinates: [] } }] })).toBe("areas");
    expect(mainKind({ features: [] })).toBeNull();
  });
});

describe("the properties a new feature is asked for", () => {
  test("are read from the layer: numbers, repeated texts as choices, required where no feature is empty", () => {
    const props = inferProperties(roads, "osm_id");
    expect(props).toEqual([
      { name: "highway", type: "choice", choices: ["service", "secondary"], required: true },
      { name: "oneway", type: "choice", choices: ["yes", "no"] },
      { name: "maxspeed", type: "text" },
      { name: "lanes", type: "number", required: true },
    ]);
  });

  test("a form says what is missing or of the wrong kind, and reads its texts as values", () => {
    const props = inferProperties(roads, "osm_id");
    expect(formProblems(props, { highway: "", lanes: "two" })).toEqual(["highway is required", "lanes takes a number"]);
    expect(formProblems(props, { highway: "residential", lanes: "2" })).toEqual([]);
    expect(formValues(props, { highway: "residential", lanes: "2", oneway: "" })).toEqual({ highway: "residential", lanes: 2 });
  });
});

describe("the id an added feature takes", () => {
  test("is one more than the largest number, or the first new-N no feature or add has", () => {
    expect(nextId(roads, [], "osm_id")).toBe(5);
    const named = { features: [{ properties: { name: "a" } }, { properties: { name: "new-1" } }] };
    expect(nextId(named, [], "name")).toBe("new-2");
    const adds: FeatureEdit[] = [{ op: "add", id: "new-2", geometry: line([[0, 0], [1, 1]]) }];
    expect(nextId(named, adds, "name")).toBe("new-3");
    // An add on another layer is not this one's.
    expect(nextId(named, [{ ...adds[0], layer: "other" }], "name")).toBe("new-2");
  });
});

describe("the features as the log leaves them", () => {
  const square = { type: "Polygon", coordinates: [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]] };
  test("adds, redraws, sets, removes and restores, each on its own layer", () => {
    const edits: FeatureEdit[] = [
      { op: "add", id: 9, geometry: line([[3, 3], [4, 4]]), values: { highway: "residential" } },
      { op: "geometry", ids: [1], geometry: line([[0, 0], [2, 2]]) },
      { op: "set", ids: [2], column: "highway", value: "primary" },
      { op: "remove", ids: [3] },
      { op: "remove", ids: [4], layer: "elsewhere" },
      { op: "add", id: "x", layer: "sketch", geometry: square },
    ];
    const out = editedFeatures(roads, edits, "osm_id", "roads", "roads");
    expect(out.map((f) => [f.id, f.status])).toEqual([[1, "redrawn"], [2, "changed"], [4, "input"], [9, "added"]]);
    expect(out[0].geometry).toEqual(line([[0, 0], [2, 2]]));
    expect(out[3].properties).toEqual({ highway: "residential", osm_id: 9 });
    const sketch = editedFeatures({ features: [] }, edits, "id", "sketch", "roads");
    expect(sketch.map((f) => f.id)).toEqual(["x"]);
    const back = editedFeatures(roads, [...edits, { op: "restore", ids: [9, 1] }], "osm_id", "roads", "roads");
    expect(back.map((f) => f.id)).toEqual([1, 2, 4]);
    expect(back[0].geometry).toEqual(roads.features[0].geometry);
  });

  test("applyEdits counts adds and redraws, and an added feature restored is gone", () => {
    const rows = roads.features.map((f) => f.properties);
    const { state, counts } = applyEdits(rows, [
      { op: "add", id: 9, geometry: line([[0, 0], [1, 1]]), values: { lanes: 4 } },
      { op: "geometry", ids: [1], geometry: line([[0, 0], [2, 2]]) },
      { op: "add_column", column: "maxspeed", value: "25 mph" },
    ], "osm_id");
    expect(counts).toMatchObject({ add: 1, geometry: 1 });
    expect(state.map((r) => r?.maxspeed)).toEqual(["25 mph", "30 mph", "25 mph", "25 mph", "25 mph"]);
    const gone = applyEdits(rows, [{ op: "add", id: 9, geometry: line([[0, 0], [1, 1]]) }, { op: "restore", ids: [9] }], "osm_id");
    expect(gone.state.filter((r) => r !== null)).toHaveLength(4);
  });
});

describe("the new edits in the log", () => {
  test("are kept whole and nothing else", () => {
    const geometry = line([[0, 0], [1, 1]]);
    expect(normalizeEdit({ op: "add", id: 1, geometry, values: { a: 1, b: { no: 1 } } })).toEqual({ op: "add", id: 1, geometry, values: { a: 1 } });
    expect(normalizeEdit({ op: "add", geometry })).toBeNull();
    expect(normalizeEdit({ op: "add", id: 1, geometry: { type: "Circle", coordinates: [] } })).toBeNull();
    expect(normalizeEdit({ op: "geometry", ids: [1], geometry, layer: "roads" })).toEqual({ op: "geometry", layer: "roads", ids: [1], geometry });
    expect(normalizeEdit({ op: "geometry", ids: [1] })).toBeNull();
    expect(normalizeEdit({ op: "add_column", column: "kind" })).toEqual({ op: "add_column", column: "kind", value: null });
    const settings = normalizeEditFeatures({
      keys: { roads: "osm_id", bad: 3 },
      newLayers: [{ name: " sketch ", geometry: "Polygon", properties: [{ name: "kind", type: "choice", choices: ["a", " "] }, { name: "", type: "text" }] }, { name: "x", geometry: "Circle" }],
      crs: "EPSG:3395",
    });
    expect(settings).toEqual({
      keys: { roads: "osm_id" },
      newLayers: [{ name: "sketch", geometry: "Polygon", properties: [{ name: "kind", type: "choice", choices: ["a"] }] }],
      crs: "EPSG:3395",
    });
  });
});

describe("the edit map's corners", () => {
  test("an area's rings drop and get back their closing corner; multi-shapes keep their parts", () => {
    const square = { type: "Polygon", coordinates: [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]] };
    const r = toRings(square);
    expect(r.rings).toEqual([[[0, 0], [2, 0], [2, 2], [0, 2]]]);
    expect(r.closed).toEqual([true]);
    expect(r.rebuild(r.rings)).toEqual(square);
    const multi = { type: "MultiPolygon", coordinates: [square.coordinates, square.coordinates] };
    const m = toRings(multi);
    expect(m.rings).toHaveLength(2);
    expect(m.rebuild(m.rings)).toEqual(multi);
    const point = toRings({ type: "Point", coordinates: [1, 2] });
    expect(point.rebuild([[[3, 4]]])).toEqual({ type: "Point", coordinates: [3, 4] });
  });
});
