/**
 * A node's widgets as data (#662): which entries count, what a valid value is,
 * and the run key that makes a changed value run the node again.
 */
import {
  checkWidgetDef,
  checkWidgetValue,
  effectiveValue,
  nodeRunKey,
  normalizeWidgets,
  type WidgetDef,
} from "../../utils/widgets/widgetModel";

const season: WidgetDef = {
  name: "season",
  type: "choice",
  default: "summer",
  options: { choices: ["summer", "winter"] },
};

describe("nodeRunKey", () => {
  test("without widgets it is the code, as before widgets were saved", () => {
    expect(nodeRunKey("return 1")).toBe("return 1");
    expect(nodeRunKey("return 1", [])).toBe("return 1");
  });

  test("a changed value changes the key, the same value does not", () => {
    const before = nodeRunKey("x = [!! season !!]", [season]);
    expect(nodeRunKey("x = [!! season !!]", [{ ...season }])).toBe(before);
    expect(nodeRunKey("x = [!! season !!]", [{ ...season, value: "winter" }])).not.toBe(before);
  });

  test("a value equal to the default is the same run as the default", () => {
    expect(nodeRunKey("c", [{ ...season, value: "summer" }])).toBe(nodeRunKey("c", [season]));
  });
});

describe("effectiveValue", () => {
  test("the set value wins over the default", () => {
    expect(effectiveValue(season)).toBe("summer");
    expect(effectiveValue({ ...season, value: "winter" })).toBe("winter");
  });
});

describe("normalizeWidgets", () => {
  test("keeps well-formed entries and drops the rest", () => {
    const out = normalizeWidgets([
      season,
      { name: "1bad", type: "number", default: 1 },
      { name: "n", type: "nonsense", default: 1 },
      { name: "season", type: "text", default: "duplicate" },
      "not an object",
      { name: "n", type: "number" },
    ]);
    expect(out.map((w) => w.name)).toEqual(["season", "n"]);
    expect(out[1].default).toBe(0);
  });

  test("anything but a list is no widgets", () => {
    expect(normalizeWidgets(undefined)).toEqual([]);
    expect(normalizeWidgets({ name: "x" })).toEqual([]);
  });
});

describe("checkWidgetValue", () => {
  test.each([
    [{ type: "number" }, 2.5, true],
    [{ type: "number" }, "2", false],
    [{ type: "number" }, NaN, false],
    [{ type: "checkbox" }, false, true],
    [{ type: "text-list" }, ["a"], true],
    [{ type: "number-list" }, [1, "2"], false],
    [{ type: "range" }, [1, 3], true],
    [{ type: "range" }, [3, 1], false],
    [{ type: "choice", options: { choices: ["a"] } }, "a", true],
    [{ type: "choice", options: { choices: ["a"] } }, "b", false],
  ] as const)("%j with %j is valid: %s", (widget, value, valid) => {
    expect(checkWidgetValue(widget as any, value) === null).toBe(valid);
  });

  test("a text file over the cap is refused", () => {
    expect(checkWidgetValue({ type: "file" }, "x".repeat(1_000_001))).toMatch(/Data Catalog/);
  });
});

describe("checkWidgetDef", () => {
  test("a name is an identifier, and unique in the node", () => {
    expect(checkWidgetDef({ name: "2x", type: "number", default: 1 }, [])).toMatch(/letters, digits/);
    expect(checkWidgetDef({ name: "season", type: "text", default: "" }, [season])).toMatch(/already/);
    expect(checkWidgetDef({ name: "x", type: "number", default: 1 }, [season])).toBeNull();
  });

  test("a choice needs choices, each once, and a default among them", () => {
    expect(checkWidgetDef({ ...season, options: { choices: [] } }, [])).toMatch(/at least one/);
    expect(checkWidgetDef({ ...season, options: { choices: ["a", "a"] } }, [])).toMatch(/only once/);
    expect(checkWidgetDef({ ...season, default: "spring" }, [])).toMatch(/choices/);
  });
});
