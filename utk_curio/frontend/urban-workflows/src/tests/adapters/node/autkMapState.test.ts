import {
  drawnFeatureAt, layerIdFor, mapStateOf, pickingTableOf, showForEdits, snapshotBeforeSolo, soloMapLayer,
} from "../../../adapters/node/autkMapState";
import { INPUT_ROW } from "../../../utils/autkInput";

/** A map whose layers have *ids*, recording what each was set to. */
function fakeMap(ids: string[]) {
  const set: Record<string, Record<string, unknown>> = {};
  return {
    set,
    layerManager: { layers: ids.map((id) => ({ layerInfo: { id } })) },
    updateRenderInfo: (id: string, info: Record<string, unknown>) => {
      set[id] = { ...(set[id] ?? {}), ...info };
    },
    requestRender: () => undefined,
  };
}

const spec = {
  map: {
    layerRefs: [
      { dataRef: "input_0", title: "Social vulnerability" },
      { dataRef: "[!! input_1 !!]", title: "Building height (m)" },
      { dataRef: "input_2" },
    ],
  },
};

describe("layerIdFor", () => {
  test("a titled layer goes by its title, an untitled one by its table", () => {
    expect(layerIdFor(spec, "input_0")).toBe("Social vulnerability");
    expect(layerIdFor(spec, "input_1")).toBe("Building height (m)");
    expect(layerIdFor(spec, "input_2")).toBe("input_2");
    expect(layerIdFor(spec, "input_9")).toBe("input_9");
    expect(layerIdFor(null, "input_0")).toBe("input_0");
  });
});

test("showing a titled layer alone keeps it and hides the others", () => {
  // autk-grammar 4.2 ids: titles where there are titles.
  const map = fakeMap(["Social vulnerability", "Building height (m)", "input_2"]);
  soloMapLayer(map, layerIdFor(spec, "input_1"));
  expect(map.set["Building height (m)"]).toMatchObject({ isSkip: false, isPick: true });
  expect(map.set["Social vulnerability"]).toMatchObject({ isSkip: true });
  expect(map.set["input_2"]).toMatchObject({ isSkip: true });
});

/**
 * A map as autk-map keeps its layers, *picking* the one that picks: each
 * layer's render settings, and one picking layer at a time.
 */
function pickingMap(ids: string[], picking: string) {
  const layers = ids.map((id) => ({ layerInfo: { id }, layerRenderInfo: { isSkip: false, isPick: id === picking } as Record<string, unknown> }));
  const map = {
    layerManager: { layers },
    get activePickingLayer() {
      return layers.find((layer) => layer.layerRenderInfo.isPick) ?? null;
    },
    updateRenderInfo: (id: string, info: Record<string, unknown>) => {
      if (info.isPick === true) for (const layer of layers) layer.layerRenderInfo.isPick = false;
      Object.assign(layers.find((layer) => layer.layerInfo.id === id)!.layerRenderInfo, info);
    },
    requestRender: () => undefined,
  };
  /** Each layer: whether it is shown, and whether it picks. */
  const shown = () =>
    Object.fromEntries(layers.map((layer) => [layer.layerInfo.id, { shown: !layer.layerRenderInfo.isSkip, picks: !!layer.layerRenderInfo.isPick }]));
  return { map, grammar: { maps: [map] }, shown };
}

describe("the map as a Map Editor node feeding it asks", () => {
  test("an action makes its layer the one that picks, and ending it puts the document's back", () => {
    const { map, grammar, shown } = pickingMap(["buildings", "parks"], "parks");
    const before = snapshotBeforeSolo(grammar);
    showForEdits(map, null, { solo: null, picking: "buildings" }, before);
    expect(shown()).toEqual({ buildings: { shown: true, picks: true }, parks: { shown: true, picks: false } });
    showForEdits(map, { solo: null, picking: "buildings" }, { solo: null, picking: null }, before);
    expect(shown()).toEqual({ buildings: { shown: true, picks: false }, parks: { shown: true, picks: true } });
  });

  test("Show only this layer turned on and off during an action leaves the action's layer the one that picks", () => {
    const { map, grammar, shown } = pickingMap(["buildings", "parks"], "parks");
    const before = snapshotBeforeSolo(grammar);
    showForEdits(map, null, { solo: null, picking: "buildings" }, before);
    showForEdits(map, { solo: null, picking: "buildings" }, { solo: "buildings", picking: "buildings" }, before);
    expect(shown()).toEqual({ buildings: { shown: true, picks: true }, parks: { shown: false, picks: false } });
    showForEdits(map, { solo: "buildings", picking: "buildings" }, { solo: null, picking: "buildings" }, before);
    expect(shown()).toEqual({ buildings: { shown: true, picks: true }, parks: { shown: true, picks: false } });
    showForEdits(map, { solo: null, picking: "buildings" }, { solo: null, picking: null }, before);
    expect(shown()).toEqual({ buildings: { shown: true, picks: false }, parks: { shown: true, picks: true } });
  });

  test("an action ended puts back only the layer that picked: a layer hidden meanwhile through the map's menu stays hidden", () => {
    const { map, grammar, shown } = pickingMap(["buildings", "parks"], "parks");
    const before = snapshotBeforeSolo(grammar);
    showForEdits(map, null, { solo: null, picking: "buildings" }, before);
    map.updateRenderInfo("parks", { isSkip: true });
    showForEdits(map, { solo: null, picking: "buildings" }, { solo: null, picking: null }, before);
    expect(shown()).toEqual({ buildings: { shown: true, picks: false }, parks: { shown: false, picks: true } });
  });

  test("a map drawn again during an action picks on the action's layer and keeps what was set on its layers", () => {
    const { map, shown } = pickingMap(["buildings", "parks"], "parks");
    // Hidden through the map's menu during the action, and kept across the draw.
    map.updateRenderInfo("parks", { isSkip: true });
    showForEdits(map, null, { solo: null, picking: "buildings" }, { buildings: { isSkip: false }, parks: { isSkip: false, isPick: true } });
    expect(shown()).toEqual({ buildings: { shown: true, picks: true }, parks: { shown: false, picks: false } });
  });
});

/**
 * A grammar whose one map draws *layers*, the one of id *picking* the layer
 * that picks, each found by its table as autk-grammar finds it (`mapLayer`).
 */
function drawnGrammar(layers: any[], picking: string | null = null) {
  const map = {
    layerManager: { layers, origin: [100, 200] },
    get activePickingLayer() {
      return layers.find((layer) => layer.layerInfo.id === picking) ?? null;
    },
  };
  return {
    maps: [map],
    mapLayer: (table: string) => {
      const layerId = layerIdFor(spec, table);
      return layers.some((layer) => layer.layerInfo.id === layerId) ? { map, layerId } : undefined;
    },
  };
}

describe("pickingTableOf", () => {
  const layers = ["Social vulnerability", "Building height (m)", "input_2"].map((id) => ({ layerInfo: { id } }));

  test("a pick is on the layer that picks now, not the document's first that may", () => {
    expect(pickingTableOf(drawnGrammar(layers, "input_2"), spec, "input_0")).toBe("input_2");
    expect(pickingTableOf(drawnGrammar(layers, "Building height (m)"), spec, "input_0")).toBe("input_1");
  });

  test("guard: a map with no layer that picks names none", () => {
    expect(pickingTableOf(drawnGrammar(layers, null), spec, "input_0")).toBeNull();
    expect(pickingTableOf(null, spec, "input_0")).toBeNull();
  });
});

describe("what a map draws and lights, as autk-map and autk-db hold it", () => {
  // autk-db exported three trees; autk-map drew none for the second, and holds
  // each point less the map's origin, [100, 200].
  const tree = (name: string, x: number, y: number, row: number) => ({
    type: "Feature", geometry: { type: "Point", coordinates: [x, y] }, properties: { name, [INPUT_ROW]: row },
  });
  const exported = [tree("oak", 110, 210, 4), tree("elm", 120, 220, 2), tree("ash", 130, 230, 7)];
  const trees = () => ({
    layerInfo: { id: "input_2" },
    layerRenderInfo: { isPick: true },
    components: [{ featureIndex: 0, nPoints: 1 }, { featureIndex: 2, nPoints: 2 }],
    pointInstances: new Float32Array([10, 10, 30, 30]),
    highlightedIds: [1],
  });
  const readBack = (features: any[]) => ({
    features: () => Promise.resolve(features),
    rows: () => Promise.resolve([4, 7]),
  });

  test("a layer lights the feature it drew there, without the row Curio tags it with", async () => {
    expect(await mapStateOf(drawnGrammar([trees()]), spec, readBack(exported))).toEqual({
      input_2: { pick: true, lit: [{ name: "ash" }], positions: [1], drawn: 2, rows: 2, pointDrift: 0 },
    });
  });

  test("guard: features read back in another order than the map was handed lie away from its points", async () => {
    const state = await mapStateOf(drawnGrammar([trees()]), spec, readBack([...exported].reverse()));
    expect(state!.input_2.pointDrift).toBeGreaterThan(20);
  });

  test("the feature a layer draws at a position, counted from the end when negative", () => {
    const grammar = drawnGrammar([trees()]);
    expect(drawnFeatureAt(grammar, "input_2", exported, 0)).toEqual({ name: "oak" });
    expect(drawnFeatureAt(grammar, "input_2", exported, -1)).toEqual({ name: "ash" });
    expect(drawnFeatureAt(grammar, "input_2", exported, 2)).toBeNull();
    expect(drawnFeatureAt(grammar, "input_0", exported, 0)).toBeNull();
  });
});
