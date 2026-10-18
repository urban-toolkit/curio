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
  const ids = rows.map((row) => idKey(row?.[key]));
  const state: (Row | null)[] = [...rows];
  const removed = new Set<number>();
  const changed = new Set<number>();
  const restored = new Set<number>();
  for (const edit of edits) {
    if (edit.enabled === false) continue;
    let targets: number[];
    if (edit.where !== undefined) {
      // A condition reads the features as the edits before left them; a
      // restore reads them as the input has them, removed ones included.
      const condition = parseExpr(edit.where);
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
      } else if (edit.op === "restore") {
        if (state[i] !== rows[i]) {
          state[i] = rows[i];
          restored.add(i);
          removed.delete(i);
          changed.delete(i);
        }
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
  return { state, counts: { remove: removed.size, set: changed.size, restore: restored.size } };
}
