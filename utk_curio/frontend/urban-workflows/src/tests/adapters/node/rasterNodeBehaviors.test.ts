/**
 * The Raster Calculator and Raster Statistics nodes start with a call to
 * Curio's raster algebra, and keep the code a saved dataflow carries.
 */
import { useRasterCalculatorBehavior, useRasterStatisticsBehavior } from "../../../adapters/node/rasterNodeBehaviors";
import { RASTER_CALCULATOR_CODE, RASTER_STATISTICS_CODE } from "../../../utils/raster/rasterNodeCode";

const fresh = { nodeId: "n1" } as never;
const saved = { nodeId: "n1", defaultCode: "return curio_raster_calculate(\"add\", input)" } as never;
const state = {} as never;

describe("raster node behaviors", () => {
  it.each([
    ["Raster Calculator", useRasterCalculatorBehavior, RASTER_CALCULATOR_CODE, 'curio_raster_calculate("subtract", [input_0, input_1])'],
    ["Raster Statistics", useRasterStatisticsBehavior, RASTER_STATISTICS_CODE, "curio_raster_statistics(input_0, mask=input_1)"],
  ])("a dropped %s starts with its call", (_name, behavior, code, call) => {
    expect(behavior(fresh, state)).toEqual({ defaultValueOverride: code });
    expect(code).toContain(`return ${call}`);
  });

  it.each([useRasterCalculatorBehavior, useRasterStatisticsBehavior])("keeps the code a dataflow carries", (behavior) => {
    expect(behavior(saved, state)).toEqual({});
  });
});
