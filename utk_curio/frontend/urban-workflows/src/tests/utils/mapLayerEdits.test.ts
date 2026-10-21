/**
 * An Interaction node plugged into an Autark map (#662,
 * `utils/editFeatures/mapLayerEdits`): which node feeds the map and on which
 * circle, the map's input without that circle, and the layers as the log
 * leaves them, the node's new layers with them.
 */
import { circleTitles, editSources, interactionOn, mapFedBy, withoutCircle, editsVersion } from "../../utils/editFeatures/mapLayerEdits";
import { editLogCode } from "../../utils/editFeatures/editFeatures";
import { fromMercator, toMercator } from "../../utils/editFeatures/mapEditBus";

const nodes = [
  { id: "roads", type: "curio.builtin/data-loading", data: { title: "Roads" } },
  { id: "map", type: "curio.builtin/autk-grammar", data: {} },
  { id: "edit", type: "curio.builtin/edit-features", data: { editFeatures: { edits: [{ op: "remove", ids: [7], layer: "input_0" }], keys: { input_0: "osm_id" } } } },
];
const edges = [
  { source: "roads", target: "map", targetHandle: "in_0" },
  { source: "edit", target: "map", targetHandle: "in_1" },
];
const line = (x: number) => ({ type: "LineString", coordinates: [[x, 0], [x, 1]] });
const roads = {
  outputTableName: "input_0",
  geojsonObject: {
    type: "FeatureCollection",
    features: [
      { type: "Feature", geometry: line(0), properties: { osm_id: 7, highway: "service" } },
      { type: "Feature", geometry: line(1), properties: { osm_id: 8, highway: "primary" } },
    ],
  },
};

test("the map finds the Interaction node plugged into it, and the node its map", () => {
  expect(interactionOn("map", nodes, edges)).toMatchObject({ nodeId: "edit", circle: 1 });
  expect(mapFedBy("edit", nodes, edges)).toBe("map");
});

test("the node's circle is left out of the map's input, the others keep their places", () => {
  const input = { dataType: "outputs", data: [{ path: "a" }, { path: "b" }, { path: "c" }] };
  expect(withoutCircle(input, 1)).toEqual({ dataType: "outputs", data: [{ path: "a" }, null, { path: "c" }] });
  expect(withoutCircle({ path: "only" }, 0)).toBeNull();
});

test("the layers are drawn as the log leaves them, with the node's new layers that have features", () => {
  const settings = {
    keys: { input_0: "osm_id" },
    newLayers: [{ name: "cooling_centers", geometry: "Point" as const }, { name: "empty", geometry: "Polygon" as const }],
    edits: [
      { op: "remove" as const, ids: [7], layer: "input_0" },
      { op: "add" as const, layer: "cooling_centers", id: 1, geometry: { type: "Point", coordinates: [5, 5] }, values: { name: "Library" } },
    ],
  };
  const { sources, added } = editSources([roads], settings);
  expect(sources[0].geojsonObject.features.map((f: any) => f.properties.osm_id)).toEqual([8]);
  expect(added).toEqual([
    {
      outputTableName: "cooling_centers",
      layerType: "points",
      geojsonObject: { type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "Point", coordinates: [5, 5] }, properties: { name: "Library", id: 1 } }] },
    },
  ]);
  // No edits, the layers as they came.
  expect(editSources([roads], { edits: [] }).sources[0]).toBe(roads);
  expect(editsVersion(settings)).not.toBe(editsVersion({ ...settings, edits: [] }));
});

test("plugged into a map, the node's code hands on its log", () => {
  expect(editLogCode({ edits: [{ op: "remove", ids: [7] }] })).toContain('return {"editFeatures": {"edits": [{"op": "remove", "ids": [7]}]}}');
});

test("World Mercator there and back", () => {
  const [x, y] = toMercator([-87.63, 41.88]);
  expect(x).toBeCloseTo(-9754926.98, 1);
  const [lon, lat] = fromMercator([x, y]);
  expect(lon).toBeCloseTo(-87.63, 9);
  expect(lat).toBeCloseTo(41.88, 9);
});

test("a layer is called by its node's header as renamed, else by the node's title", () => {
  expect(circleTitles("map", nodes, edges)).toEqual({ 0: "Roads" });
  const renamed = nodes.map((n) => (n.id === "roads" ? { ...n, data: { ...n.data, packageTemplateLabel: "Streets" } } : n));
  expect(circleTitles("map", renamed, edges)).toEqual({ 0: "Streets" });
});
