/**
 * A building's height as autk-map extrudes it: autk-map reads the first height
 * key a building has, whatever its value, and a table gives every row every key.
 */
import { deriveBuildingHeight, readableBuildingProperties } from "../../utils/buildingHeight";

describe("readableBuildingProperties", () => {
  test("a height autk-map already reads is left alone, the same object", () => {
    for (const props of [
      { height: 12 },
      { height: "12" },
      { height: "40 ft" },
      { "building:levels": 3 },
      { levels: 2, min_height: 1 },
      { height: 20, "building:min_level": 2 },
    ]) {
      expect(readableBuildingProperties(props)).toBe(props);
    }
  });

  test("a height key with no number in it no longer hides building:levels", () => {
    expect(readableBuildingProperties({ height: null, "building:levels": 3 }))
      .toEqual({ height: 3 * 3.4, "building:levels": 3 });
    expect(readableBuildingProperties({ height: "none", levels: null, "building:levels": 2 }).height)
      .toBeCloseTo(6.8);
  });

  test("a building with no height at all stands 6 m above its base, as a grammar layer's does", () => {
    expect(readableBuildingProperties({ height: null, "building:levels": null }))
      .toEqual({ height: 6, "building:levels": null });
    expect(readableBuildingProperties({})).toEqual({ height: 6 });
    expect(readableBuildingProperties(null)).toEqual({ height: 6 });
    expect(readableBuildingProperties({ min_height: 10 })).toEqual({ min_height: 10, height: 16 });
  });

  test("a base key with no number in it no longer hides building:min_level", () => {
    expect(readableBuildingProperties({ height: 20, min_height: null, "building:min_level": 2 }))
      .toEqual({ height: 20, min_height: 2 * 3.4, "building:min_level": 2 });
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
  });
});
