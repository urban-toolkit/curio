/**
 * The Interaction node (#662; its type id is still
 * `curio.builtin/edit-features`): features picked on its map, or by a
 * condition, removed, put back or given new values, as an edit log that is
 * the node's setting (`metadata.editFeatures`):
 *
 * - `key`, the column that identifies a feature: `osm_id` or `building_id`
 *   when the layer has them, or another column whose values differ in every
 *   row. Never a row's place: a layer without such a column is refused.
 * - `layer`, the layer the edits apply to, by name, when the input names its
 *   layers (an Autark node hands on several).
 * - `edits`, in the order they were made (`FeatureEdit`): `remove`, `set`,
 *   `restore`, `scale`, `offset` or `expr`, each on the features whose `key`
 *   is one of `ids` or that its `where` condition picks (`editExpr`).
 *
 * The node's code is written from these (`editFeaturesCode`): one call of the
 * sandbox's `curio_edit_features` (`utk_curio/sandbox/util/feature_edits.py`),
 * so a run in the browser, a run on the server and the headless runner apply
 * the same edits. Written only when present. `applyEdits` applies the log in
 * the browser, for the node's table and its condition count.
 */
import type { SelectDetail } from "../selectionMatch";
import { featureRows } from "../selectionMatch";
import { idColumns, selectedIds, STABLE_ID_COLUMNS, type SelectionId } from "../references/selectionTags";
import { widgetLiteral } from "../references/codeReferences";

export const EDIT_FEATURES_NODE_TYPE = "curio.builtin/edit-features";

/** What the node's code calls (`utk_curio/sandbox/util/feature_edits.py`). */
export const EDIT_HELPER = "curio_edit_features";

/** In the order of the op enum in `docs/schemas/trill.v1.json` and `OPS` in `feature_edits.py`. */
export const EDIT_OPS = ["remove", "set", "restore", "scale", "offset", "expr"] as const;
export type EditOp = (typeof EDIT_OPS)[number];
/** The ops that write a column. */
export const WRITE_OPS: readonly EditOp[] = ["set", "scale", "offset", "expr"];

/** A value an edit writes: a text, a number, true or false, or nothing. */
export type EditValue = string | number | boolean | null;

/**
 * One entry of the node's edit log, on the features whose `key` is one of
 * `ids` or, in place of `ids`, those its `where` condition holds for. `set`
 * writes `value` into `column`; `scale` multiplies the number there by
 * `value` and `offset` adds `value` to it; `expr` writes what the expression
 * `value` makes of the feature.
 */
export interface FeatureEdit {
  op: EditOp;
  /** The `key` values of the features it applies to, each once. */
  ids?: SelectionId[];
  /** In place of `ids`: the condition that picks the features (`editExpr`). */
  where?: string;
  /** For a writing op: the column it writes. */
  column?: string;
  /** For a writing op: the value, the factor, the amount or the expression. */
  value?: EditValue;
  /** What people call the entry; it changes nothing. */
  label?: string;
  /** False: kept in the log and skipped by the run. Written only when false. */
  enabled?: boolean;
}

export interface EditFeaturesSettings {
  key?: string;
  layer?: string;
  edits?: FeatureEdit[];
}

export const EDIT_CODE_NOTE = [
  "# Edit Features writes this code from its edit list: each edit, in the",
  "# order it was made, on the features whose key is one of its ids. It is",
  "# written again when the list changes.",
];

const isId = (value: unknown): value is SelectionId =>
  typeof value === "string" || (typeof value === "number" && Number.isFinite(value));

const isValue = (value: unknown): value is EditValue =>
  value === null || typeof value === "string" || typeof value === "boolean"
  || (typeof value === "number" && Number.isFinite(value));

function uniqueIds(raw: unknown[]): SelectionId[] {
  const out: SelectionId[] = [];
  const seen = new Set<string>();
  for (const id of raw) {
    if (!isId(id)) continue;
    const key = `${typeof id}:${id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(id);
  }
  return out;
}

/**
 * The well-formed edit *raw* holds, or null: features named by ids or by a
 * condition, never both; a writing op's column and value, a number for a
 * scale or an offset and a text for an expression.
 */
export function normalizeEdit(raw: unknown): FeatureEdit | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const e = raw as Record<string, unknown>;
  if (!EDIT_OPS.includes(e.op as EditOp)) return null;
  const op = e.op as EditOp;
  const ids = Array.isArray(e.ids) ? uniqueIds(e.ids) : [];
  const where = typeof e.where === "string" && e.where.trim() !== "" ? e.where.trim() : undefined;
  if ((ids.length > 0) === (where !== undefined)) return null;
  const out: FeatureEdit = where !== undefined ? { op, where } : { op, ids };
  if (WRITE_OPS.includes(op)) {
    if (typeof e.column !== "string" || e.column === "" || !isValue(e.value)) return null;
    if ((op === "scale" || op === "offset") && typeof e.value !== "number") return null;
    if (op === "expr" && typeof e.value !== "string") return null;
    out.column = e.column;
    out.value = e.value;
  }
  if (typeof e.label === "string" && e.label.trim() !== "") out.label = e.label.trim();
  if (e.enabled === false) out.enabled = false;
  return out;
}

/**
 * The well-formed settings in *raw* (a spec's `metadata.editFeatures`), or
 * undefined when it holds none. Kept in sync with `$defs.nodeMetadata` in
 * `docs/schemas/trill.v1.json`.
 */
export function normalizeEditFeatures(raw: unknown): EditFeaturesSettings | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const r = raw as Record<string, unknown>;
  const out: EditFeaturesSettings = {};
  if (typeof r.key === "string" && r.key !== "") out.key = r.key;
  if (typeof r.layer === "string" && r.layer !== "") out.layer = r.layer;
  const edits = Array.isArray(r.edits) ? r.edits.map(normalizeEdit).filter((e): e is FeatureEdit => e !== null) : [];
  if (edits.length > 0) out.edits = edits;
  return Object.keys(out).length > 0 ? out : undefined;
}

/** One edit as a Python dict: op, ids or where, column, value, label, enabled. */
function editLine(edit: FeatureEdit): string {
  const parts = [`"op": ${widgetLiteral(edit.op, "python")}`];
  if (edit.where !== undefined) parts.push(`"where": ${widgetLiteral(edit.where, "python")}`);
  else parts.push(`"ids": [${(edit.ids ?? []).map((id) => widgetLiteral(id, "python")).join(", ")}]`);
  if (WRITE_OPS.includes(edit.op)) {
    parts.push(`"column": ${widgetLiteral(edit.column ?? "", "python")}`, `"value": ${widgetLiteral(edit.value ?? null, "python")}`);
  }
  if (edit.label) parts.push(`"label": ${widgetLiteral(edit.label, "python")}`);
  if (edit.enabled === false) parts.push(`"enabled": False`);
  return `    {${parts.join(", ")}},`;
}

/** The node's code for *settings*. */
export function editFeaturesCode(settings: EditFeaturesSettings | undefined): string {
  const edits = settings?.edits ?? [];
  const args = [
    settings?.key ? `key=${widgetLiteral(settings.key, "python")}` : "",
    settings?.layer ? `layer=${widgetLiteral(settings.layer, "python")}` : "",
  ].filter(Boolean);
  const tail = args.length > 0 ? `, ${args.join(", ")}` : "";
  if (edits.length === 0) return [...EDIT_CODE_NOTE, `return ${EDIT_HELPER}(input_0, []${tail})`, ""].join("\n");
  return [...EDIT_CODE_NOTE, `return ${EDIT_HELPER}(input_0, [`, ...edits.map(editLine), `]${tail})`, ""].join("\n");
}

/** The columns the features of *fc* carry, in the order the first ones name them. */
export function featureColumns(fc: { features?: any[] } | null | undefined): string[] {
  const columns: string[] = [];
  for (const feature of (fc?.features ?? []).slice(0, 50)) {
    for (const column of Object.keys(feature?.properties ?? {})) if (!columns.includes(column)) columns.push(column);
  }
  return columns;
}

/**
 * The columns that can identify the features of *fc*: `osm_id` and
 * `building_id` when they have them, then every column whose values differ in
 * every feature (`idColumns`, as a selection tag offers them).
 */
export function keyColumns(fc: { features?: any[] } | null | undefined): string[] {
  return idColumns(featureRows(fc), featureColumns(fc));
}

/** The key the node starts with: `osm_id` or `building_id` when the layer has one. */
export function defaultKey(columns: readonly string[]): string | undefined {
  return STABLE_ID_COLUMNS.find((column) => columns.includes(column));
}

/** What the node says about a layer it cannot edit, or null when it can. */
export function keyRefusal(columns: readonly string[], layerLabel: string): string | null {
  if (columns.length > 0) return null;
  return (
    `${layerLabel} has no column that identifies its features: no osm_id or building_id, `
    + "and no column whose values differ in every feature. The Interaction node matches features by such a column, "
    + "never by their place in the layer, which changes when rows change upstream. "
    + "Add an id column in the node that feeds it."
  );
}

/** The ids a pick on the map names, read from *fc*'s *key* column, each once. */
export function pickedIds(details: Record<string, SelectDetail> | null | undefined, fc: { features?: any[] }, key: string): SelectionId[] {
  const state = selectedIds(details, featureRows(fc), key);
  return "ids" in state ? state.ids : [];
}

/** *current* with the ids a new pick names added after it. */
export function addPicked(current: readonly SelectionId[], ids: readonly SelectionId[]): SelectionId[] {
  return uniqueIds([...current, ...ids]);
}

/** *settings* with *edit* made after its others. */
export function withEdit(settings: EditFeaturesSettings | undefined, edit: FeatureEdit): EditFeaturesSettings {
  const normalized = normalizeEdit(edit);
  const edits = [...(settings?.edits ?? []), ...(normalized ? [normalized] : [])];
  return { ...(settings ?? {}), ...(edits.length > 0 ? { edits } : {}) };
}

/** *settings* without its edit at *index*. */
export function withoutEdit(settings: EditFeaturesSettings | undefined, index: number): EditFeaturesSettings | undefined {
  const edits = (settings?.edits ?? []).filter((_, i) => i !== index);
  const { edits: _old, ...rest } = settings ?? {};
  return normalizeEditFeatures(edits.length > 0 ? { ...rest, edits } : rest);
}

function idList(ids: readonly SelectionId[]): string {
  return ids.map((id) => String(id)).join(", ");
}

/**
 * One line for *edit*, naming the features by *key* ("on building_id 3") or
 * by its condition ("where height > 100"), after its label when it has one.
 */
export function describeEdit(edit: FeatureEdit, key: string | undefined): string {
  const by = key ? `${key} ` : "";
  const named = edit.where !== undefined ? `where ${edit.where}` : `${by}${idList(edit.ids ?? [])}`;
  const on = edit.where !== undefined ? named : `on ${named}`;
  const value = typeof edit.value === "string" ? edit.value : JSON.stringify(edit.value);
  let line: string;
  if (edit.op === "remove") line = `Remove ${named}`;
  else if (edit.op === "restore") line = `Restore ${named}`;
  else if (edit.op === "scale") line = `Scale ${edit.column} by ${value} ${on}`;
  else if (edit.op === "offset") {
    const amount = typeof edit.value === "number" ? edit.value : 0;
    line = `${amount < 0 ? "Lower" : "Raise"} ${edit.column} by ${Math.abs(amount)} ${on}`;
  } else if (edit.op === "expr") line = `Compute ${edit.column} as ${value} ${on}`;
  else line = `Set ${edit.column} to ${value} ${on}`;
  return edit.label ? `${edit.label}: ${line}` : line;
}

/** *settings* with its edit at *index* switched on or off. */
export function withEditEnabled(settings: EditFeaturesSettings | undefined, index: number, enabled: boolean): EditFeaturesSettings | undefined {
  const edits = (settings?.edits ?? []).map((edit, i) => {
    if (i !== index) return edit;
    const { enabled: _old, ...rest } = edit;
    return enabled ? rest : { ...rest, enabled: false };
  });
  return normalizeEditFeatures({ ...(settings ?? {}), edits });
}

/** A sum or a product kept to 15 significant digits, as the sandbox keeps it. */
const tidy = (value: number): number => (value === 0 ? 0 : Number(value.toPrecision(15)));

/**
 * *settings* with the nudge *edit* (an offset or a scale) made after its
 * others, folded into the last entry when that is the same nudge of the same
 * column on the same features, on and unlabelled: pressing an arrow again
 * makes one entry, not one per press. A fold back to nothing (an offset of 0,
 * a scale of 1) drops the entry.
 */
export function withNudge(settings: EditFeaturesSettings | undefined, edit: FeatureEdit): EditFeaturesSettings {
  const edits = settings?.edits ?? [];
  const last = edits[edits.length - 1];
  const nudge = edit.op === "offset" || edit.op === "scale";
  const same = nudge && last !== undefined && last.op === edit.op && last.column === edit.column
    && last.enabled !== false && !last.label
    && (last.where ?? null) === (edit.where ?? null)
    && JSON.stringify(last.ids ?? null) === JSON.stringify(edit.ids ?? null);
  if (!same || typeof last.value !== "number" || typeof edit.value !== "number") return withEdit(settings, edit);
  const value = edit.op === "offset" ? tidy(last.value + edit.value) : tidy(last.value * edit.value);
  const neutral = edit.op === "offset" ? value === 0 : value === 1;
  const folded = [...edits.slice(0, -1), ...(neutral ? [] : [{ ...last, value }])];
  const { edits: _old, ...rest } = settings ?? {};
  return normalizeEditFeatures(folded.length > 0 ? { ...rest, edits: folded } : rest) ?? {};
}

/**
 * The value a text typed into Set value stands for, written into *column*:
 * a number when the layer's features hold numbers there, else the text.
 * Null for a number column given text that is not a number.
 */
export function typedValue(text: string, fc: { features?: any[] } | null | undefined, column: string): EditValue | undefined {
  const sample = (fc?.features ?? []).map((f) => f?.properties?.[column]).find((v) => v !== null && v !== undefined);
  if (typeof sample === "number") {
    const trimmed = text.trim();
    if (trimmed === "") return undefined;
    const number = Number(trimmed);
    return Number.isFinite(number) ? number : undefined;
  }
  if (typeof sample === "boolean") {
    if (text.trim().toLowerCase() === "true") return true;
    if (text.trim().toLowerCase() === "false") return false;
    return undefined;
  }
  return text;
}
