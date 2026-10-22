/**
 * The Map Edits node's edit log applied in the browser, the one way it is
 * applied there: to a layer's features, shapes and properties, as a run
 * applies it. What the node's table and its condition count read
 * (`applyEdits`), what its tools read (`layerModel.editedFeatures`) and what
 * the map it feeds draws before Commit edits (`mapEditsPreview`) all come
 * from `applyFeatureEdits`. The twin of `_edit_fc` in
 * `utk_curio/sandbox/util/feature_edits.py`; both read the cases in
 * `editFeaturesApply.cases.json` and the edit logs in `editExpr.cases.json`.
 *
 * Features are matched by their key, never by their place. A feature no edit
 * touches stays the same object, and the input is never changed.
 */
import type { SelectionId } from "../references/selectionTags";
import { evaluate, exprNumber, exprResult, parseExpr, truthy, type Expr, type ExprValue } from "./editExpr";
import type { FeatureEdit, Geometry } from "./editFeatures";

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

/** What the log made of a feature: added, redrawn, changed, or as the input has it. */
export type EditStatus = "input" | "added" | "redrawn" | "changed";

/** A feature as the log reads and writes it: its shape and its properties. */
export interface EditableFeature {
  geometry?: Geometry | null;
  properties?: Row | null;
  [member: string]: unknown;
}

/** An id as the sandbox compares it: a number by its value, a text as it is. */
export function idKey(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean") return `b:${value}`;
  if (typeof value === "number") return Number.isFinite(value) ? `n:${value}` : null;
  return `s:${String(value)}`;
}

const propertiesOf = (feature: EditableFeature | null | undefined): Row => (feature?.properties ?? {}) as Row;

/** What a writing *edit* puts into its column of *row*, or undefined when it leaves the row alone. */
function written(edit: FeatureEdit, formula: Expr | null, row: Row): ExprValue | undefined {
  if (edit.op === "set") return edit.value ?? null;
  if (edit.op === "expr") return evaluate(formula as Expr, row);
  const current = exprNumber(row[edit.column as string]);
  const by = exprNumber(edit.value);
  if (current === null || by === null) return undefined;
  return exprResult(edit.op === "scale" ? current * by : current + by);
}

/** The feature an add makes: its values, then its id in *key*, and its shape. */
function addedFeature(edit: FeatureEdit, key: string): EditableFeature {
  const values = Object.fromEntries(Object.entries(edit.values ?? {}).filter(([column]) => column !== key));
  return { type: "Feature", geometry: edit.geometry ?? null, properties: { ...values, [key]: edit.id } };
}

/**
 * *edits* over *features*, matched on *key*: the features after them, null
 * for a removed one and the input's own object for one no edit touched, what
 * each became, and what changed. An entry switched off is skipped. A
 * condition or an expression that is not one throws an `ExprError`, as a run
 * refuses it.
 */
export function applyFeatureEdits<F extends EditableFeature>(
  features: readonly F[],
  edits: readonly FeatureEdit[],
  key: string,
): { state: (F | EditableFeature | null)[]; status: EditStatus[]; counts: EditCounts } {
  // The input's features, then a null per added one: restoring an added
  // feature puts back what the input has, which is nothing.
  const base: (F | null)[] = [...features];
  const ids = features.map((feature) => idKey(propertiesOf(feature)[key]));
  const known = new Set(ids.filter((id): id is string => id !== null));
  const state: (F | EditableFeature | null)[] = [...features];
  const status: EditStatus[] = features.map(() => "input");
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
      state.push(addedFeature(edit, key));
      status.push("added");
      ids.push(id);
      known.add(id);
      added.add(state.length - 1);
      continue;
    }
    if (edit.op === "add_column") {
      const column = edit.column as string;
      state.forEach((feature, i) => {
        const row = propertiesOf(feature);
        if (feature === null || (row[column] !== null && row[column] !== undefined)) return;
        state[i] = { ...feature, properties: { ...row, [column]: edit.value ?? null } };
        if (status[i] === "input") status[i] = "changed";
      });
      continue;
    }
    let targets: number[];
    if (edit.where !== undefined) {
      // A condition reads the features as the edits before left them; a
      // restore reads them as the input has them, removed ones included.
      const condition = parseExpr(edit.where);
      const source = edit.op === "restore" ? base : state;
      targets = source.flatMap((feature, i) => (feature !== null && truthy(evaluate(condition, propertiesOf(feature))) ? [i] : []));
    } else {
      const wanted = new Set((edit.ids ?? []).map((id: SelectionId) => idKey(id)));
      targets = ids.flatMap((id, i) => (id !== null && wanted.has(id) ? [i] : []));
    }
    const formula = edit.op === "expr" ? parseExpr(String(edit.value ?? "")) : null;
    for (const i of targets) {
      const current = state[i];
      if (edit.op === "remove") {
        if (current !== null) {
          state[i] = null;
          removed.add(i);
        }
      } else if (edit.op === "restore") {
        if (current !== base[i]) {
          state[i] = base[i];
          status[i] = "input";
          if (!added.has(i)) restored.add(i);
          removed.delete(i);
          changed.delete(i);
          redrawn.delete(i);
          added.delete(i);
        }
      } else if (edit.op === "geometry") {
        if (current === null) continue;
        state[i] = { ...current, geometry: edit.geometry ?? null };
        if (status[i] !== "added") status[i] = "redrawn";
        redrawn.add(i);
      } else {
        if (current === null) continue;
        const value = written(edit, formula, propertiesOf(current));
        if (value === undefined) continue;
        state[i] = { ...current, properties: { ...propertiesOf(current), [edit.column as string]: value } };
        if (status[i] === "input") status[i] = "changed";
        changed.add(i);
      }
    }
  }
  // Adds and redraws are counted only when there are any.
  const counts: EditCounts = { remove: removed.size, set: changed.size, restore: restored.size };
  if (added.size > 0) counts.add = added.size;
  if (redrawn.size > 0) counts.geometry = redrawn.size;
  return { state, status, counts };
}

/**
 * *edits* over *rows*, one feature's properties each, matched on *key*: the
 * rows after them, null for a removed feature and the input's own object for
 * one no edit touched, and what changed (`applyFeatureEdits`).
 */
export function applyEdits(rows: readonly Row[], edits: readonly FeatureEdit[], key: string): { state: (Row | null)[]; counts: EditCounts } {
  const { state, counts } = applyFeatureEdits(rows.map((row) => ({ properties: row })), edits, key);
  return { state: state.map((feature) => (feature === null ? null : propertiesOf(feature))), counts };
}

/**
 * The layer *fc* as *edits* leave it, matched on *key*: the FeatureCollection
 * a run hands on for it (`_edit_fc`), its members kept and its features those
 * the edits keep, in their order.
 */
export function editedCollection<C extends { features?: readonly any[] }>(fc: C, edits: readonly FeatureEdit[], key: string): C {
  const { state } = applyFeatureEdits(fc.features ?? [], edits, key);
  return { ...fc, features: state.filter((feature) => feature !== null) };
}
