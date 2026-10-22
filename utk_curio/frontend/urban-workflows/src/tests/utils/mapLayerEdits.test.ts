/**
 * An Interaction node and the Autark map it edits on (#662,
 * `utils/editFeatures/mapLayerEdits`): Data → Interaction → map on data
 * edges, and an interaction edge between the node and the map; which map a
 * node picks and draws on (one it feeds and is linked to), and how many
 * circles feed the node.
 */
import { circlesInto, circleTitles, feeds, isInteractionEdge, linkedMaps, mapFedBy } from "../../utils/editFeatures/mapLayerEdits";
import { editFeaturesCode } from "../../utils/editFeatures/editFeatures";
import { fromMercator, toMercator } from "../../utils/editFeatures/mapEditBus";

const nodes = [
  { id: "roads", type: "curio.builtin/data-loading", data: { title: "Roads" } },
  { id: "parks", type: "curio.builtin/data-loading", data: { title: "Parks" } },
  { id: "map", type: "curio.builtin/autk-grammar", data: {} },
  { id: "second", type: "curio.builtin/autk-grammar", data: {} },
  { id: "chart", type: "curio.builtin/vis-vega", data: {} },
  { id: "edit", type: "curio.builtin/edit-features", data: {} },
];
const link = { source: "edit", target: "map", sourceHandle: "in/out", targetHandle: "in/out", type: "BIDIRECTIONAL_EDGE" };
const edges = [
  { source: "roads", target: "edit", sourceHandle: "out", targetHandle: "in_0" },
  { source: "parks", target: "edit", sourceHandle: "out", targetHandle: "in_1" },
  { source: "edit", target: "map", sourceHandle: "out", targetHandle: "in_0" },
  link,
];

test("the node picks and draws on the map it feeds and is linked to, either way round", () => {
  expect(isInteractionEdge(link)).toBe(true);
  expect(isInteractionEdge(edges[2])).toBe(false);
  expect(feeds("edit", "map", edges)).toBe(true);
  expect(mapFedBy("edit", nodes, edges)).toBe("map");
  const backwards = [...edges.slice(0, 3), { ...link, source: "map", target: "edit" }];
  expect(mapFedBy("edit", nodes, backwards)).toBe("map");
});

test("a data edge alone links nothing, and a map linked but not fed is not the node's", () => {
  expect(mapFedBy("edit", nodes, edges.slice(0, 3))).toBeNull();
  // Linked to a second map it does not feed: still only the one it feeds.
  const second = { ...link, target: "second" };
  expect(linkedMaps("edit", nodes, [...edges, second])).toEqual(["map"]);
  expect(mapFedBy("edit", nodes, [...edges.slice(0, 2), second])).toBeNull();
  // Nor is a chart linked to it a map.
  expect(linkedMaps("edit", nodes, [...edges, { ...link, target: "chart" }, { source: "edit", target: "chart", sourceHandle: "out", targetHandle: "in" }])).toEqual(["map"]);
});

test("every map the node feeds and is linked to is one it edits on, in the order of their links", () => {
  const both = [...edges, { source: "edit", target: "second", sourceHandle: "out", targetHandle: "in" }, { ...link, target: "second" }];
  expect(linkedMaps("edit", nodes, both)).toEqual(["map", "second"]);
});

test("the node's code hands the step every circle that feeds it", () => {
  expect(circlesInto("edit", edges)).toBe(2);
  expect(circlesInto("roads", edges)).toBe(1);
  const code = editFeaturesCode({ edits: [{ op: "remove", ids: [7], layer: "input_0" }], keys: { input_0: "osm_id" } }, 2);
  expect(code).toContain("return curio_edit_features([input_0, input_1], [");
  expect(code).toContain("by_input=True)");
  expect(editFeaturesCode(undefined, 1)).toContain("return curio_edit_features(input_0, [])");
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
