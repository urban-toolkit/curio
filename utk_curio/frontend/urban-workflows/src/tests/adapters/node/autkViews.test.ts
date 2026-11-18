/**
 * An Autark node's run reads its views as a list (adapters/node/autkViews,
 * autkMapState): each map and each plot of the document, known by the key
 * autk-grammar knows it by, a map's `id` else its index and a plot's `id`
 * else its `dataRef`. A highlight lights each map's layers on that map alone,
 * and a pick is read from the map that picked.
 *
 * A node draws one view while the one-view rule stands, so these tests drive
 * the per-view helpers with a grammar that drew two maps (`grammarThatRan`,
 * whose highlights address one map as autk-grammar 5.0.0's do), and two
 * plots where it matters. The modules are loaded in each test, so a checkout
 * without them fails each test on its own.
 */
import { grammarThatRan } from "../../_support/autkGrammarMaps";

const views = () =>
  require("../../../adapters/node/autkViews") as {
    mapEntries: (spec: unknown) => any[];
    plotEntries: (spec: unknown) => any[];
    mapKey: (entry: unknown, index: number) => string | number;
    plotKey: (entry: unknown) => string;
    mapIndexOf: (spec: unknown, mapId: unknown) => number;
    plotEntryOf: (spec: unknown, plotId: unknown) => { index: number; entry: any } | null;
    pickLayerOf: (entry: unknown) => string | undefined;
    mapLayerRefs: (spec: unknown) => Array<{ index: number; entry: any; ref: any }>;
    lightMaps: (
      grammar: unknown,
      spec: unknown,
      positionsOf: (layer: { index: number; entry: any; ref: any }, at: number) => number[],
    ) => void;
  };

const mapState = () =>
  require("../../../adapters/node/autkMapState") as {
    pickOn: (grammar: unknown, spec: unknown, mapId: unknown) => { index: number; entry: any; table: string | undefined } | null;
  };

/** A map as autk-map keeps it for a highlight: what each of its layers lights, by layer id. */
function litMap() {
  const lit: Record<string, number[]> = {};
  const map = {
    setHighlightedIds: (layerId: string, ids: number[]) => { lit[layerId] = [...ids]; },
    clearHighlightedIds: (layerId: string) => { delete lit[layerId]; },
  };
  return { map, lit };
}

/** Two maps of one table, each in a workspace of its own: the second has an id. */
const TWO_MAPS_OF_ONE_TABLE = {
  map: [
    { workspace: "north", layerRefs: [{ dataRef: "trees" }] },
    { id: "south", workspace: "south", layerRefs: [{ dataRef: "trees" }] },
  ],
};

describe("the views a document draws", () => {
  test("a map or plot written as one object is a list of one, and none is an empty list", () => {
    const map = { layerRefs: [{ dataRef: "trees" }] };
    expect(views().mapEntries({ map })).toEqual([map]);
    expect(views().mapEntries({ map: [map, map] })).toEqual([map, map]);
    expect(views().mapEntries({})).toEqual([]);
    expect(views().plotEntries({ plot: { dataRef: "trees" } })).toEqual([{ dataRef: "trees" }]);
    expect(views().plotEntries(null)).toEqual([]);
  });

  test("a map is known by its id, else its index, and a mapId finds it either way", () => {
    expect(views().mapKey(TWO_MAPS_OF_ONE_TABLE.map[0], 0)).toBe(0);
    expect(views().mapKey(TWO_MAPS_OF_ONE_TABLE.map[1], 1)).toBe("south");
    expect(views().mapIndexOf(TWO_MAPS_OF_ONE_TABLE, 0)).toBe(0);
    expect(views().mapIndexOf(TWO_MAPS_OF_ONE_TABLE, 1)).toBe(1);
    expect(views().mapIndexOf(TWO_MAPS_OF_ONE_TABLE, "south")).toBe(1);
    // A name of no map, an index past the last, and no name at all find none.
    expect(views().mapIndexOf(TWO_MAPS_OF_ONE_TABLE, "east")).toBe(-1);
    expect(views().mapIndexOf(TWO_MAPS_OF_ONE_TABLE, 2)).toBe(-1);
    expect(views().mapIndexOf(TWO_MAPS_OF_ONE_TABLE, undefined)).toBe(-1);
  });

  test("two plots of one table with ids are two views, each found by its id", () => {
    const spec = {
      plot: [
        { id: "heights", dataRef: "trees", mark: "bar" },
        { id: "species", dataRef: "trees", mark: "bar" },
      ],
    };
    expect(views().plotEntries(spec).map(views().plotKey)).toEqual(["heights", "species"]);
    expect(views().plotEntryOf(spec, "species")).toEqual({ index: 1, entry: spec.plot[1] });
    // A plot without an id is known by its table.
    expect(views().plotKey({ dataRef: "trees" })).toBe("trees");
    expect(views().plotEntryOf({ plot: { dataRef: "trees" } }, "trees")).toEqual({ index: 0, entry: { dataRef: "trees" } });
    expect(views().plotEntryOf(spec, "trees")).toBeNull();
  });

  test("each layer of each map is listed with the index of its map", () => {
    expect(views().mapLayerRefs(TWO_MAPS_OF_ONE_TABLE).map(({ index, entry, ref }) => [index, entry.workspace, ref.dataRef]))
      .toEqual([[0, "north", "trees"], [1, "south", "trees"]]);
  });

  test("a map's own picking layer is its first that picks, else its first", () => {
    expect(views().pickLayerOf({ layerRefs: [{ dataRef: "roads" }, { dataRef: "parks", isPick: true }] })).toBe("parks");
    expect(views().pickLayerOf({ layerRefs: [{ dataRef: "roads" }, { dataRef: "parks" }] })).toBe("roads");
    expect(views().pickLayerOf({ layerRefs: [] })).toBeUndefined();
  });
});

describe("a highlight lights each map alone", () => {
  test("two maps of one table, in two workspaces, each light only their own rows", () => {
    const north = litMap();
    const south = litMap();
    const grammar = grammarThatRan(TWO_MAPS_OF_ONE_TABLE, north.map, south.map);

    views().lightMaps(grammar, TWO_MAPS_OF_ONE_TABLE, ({ index }) => (index === 0 ? [1] : [0, 2]));
    expect(north.lit).toEqual({ trees: [1] });
    expect(south.lit).toEqual({ trees: [0, 2] });

    // A map whose layer lights nothing is cleared, and the other keeps its rows.
    views().lightMaps(grammar, TWO_MAPS_OF_ONE_TABLE, ({ index }) => (index === 0 ? [] : [2]));
    expect(north.lit).toEqual({});
    expect(south.lit).toEqual({ trees: [2] });
  });

  test("each layer is asked for its rows once, in the order the maps list them", () => {
    const asked: Array<[number, string, number]> = [];
    const spec = { map: [{ layerRefs: [{ dataRef: "roads" }, { dataRef: "trees" }] }, { layerRefs: [{ dataRef: "trees" }] }] };
    views().lightMaps(grammarThatRan(spec, litMap().map, litMap().map), spec, ({ index, ref }, at) => {
      asked.push([index, ref.dataRef, at]);
      return [];
    });
    expect(asked).toEqual([[0, "roads", 0], [0, "trees", 1], [1, "trees", 2]]);
  });
});

describe("a pick is read from the map that picked", () => {
  /** A map whose picking layer is *picking*, as autk-map keeps it. */
  const pickingMap = (picking: string | null) => ({ activePickingLayer: picking ? { layerInfo: { id: picking } } : null });
  /** Two maps whose layers share a title: each draws another table under it. */
  const spec = {
    map: [
      { layerRefs: [{ dataRef: "roads", title: "Streets", isPick: true }, { dataRef: "parks" }] },
      { id: "detail", workspace: "south", layerRefs: [{ dataRef: "lanes", title: "Streets" }, { dataRef: "trees", isPick: true }] },
    ],
  };

  test("a pick on the second map names its table, though the first map's layer has the same title", () => {
    const grammar = grammarThatRan(spec, pickingMap("Streets"), pickingMap("Streets"));
    expect(mapState().pickOn(grammar, spec, "detail")).toEqual({ index: 1, entry: spec.map[1], table: "lanes" });
    expect(mapState().pickOn(grammar, spec, 1)).toEqual({ index: 1, entry: spec.map[1], table: "lanes" });
    expect(mapState().pickOn(grammar, spec, 0)).toEqual({ index: 0, entry: spec.map[0], table: "roads" });
  });

  test("a map with no layer picking now names its entry's own picking layer", () => {
    const grammar = grammarThatRan(spec, pickingMap("Streets"), pickingMap(null));
    expect(mapState().pickOn(grammar, spec, "detail")).toEqual({ index: 1, entry: spec.map[1], table: "trees" });
  });

  test("a pick that names no map is the first map's, and one that names a map the document has not is none", () => {
    const grammar = grammarThatRan(spec, pickingMap("parks"), pickingMap("Streets"));
    expect(mapState().pickOn(grammar, spec, undefined)).toEqual({ index: 0, entry: spec.map[0], table: "parks" });
    expect(mapState().pickOn(grammar, spec, "east")).toBeNull();
  });
});
