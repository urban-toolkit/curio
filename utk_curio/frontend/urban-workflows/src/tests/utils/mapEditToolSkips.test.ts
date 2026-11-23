/**
 * A Map Editor node's tools draw the feature they reshape or move, and hide it
 * in its own layer meanwhile (utils/editFeatures/mapEditLayers,
 * `showMapEditTools`). The layer can already hide features of its own: those
 * its document's `skippedComps` names (autk-grammar 5.3.0). The tools hide
 * their feature beside those, and put the layer's own back when they stop.
 * They hide it on a layer of points too: autk-map's own `AutkMap.setSkippedIds`
 * passes over points layers, so the tools call the layer's.
 *
 * The map stands in for autk-map's, as it keeps a layer's hidden features:
 * each layer toggles the positions it is given into a set of its own, and the
 * map's `setSkippedIds` and `clearSkippedIds` reach vector layers only.
 */
import { showMapEditTools, type MapEditTools } from "../../utils/editFeatures/mapEditLayers";

/** A layer of autk-map that hides features: a vector layer, or a points layer when *points*. */
function skippingLayer(id: string, points: boolean, own: number[] = []) {
  const skipped = new Set<number>(own);
  return {
    points,
    layerInfo: { id, typeLayer: points ? "points" : "polygons" },
    layerRenderInfo: {},
    // A vector layer reads its set back; a points layer keeps it to itself.
    ...(points ? { _skippedIds: skipped } : { get skippedIds() { return [...skipped]; } }),
    setSkippedIds: (ids: number[]) => {
      for (const id of ids) {
        if (skipped.has(id)) skipped.delete(id);
        else skipped.add(id);
      }
    },
    clearSkippedIds: () => skipped.clear(),
    hidden: () => [...skipped].sort((a, b) => a - b),
  };
}

/** A map of *layers*, whose own skip calls reach its vector layers only, as autk-map's do. */
function skippingMap(...layers: Array<ReturnType<typeof skippingLayer>>) {
  const find = (id: string) => layers.find((layer) => layer.layerInfo.id === id) ?? null;
  return {
    layerManager: { layers, searchByLayerId: find },
    loadCollection: jest.fn(),
    removeLayer: jest.fn(),
    updateRenderInfo: jest.fn(),
    requestRender: jest.fn(),
    setSkippedIds: (id: string, ids: number[]) => {
      const layer = find(id);
      if (layer && !layer.points) layer.setSkippedIds(ids);
    },
    clearSkippedIds: (id: string) => {
      const layer = find(id);
      if (layer && !layer.points) layer.clearSkippedIds();
    },
  };
}

/** The tools while they reshape the feature *layer* draws at *positions*: nothing else drawn. */
const hiding = (layer: string, positions: number[]): MapEditTools => ({
  shapes: [], path: [], corners: [], midpoints: [], hidden: { layer, positions },
});

test("the tools hide the feature they draw beside the features the layer hides itself, and put those back when they stop", () => {
  const zones = skippingLayer("zones", false, [1, 2]);
  const map = skippingMap(zones);

  showMapEditTools(map, hiding("zones", [3]), false);
  expect(zones.hidden()).toEqual([1, 2, 3]);

  // Another feature: the first is shown again, the layer's own stay hidden.
  showMapEditTools(map, hiding("zones", [0]), false);
  expect(zones.hidden()).toEqual([0, 1, 2]);

  showMapEditTools(map, null, false);
  expect(zones.hidden()).toEqual([1, 2]);
});

test("the tools hide a point they move on a layer of points, and show it again when they stop", () => {
  const stops = skippingLayer("stops", true, [4]);
  const map = skippingMap(stops);

  showMapEditTools(map, hiding("stops", [0]), false);
  expect(stops.hidden()).toEqual([0, 4]);

  showMapEditTools(map, null, false);
  expect(stops.hidden()).toEqual([4]);
});
