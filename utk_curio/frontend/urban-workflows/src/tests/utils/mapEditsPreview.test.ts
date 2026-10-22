/**
 * What an Autark map draws when Interaction nodes feed it (#662,
 * `utils/editFeatures/mapEditsPreview`): each circle an Interaction node feeds
 * is drawn from that node's input with the edits its code holds, as the
 * node's run hands it on, under the names the map reads the run's output by;
 * every other circle draws as it came. A map fed by two Interaction nodes
 * takes each one's edits on the circle it feeds.
 */
import { autkSourcesFrom } from "../../utils/autkInput";
import type { GrammarFrame, GrammarInput } from "../../utils/grammarInput";
import { editFeaturesCode } from "../../utils/editFeatures/editFeatures";
import { drawnInput, editedOutput, editFeedsOf, fedByInteraction, feedsVersion, mapTableName, newLayerTables } from "../../utils/editFeatures/mapEditsPreview";

const square = (x: number) => ({ type: "Polygon", coordinates: [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]] });
const fc = (ids: number[], key = "building_id") => ({
  type: "FeatureCollection",
  features: ids.map((id, i) => ({ type: "Feature", geometry: square(i), properties: { [key]: id, height: 10 * id } })),
});

/** A frame as the map's input reader makes it. */
function frame(payload: any, place: Partial<GrammarFrame> = {}): GrammarFrame {
  return { name: null, dataType: "geodataframe", payload, schema: null, geometryName: null, crsName: null, fromBundle: false, index: 0, circle: 0, ...place };
}

const BUILDINGS_IN = { path: "art-buildings", dataType: "geodataframe" };
const TREES_IN = { path: "art-trees", dataType: "geodataframe" };
const readOf = (map: Map<unknown, GrammarInput>) => async (input: unknown) => map.get(input) ?? { frames: [] };

/** A map fed on three circles: an Interaction node on buildings, a loader, an Interaction node on trees. */
function canvas(codeA: string, codeB: string) {
  const nodes = [
    { id: "a", type: "curio.builtin/edit-features", data: { input: BUILDINGS_IN, code: codeA } },
    { id: "loader", type: "curio.builtin/data-loading", data: {} },
    { id: "b", type: "curio.builtin/edit-features", data: { input: TREES_IN, code: codeB } },
    { id: "map", type: "curio.builtin/autk-grammar", data: {} },
  ];
  const edges = [
    { source: "a", target: "map", sourceHandle: "out", targetHandle: "in" },
    { source: "loader", target: "map", sourceHandle: "out", targetHandle: "in_1" },
    { source: "b", target: "map", sourceHandle: "out", targetHandle: "in_2" },
    { source: "a", target: "map", sourceHandle: "in/out", targetHandle: "in/out", type: "BIDIRECTIONAL_EDGE" },
  ];
  return { nodes, edges };
}

const REMOVE_1 = editFeaturesCode({ key: "building_id", layer: "input_0", edits: [{ op: "remove", ids: [1] }] });
const REMOVE_7 = editFeaturesCode({ key: "tree_id", layer: "input_0", edits: [{ op: "remove", ids: [7] }] });

test("the circles Interaction nodes feed, each with the edits its code holds; a node whose code it cannot read draws as it came", () => {
  const { nodes, edges } = canvas(REMOVE_1, REMOVE_7);
  expect(fedByInteraction("map", nodes, edges)).toBe(true);
  expect(fedByInteraction("loader", nodes, edges)).toBe(false);
  const feeds = editFeedsOf("map", nodes, edges);
  expect(feeds.map((feed) => [feed.nodeId, feed.position, feed.several, feed.circles])).toEqual([["a", 0, true, 1], ["b", 2, true, 1]]);
  expect(feeds[0].settings?.edits).toEqual([{ op: "remove", ids: [1] }]);
  // Code of another shape: still fed by an Interaction node, but drawn as fed.
  const hand = canvas("return input_0\n", REMOVE_7);
  expect(fedByInteraction("map", hand.nodes, hand.edges)).toBe(true);
  expect(editFeedsOf("map", hand.nodes, hand.edges).map((feed) => feed.nodeId)).toEqual(["b"]);
  // An edit is a new version of what the map draws.
  const edited = canvas(editFeaturesCode({ key: "building_id", layer: "input_0", edits: [{ op: "remove", ids: [2] }] }), REMOVE_7);
  expect(feedsVersion(editFeedsOf("map", edited.nodes, edited.edges))).not.toBe(feedsVersion(feeds));
});

test("a map fed by two Interaction nodes takes each one's edits on the circle it feeds, the loader's as it came", async () => {
  const { nodes, edges } = canvas(REMOVE_1, REMOVE_7);
  const feeds = editFeedsOf("map", nodes, edges);
  // The map's own input: the outputs the two nodes' last runs made, and the loader's.
  const own: GrammarInput = {
    frames: [
      frame(fc([1, 2]), { fromBundle: true, index: 0, circle: 0 }),
      frame(fc([5]), { fromBundle: true, index: 1, circle: 1 }),
      frame(fc([7, 8], "tree_id"), { fromBundle: true, index: 2, circle: 2 }),
    ],
  };
  const reads = new Map<unknown, GrammarInput>([
    [BUILDINGS_IN, { frames: [frame(fc([1, 2, 3]))] }],
    [TREES_IN, { frames: [frame(fc([7, 8, 9], "tree_id"))] }],
  ]);
  const drawn = await drawnInput(own, feeds, readOf(reads));
  const sources = autkSourcesFrom(drawn, { map: { layerRefs: [] } }).sources;
  const ids = Object.fromEntries(sources.map((s) => [s.outputTableName, s.geojsonObject.features.map((f: any) => f.properties.building_id ?? f.properties.tree_id)]));
  // Each circle under the name the map reads the run's output by.
  expect(ids).toEqual({ input_0: [2, 3], input_1: [5], input_2: [8, 9] });
  expect(mapTableName("input_0", false, feeds[1])).toBe("input_2");
});

test("a node's run hands on its input as it came with no edits, one unnamed table edited, every layer named by circle, and its new layers after", () => {
  const read: GrammarInput = { frames: [frame(fc([1, 2]))] };
  expect(editedOutput(read, { settings: undefined, circles: 1 })).toBeNull();
  // One table: edited, still unnamed, as a table comes back.
  expect(editedOutput(read, { settings: { key: "building_id", edits: [{ op: "remove", ids: [1] }] }, circles: 1 })).toMatchObject({
    dataType: "geodataframe",
    data: { features: [{ properties: { building_id: 2 } }] },
  });
  expect((editedOutput(read, { settings: { key: "building_id", edits: [{ op: "remove", ids: [1] }] }, circles: 1 }) as any).layerName).toBeUndefined();
  // Several circles: every layer named after its circle, edited or not.
  const two: GrammarInput = {
    frames: [frame(fc([1, 2]), { fromBundle: true, index: 0, circle: 0 }), frame(fc([7], "tree_id"), { fromBundle: true, index: 1, circle: 1 })],
  };
  const byInput = editedOutput(two, { settings: { keys: { input_0: "building_id" }, edits: [{ op: "remove", layer: "input_0", ids: [2] }] }, circles: 2 }) as any;
  expect(byInput.dataType).toBe("outputs");
  expect(byInput.data.map((item: any) => item.layerName)).toEqual(["input_0", "input_1"]);
  expect(byInput.data[0].data.features.map((f: any) => f.properties.building_id)).toEqual([1]);
  // A new layer, its drawn point in the CRS the node drew in, an entry switched off skipped.
  const made = editedOutput(read, {
    settings: {
      key: "building_id",
      layer: "input_0",
      crs: "EPSG:4326",
      newLayers: [{ name: "cooling_centers", geometry: "Point" }],
      edits: [
        { op: "add", layer: "cooling_centers", id: "c1", geometry: { type: "Point", coordinates: [-87.63, 41.88] }, values: { name: "Library" } },
        { op: "remove", ids: [1], enabled: false },
      ],
    },
    circles: 1,
  }) as any;
  expect(made.data.map((item: any) => item.layerName)).toEqual([undefined, "cooling_centers"]);
  expect(made.data[0].data.features).toHaveLength(2);
  expect(made.data[1]).toMatchObject({
    layerType: "points",
    data: {
      crs: { type: "name", properties: { name: "urn:ogc:def:crs:EPSG::4326" } },
      features: [{ type: "Feature", geometry: { type: "Point", coordinates: [-87.63, 41.88] }, properties: { name: "Library", id: "c1" } }],
    },
  });
  expect(newLayerTables([{ nodeId: "a", position: 0, several: false, input: null, circles: 1, settings: { newLayers: [{ name: "cooling_centers", geometry: "Point" }] } }])).toEqual(["cooling_centers"]);
});

test("a node not fed yet, or whose input cannot be read, leaves its circle as the map was fed", async () => {
  const { nodes, edges } = canvas(REMOVE_1, REMOVE_7);
  const unfed = nodes.map((n) => (n.id === "a" ? { ...n, data: { ...n.data, input: "" } } : n));
  expect(editFeedsOf("map", unfed, edges).map((feed) => feed.nodeId)).toEqual(["b"]);
  const own: GrammarInput = { frames: [frame(fc([1, 2]), { fromBundle: true, index: 0, circle: 0 })] };
  const feeds = editFeedsOf("map", nodes, edges).slice(0, 1);
  const refused = await drawnInput(own, feeds, async () => ({ frames: [], emptyReason: "input-type-rejected", detail: "no" }));
  expect(refused).toBe(own);
});
