/**
 * An Interaction node linked to an Autark map (#662,
 * `utils/editFeatures/mapLayerEdits`): Data → Interaction → map on data
 * edges, and an interaction edge between the node and the map; which node a
 * map is linked to, what the map draws, how many circles feed the node, and
 * the layers as the log leaves them, the node's new layers with them.
 */
import { circlesInto, circleTitles, editSources, interactionOn, isInteractionEdge, mapFedBy, editsVersion } from "../../utils/editFeatures/mapLayerEdits";
import { editFeaturesCode } from "../../utils/editFeatures/editFeatures";
import { fromMercator, toMercator } from "../../utils/editFeatures/mapEditBus";

const RAW = { dataType: "outputs", data: [{ path: "roads" }, { path: "parks" }] };
const nodes = [
  { id: "roads", type: "curio.builtin/data-loading", data: { title: "Roads" } },
  { id: "parks", type: "curio.builtin/data-loading", data: { title: "Parks" } },
  { id: "map", type: "curio.builtin/autk-grammar", data: {} },
  { id: "edit", type: "curio.builtin/edit-features", data: { input: RAW, editFeatures: { edits: [{ op: "remove", ids: [7], layer: "input_0" }], keys: { input_0: "osm_id" } } } },
];
const link = { source: "edit", target: "map", sourceHandle: "in/out", targetHandle: "in/out", type: "BIDIRECTIONAL_EDGE" };
const edges = [
  { source: "roads", target: "edit", sourceHandle: "out", targetHandle: "in_0" },
  { source: "parks", target: "edit", sourceHandle: "out", targetHandle: "in_1" },
  { source: "edit", target: "map", sourceHandle: "out", targetHandle: "in_0" },
  link,
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

test("the map finds the node linked to it by an interaction edge, either way round, and the node its map", () => {
  expect(isInteractionEdge(link)).toBe(true);
  expect(isInteractionEdge(edges[2])).toBe(false);
  expect(interactionOn("map", nodes, edges)).toMatchObject({ nodeId: "edit", feeds: true, drawFrom: RAW });
  expect(mapFedBy("edit", nodes, edges)).toBe("map");
  const backwards = [...edges.slice(0, 3), { ...link, source: "map", target: "edit" }];
  expect(interactionOn("map", nodes, backwards)?.nodeId).toBe("edit");
  expect(mapFedBy("edit", nodes, backwards)).toBe("map");
});

test("a data edge alone links nothing: the map just draws what the node hands on", () => {
  expect(interactionOn("map", nodes, edges.slice(0, 3))).toBeNull();
  expect(mapFedBy("edit", nodes, edges.slice(0, 3))).toBeNull();
});

test("the map draws the node's own input only when the node is all that feeds it", () => {
  // Fed by the node and by roads too: the map draws what it was fed.
  const mixed = [...edges, { source: "roads", target: "map", sourceHandle: "out", targetHandle: "in_1" }];
  const fedTwice = interactionOn("map", nodes, mixed);
  expect(fedTwice).toMatchObject({ feeds: true });
  expect(fedTwice).not.toHaveProperty("drawFrom");
  // Linked but fed by roads alone: the map applies the log to its own layers.
  const notFed = [{ source: "roads", target: "map", sourceHandle: "out", targetHandle: "in_0" }, link];
  expect(interactionOn("map", nodes, notFed)).toMatchObject({ nodeId: "edit", feeds: false });
  expect(interactionOn("map", nodes, notFed)).not.toHaveProperty("drawFrom");
});

test("the node's code hands the step every circle that feeds it", () => {
  expect(circlesInto("edit", edges)).toBe(2);
  expect(circlesInto("roads", edges)).toBe(1);
  const code = editFeaturesCode({ edits: [{ op: "remove", ids: [7], layer: "input_0" }], keys: { input_0: "osm_id" } }, 2);
  expect(code).toContain("return curio_edit_features([input_0, input_1], [");
  expect(code).toContain("by_input=True)");
  expect(editFeaturesCode(undefined, 1)).toContain("return curio_edit_features(input_0, [])");
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

test("World Mercator there and back", () => {
  const [x, y] = toMercator([-87.63, 41.88]);
  expect(x).toBeCloseTo(-9754926.98, 1);
  const [lon, lat] = fromMercator([x, y]);
  expect(lon).toBeCloseTo(-87.63, 9);
  expect(lat).toBeCloseTo(41.88, 9);
});

test("a layer is called by its node's header as renamed, else by the node's title", () => {
  expect(circleTitles("edit", nodes, edges)).toEqual({ 0: "Roads", 1: "Parks" });
  const renamed = nodes.map((n) => (n.id === "roads" ? { ...n, data: { ...n.data, packageTemplateLabel: "Streets" } } : n));
  expect(circleTitles("edit", renamed, edges)).toEqual({ 0: "Streets", 1: "Parks" });
});
