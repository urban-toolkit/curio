/**
 * A building's height where a node uses it (utils/autkInput).
 *
 * Curio's loaders hand a building part with no height on with none. A node
 * takes it to be 6 m tall above its base where a number is used: in a table
 * a map layer draws, which autk-map extrudes and colors by its height, and in
 * one a compute pass reads. A table a layer with `buildingsZeroHeight` draws
 * keeps none, and holds no key of a height that holds no number, so autk-map
 * raises its parts with no height at its own random 3 to 7 floors. A table only
 * a plot reads keeps the heights it holds. A compute step hands on a table a
 * pass wrote over its buildings with each building's own height.
 */
import type { FeatureCollection } from "geojson";

import * as autkInput from "../../utils/autkInput";

/** Read off the module, so a checkout without them fails each case on its own. */
const {
  heightUses, heightsAtUse, withDefaultHeights, withHeightsAsHeld, withoutEmptyBuildingHeights, zeroHeightTables,
} = autkInput as any;

const collection = (...properties: object[]): FeatureCollection => ({
  type: "FeatureCollection",
  features: properties.map((props, i) => ({
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [[[i, 0], [i + 1, 0], [i + 1, 1], [i, 0]]] },
    properties: props,
  })),
} as FeatureCollection);

const propertiesOf = (fc: any) => fc.features.map((feature: any) => feature.properties);

const buildings = (name: string, fc: FeatureCollection, more: object = {}) => ({
  type: "geojson", outputTableName: name, geojsonObject: fc, coordinateFormat: "EPSG:3395", layerType: "buildings", ...more,
});

describe("where a document uses its tables' heights", () => {
  test("a layer with buildingsZeroHeight names its table, by key, in its map's workspace", () => {
    const spec = {
      map: [
        { layerRefs: [{ dataRef: "a", buildingsZeroHeight: true }, { dataRef: "b" }, { dataRef: "c", buildingsZeroHeight: false }] },
        { workspace: "east", layerRefs: [{ dataRef: "d", buildingsZeroHeight: true }] },
      ],
    };
    expect([...zeroHeightTables(spec)].sort()).toEqual(["a", "east/d"]);
  });

  test("a map layer and every table a pass reads use the default, but a table a layer with buildingsZeroHeight draws", () => {
    const uses = heightUses({
      map: { layerRefs: [{ dataRef: "towers" }, { dataRef: "zero", buildingsZeroHeight: true }, { dataRef: "zero" }] },
      plot: { dataRef: "plotted", mark: "bar", axis: ["height"] },
      compute: [
        { dataRef: "roads", uniforms: { h: { fromFeature: { layer: "blocks", iterate: "batched", path: "properties.height" } } } },
        { type: "windows", dataRef: "walls", floors: 3, outputTableName: "windows", workspace: "east" },
        { type: "render", viewpoints: { dataRef: "streets" }, layers: [{ id: "b", dataRef: "solids", type: "buildings" }] },
      ],
    });
    expect([...uses.numbered].sort()).toEqual(["blocks", "east/walls", "roads", "solids", "streets", "towers"]);
    expect([...uses.zero]).toEqual(["zero"]);
    expect([...uses.asBuildings]).toEqual(["solids"]);
  });

  test("a layer that draws a table as buildings makes it a buildings table", () => {
    const uses = heightUses({ map: { layerRefs: [{ dataRef: "footprints", layerType: "buildings" }] } });
    expect([...uses.asBuildings]).toEqual(["footprints"]);
  });
});

describe("a buildings table as a node hands it to its grammar", () => {
  const ROWS = collection({ height: 12 }, {}, { height: null }, { min_height: 4 }, { height: null, "building:levels": 2 });

  test("a table a map layer draws or a pass reads holds a part with no height 6 m above its base", () => {
    const uses = heightUses({ map: { layerRefs: [{ dataRef: "towers" }] } });
    const handed = heightsAtUse(buildings("towers", ROWS), uses);
    expect(propertiesOf(handed.geojsonObject)).toEqual([
      { height: 12 }, { height: 6 }, { height: 6 }, { min_height: 4, height: 10 }, { height: 2 * 3.4, "building:levels": 2 },
    ]);
    // The table the node holds is left as it is.
    expect(propertiesOf(ROWS)[1]).toEqual({});
  });

  test("a table a layer with buildingsZeroHeight draws holds no key of a height with no number", () => {
    const uses = heightUses({
      map: { layerRefs: [{ dataRef: "towers", buildingsZeroHeight: true }] },
      compute: [{ dataRef: "roads", uniforms: { h: { fromFeature: { layer: "towers", iterate: "batched", path: "properties.height" } } } }],
    });
    const handed = heightsAtUse(buildings("towers", ROWS), uses);
    expect(propertiesOf(handed.geojsonObject)).toEqual([
      { height: 12 }, {}, {}, { min_height: 4 }, { "building:levels": 2 },
    ]);
  });

  test("a table only a plot reads, and a table of another kind, is the same object", () => {
    const uses = heightUses({ plot: { dataRef: "towers", mark: "bar", axis: ["height"] }, map: { layerRefs: [{ dataRef: "lots" }] } });
    const plotted = buildings("towers", ROWS);
    expect(heightsAtUse(plotted, uses)).toBe(plotted);
    const lots = { ...buildings("lots", ROWS), layerType: "polygons" };
    expect(heightsAtUse(lots, uses)).toBe(lots);
    const raster = { type: "raster", outputTableName: "towers" };
    expect(heightsAtUse(raster, uses)).toBe(raster);
  });

  test("a polygons table a layer draws as buildings is a buildings table", () => {
    const uses = heightUses({ map: { layerRefs: [{ dataRef: "lots", layerType: "buildings" }] } });
    const handed = heightsAtUse({ ...buildings("lots", ROWS), layerType: "polygons" }, uses);
    expect(propertiesOf(handed.geojsonObject)[1]).toEqual({ height: 6 });
  });

  test("a table in a workspace is told apart by its key", () => {
    const uses = heightUses({ map: { workspace: "east", layerRefs: [{ dataRef: "towers", buildingsZeroHeight: true }] } });
    const east = heightsAtUse(buildings("towers", ROWS, { workspace: "east" }), uses);
    expect(propertiesOf(east.geojsonObject)[2]).toEqual({});
    const plain = buildings("towers", ROWS);
    expect(heightsAtUse(plain, uses)).toBe(plain);
  });

  test("the table-wide helpers keep a table with nothing to change as the same object", () => {
    const tall = collection({ height: 12 }, { "building:levels": 3, height: 10.2 });
    expect(withDefaultHeights(tall)).toBe(tall);
    expect(withoutEmptyBuildingHeights(tall)).toBe(tall);
  });
});

describe("a table a compute step's pass wrote over its buildings, as the step hands it on", () => {
  test("a building with no height holds none again, and keeps what the pass computed", () => {
    const held = collection({ height: 12, a: 1 }, { a: 2 }, { height: null, a: 3 });
    const computed = {
      type: "FeatureCollection",
      features: withDefaultHeights(held).features.map((feature: any) => ({
        ...feature, properties: { ...feature.properties, compute: { shade: feature.properties.height * 2 } },
      })),
    } as FeatureCollection;
    expect(propertiesOf(computed).map((p: any) => p.height)).toEqual([12, 6, 6]);
    expect(propertiesOf(withHeightsAsHeld(computed, held))).toEqual([
      { height: 12, a: 1, compute: { shade: 24 } },
      { a: 2, compute: { shade: 12 } },
      { height: null, a: 3, compute: { shade: 12 } },
    ]);
  });

  test("a table of another length than the one it was computed over is the same object", () => {
    const held = collection({ a: 1 }, { a: 2 });
    const windows = collection({ height: 3 }, { height: 3 }, { height: 3 });
    expect(withHeightsAsHeld(windows, held)).toBe(windows);
  });
});
