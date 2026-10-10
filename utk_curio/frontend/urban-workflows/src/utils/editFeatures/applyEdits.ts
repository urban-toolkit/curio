/**
 * The Interaction node's edit log applied in the browser, for its map's
 * preview: the twin of `_apply` in `utk_curio/sandbox/util/feature_edits.py`
 * (both read `applyEdits.cases.json`), so what the map shows is what a run
 * hands on. Features are matched by their key, as there; a feature an edit
 * leaves alone stays the same object, so a redraw can tell what changed.
 */
import type { SelectionId } from "../references/selectionTags";
import { evaluate, parseExpr, truthy, type Expr } from "./editExpr";
import type { EditFeaturesSettings, FeatureEdit } from "./editFeatures";

export interface EditCounts {
  remove: number;
  set: number;
  restore: number;
}

/** An id as the sandbox compares it: a number by its value, a text as it is. */
function idKey(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean") return `b:${value}`;
  if (typeof value === "number") return Number.isFinite(value) ? `n:${value}` : null;
  return `s:${String(value)}`;
}

const asNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

type Row = Record<string, unknown>;

/**
 * *edits* over the property rows *rows* (the input's, one per feature),
 * matched on *key*: the rows after them (null for a removed feature, the
 * input's own object for an untouched one) and what changed. A malformed
 * condition or expression throws, as a run refuses it.
 */
export function applyToRows(rows: readonly Row[], edits: readonly FeatureEdit[], key: string): { state: (Row | null)[]; counts: EditCounts } {
  const ids = rows.map((row) => idKey(row[key]));
  const state: (Row | null)[] = [...rows];
  const removed = new Set<number>();
  const changed = new Set<number>();
  const restored = new Set<number>();
  for (const edit of edits) {
    if (edit.enabled === false) continue;
    let targets: number[];
    if (edit.where !== undefined) {
      const condition: Expr = parseExpr(edit.where);
      const source = edit.op === "restore" ? rows : state;
      targets = source.flatMap((row, i) => (row !== null && truthy(evaluate(condition, row)) ? [i] : []));
    } else {
      const wanted = new Set((edit.ids ?? []).map((id: SelectionId) => idKey(id)));
      targets = ids.flatMap((id, i) => (id !== null && wanted.has(id) ? [i] : []));
    }
    const formula = edit.op === "expr" ? parseExpr(String(edit.value ?? "")) : null;
    for (const i of targets) {
      if (edit.op === "remove") {
        if (state[i] !== null) {
          state[i] = null;
          removed.add(i);
        }
        continue;
      }
      if (edit.op === "restore") {
        if (state[i] !== rows[i]) {
          state[i] = rows[i];
          restored.add(i);
          removed.delete(i);
          changed.delete(i);
        }
        continue;
      }
      const current = state[i];
      if (current === null) continue;
      const column = edit.column as string;
      let value: unknown;
      if (edit.op === "set") value = edit.value ?? null;
      else if (edit.op === "expr") value = evaluate(formula as Expr, current);
      else {
        const n = asNumber(current[column]);
        const by = asNumber(edit.value);
        if (n === null || by === null) continue;
        value = Number((edit.op === "scale" ? n * by : n + by).toPrecision(15));
      }
      state[i] = { ...current, [column]: value };
      changed.add(i);
    }
  }
  return { state, counts: { remove: removed.size, set: changed.size, restore: restored.size } };
}

/** *fc* with *settings*' edit log applied, for the map; the input when it has none. */
export function applyEdits<T extends { features?: any[] }>(fc: T, settings: EditFeaturesSettings | undefined, key: string | undefined): { fc: T; counts: EditCounts; problem: string | null } {
  const edits = settings?.edits ?? [];
  const none = { remove: 0, set: 0, restore: 0 };
  if (!key || edits.length === 0) return { fc, counts: none, problem: null };
  const features = fc?.features ?? [];
  const rows = features.map((f) => (f?.properties ?? {}) as Row);
  try {
    const { state, counts } = applyToRows(rows, edits, key);
    const out: any[] = [];
    state.forEach((row, i) => {
      if (row === null) return;
      out.push(row === rows[i] ? features[i] : { ...features[i], properties: row });
    });
    return { fc: { ...fc, features: out }, counts, problem: null };
  } catch (error) {
    return { fc, counts: none, problem: error instanceof Error ? error.message : String(error) };
  }
}
