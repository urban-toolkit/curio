import { layerIdFor, soloMapLayer } from "../../../adapters/node/autkMapState";

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
