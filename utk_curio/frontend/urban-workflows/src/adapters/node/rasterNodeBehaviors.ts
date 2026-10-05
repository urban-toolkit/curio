/**
 * The Raster Calculator and Raster Statistics nodes (`curio.builtin@1`): Python
 * nodes whose code is written for them when they are dropped, a call to
 * Curio's raster algebra (`utils/raster/rasterNodeCode`). The user edits it as
 * any Python node's code, and code a saved dataflow carries is kept.
 */
import type { NodeBehaviorHook } from "../../registry/types";
import { RASTER_CALCULATOR_CODE, RASTER_STATISTICS_CODE } from "../../utils/raster/rasterNodeCode";

function startsWith(code: string): NodeBehaviorHook {
  return (data) => (data.defaultCode ? {} : { defaultValueOverride: code });
}

export const useRasterCalculatorBehavior: NodeBehaviorHook = startsWith(RASTER_CALCULATOR_CODE);

export const useRasterStatisticsBehavior: NodeBehaviorHook = startsWith(RASTER_STATISTICS_CODE);
