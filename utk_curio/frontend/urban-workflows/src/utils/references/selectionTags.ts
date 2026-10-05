/**
 * Selection tags (#662): a view's current selection, read by a node's code as
 * `[!! selection name !!]`.
 *
 * A tag belongs to the node whose code reads it, and names the view (a
 * Vega-Lite or Autark node) and the column whose values identify the rows. It
 * holds the ids of the rows the view's latest selection picks, so the saved
 * dataflow carries them (`metadata.selections`) and every run reads the same
 * ids: the browser, a run on the server and the headless runner. A new
 * selection writes new ids, and the node's run key changes with them.
 *
 * The ids are values of a column of the view's rows, never a position or
 * Vega's `_vgsid_`: a node reads its own upstream artifact, where those mean
 * nothing.
 *
 * Kept in sync with `normalize_selections` and `SELECTION_ID_CAP` in
 * `utk_curio/backend/app/execution/code_references.py`.
 */
import { WIDGET_NAME_RE } from "../widgets/widgetModel";
import { isActiveSelect, matchSelections, type SelectDetail, type SelectionRows } from "../selectionMatch";

/** The most ids one tag holds. A selection that picks more is refused, with a
 * message that says so. Kept in sync with `SELECTION_ID_CAP` in
 * `code_references.py` and `maxItems` in `docs/schemas/trill.v1.json`. */
export const SELECTION_ID_CAP = 10000;

/** The columns that identify rows wherever Curio's OpenStreetMap layers go. */
export const STABLE_ID_COLUMNS = ["osm_id", "building_id"] as const;

/** Columns a view adds to its own rows, which identify nothing upstream. */
const VIEW_COLUMNS = new Set(["__row_index__", "__input__", "_vgsid_", "interacted", "linked"]);

export type SelectionId = string | number;

export interface SelectionTag {
  /** What the code's `[!! selection name !!]` references name. */
  name: string;
  /** The id of the view node whose selection it reads. */
  node: string;
  /** The column whose values identify the selected rows. */
  column: string;
  /** The ids of the selected rows, each once, in row order. */
  ids?: SelectionId[];
  /** In place of `ids`, when the selection holds more than SELECTION_ID_CAP. */
  count?: number;
}

/** What a selection holds for one tag: its ids, or how many there were. */
export type SelectionState = { ids: SelectionId[] } | { count: number };

const isCount = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 0;

/**
 * The well-formed tags in *raw* (a spec's `metadata.selections`), one per
 * name. A tag holds a list of ids, or a count in their place. Kept in sync
 * with `normalize_selections` in `code_references.py`.
 */
export function normalizeSelections(raw: unknown): SelectionTag[] {
  if (!Array.isArray(raw)) return [];
  const out: SelectionTag[] = [];
  const seen = new Set<string>();
  for (const entry of raw) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) continue;
    const e = entry as Record<string, unknown>;
    const name = typeof e.name === "string" ? e.name : "";
    if (!WIDGET_NAME_RE.test(name) || seen.has(name)) continue;
    if (typeof e.node !== "string" || e.node === "") continue;
    if (typeof e.column !== "string" || e.column === "") continue;
    const tag: SelectionTag = { name, node: e.node, column: e.column };
    if (Array.isArray(e.ids)) tag.ids = [...(e.ids as SelectionId[])];
    else if (isCount(e.count)) tag.count = e.count;
    else continue;
    seen.add(name);
    out.push(tag);
  }
  return out;
}

/** How many ids *tag* holds, or held when it was refused for holding too many. */
export function selectionSize(tag: SelectionTag): number {
  return Array.isArray(tag.ids) ? tag.ids.length : tag.count ?? 0;
}

/** Whether *tag* holds more ids than a tag takes. */
export function isOverCap(tag: SelectionTag): boolean {
  return !Array.isArray(tag.ids) || tag.ids.length > SELECTION_ID_CAP;
}

/** What a tag holding *size* ids, more than it takes, says. A run that reads
 * it stops with this message too (`codeReferences.ts`). */
export function overCapText(size: number): string {
  return (
    `the selection holds ${size} ids, more than the ${SELECTION_ID_CAP} a selection tag takes. `
    + "Select fewer rows in its view."
  );
}

const isId = (value: unknown): value is SelectionId =>
  typeof value === "string" || (typeof value === "number" && Number.isFinite(value));

/**
 * The columns that can identify the rows of a view: `osm_id` and
 * `building_id` when the rows have them (a building's parts share its
 * `building_id`), then every other column in which each row holds a text or
 * a number and no two rows hold the same one. None, for rows that have no such
 * column.
 */
export function idColumns(rows: SelectionRows, columns: readonly string[]): string[] {
  const usable = columns.filter((c) => typeof c === "string" && c !== "" && !VIEW_COLUMNS.has(c));
  const stable = STABLE_ID_COLUMNS.filter((c) => usable.includes(c));
  if (rows.count === 0) return [...stable];
  const keys = usable.filter((column) => {
    if ((STABLE_ID_COLUMNS as readonly string[]).includes(column)) return false;
    const seen = new Set<string>();
    for (let i = 0; i < rows.count; i++) {
      const value = rows.value(i, column);
      if (!isId(value)) return false;
      const key = `${typeof value}:${value}`;
      if (seen.has(key)) return false;
      seen.add(key);
    }
    return true;
  });
  return [...stable, ...keys];
}

/**
 * The ids of the rows a view's selection picks: the values of *column* in the
 * rows its latest select covers (as a Data Pool reads it, `matchSelections`),
 * each once, in row order. A row with no value in the column has no id and is
 * left out. More than SELECTION_ID_CAP comes back as a count.
 */
export function selectedIds(
  details: Record<string, SelectDetail> | null | undefined,
  rows: SelectionRows,
  column: string,
): SelectionState {
  const picked = details ? matchSelections([{ details, priority: 1 }], rows) : [];
  const ids: SelectionId[] = [];
  const seen = new Set<string>();
  for (const index of [...new Set(picked)].sort((a, b) => a - b)) {
    const value = rows.value(index, column);
    if (!isId(value)) continue;
    const key = `${typeof value}:${value}`;
    if (seen.has(key)) continue;
    seen.add(key);
    ids.push(value);
  }
  return ids.length > SELECTION_ID_CAP ? { count: ids.length } : { ids };
}

/** *tag* holding *state* in place of what it held. */
export function withState(tag: SelectionTag, state: SelectionState): SelectionTag {
  const { ids: _ids, count: _count, ...rest } = tag;
  return "ids" in state ? { ...rest, ids: state.ids } : { ...rest, count: state.count };
}

/** Whether two tags hold the same ids (or the same count in their place). */
export function sameState(a: SelectionTag, b: SelectionTag): boolean {
  if (Array.isArray(a.ids) !== Array.isArray(b.ids)) return false;
  if (!Array.isArray(a.ids) || !Array.isArray(b.ids)) return a.count === b.count;
  return a.ids.length === b.ids.length && a.ids.every((id, i) => id === b.ids![i]);
}

/** Whether *details* hold a selection the user just made: a select at
 * priority 1. A view that only declared its selects, as a Vega chart does when
 * it compiles, holds none, so a reload keeps the ids a dataflow was saved with. */
export function isNewSelection(details: unknown): boolean {
  if (!details || typeof details !== "object") return false;
  return Object.values(details as Record<string, any>).some((select) => select?.priority === 1);
}

/** Whether any select of *details* holds a selection. */
export function holdsSelection(details: unknown): boolean {
  if (!details || typeof details !== "object") return false;
  return Object.values(details as Record<string, SelectDetail>).some((select) => isActiveSelect(select));
}

/**
 * Whether *details*, reported after *previous*, change what the view's tags
 * hold: a new selection, or one that clears a selection *previous* held. A
 * chart reports its empty selects at priority 1 as it first draws (its signal
 * listeners hear the first pulse), and that clears nothing, so a reload or a
 * redraw keeps the ids a dataflow was saved with.
 */
export function changesSelection(previous: unknown, details: unknown): boolean {
  return isNewSelection(details) && (holdsSelection(details) || holdsSelection(previous));
}

/** The layer an Autark pick names, when the selection names one. */
export function selectionLayer(details: unknown): string | undefined {
  const layer = (details as any)?.autk_selection?.layerRef;
  return typeof layer === "string" && layer ? layer : undefined;
}

/** A tag name for the view labelled *label*, unlike the names in *taken*. */
export function suggestTagName(label: string | null | undefined, taken: readonly string[]): string {
  const base = (label ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^(\d)/, "_$1")
    .slice(0, 48) || "selection";
  if (!taken.includes(base)) return base;
  let n = 2;
  while (taken.includes(`${base}_${n}`)) n += 1;
  return `${base}_${n}`;
}
