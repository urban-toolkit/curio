/**
 * A building's height as autk-map extrudes it: autk-map reads the first height
 * key a building has, whatever its value, and a table gives every row every key.
 * A building with no height keeps none in the data; where a number is used, a
 * map draws it and a pass reads it 6 m tall above its base.
 */
import * as buildingHeight from "../../utils/buildingHeight";
import { deriveBuildingHeight, readableBuildingProperties } from "../../utils/buildingHeight";

/** The functions this branch adds, read off the module, so a checkout without them fails each case on its own. */
const { withDefaultHeight, withoutEmptyHeights } = buildingHeight as any;

describe("readableBuildingProperties", () => {
  test("a height autk-map already reads is left alone, the same object", () => {
    for (const props of [
      { height: 12 },
      { height: "12" },
      { height: "40 ft" },
      { height: 20, "building:min_level": 2 },
    ]) {
      expect(readableBuildingProperties(props)).toBe(props);
    }
  });

  test("a building with no height key gets the one autk-map draws, so a compute reads it too (#757)", () => {
    const levels: Record<string, any> = readableBuildingProperties({ "building:levels": 3 });
    expect(levels).toEqual({ "building:levels": 3, height: expect.any(Number) });
    expect(levels.height).toBeCloseTo(3 * 3.4);
    const based: Record<string, any> = readableBuildingProperties({ levels: 2, min_height: 1 });
    expect(based).toEqual({ levels: 2, min_height: 1, height: expect.any(Number) });
    expect(based.height).toBeCloseTo(2 * 3.4);
    // As a table hands the same building on, with every key and no value.
    expect(readableBuildingProperties({ height: null, "building:levels": 3 }).height).toBeCloseTo(levels.height);
  });

  test("a height key with no number in it no longer hides building:levels", () => {
    expect(readableBuildingProperties({ height: null, "building:levels": 3 }))
      .toEqual({ height: 3 * 3.4, "building:levels": 3 });
    expect(readableBuildingProperties({ height: "none", levels: null, "building:levels": 2 }).height)
      .toBeCloseTo(6.8);
  });

  test("a building with no height at all keeps none: the data holds no height Curio made", () => {
    for (const props of [{ height: null, "building:levels": null }, {}, { min_height: 10 }, { height: 0 }]) {
      expect(readableBuildingProperties(props)).toBe(props);
    }
    expect(readableBuildingProperties(null)).toBeNull();
    // A base key with no number is still made readable.
    expect(readableBuildingProperties({ min_height: null, "building:min_level": 2 }))
      .toEqual({ min_height: 2 * 3.4, "building:min_level": 2 });
  });

  test("a base key with no number in it no longer hides building:min_level", () => {
    expect(readableBuildingProperties({ height: 20, min_height: null, "building:min_level": 2 }))
      .toEqual({ height: 20, min_height: 2 * 3.4, "building:min_level": 2 });
  });

  test("building:height is read after height and before the levels, as autk-map 4 reads it", () => {
    expect(readableBuildingProperties({ "building:height": 30 })).toEqual({ "building:height": 30, height: 30 });
    expect(readableBuildingProperties({ height: null, "building:height": "30", "building:levels": 2 }).height).toBe(30);
    expect(readableBuildingProperties({ height: 12, "building:height": 30 }).height).toBe(12);
  });

  test("the input is never changed", () => {
    const props = { height: null, "building:levels": 3 };
    readableBuildingProperties(props);
    expect(props).toEqual({ height: null, "building:levels": 3 });
  });
});

describe("deriveBuildingHeight", () => {
  test("only a building that would be culled gets a height", () => {
    expect(deriveBuildingHeight({ height: 12 })).toBeNull();
    expect(deriveBuildingHeight({ "building:levels": 3 })).toBeNull();
    expect(deriveBuildingHeight({})).toBe(6);
    expect(deriveBuildingHeight({ min_height: 3 })).toBe(9);
    expect(deriveBuildingHeight({ parts: [{ height: 5 }] })).toBeNull();
    expect(deriveBuildingHeight({ "building:height": 30 })).toBeNull();
  });
});

describe("withDefaultHeight: a building as a map draws it and a pass reads it", () => {
  test("the default is 6 m", () => {
    expect((buildingHeight as any).DEFAULT_BUILDING_HEIGHT).toBe(6);
  });

  test("a building with no height stands 6 m above its base", () => {
    expect(withDefaultHeight({ height: null, "building:levels": null })).toEqual({ height: 6, "building:levels": null });
    expect(withDefaultHeight({})).toEqual({ height: 6 });
    expect(withDefaultHeight(null)).toEqual({ height: 6 });
    expect(withDefaultHeight({ min_height: 10 })).toEqual({ min_height: 10, height: 16 });
    // A top not above its base is no height, as autk-map culls it.
    expect(withDefaultHeight({ height: 0 })).toEqual({ height: 6 });
    expect(withDefaultHeight({ min_height: null, "building:min_level": 2 }))
      .toEqual({ min_height: 2 * 3.4, "building:min_level": 2, height: 2 * 3.4 + 6 });
  });

  test("a building with a height is read as readableBuildingProperties reads it", () => {
    const props = { height: 12 };
    expect(withDefaultHeight(props)).toBe(props);
    expect(withDefaultHeight({ "building:levels": 3 })).toEqual(readableBuildingProperties({ "building:levels": 3 }));
    expect(withDefaultHeight({ height: null, "building:height": "30" }).height).toBe(30);
  });

  test("the input is never changed", () => {
    const props = { height: null, "building:levels": null };
    withDefaultHeight(props);
    expect(props).toEqual({ height: null, "building:levels": null });
  });
});

describe("withoutEmptyHeights: a building a layer with buildingsZeroHeight draws", () => {
  test("a key of its top that holds no number goes, on the building and on each part", () => {
    expect(withoutEmptyHeights({ height: null, levels: "", name: "a" })).toEqual({ name: "a" });
    expect(withoutEmptyHeights({ height: "none", "building:levels": 3 })).toEqual({ "building:levels": 3 });
    expect(withoutEmptyHeights({ parts: [{ height: null }, { height: 9 }] })).toEqual({ parts: [{}, { height: 9 }] });
  });

  test("a building whose keys all hold numbers, or that has none, is the same object", () => {
    for (const props of [{ height: 12 }, { "building:levels": "3" }, { height: 0 }, {}, { parts: [{ height: 5 }] }]) {
      expect(withoutEmptyHeights(props)).toBe(props);
    }
    expect(withoutEmptyHeights(null)).toBeNull();
  });
});
