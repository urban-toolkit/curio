/**
 * The Raster Calculator starts with a call to Curio's raster algebra that
 * lists its operations, statistics among them, and keeps the code a saved
 * dataflow carries. Statistics are one of its operations, not a node of their
 * own.
 */
// The built-in behaviors pull in vega and vega-lite, whose ESM Jest's default
// transform skips; this suite never compiles a chart.
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

import * as rasterNodeBehaviors from "../../../adapters/node/rasterNodeBehaviors";
import * as rasterNodeCode from "../../../utils/raster/rasterNodeCode";
import { useRasterCalculatorBehavior } from "../../../adapters/node/rasterNodeBehaviors";
import { RASTER_CALCULATOR_CODE } from "../../../utils/raster/rasterNodeCode";
import { getBehavior } from "../../../registry/behaviorRegistry";
import "../../../registry/builtinBehaviors";

const fresh = { nodeId: "n1" } as never;
const saved = { nodeId: "n1", defaultCode: "return curio_raster_calculate(\"add\", [input_0, input_1])" } as never;
const state = {} as never;

describe("raster node behaviors", () => {
  it("a dropped Raster Calculator starts with its call", () => {
    expect(useRasterCalculatorBehavior(fresh, state)).toEqual({ defaultValueOverride: RASTER_CALCULATOR_CODE });
    expect(RASTER_CALCULATOR_CODE.endsWith('\nreturn curio_raster_calculate("subtract", [input_0, input_1])\n')).toBe(true);
  });

  it("lists statistics among its operations, with a condition and a mask explained", () => {
    expect(RASTER_CALCULATOR_CODE).toContain("\n#   return curio_raster_statistics(input_0, mask=input_1)\n");
    expect(RASTER_CALCULATOR_CODE).toContain("as a table of one row");
    expect(RASTER_CALCULATOR_CODE).toContain("where=lambda value: value < 1.08");
    expect(RASTER_CALCULATOR_CODE).toContain("mask_values=[0]");
  });

  it("keeps the code a dataflow carries", () => {
    expect(useRasterCalculatorBehavior(saved, state)).toEqual({});
  });

  it("is the one raster node: statistics have no behavior or code of their own", () => {
    expect(getBehavior("raster-calculator")).toBe(useRasterCalculatorBehavior);
    expect(getBehavior("raster-statistics")).toBeUndefined();
    expect(rasterNodeBehaviors).not.toHaveProperty("useRasterStatisticsBehavior");
    expect(rasterNodeCode).not.toHaveProperty("RASTER_STATISTICS_CODE");
  });
});
