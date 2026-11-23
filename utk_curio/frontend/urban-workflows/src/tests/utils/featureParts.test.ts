/**
 * How the Map Editor node's map tools name one row of a feature of several
 * (utils/editFeatures/featureParts, #1092): an OSM building of several parts
 * is a row for each, holding its building's building_id and an osm_id of its
 * own. An edit of one part names it by both, through `where`; a feature of one
 * row by its id; a feature whose rows nothing tells apart is refused. The
 * node's form lists a building's parts, a part with no height at the height
 * the map draws it at, marked as the default (`partsForm`, `buildingDefault`).
 */
import { applyEdits } from "../../utils/editFeatures/applyEdits";
import { partConditions, partRedraw, partsRefusal, partsToldApart, rowsOf, samePart } from "../../utils/editFeatures/featureParts";

const SHAPE = { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] };

/** A row of a layer keyed by building_id, as the node's tools read it. */
const row = (properties: Record<string, unknown>) => ({ id: (properties.building_id ?? null) as any, properties });

const TOWER = [row({ building_id: 29623484, osm_id: 29623484 }), row({ building_id: 29623484, osm_id: 236608503 })];
const LAYER = [row({ building_id: 11, osm_id: 11 }), ...TOWER, row({ building_id: 12345678901, osm_id: 98765432109 })];

test("each part of a building is named by its building_id and its own osm_id, and each condition picks that part alone", () => {
  const conditions = partConditions(TOWER, "building_id");
  expect(conditions).toEqual([
    "building_id == 29623484 and osm_id == 29623484",
    "building_id == 29623484 and osm_id == 236608503",
  ]);
  for (const [i, where] of (conditions ?? []).entries()) {
    const { state } = applyEdits(LAYER.map((r) => r.properties), [{ op: "remove", where }], "building_id");
    expect(state.map((kept) => kept === null)).toEqual(LAYER.map((r) => r === TOWER[i]));
  }
});

test("a text id is written in quotes, its quotes and backslashes escaped, and still picks its part alone", () => {
  const parts = [row({ building_id: 'b"1', osm_id: "w\\1" }), row({ building_id: 'b"1', osm_id: "w2" })];
  const conditions = partConditions(parts, "building_id");
  expect(conditions).toEqual(['building_id == "b\\"1" and osm_id == "w\\\\1"', 'building_id == "b\\"1" and osm_id == "w2"']);
  const { state } = applyEdits(parts.map((r) => r.properties), [{ op: "remove", where: conditions![0] }], "building_id");
  expect(state.map((kept) => kept === null)).toEqual([true, false]);
});

test("rows that no osm_id tells apart are refused: one with none, two with the same, or a layer keyed by osm_id", () => {
  const none = [row({ building_id: 136 }), row({ building_id: 136 })];
  const same = [row({ building_id: 136, osm_id: 7 }), row({ building_id: 136, osm_id: 7 })];
  for (const rows of [none, same]) {
    expect(partConditions(rows, "building_id")).toBeNull();
    expect(partsToldApart(rows, "building_id")).toBe(false);
    expect(partsRefusal(rows, "building_id")).toBe("Its 2 parts have no osm_id of their own to tell them apart, so its shape cannot be changed on the map.");
  }
  expect(partConditions(TOWER, "osm_id")).toBeNull();
  // One row is no feature of several: it is changed alone, by its id.
  expect(partsToldApart([TOWER[0]], "building_id")).toBe(true);
  expect(partsRefusal([TOWER[0]], "building_id")).toBeNull();
});

test("a redraw names a feature of one row by its id, a part of several by its condition, and refuses parts nothing tells apart", () => {
  expect(partRedraw(LAYER, LAYER[0], "building_id", SHAPE)).toEqual({ op: "geometry", ids: [11], geometry: SHAPE });
  expect(partRedraw(LAYER, { ...TOWER[1], properties: { ...TOWER[1].properties } }, "building_id", SHAPE)).toEqual({
    op: "geometry",
    where: "building_id == 29623484 and osm_id == 236608503",
    geometry: SHAPE,
  });
  // Ids past 2^32 are written whole.
  expect(partRedraw([...LAYER, row({ building_id: 12345678901, osm_id: 12345678902 })], LAYER[3], "building_id", SHAPE)).toEqual({
    op: "geometry",
    where: "building_id == 12345678901 and osm_id == 98765432109",
    geometry: SHAPE,
  });
  const untold = [row({ building_id: 136 }), row({ building_id: 136 })];
  expect(partRedraw(untold, untold[1], "building_id", SHAPE)).toBeNull();
  expect(partRedraw(TOWER, TOWER[1], undefined, SHAPE)).toBeNull();
});

test("a feature's rows are found by its id as a selection names it, and a part by its own osm_id", () => {
  expect(rowsOf(LAYER, "29623484")).toEqual(TOWER);
  expect(rowsOf(LAYER, null)).toEqual([]);
  expect(samePart(TOWER[1], { ...TOWER[1] })).toBe(true);
  expect(samePart(TOWER[0], TOWER[1])).toBe(false);
  expect(samePart(TOWER[0], null)).toBe(false);
});

describe("the form of a building's parts, as a buildings layer draws them", () => {
  // Read off the module, so a checkout without them fails each case on its own.
  const { buildingDefault, partsForm } = require("../../utils/editFeatures/featureParts") as any;
  // A part 140 m tall, one 13.6 m tall from its levels, one with no height,
  // and one with none above its base of 10 m.
  const PARTS = [
    row({ building_id: 7, osm_id: 1, height: 140 }),
    row({ building_id: 7, osm_id: 2, height: 13.6, "building:levels": 4 }),
    row({ building_id: 7, osm_id: 3, height: null }),
    row({ building_id: 7, osm_id: 4, min_height: 10 }),
  ];
  const NAMES = ["osm_id", "height"];

  test("on all the parts, a part with no height is listed at the height the map draws it at, marked as the default", () => {
    const form = partsForm(PARTS, NAMES, null, buildingDefault);
    expect(form.mixed.height).toBe("4 values: 140, 13.6, 6 (default), and 1 more");
    expect(form.labels).toEqual([
      "osm_id 1, height 140", "osm_id 2, height 13.6", "osm_id 3, height 6 (default)", "osm_id 4, height 16 (default)",
    ]);
    // The field of a value the parts differ in shows none, and no default.
    expect(form.values).not.toHaveProperty("height");
    expect(form.defaults).toEqual({});
  });

  test("a part with no height chosen holds none, and its field shows the default in its place", () => {
    const form = partsForm(PARTS, NAMES, PARTS[2], buildingDefault);
    expect(form.values.height).toBeNull();
    expect(form.defaults).toEqual({ height: "6 (default)" });
    expect(partsForm(PARTS, NAMES, PARTS[3], buildingDefault).defaults).toEqual({ height: "16 (default)" });
    expect(partsForm(PARTS, NAMES, PARTS[0], buildingDefault).defaults).toEqual({});
  });

  test("a building of one part with no height shows the default too, and parts that share none show it once", () => {
    expect(partsForm([PARTS[2]], NAMES, null, buildingDefault).defaults).toEqual({ height: "6 (default)" });
    const bare = [row({ building_id: 8, osm_id: 1 }), row({ building_id: 8, osm_id: 2 })];
    const form = partsForm(bare, NAMES, null, buildingDefault);
    expect(form.mixed).toEqual({});
    expect(form.defaults).toEqual({ height: "6 (default)" });
  });

  test("a height of 0 is the part's own, and another layer, or another property, has no default", () => {
    expect(buildingDefault("height", { height: 0 })).toBeNull();
    expect(buildingDefault("height", { "building:levels": 3 })).toBeNull();
    expect(buildingDefault("name", {})).toBeNull();
    expect(buildingDefault("height", {})).toBe(6);
    // Without a layer's default, the two parts with no height are one empty value.
    const form = partsForm(PARTS, NAMES);
    expect(form.mixed.height).toBe("3 values: 140, 13.6, empty");
    expect(form.defaults).toEqual({});
  });
});
