import { layerIdFor, showForEdits, snapshotBeforeSolo, soloMapLayer } from "../../../adapters/node/autkMapState";

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

describe("the map as a Map Edits node feeding it asks", () => {
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

  test("a map drawn again during an action picks on the action's layer and keeps what was set on its layers", () => {
    const { map, shown } = pickingMap(["buildings", "parks"], "parks");
    // Hidden through the map's menu during the action, and kept across the draw.
    map.updateRenderInfo("parks", { isSkip: true });
    showForEdits(map, null, { solo: null, picking: "buildings" }, { buildings: { isSkip: false }, parks: { isSkip: false, isPick: true } });
    expect(shown()).toEqual({ buildings: { shown: true, picks: true }, parks: { shown: false, picks: false } });
  });
});
