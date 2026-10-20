/**
 * How a chart names and colors scenarios (#662): the scale of each scenario's
 * name to its box's color, in input order, and a table's text, in a shade of a
 * scenario's color that reads on white.
 */
import {
  NO_SCENARIO_COLOR,
  SCENARIO_FIELD,
  SCENARIO_NAME_FIELD,
  scenarioScale,
  tableTextColor,
} from "../../utils/scenarios/scenarioColors";
import { SCENARIO_COLORS } from "../../utils/scenarios/scenarioEdits";

/** A `#rrggbb` color's contrast on white (WCAG 2), worked out here apart from the module. */
function contrastOnWhite(color: string): number {
  const [r, g, b] = [1, 3, 5].map((at) => {
    const value = parseInt(color.slice(at, at + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 1.05 / (0.2126 * r + 0.7152 * g + 0.0722 * b + 0.05);
}

test("the stacked rows name their scenario in scenario and scenario_name, as scenario_stack.py writes them", () => {
  expect([SCENARIO_FIELD, SCENARIO_NAME_FIELD]).toEqual(["scenario", "scenario_name"]);
  expect(NO_SCENARIO_COLOR).toMatch(/^#[0-9a-f]{6}$/);
});

test("each scenario name once, with the color of its first input, in input order", () => {
  expect(
    scenarioScale([
      { scenario: "b", name: "Twice as tall", color: "#e76f51" },
      { scenario: "a", name: "Baseline", color: "#2a9d8f" },
      { scenario: "b", name: "Twice as tall", color: "#000000" },
    ]),
  ).toEqual({ domain: ["Twice as tall", "Baseline"], range: ["#e76f51", "#2a9d8f"] });
});

test("a color under 3:1 on white is written in its lightest shade that reaches 3:1, the others as they are", () => {
  // The scenario comparison charts' green roofs: 1.6:1, 2.9:1 and 6.5:1 on white.
  expect(["#a1d99b", "#41ab5d", "#006d2c"].map(tableTextColor)).toEqual(["#769e71", "#40a85b", "#006d2c"]);
  for (const color of ["#769e71", "#40a85b"]) expect(contrastOnWhite(color)).toBeGreaterThanOrEqual(3);
});

test("Curio's eight default scenario colors reach 3:1, so a table writes them as they are", () => {
  expect(SCENARIO_COLORS).toHaveLength(8);
  for (const color of SCENARIO_COLORS) expect(tableTextColor(color)).toBe(color);
});

test("what is not a #rrggbb color is written as it is", () => {
  expect(tableTextColor("steelblue")).toBe("steelblue");
});
