/**
 * The Raster Calculator node (`scout.rasters@1`, SCOUT Rasters, whose template
 * names the `raster-calculator` behavior): a Python node whose code is
 * written for it when it is dropped, a call to Curio's raster algebra with its
 * operations listed, statistics among them (`utils/raster/rasterNodeCode`).
 * The user edits it as any Python node's code, and code a saved dataflow
 * carries is kept.
 */
import type { NodeBehaviorHook } from "../../registry/types";
import { RASTER_CALCULATOR_CODE } from "../../utils/raster/rasterNodeCode";

function startsWith(code: string): NodeBehaviorHook {
  return (data) => (data.defaultCode ? {} : { defaultValueOverride: code });
}

export const useRasterCalculatorBehavior: NodeBehaviorHook = startsWith(RASTER_CALCULATOR_CODE);
