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
 * matches any rows that have those columns. So does a point selection over
 * fields (#847): it names the values of each point it picked, `{unit_id: 103}`,
 * and picks every row that holds them, wherever the row sits.
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

type Resolved = { priority: number | undefined; indices: number[]; active?: boolean };

const KNOWN_TYPES = new Set<string>([
  VisInteractionType.POINT,
  VisInteractionType.INTERVAL,
  VisInteractionType.UNDETERMINED,
]);

/**
 * Does this select hold a selection? A point selection names rows; an
 * interval names at least one column. A select that has not been used, or
 * was cleared, holds none.
 */
export function isActiveSelect(detail: SelectDetail | undefined): boolean {
  if (!detail) return false;
  if (detail.type === VisInteractionType.POINT) return (detail.data?.length ?? 0) > 0;
  if (detail.type === VisInteractionType.INTERVAL) return Object.keys(detail.data ?? {}).length > 0;
  return false;
}

/** The entries MERGE_AND intersects: only those holding a selection. */
function forMode(entries: Resolved[], mode: string): Resolved[] {
  return mode === ResolutionType.MERGE_AND ? entries.filter((entry) => entry.active !== false) : entries;
}

/** Whether what `resolveIndices(entries, mode)` returns came from a selection. */
function resolvedActive(entries: Resolved[], mode: string): boolean {
  if (mode === ResolutionType.OVERWRITE) {
    let chosen: Resolved | undefined;
    for (const entry of entries) if (entry.priority === 1) chosen = entry;
    return chosen !== undefined && chosen.active !== false;
  }
  return entries.some((entry) => entry.active !== false);
}

/**
 * One point a point selection over fields picked: the value it holds for each
 * of its fields, `{unit_id: 103}`. A binned field's value is its bin, as vega
 * reports it: [start, end).
 */
export type PointValue = Record<string, unknown>;

const isPointValue = (entry: unknown): entry is PointValue =>
  entry != null && typeof entry === "object" && !Array.isArray(entry);

const comparable = (value: unknown) => (value instanceof Date ? value.getTime() : value);

/** Whether a row's *value* is the one a point *held*: equal, or inside the [start, end) of a bin. */
function holdsValue(held: unknown, value: unknown): boolean {
  if (Array.isArray(held) && held.length === 2) {
    const [start, end, at] = [comparable(held[0]), comparable(held[1]), comparable(value)];
    return typeof at === "number" && typeof start === "number" && typeof end === "number"
      && start <= at && at < end;
  }
  return comparable(held) === comparable(value);
}

/** Positions of the rows that hold every field value of one of *points*. */
function rowsHolding(points: PointValue[], rows: SelectionRows): number[] {
  const wanted = points.map((point) => Object.entries(point)).filter((fields) => fields.length > 0);
  const indices: number[] = [];
  for (let i = 0; i < rows.count; i++) {
    if (wanted.some((fields) => fields.every(([field, held]) => holdsValue(held, rows.value(i, field))))) {
      indices.push(i);
    }
  }
  return indices;
}

/** Text that starts as an ISO date, as a table holds dates: "2020-01-02", "2020-01-02T10:00:00". */
const ISO_DATE = /^\d{4}-\d{2}-\d{2}/;

/**
 * A row's value as a numeric range reads it: a number, a Date's time, text
 * that reads as a number, or the time of text that starts as an ISO date (a
 * temporal brush's bounds are times). Anything else (a column the row lacks, a
 * null, other text) is NaN, which no range holds (#872).
 */
function rangeValue(value: unknown): number {
  const at = comparable(value);
  if (typeof at === "number") return at;
  if (typeof at !== "string" || at.trim() === "") return NaN;
  const number = Number(at);
  if (Number.isFinite(number) || !ISO_DATE.test(at)) return number;
  // Vega's parse of the same text: a date alone is UTC, a time without a zone is local.
  return Date.parse(at);
}

/** Row positions one select covers. */
export function selectIndices(detail: SelectDetail, rows: SelectionRows): number[] {
  if (detail.type === VisInteractionType.POINT) {
    const data: unknown[] = detail.data ?? [];
    // A point over fields names values; any other point, row positions.
    if (data.some(isPointValue)) return rowsHolding(data.filter(isPointValue), rows);
    return data.map((index) => index as number);
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
        // numerical interval: a row with no number in the column is outside it
        const value = rangeValue(rows.value(i, column));
        if (!Number.isFinite(value) || value < bounds[0] || value > bounds[1]) {
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
 *
 * MERGE_AND intersects the selections that are active: a select nobody has
 * used, or one that was cleared, takes no part, so one chart's brush still
 * shows while the other charts have nothing selected. A selection that is
 * active and covers no row does take part, and leaves nothing.
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
        active: isActiveSelect(details[select]),
      }));
    perSource.push({
      priority: selection?.priority,
      indices: resolveIndices(forMode(perSelect, plot), plot),
      active: resolvedActive(perSelect, plot),
    });
  }
  return resolveIndices(forMode(perSource, between), between);
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
