/**
 * The Interaction node (#662; it was the Edit Features node, and keeps its
 * type id and its setting, `metadata.editFeatures`): features picked on its
 * map, or picked by a condition, removed, put back or given new values, as an
 * edit log that is the node's setting:
 *
 * - `key`, the column that identifies a feature: `osm_id` or `building_id`
 *   when the layer has them, or another column whose values differ in every
 *   row. Never a row's place: a layer without such a column is refused.
 * - `layer`, the layer the edits apply to, by name, when the input names its
 *   layers (an Autark node hands on several).
 * - `edits`, in the order they were made (`FeatureEdit`): `remove`,
 *   `restore`, `set`, `scale`, `offset` or `expr`, each on the features whose
 *   `key` is one of `ids` or that its `where` condition picks (`editExpr`).
 *
 * The node's code is written from the log; `applyEdits` applies it in the
 * browser for the map's preview, as the sandbox's `curio_edit_features`
 * applies it in a run.
 */
import type { SelectDetail } from "../selectionMatch";
import { featureRows } from "../selectionMatch";
import { idColumns, selectedIds, STABLE_ID_COLUMNS, type SelectionId } from "../references/selectionTags";
import { widgetLiteral } from "../references/codeReferences";
import { getUnversionedFlowNodeType } from "../flowNodeCanonicalType";

export const EDIT_FEATURES_NODE_TYPE = "curio.builtin/edit-features";

/** What the node's code calls (`utk_curio/sandbox/util/feature_edits.py`). */
export const EDIT_HELPER = "curio_edit_features";

export const EDIT_OPS = ["remove", "set", "restore", "scale", "offset", "expr"] as const;
export type EditOp = (typeof EDIT_OPS)[number];
/** The ops that write a column. */
export const WRITE_OPS: readonly EditOp[] = ["set", "scale", "offset", "expr"];

/** A value an edit writes: a text, a number, true or false, or nothing. */
export type EditValue = string | number | boolean | null;

/**
 * One entry of the node's edit log, on the features whose key is one of
 * `ids` or, in place of `ids`, those its `where` condition holds for
 * (`editExpr`). `set` writes `value` into `column`; `scale` multiplies the
 * number there by `value`, `offset` adds `value` to it; `expr` writes what the
 * expression `value` makes of the feature. An entry with `enabled: false` is
 * kept and skipped.
 */
export interface FeatureEdit {
  op: EditOp;
  /** The `key` values of the features it applies to, each once. */
  ids?: SelectionId[];
  /** In place of `ids`: the condition that picks the features. */
  where?: string;
  /** For a writing op: the column it writes. */
  column?: string;
  /** For a writing op: the value, the factor, the amount or the expression. */
  value?: EditValue;
  /** What the entry is called in the log. */
  label?: string;
  /** False: kept in the log, skipped by the run. */
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

/** The well-formed edit *raw* holds, or null. */
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

function editLine(edit: FeatureEdit): string {
  const py = (value: unknown) => widgetLiteral(value as any, "python");
  const parts = [`"op": ${py(edit.op)}`];
  if (edit.where !== undefined) parts.push(`"where": ${py(edit.where)}`);
  else parts.push(`"ids": [${(edit.ids ?? []).map((id) => py(id)).join(", ")}]`);
  if (WRITE_OPS.includes(edit.op)) parts.push(`"column": ${py(edit.column ?? "")}`, `"value": ${py(edit.value ?? null)}`);
  if (edit.label) parts.push(`"label": ${py(edit.label)}`);
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

/** Whether *node* is an Edit Features node. */
export function isEditFeaturesNode(node: { type?: string | null; data?: any } | undefined): boolean {
  return node !== undefined && getUnversionedFlowNodeType(node as any) === EDIT_FEATURES_NODE_TYPE;
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
    + "and no column whose values differ in every feature. Edit Features matches features by such a column, "
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

/** One line for *edit*, naming the features by *key*. */
export function describeEdit(edit: FeatureEdit, key: string | undefined): string {
  const by = key ? `${key} ` : "";
  const on = edit.where !== undefined ? `where ${edit.where}` : `${by}${idList(edit.ids ?? [])}`;
  const value = typeof edit.value === "string" ? edit.value : JSON.stringify(edit.value);
  let what: string;
  if (edit.op === "remove") what = `Remove ${on}`;
  else if (edit.op === "restore") what = `Restore ${on}`;
  else if (edit.op === "scale") what = `Scale ${edit.column} ×${value} on ${on}`;
  else if (edit.op === "offset") what = `${(edit.value as number) >= 0 ? "Raise" : "Lower"} ${edit.column} by ${Math.abs(edit.value as number)} on ${on}`;
  else if (edit.op === "expr") what = `Set ${edit.column} = ${value} on ${on}`;
  else what = `Set ${edit.column} to ${value} on ${on}`;
  return edit.label ? `${edit.label}: ${what}` : what;
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

/**
 * *settings* with *edit* made after its others, folded into the last entry
 * when that is the same nudge (an offset or a scale of the same column on the
 * same features): holding ↑ makes one entry, not one per press.
 */
export function withNudge(settings: EditFeaturesSettings | undefined, edit: FeatureEdit): EditFeaturesSettings {
  const edits = settings?.edits ?? [];
  const last = edits[edits.length - 1];
  const same = last && last.enabled !== false && last.op === edit.op && last.column === edit.column
    && (edit.op === "offset" || edit.op === "scale") && !last.label
    && JSON.stringify(last.ids ?? null) === JSON.stringify(edit.ids ?? null) && (last.where ?? null) === (edit.where ?? null);
  if (!same) return withEdit(settings, edit);
  const value = edit.op === "offset"
    ? Number(((last.value as number) + (edit.value as number)).toPrecision(15))
    : Number(((last.value as number) * (edit.value as number)).toPrecision(15));
  const folded = edits.slice(0, -1);
  const neutral = edit.op === "offset" ? value === 0 : value === 1;
  return normalizeEditFeatures({ ...(settings ?? {}), edits: neutral ? folded : [...folded, { ...last, value }] }) ?? {};
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
