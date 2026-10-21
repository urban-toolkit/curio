/**
 * The Map Edits node's input, as its body and its map read it
 * (utils/mapEdits/mapEditsLayers): the layer it edits and the column that
 * identifies a feature, the document and the inline input its map draws, and
 * the input row a pick on that map names.
 */
import { VisInteractionType } from "../../constants";
import { applyMapEdits, type MapEdits } from "../../utils/mapEdits/mapEdits";
import {
  chosenLayer,
  defaultKey,
  fieldProperties,
  keptRows,
  keyColumns,
  keyRefusal,
  mapDocument,
  mapInput,
  pickedRow,
  type InputLayer,
} from "../../utils/mapEdits/mapEditsLayers";

const feature = (properties: Record<string, unknown>) => ({ type: "Feature", geometry: null, properties });

const PARTS = [
  feature({ building_id: 119, height: 240 }),
  feature({ building_id: 119, height: 60 }),
  feature({ building_id: 136, height: 60 }),
  feature({ building_id: "136", height: 9 }),
];

const edits = (more: Partial<MapEdits>): MapEdits => ({ key: "building_id", remove: [], change: [], ...more });

const BUILDINGS: InputLayer = { table: "table_osm_buildings", name: "table_osm_buildings", layerType: "buildings", fc: { features: PARTS } };
const ROADS: InputLayer = { table: "table_osm_roads", name: "table_osm_roads", layerType: "roads", fc: { features: [feature({ highway: "primary" }), feature({ highway: "primary" })] } };

describe("the layer and its id column", () => {
  test("the edits' layer by name, else the first that has an id column", () => {
    expect(chosenLayer([ROADS, BUILDINGS], undefined)).toBe(BUILDINGS);
    expect(chosenLayer([ROADS, BUILDINGS], "table_osm_roads")).toBe(ROADS);
    expect(chosenLayer([ROADS, BUILDINGS], "gone")).toBe(BUILDINGS);
    expect(chosenLayer([ROADS], undefined)).toBe(ROADS);
  });

  test("osm_id or building_id when the layer has one; a layer with none is refused, naming Map Edits", () => {
    expect(defaultKey(keyColumns(BUILDINGS.fc))).toBe("building_id");
    expect(keyRefusal(keyColumns(BUILDINGS.fc), "Buildings")).toBeNull();
    expect(keyRefusal(keyColumns(ROADS.fc), "table_osm_roads")).toMatch(
      /^table_osm_roads has no column that identifies its features: .* Map Edits matches features by such a column/,
    );
  });
});

describe("the map", () => {
  test("draws every layer, the one to edit last and pickable", () => {
    expect(JSON.parse(mapDocument([BUILDINGS, ROADS], "table_osm_buildings")).map.layerRefs).toEqual([
      { dataRef: "table_osm_roads" },
      { dataRef: "table_osm_buildings", isPick: true },
    ]);
  });

  test("is handed every layer inline, as an Autark node's records, the one to edit as the edits leave it", () => {
    const edited = applyMapEdits(PARTS, edits({ remove: [119] }));
    const input = mapInput([ROADS, BUILDINGS, { table: "input_0", name: null, fc: { features: [] } }], "table_osm_buildings", edited);
    expect(input.dataType).toBe("list");
    expect(input.data.map((record) => [record.name, record.type])).toEqual([
      ["table_osm_roads", "roads"],
      ["table_osm_buildings", "buildings"],
      // A layer of no known type leaves it to Autark.
      ["input_0", undefined],
    ]);
    expect(input.data[0].geojson).toBe(ROADS.fc);
    expect((input.data[1].geojson as any).features).toEqual(edited);
    // The input's own layer is left as it came.
    expect(BUILDINGS.fc.features).toHaveLength(4);
  });
});

describe("a pick", () => {
  test("keptRows: the input row of each row the edits keep, by the id's type as the sandbox compares it", () => {
    expect(keptRows(PARTS, edits({}))).toEqual([0, 1, 2, 3]);
    expect(keptRows(PARTS, edits({ remove: [119] }))).toEqual([2, 3]);
    expect(keptRows(PARTS, edits({ remove: [136] }))).toEqual([0, 1, 3]);
    expect(keptRows(PARTS, edits({ remove: ["136"] }))).toEqual([0, 1, 2]);
    // With no key, nothing is removed, as applyMapEdits removes nothing.
    expect(keptRows(PARTS, { remove: [119], change: [] })).toEqual([0, 1, 2, 3]);
  });

  test("names the first row it picks: a drawn row, or the first row holding the values a view sends", () => {
    const pick = (data: unknown[]) => ({ autk_selection: { type: VisInteractionType.POINT, data, priority: 1 } });
    expect(pickedRow(pick([2, 0]), PARTS)).toBe(2);
    expect(pickedRow(pick([{ building_id: 119 }]), PARTS)).toBe(0);
    expect(pickedRow(pick([]), PARTS)).toBeNull();
    expect(pickedRow(pick([9]), PARTS)).toBeNull();
    expect(pickedRow(null, PARTS)).toBeNull();
  });
});

test("the panel's JSON: the properties as JSON writes them, without a geometry property", () => {
  expect(fieldProperties({ building_id: 7, geometry: "POINT (0 0)", when: new Date(Date.UTC(2026, 9, 21)), gone: undefined, big: BigInt(12) })).toEqual({
    building_id: 7,
    when: "2026-10-21T00:00:00.000Z",
    big: 12,
  });
  expect(fieldProperties(null)).toEqual({});
});
