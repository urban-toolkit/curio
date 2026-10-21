/**
 * The Interaction node's edit log applied in the browser, to a layer's
 * feature properties: what the node's table and its condition count read, so
 * they show the features as a run will hand them on. The twin of
 * `_edit_fc` in `utk_curio/sandbox/util/feature_edits.py`; both read the edit
 * logs in `editExpr.cases.json`.
 *
 * Features are matched by their key, never by their place. A feature no edit
 * touches stays the same object.
 */
import type { SelectionId } from "../references/selectionTags";
import { evaluate, exprNumber, exprResult, parseExpr, truthy, type Expr, type ExprValue } from "./editExpr";
import type { FeatureEdit } from "./editFeatures";

type Row = Record<string, unknown>;

/** How many features the log removed, changed and restored. */
export interface EditCounts {
  remove: number;
  set: number;
  restore: number;
  /** Features added, drawn on the node's map. */
  add?: number;
  /** Features whose shape was redrawn. */
  geometry?: number;
}

/** An id as the sandbox compares it: a number by its value, a text as it is. */
function idKey(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean") return `b:${value}`;
  if (typeof value === "number") return Number.isFinite(value) ? `n:${value}` : null;
  return `s:${String(value)}`;
}

/** What a writing *edit* puts into its column of *row*, or undefined when it leaves the row alone. */
function written(edit: FeatureEdit, formula: Expr | null, row: Row): ExprValue | undefined {
  if (edit.op === "set") return edit.value ?? null;
  if (edit.op === "expr") return evaluate(formula as Expr, row);
  const current = exprNumber(row[edit.column as string]);
  const by = exprNumber(edit.value);
  if (current === null || by === null) return undefined;
  return exprResult(edit.op === "scale" ? current * by : current + by);
}

/**
 * *edits* over *rows*, one feature's properties each, matched on *key*: the
 * rows after them, null for a removed feature and the input's own object for
 * one no edit touched, and what changed. An entry switched off is skipped. A
 * condition or an expression that is not one throws an `ExprError`, as a run
 * refuses it.
 */
export function applyEdits(rows: readonly Row[], edits: readonly FeatureEdit[], key: string): { state: (Row | null)[]; counts: EditCounts } {
  // The input's rows, then a null per added one: restoring an added feature
  // puts back what the input has, which is nothing.
  const base: (Row | null)[] = [...rows];
  const ids = rows.map((row) => idKey(row?.[key]));
  const known = new Set(ids.filter((id): id is string => id !== null));
  const state: (Row | null)[] = [...rows];
  const removed = new Set<number>();
  const changed = new Set<number>();
  const restored = new Set<number>();
  const added = new Set<number>();
  const redrawn = new Set<number>();
  for (const edit of edits) {
    if (edit.enabled === false) continue;
    if (edit.op === "add") {
      const id = idKey(edit.id);
      if (id === null || known.has(id)) continue;
      base.push(null);
      state.push({ ...(edit.values ?? {}), [key]: edit.id });
      ids.push(id);
      known.add(id);
      added.add(state.length - 1);
      continue;
    }
    if (edit.op === "add_column") {
      const column = edit.column as string;
      state.forEach((row, i) => {
        if (row !== null && (row[column] === null || row[column] === undefined)) state[i] = { ...row, [column]: edit.value ?? null };
      });
      continue;
    }
    let targets: number[];
    if (edit.where !== undefined) {
      // A condition reads the features as the edits before left them; a
      // restore reads them as the input has them, removed ones included.
      const condition = parseExpr(edit.where);
      const source = edit.op === "restore" ? base : state;
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
      } else if (edit.op === "restore") {
        if (state[i] !== base[i]) {
          state[i] = base[i];
          if (!added.has(i)) restored.add(i);
          removed.delete(i);
          changed.delete(i);
          redrawn.delete(i);
          added.delete(i);
        }
      } else if (edit.op === "geometry") {
        if (state[i] !== null) redrawn.add(i);
      } else {
        const current = state[i];
        if (current === null) continue;
        const value = written(edit, formula, current);
        if (value === undefined) continue;
        state[i] = { ...current, [edit.column as string]: value };
        changed.add(i);
      }
    }
  }
  // Adds and redraws are counted only when there are any.
  const counts: EditCounts = { remove: removed.size, set: changed.size, restore: restored.size };
  if (added.size > 0) counts.add = added.size;
  if (redrawn.size > 0) counts.geometry = redrawn.size;
  return { state, counts };
}
