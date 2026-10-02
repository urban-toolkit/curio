/**
 * A Data Pool's two conflict modes, as its node data and a saved spec carry
 * them (`metadata.dataPool`).
 *
 * `insideChart` resolves the selects of one chart; `betweenCharts` resolves the
 * latest selection of each chart linked to the pool. Each is a ResolutionType,
 * and anything else, or nothing, is OVERWRITE.
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

/** What a spec saves: the modes that are not OVERWRITE, or nothing at all. */
export function savedDataPoolModes(modes: unknown): DataPoolModes | undefined {
  const given = (modes ?? {}) as DataPoolModes;
  const saved: DataPoolModes = {};
  const insideChart = dataPoolMode(given.insideChart);
  const betweenCharts = dataPoolMode(given.betweenCharts);
  if (insideChart !== ResolutionType.OVERWRITE) saved.insideChart = insideChart;
  if (betweenCharts !== ResolutionType.OVERWRITE) saved.betweenCharts = betweenCharts;
  return Object.keys(saved).length > 0 ? saved : undefined;
}
