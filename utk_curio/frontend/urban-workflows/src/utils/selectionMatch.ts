/**
 * Which rows a selection picks out.
 *
 * The Data Pool has always done this for the charts linked through it; a chart
 * joined to another by a direct interaction edge does the same thing with its
 * own rows. One implementation, so the two routes cannot disagree about what a
 * brush covers.
 *
 * A point selection names row positions: it lines up only when both ends read
 * the same rows in the same order. An interval names column values, so it
 * matches any rows that have those columns.
 */
import { ResolutionType, VisInteractionType } from "../constants";

/** One select of one source: a Vega param, or Autark's `autk_selection`. */
export interface SelectDetail {
  type: VisInteractionType | string;
  data: any;
  priority?: number;
}

/** One source's selection as the flow provider delivers it. */
export interface IncomingSelection {
  details: Record<string, SelectDetail>;
  priority: number;
}

/** The rows a selection is matched against. */
export interface SelectionRows {
  count: number;
  value(index: number, column: string): unknown;
}

type Resolved = { priority: number | undefined; indices: number[] };

const KNOWN_TYPES = new Set<string>([
  VisInteractionType.POINT,
  VisInteractionType.INTERVAL,
  VisInteractionType.UNDETERMINED,
]);

/** Row positions one select covers. */
export function selectIndices(detail: SelectDetail, rows: SelectionRows): number[] {
  if (detail.type === VisInteractionType.POINT) {
    return (detail.data ?? []).map((index: number) => index);
  }
  if (detail.type !== VisInteractionType.INTERVAL) return [];

  const brushedColumns = Object.keys(detail.data ?? {});
  const indices: number[] = [];
  if (brushedColumns.length === 0) return indices;

  for (let i = 0; i < rows.count; i++) {
    let interacted = true;
    for (const column of brushedColumns) {
      const bounds = detail.data[column];
      if (bounds.length > 0 && typeof bounds[0] === "string") {
        // categorical or ordinal
        if (!bounds.includes(rows.value(i, column))) {
          interacted = false;
          break;
        }
      } else if (bounds.length === 2) {
        // numerical interval
        const value = rows.value(i, column) as number;
        if (value < bounds[0] || value > bounds[1]) {
          interacted = false;
          break;
        }
      }
    }
    if (interacted) indices.push(i);
  }
  return indices;
}

/** OVERWRITE keeps the latest (priority 1) entry; MERGE_AND intersects; MERGE_OR unions. */
export function resolveIndices(entries: Resolved[], mode: string): number[] {
  if (mode === ResolutionType.OVERWRITE) {
    let chosen: number[] = [];
    for (const entry of entries) {
      if (entry.priority === 1) chosen = [...entry.indices];
    }
    return chosen;
  }
  if (mode === ResolutionType.MERGE_AND) {
    const all = entries.map((entry) => [...entry.indices]);
    if (all.length === 0) return [];
    return all.reduce((a, b) => a.filter((c) => b.includes(c)));
  }
  if (mode === ResolutionType.MERGE_OR) {
    const union = new Set<number>();
    for (const entry of entries) for (const index of entry.indices) union.add(index);
    return Array.from(union);
  }
  return [];
}

/**
 * The row positions a set of incoming selections picks out: each source's
 * selects are resolved by `plot`, then the sources by `between`.
 */
export function matchSelections(
  selections: IncomingSelection[],
  rows: SelectionRows,
  modes: { plot?: string; between?: string } = {},
): number[] {
  const plot = modes.plot ?? ResolutionType.OVERWRITE;
  const between = modes.between ?? ResolutionType.OVERWRITE;
  const perSource: Resolved[] = [];
  for (const selection of selections) {
    const details = selection?.details ?? {};
    const perSelect: Resolved[] = Object.keys(details)
      .filter((select) => KNOWN_TYPES.has(details[select]?.type))
      .map((select) => ({
        priority: details[select].priority,
        indices: selectIndices(details[select], rows),
      }));
    perSource.push({ priority: selection?.priority, indices: resolveIndices(perSelect, plot) });
  }
  return resolveIndices(perSource, between);
}

/** Rows of a column-major frame, `{col: [...]}` or `{col: {"0": ...}}`. */
export function columnRows(data: Record<string, any>): SelectionRows {
  const columns = Object.keys(data ?? {});
  const keys = columns.length > 0 ? Object.keys(data[columns[0]] ?? {}) : [];
  return {
    count: keys.length,
    value: (index, column) => data[column]?.[keys[index]],
  };
}

/** Rows of a FeatureCollection: each feature's properties. */
export function featureRows(fc: { features?: any[] } | null | undefined): SelectionRows {
  const features = fc?.features ?? [];
  return {
    count: features.length,
    value: (index, column) => features[index]?.properties?.[column],
  };
}

/** Rows that are already objects, as a Vega view holds them. */
export function objectRows(rows: any[]): SelectionRows {
  return {
    count: rows.length,
    value: (index, column) => rows[index]?.[column],
  };
}
