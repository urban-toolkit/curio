/**
 * A Data Pool's two conflict modes, as its node data carries them
 * (`data.dataPool`) and as a spec stores them (`metadata.dataPool`, #581), and
 * back.
 *
 * `insideChart` resolves the selects of one chart; `betweenCharts` resolves the
 * latest selection of each chart linked to the pool. Each is a ResolutionType;
 * anything else, or nothing, is OVERWRITE.
 *
 * TrillGenerator writes with `dataPoolToSpec`, and `loadTrill` reads with
 * `dataPoolFromSpec`. This module imports nothing but the constants.
 */
import { ResolutionType } from "../constants";

export interface DataPoolModes {
  insideChart?: string;
  betweenCharts?: string;
}

const MODES = new Set<string>(Object.values(ResolutionType));

/** The mode a saved value names: a ResolutionType, else OVERWRITE. */
export function dataPoolMode(value: unknown): ResolutionType {
  return typeof value === "string" && MODES.has(value)
    ? (value as ResolutionType)
    : ResolutionType.OVERWRITE;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/**
 * What `data.dataPool` writes into the spec: the modes that are not
 * OVERWRITE. Undefined means write nothing, so an untouched pool serializes as
 * it did before.
 */
export function dataPoolToSpec(modes: unknown): DataPoolModes | undefined {
  if (!isRecord(modes)) return undefined;
  const spec: DataPoolModes = {};
  const insideChart = dataPoolMode(modes.insideChart);
  const betweenCharts = dataPoolMode(modes.betweenCharts);
  if (insideChart !== ResolutionType.OVERWRITE) spec.insideChart = insideChart;
  if (betweenCharts !== ResolutionType.OVERWRITE) spec.betweenCharts = betweenCharts;
  return Object.keys(spec).length > 0 ? spec : undefined;
}

/**
 * What a spec's `metadata.dataPool` puts back on the node: the members that
 * name a mode. A value that names none is dropped, and reads as OVERWRITE.
 */
export function dataPoolFromSpec(spec: unknown): DataPoolModes | undefined {
  if (!isRecord(spec)) return undefined;
  const modes: DataPoolModes = {};
  for (const key of ["insideChart", "betweenCharts"] as const) {
    const value = spec[key];
    if (typeof value === "string" && MODES.has(value)) modes[key] = value;
  }
  return Object.keys(modes).length > 0 ? modes : undefined;
}
