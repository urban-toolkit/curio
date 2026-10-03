/**
 * A node's widgets as data (#662): which entries count, what a valid value is,
 * and the run key that makes a changed value run the node again.
 */
import {
  DATETIME_FALLBACK,
  checkWidgetDef,
  checkWidgetValue,
  dateTimeValue,
  defaultValueFor,
  effectiveValue,
  nodeRunKey,
  normalizeDateTime,
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

  test("keeps every option the controls read, and drops malformed ones", () => {
    const [slider, choice] = normalizeWidgets([
      { name: "s", type: "slider", default: 2, options: { min: 0, max: 10, step: 0.5, units: "m", extra: 1 } },
      { name: "c", type: "choice", default: "a", options: { choices: ["a", 3], display: "carousel" } },
    ]);
    expect(slider.options).toEqual({ min: 0, max: 10, step: 0.5, units: "m" });
    expect(choice.options).toEqual({ choices: ["a"] });
  });

  test("a widget without a default takes its kind's", () => {
    const out = normalizeWidgets([
      { name: "s", type: "slider", options: { min: 3, max: 9 } },
      { name: "g", type: "checkbox-group", options: { choices: ["a"] } },
      { name: "t", type: "datetime" },
      { name: "l", type: "location" },
    ]);
    expect(out.map((w) => w.default)).toEqual([3, [], DATETIME_FALLBACK, { lat: 0, lon: 0 }]);
  });
});

describe("dates and times", () => {
  test("a browser's value without seconds gains them; a date that does not exist is refused", () => {
    expect(normalizeDateTime("2026-06-21T12:05")).toBe("2026-06-21T12:05:00");
    expect(normalizeDateTime("2026-06-21T12:05:30")).toBe("2026-06-21T12:05:30");
    expect(normalizeDateTime("2026-02-30T12:00")).toBeNull();
    expect(normalizeDateTime("2026-06-21T24:00")).toBeNull();
    expect(normalizeDateTime("2026-06-21")).toBeNull();
    expect(normalizeDateTime("")).toBeNull();
  });

  test("a new date-time widget starts at the given minute, local time", () => {
    expect(dateTimeValue(new Date(2026, 5, 21, 9, 7, 45))).toBe("2026-06-21T09:07:00");
  });

  test("the fallback is a value the widget accepts", () => {
    expect(checkWidgetValue({ type: "datetime" }, defaultValueFor("datetime"))).toBeNull();
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
    [{ type: "number", options: { min: 1, max: 3 } }, 3, true],
    [{ type: "number", options: { min: 1, max: 3 } }, 4, false],
    [{ type: "number", options: { min: 1 } }, 0, false],
    [{ type: "slider", options: { min: 0, max: 10 } }, 7.5, true],
    [{ type: "slider", options: { min: 0, max: 10 } }, 11, false],
    [{ type: "checkbox-group", options: { choices: ["a", "b"] } }, ["b", "a"], true],
    [{ type: "checkbox-group", options: { choices: ["a", "b"] } }, [], true],
    [{ type: "checkbox-group", options: { choices: ["a", "b"] } }, ["a", "a"], false],
    [{ type: "multi-select", options: { choices: ["a", "b"] } }, ["c"], false],
    [{ type: "multi-select", options: { choices: ["a", "b"] } }, "a", false],
    [{ type: "datetime" }, "2026-06-21T12:00:00", true],
    [{ type: "datetime" }, "2026-06-21T12:00", false],
    [{ type: "datetime" }, "2026-13-01T00:00:00", false],
    [{ type: "location" }, { lat: 41.88, lon: -87.63 }, true],
    [{ type: "location" }, { lat: 91, lon: 0 }, false],
    [{ type: "location" }, { lat: 0, lon: 181 }, false],
    [{ type: "location" }, { lat: 0, lon: 0, name: "x" }, false],
    [{ type: "location" }, [41.88, -87.63], false],
    [{ type: "location" }, { lat: NaN, lon: 0 }, false],
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

  test("a checkbox group and a multi-select need choices too", () => {
    for (const type of ["checkbox-group", "multi-select"] as const) {
      expect(checkWidgetDef({ name: "g", type, default: [], options: { choices: [] } }, [])).toMatch(/at least one/);
      expect(checkWidgetDef({ name: "g", type, default: ["b"], options: { choices: ["a", "b"] } }, [])).toBeNull();
    }
  });

  test("a slider needs both bounds, in order, a positive step, and a default between them", () => {
    const slider: WidgetDef = { name: "rain", type: "slider", default: 5, options: { min: 0, max: 10 } };
    expect(checkWidgetDef(slider, [])).toBeNull();
    expect(checkWidgetDef({ ...slider, options: { min: 0 } }, [])).toMatch(/minimum and a maximum/);
    expect(checkWidgetDef({ ...slider, options: { min: 10, max: 0 } }, [])).toMatch(/below the maximum/);
    expect(checkWidgetDef({ ...slider, options: { min: 0, max: 10, step: 0 } }, [])).toMatch(/step must be above 0/);
    expect(checkWidgetDef({ ...slider, default: 12 }, [])).toMatch(/from 0 to 10/);
  });

  test("a number's bounds are optional", () => {
    expect(checkWidgetDef({ name: "k", type: "number", default: 2, options: { min: 1 } }, [])).toBeNull();
  });
});
