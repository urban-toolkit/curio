/**
 * The Map Edits node (#662; its type id is still
 * `curio.builtin/edit-features`): features picked on its map, or by a
 * condition, removed, put back or given new values, as an edit log:
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
 * The node's code is its only state: one call of the sandbox's
 * `curio_edit_features` (`utk_curio/sandbox/util/feature_edits.py`), which
 * this module writes (`editFeaturesCode`) and reads back
 * (`readEditFeaturesCode`), so a run in the browser, a run on the server and
 * the headless runner apply the same edits. Code of another shape is never
 * rewritten: the reader says why it cannot read it, and the run still runs
 * it. `applyEdits` applies the log in the browser.
 */
import type { SelectDetail } from "../selectionMatch";
import { featureRows } from "../selectionMatch";
import { idColumns, selectedIds, STABLE_ID_COLUMNS, type SelectionId } from "../references/selectionTags";
import { REFERENCE_PATTERN } from "../references/codeReferences";
import { exprProblem } from "./editExpr";
import { jsonOf, pyLiteral, readCallArgs, shown, Unreadable, type JsonValue, type Literal } from "./pyLiteral";

/** What the node's code calls (`utk_curio/sandbox/util/feature_edits.py`). */
export const EDIT_HELPER = "curio_edit_features";

/** In the order of `OPS` in `feature_edits.py`: Jest and pytest pin both to the `ops` of `editFeaturesCode.cases.json`. */
export const EDIT_OPS = ["remove", "set", "restore", "scale", "offset", "expr", "add", "geometry", "add_column"] as const;
export type EditOp = (typeof EDIT_OPS)[number];
/** The ops that write a column. */
export const WRITE_OPS: readonly EditOp[] = ["set", "scale", "offset", "expr"];
/** The ops that name no features: they add one, or a column to every one. */
export const UNNAMED_OPS: readonly EditOp[] = ["add", "add_column"];
/** The geometry a new layer's features take. */
export const NEW_LAYER_GEOMETRIES = ["Point", "LineString", "Polygon"] as const;
export type NewLayerGeometry = (typeof NEW_LAYER_GEOMETRIES)[number];
/** The column that identifies a new layer's features (`NEW_LAYER_KEY` in `feature_edits.py`). */
export const NEW_LAYER_KEY = "id";
/** The kinds of value a property takes. */
export const PROPERTY_TYPES = ["text", "number", "boolean", "choice", "date"] as const;
export type PropertyType = (typeof PROPERTY_TYPES)[number];
const GEOMETRY_TYPES = ["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"];

/** A GeoJSON geometry: what the node's map draws and an add or a redraw writes. */
export interface Geometry {
  type: string;
  coordinates: any[];
}

/** One property a new layer's features carry. */
export interface PropertyDef {
  name: string;
  type: PropertyType;
  required?: boolean;
  /** For a choice: the values offered. */
  choices?: string[];
  default?: EditValue;
}

/** A layer the node makes: empty until features are drawn into it. */
export interface NewLayerDef {
  name: string;
  geometry: NewLayerGeometry;
  properties?: PropertyDef[];
}

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
  /** The layer it applies to, when it is not the node's `layer`. */
  layer?: string;
  /** For an add: the new feature's id, written into the layer's id column. */
  id?: SelectionId;
  /** For an add or a redraw: the shape drawn on the node's map. */
  geometry?: Geometry;
  /** For an add or a redraw: the CRS its shape is drawn in, its layer's own,
   * so layers in different CRSs each read their shapes in theirs. */
  crs?: string;
  /** For an add: the new feature's values. */
  values?: Record<string, EditValue>;
}

export interface EditFeaturesSettings {
  key?: string;
  layer?: string;
  /** The id column of each other layer the edits name. */
  keys?: Record<string, string>;
  /** The layers the node makes. */
  newLayers?: NewLayerDef[];
  /** The CRS of the node's first drawn shape: the one a new layer's features
   * are in, and a drawn shape's when its edit names none. */
  crs?: string;
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
export function isGeometry(value: unknown): value is Geometry {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const g = value as Record<string, unknown>;
  return typeof g.type === "string" && GEOMETRY_TYPES.includes(g.type) && Array.isArray(g.coordinates);
}

function cleanValues(raw: unknown): Record<string, EditValue> {
  const out: Record<string, EditValue> = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const [column, value] of Object.entries(raw as Record<string, unknown>)) {
    if (column !== "" && isValue(value)) out[column] = value;
  }
  return out;
}

export function normalizeEdit(raw: unknown): FeatureEdit | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const e = raw as Record<string, unknown>;
  if (!EDIT_OPS.includes(e.op as EditOp)) return null;
  const op = e.op as EditOp;
  const layer = typeof e.layer === "string" && e.layer !== "" ? { layer: e.layer } : {};
  const tail = (out: FeatureEdit): FeatureEdit => {
    if (typeof e.label === "string" && e.label.trim() !== "") out.label = e.label.trim();
    if (e.enabled === false) out.enabled = false;
    return out;
  };
  const drawnIn = typeof e.crs === "string" && e.crs !== "" ? e.crs : undefined;
  if (op === "add") {
    if (!isId(e.id) || !isGeometry(e.geometry)) return null;
    const values = cleanValues(e.values);
    return tail({
      op, ...layer, id: e.id, geometry: e.geometry,
      ...(drawnIn ? { crs: drawnIn } : {}),
      ...(Object.keys(values).length > 0 ? { values } : {}),
    });
  }
  if (op === "add_column") {
    if (typeof e.column !== "string" || e.column === "" || !isValue(e.value ?? null)) return null;
    return tail({ op, ...layer, column: e.column, value: (e.value ?? null) as EditValue });
  }
  const ids = Array.isArray(e.ids) ? uniqueIds(e.ids) : [];
  const where = typeof e.where === "string" && e.where.trim() !== "" ? e.where.trim() : undefined;
  if ((ids.length > 0) === (where !== undefined)) return null;
  const out: FeatureEdit = where !== undefined ? { op, ...layer, where } : { op, ...layer, ids };
  if (op === "geometry") {
    if (!isGeometry(e.geometry)) return null;
    out.geometry = e.geometry;
    if (drawnIn) out.crs = drawnIn;
  }
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

/** The well-formed settings in *raw*, or undefined when it holds none. */
export function normalizeEditFeatures(raw: unknown): EditFeaturesSettings | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const r = raw as Record<string, unknown>;
  const out: EditFeaturesSettings = {};
  if (typeof r.key === "string" && r.key !== "") out.key = r.key;
  if (typeof r.layer === "string" && r.layer !== "") out.layer = r.layer;
  if (r.keys && typeof r.keys === "object" && !Array.isArray(r.keys)) {
    const keys = Object.fromEntries(
      Object.entries(r.keys as Record<string, unknown>).filter(([name, k]) => name !== "" && typeof k === "string" && k !== ""),
    ) as Record<string, string>;
    if (Object.keys(keys).length > 0) out.keys = keys;
  }
  const newLayers = Array.isArray(r.newLayers) ? r.newLayers.map(normalizeNewLayer).filter((l): l is NewLayerDef => l !== null) : [];
  if (newLayers.length > 0) out.newLayers = newLayers;
  if (typeof r.crs === "string" && r.crs !== "") out.crs = r.crs;
  const edits = Array.isArray(r.edits) ? r.edits.map(normalizeEdit).filter((e): e is FeatureEdit => e !== null) : [];
  if (edits.length > 0) out.edits = edits;
  return Object.keys(out).length > 0 ? out : undefined;
}

/** A new layer's well-formed definition, or null. */
export function normalizeNewLayer(raw: unknown): NewLayerDef | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.name !== "string" || r.name.trim() === "") return null;
  if (!NEW_LAYER_GEOMETRIES.includes(r.geometry as NewLayerGeometry)) return null;
  const properties: PropertyDef[] = [];
  for (const item of Array.isArray(r.properties) ? r.properties : []) {
    if (!item || typeof item !== "object") continue;
    const p = item as Record<string, unknown>;
    if (typeof p.name !== "string" || p.name.trim() === "" || !PROPERTY_TYPES.includes(p.type as PropertyType)) continue;
    if (properties.some((other) => other.name === p.name)) continue;
    const def: PropertyDef = { name: p.name.trim(), type: p.type as PropertyType };
    if (p.required === true) def.required = true;
    if (Array.isArray(p.choices)) {
      const choices = p.choices.filter((c): c is string => typeof c === "string" && c.trim() !== "").map((c) => c.trim());
      if (choices.length > 0) def.choices = choices;
    }
    if (p.default !== undefined && isValue(p.default)) def.default = p.default;
    properties.push(def);
  }
  return { name: r.name.trim(), geometry: r.geometry as NewLayerGeometry, ...(properties.length > 0 ? { properties } : {}) };
}

/** One edit as a Python dict: op, layer, ids or where, column, value, id, geometry, crs, values, label, enabled. */
function editLine(edit: FeatureEdit): string {
  const parts = [`"op": ${pyLiteral(edit.op)}`];
  if (edit.layer) parts.push(`"layer": ${pyLiteral(edit.layer)}`);
  if (edit.op === "add") {
    parts.push(`"id": ${pyLiteral(edit.id)}`, `"geometry": ${pyLiteral(edit.geometry)}`);
    if (edit.crs) parts.push(`"crs": ${pyLiteral(edit.crs)}`);
    if (edit.values && Object.keys(edit.values).length > 0) parts.push(`"values": ${pyLiteral(edit.values)}`);
  } else if (edit.op === "add_column") {
    parts.push(`"column": ${pyLiteral(edit.column ?? "")}`, `"value": ${pyLiteral(edit.value ?? null)}`);
  } else {
    if (edit.where !== undefined) parts.push(`"where": ${pyLiteral(edit.where)}`);
    else parts.push(`"ids": ${pyLiteral(edit.ids ?? [])}`);
    if (WRITE_OPS.includes(edit.op)) {
      parts.push(`"column": ${pyLiteral(edit.column ?? "")}`, `"value": ${pyLiteral(edit.value ?? null)}`);
    }
    if (edit.op === "geometry") {
      parts.push(`"geometry": ${pyLiteral(edit.geometry)}`);
      if (edit.crs) parts.push(`"crs": ${pyLiteral(edit.crs)}`);
    }
  }
  if (edit.label) parts.push(`"label": ${pyLiteral(edit.label)}`);
  if (edit.enabled === false) parts.push(`"enabled": False`);
  return `    {${parts.join(", ")}},`;
}

/** What the node's code hands the step: its input, or every circle's, one per circle. */
export function editInputs(circles = 1): string {
  return circles > 1 ? `[${Array.from({ length: circles }, (_, k) => `input_${k}`).join(", ")}]` : "input_0";
}

/**
 * The node's code for *settings*, fed by *circles* inputs: with several, it
 * hands the step every input, one per circle, and the step names each
 * unnamed layer after its circle (`input_<k>`), as the Autark map it feeds
 * names them. *comments* are the lines the reader found above the call, kept
 * as they are; without them (a new node), the node's own.
 */
export function editFeaturesCode(settings: EditFeaturesSettings | undefined, circles = 1, comments?: readonly string[]): string {
  const edits = settings?.edits ?? [];
  const byInput = circles > 1;
  const args = [
    settings?.key ? `key=${pyLiteral(settings.key)}` : "",
    settings?.layer ? `layer=${pyLiteral(settings.layer)}` : "",
    settings?.keys && Object.keys(settings.keys).length > 0 ? `keys=${pyLiteral(settings.keys)}` : "",
    settings?.newLayers && settings.newLayers.length > 0 ? `new_layers=${pyLiteral(settings.newLayers)}` : "",
    settings?.crs ? `crs=${pyLiteral(settings.crs)}` : "",
    byInput ? "by_input=True" : "",
  ].filter(Boolean);
  const tail = args.length > 0 ? `, ${args.join(", ")}` : "";
  const value = editInputs(circles);
  const head = comments === undefined ? EDIT_CODE_NOTE : [...comments];
  if (edits.length === 0) return [...head, `return ${EDIT_HELPER}(${value}, []${tail})`, ""].join("\n");
  return [...head, `return ${EDIT_HELPER}(${value}, [`, ...edits.map(editLine), `]${tail})`, ""].join("\n");
}

/** What `readEditFeaturesCode` makes of a node's code. */
export type EditFeaturesRead =
  /**
   * The edits, how many circles the call hands the step (none for a new
   * node's blank code), and the comment lines above the call.
   */
  | { settings: EditFeaturesSettings | undefined; circles?: number; comments?: string[] }
  /** Why the code is not one the node writes. */
  | { problem: string };

/** The keywords `curio_edit_features` takes after its input and its edits. */
const KEYWORDS = ["key", "layer", "keys", "new_layers", "crs", "by_input"];
const NOT_THE_CALL = `This node reads one call, return ${EDIT_HELPER}(input_0, [...]), and this code holds something else.`;
/** What each op's dict holds, besides its op, its layer, its label and its switch. */
const EDIT_FIELDS: Record<EditOp, readonly string[]> = {
  remove: ["ids", "where"],
  restore: ["ids", "where"],
  set: ["ids", "where", "column", "value"],
  scale: ["ids", "where", "column", "value"],
  offset: ["ids", "where", "column", "value"],
  expr: ["ids", "where", "column", "value"],
  geometry: ["ids", "where", "geometry", "crs"],
  add: ["id", "geometry", "crs", "values"],
  add_column: ["column", "value"],
};
const NOT_A_VALUE = "is not a text, a number, True, False or None";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

/** A value as a reason shows it, as Python writes it. */
const show = (value: unknown): string => {
  if (value === undefined) return "nothing";
  if (value === null) return "None";
  if (typeof value === "boolean") return value ? "True" : "False";
  return JSON.stringify(value);
};

/**
 * Why the dict *raw* is not an edit the node writes, or null when it is one:
 * the checks `normalizeEdit` makes, each with what is wrong, and no field the
 * node would not write back.
 */
export function editProblem(raw: unknown): string | null {
  if (!isRecord(raw)) return "is not a dict";
  if (!EDIT_OPS.includes(raw.op as EditOp)) return `has the op ${show(raw.op)}, which is none of ${EDIT_OPS.join(", ")}`;
  const op = raw.op as EditOp;
  const extra = Object.keys(raw).find((name) => !["op", "layer", "label", "enabled", ...EDIT_FIELDS[op]].includes(name));
  if (extra !== undefined) return `is a ${op}, which takes no ${extra}`;
  if (raw.layer !== undefined && (typeof raw.layer !== "string" || raw.layer === "")) return "has a layer that is not a name";
  if (raw.label !== undefined && typeof raw.label !== "string") return "has a label that is not a text";
  if (typeof raw.label === "string" && raw.label.trim() === "") return "has an empty label";
  if (raw.enabled !== undefined && typeof raw.enabled !== "boolean") return "has an enabled that is not True or False";
  if (raw.crs !== undefined && (typeof raw.crs !== "string" || raw.crs === "")) return "has a crs that is not a CRS name";
  if (op === "add") {
    if (!isId(raw.id)) return "adds a feature with no id";
    if (!isGeometry(raw.geometry)) return "adds a feature with no geometry the node reads";
    if (raw.values === undefined) return null;
    if (!isRecord(raw.values)) return "adds a feature whose values are not a dict";
    const bad = Object.entries(raw.values).find(([column, value]) => column === "" || !isValue(value));
    return bad ? `adds a feature whose ${bad[0] || "unnamed value"} ${NOT_A_VALUE}` : null;
  }
  if (op === "add_column") {
    if (typeof raw.column !== "string" || raw.column === "") return "adds a property but names none";
    return raw.value === undefined || isValue(raw.value) ? null : `gives ${raw.column} a value that ${NOT_A_VALUE}`;
  }
  const byIds = raw.ids !== undefined;
  const byWhere = raw.where !== undefined;
  if (byIds && byWhere) return "names its features both by ids and by a condition";
  if (!byIds && !byWhere) return "names no features: it takes ids or a where condition";
  if (byWhere && (typeof raw.where !== "string" || raw.where.trim() === "")) return "has a where that is not a condition";
  const whereProblem = byWhere ? exprProblem(raw.where as string) : null;
  if (whereProblem) return `has the condition ${show(raw.where)}, which is not one: ${whereProblem}`;
  if (byIds && (!Array.isArray(raw.ids) || raw.ids.length === 0)) return "has ids that are not a list of ids";
  const notId = byIds ? (raw.ids as unknown[]).find((id) => !isId(id)) : undefined;
  if (byIds && (raw.ids as unknown[]).some((id) => !isId(id))) return `names ${show(notId)}, which is not an id`;
  if (op === "geometry" && !isGeometry(raw.geometry)) return "redraws features with no geometry the node reads";
  if (!WRITE_OPS.includes(op)) return null;
  if (typeof raw.column !== "string" || raw.column === "") return "writes a value but names no column";
  if (raw.value === undefined) return `writes no value into ${raw.column}`;
  if (!isValue(raw.value)) return `writes a value into ${raw.column} that ${NOT_A_VALUE}`;
  if ((op === "scale" || op === "offset") && typeof raw.value !== "number") {
    return `${op === "scale" ? "scales" : "offsets"} ${raw.column} by ${show(raw.value)}, which is not a number`;
  }
  if (op === "expr" && typeof raw.value !== "string") return `computes ${raw.column} from ${show(raw.value)}, which is not an expression`;
  const formulaProblem = op === "expr" ? exprProblem(raw.value as string) : null;
  return formulaProblem ? `computes ${raw.column} from ${show(raw.value)}, which is not an expression: ${formulaProblem}` : null;
}

/** Why the dict *raw* is not a layer the node makes, or null when it is one. */
export function newLayerProblem(raw: unknown): string | null {
  if (!isRecord(raw)) return "is not a dict";
  const extra = Object.keys(raw).find((name) => !["name", "geometry", "properties"].includes(name));
  if (extra !== undefined) return `takes no ${extra}`;
  if (typeof raw.name !== "string" || raw.name.trim() === "" || raw.name !== raw.name.trim()) return "has no name";
  if (!NEW_LAYER_GEOMETRIES.includes(raw.geometry as NewLayerGeometry)) {
    return `has the geometry ${show(raw.geometry)}, which is none of ${NEW_LAYER_GEOMETRIES.join(", ")}`;
  }
  if (raw.properties === undefined) return null;
  if (!Array.isArray(raw.properties)) return "has properties that are not a list";
  const names = new Set<string>();
  for (const property of raw.properties) {
    if (!isRecord(property)) return "has a property that is not a dict";
    const name = property.name;
    if (typeof name !== "string" || name.trim() === "" || name !== name.trim()) return "has a property with no name";
    const more = Object.keys(property).find((field) => !["name", "type", "required", "choices", "default"].includes(field));
    if (more !== undefined) return `has a property ${name} that takes no ${more}`;
    if (names.has(name)) return `gives the property ${name} twice`;
    names.add(name);
    if (!PROPERTY_TYPES.includes(property.type as PropertyType)) return `has a property ${name} of the type ${show(property.type)}, which is none of ${PROPERTY_TYPES.join(", ")}`;
    if (property.required !== undefined && typeof property.required !== "boolean") return `has a property ${name} whose required is not True or False`;
    if (property.choices !== undefined && (!Array.isArray(property.choices) || property.choices.some((c) => typeof c !== "string" || c.trim() === "" || c !== c.trim()))) {
      return `has a property ${name} whose choices are not a list of texts`;
    }
    if (property.default !== undefined && !isValue(property.default)) return `has a property ${name} whose default ${NOT_A_VALUE}`;
  }
  return null;
}

/** The circles the call's first argument hands the step: `input_0`, or `[input_0, input_1, ...]`. */
function circlesOf(literal: Literal | undefined): number {
  if (literal?.kind === "name" && literal.name === "input_0") return 1;
  if (literal?.kind === "list" && literal.items.length > 1 && literal.items.every((item, k) => item.kind === "name" && item.name === `input_${k}`)) {
    return literal.items.length;
  }
  throw new Unreadable(`The call's first argument is neither input_0 nor a list of the inputs in order, [input_0, input_1, ...].`);
}

/** A keyword that holds a text, or None. */
function textArg(literal: Literal | undefined, name: string): string | undefined {
  if (literal === undefined || (literal.kind === "value" && literal.value === null)) return undefined;
  if (literal.kind === "value" && typeof literal.value === "string") return literal.value === "" ? undefined : literal.value;
  throw new Unreadable(`${name} is not a text.`);
}

/** The settings the call's arguments hold. */
function settingsOf(args: { positional: Literal[]; keywords: Map<string, Literal> }): { settings: EditFeaturesSettings | undefined; circles: number } {
  if (args.positional.length < 2) throw new Unreadable(`The call takes its input and its list of edits, then ${KEYWORDS.join(", ")} by name.`);
  if (args.positional.length > 2) throw new Unreadable(`After its input and its edits, the call takes ${KEYWORDS.join(", ")} by name.`);
  const other = [...args.keywords.keys()].find((name) => !KEYWORDS.includes(name));
  if (other !== undefined) throw new Unreadable(`${EDIT_HELPER} takes ${KEYWORDS.join(", ")}, not ${other}.`);
  const circles = circlesOf(args.positional[0]);
  const byInput = args.keywords.get("by_input");
  const several = byInput !== undefined && byInput.kind === "value" && byInput.value === true;
  if (byInput !== undefined && !(byInput.kind === "value" && (typeof byInput.value === "boolean" || byInput.value === null))) {
    throw new Unreadable("by_input is not True or False.");
  }
  if (several !== circles > 1) {
    throw new Unreadable(circles > 1 ? "A list of inputs takes by_input=True." : "by_input=True takes a list of inputs, [input_0, input_1, ...].");
  }
  const raw: Record<string, unknown> = {};
  const key = textArg(args.keywords.get("key"), "key");
  const layer = textArg(args.keywords.get("layer"), "layer");
  const crs = textArg(args.keywords.get("crs"), "crs");
  if (key) raw.key = key;
  if (layer) raw.layer = layer;
  if (crs) raw.crs = crs;
  const keys = args.keywords.get("keys");
  if (keys !== undefined && !(keys.kind === "value" && keys.value === null)) {
    const value = jsonOf(keys, "keys");
    if (!isRecord(value) || Object.entries(value).some(([name, column]) => name === "" || typeof column !== "string" || column === "")) {
      throw new Unreadable("keys is not a dict of layer names and the columns that identify their features.");
    }
    raw.keys = value;
  }
  const newLayers = args.keywords.get("new_layers");
  if (newLayers !== undefined && !(newLayers.kind === "value" && newLayers.value === null)) {
    const value = jsonOf(newLayers, "new_layers");
    if (!Array.isArray(value)) throw new Unreadable("new_layers is not a list of layers.");
    value.forEach((item, i) => {
      const problem = newLayerProblem(item);
      if (problem) throw new Unreadable(`New layer ${i + 1} ${problem}.`);
    });
    raw.newLayers = value;
  }
  const edits = args.positional[1];
  if (edits.kind !== "list") throw new Unreadable(`The call's second argument is ${shown(edits)}, not a list of edits.`);
  raw.edits = edits.items.map((item, i): JsonValue => {
    const value = jsonOf(item, "the edits");
    const problem = editProblem(value);
    if (problem) throw new Unreadable(`Edit ${i + 1} ${problem}.`);
    return value;
  });
  return { settings: normalizeEditFeatures(raw), circles };
}

/**
 * The edits *code* holds, how many circles it hands the step and the comment
 * lines above its call, or why the node cannot read it. Blank code is a new
 * node: no edits. Otherwise the code is comment and blank lines, then
 * `return curio_edit_features(input, [edits], ...)` from the start of its
 * line: its input (`input_0`, or every circle's with `by_input=True`), its
 * edits, each a dict the node writes (`editProblem`), and the keywords `key`,
 * `layer`, `keys`, `new_layers`, `crs` and `by_input` in any order, each at
 * most once and each a literal. Anything else is refused: another statement,
 * a comment inside the call, a reference, a field the node would not write
 * back.
 */
export function readEditFeaturesCode(code: string | null | undefined): EditFeaturesRead {
  const text = code ?? "";
  if (text.trim() === "") return { settings: undefined };
  const head = (/^(?:[ \t\f]*(?:#[^\r\n]*)?(?:\r\n|\r|\n))*/.exec(text) as RegExpExecArray)[0];
  const comments = head.split(/\r\n|\r|\n/).slice(0, -1);
  const call = text.slice(head.length);
  const opening = new RegExp(`^return[ \\t\\f]+${EDIT_HELPER}[ \\t\\f]*\\(`).exec(call);
  if (!opening) {
    return { problem: /^[ \t\f]+return\b/.test(call) ? "The return line starts with spaces; the node writes it from the line's start." : NOT_THE_CALL };
  }
  if (new RegExp(REFERENCE_PATTERN).test(call)) {
    return { problem: "The call holds a [!! !!] reference, whose value the node cannot know before a run." };
  }
  try {
    const args = readCallArgs(text, head.length + opening[0].length, EDIT_HELPER, (position) => position === 0);
    return { ...settingsOf(args), comments };
  } catch (error) {
    if (error instanceof Unreadable) return { problem: error.message };
    throw error;
  }
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

/** The key the node starts with: `building_id` when the layer has it (the whole building), else `osm_id`. */
export function defaultKey(columns: readonly string[]): string | undefined {
  return STABLE_ID_COLUMNS.find((column) => columns.includes(column));
}

/** What the node says about a layer it cannot edit, or null when it can. */
export function keyRefusal(columns: readonly string[], layerLabel: string): string | null {
  if (columns.length > 0) return null;
  return (
    `${layerLabel} has no column that identifies its features: no osm_id or building_id, `
    + "and no column whose values differ in every feature. The Map Edits node matches features by such a column, "
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
export function describeEdit(edit: FeatureEdit, key: string | undefined, layerLabel?: string): string {
  const where = edit.layer ? ` in ${layerLabel ?? edit.layer}` : "";
  if (edit.op === "add") {
    const shape = (edit.geometry?.type ?? "feature").replace(/^Multi/, "").replace("LineString", "line").replace("Polygon", "area").toLowerCase();
    const values = Object.entries(edit.values ?? {}).filter(([, v]) => v !== null && v !== "").map(([c, v]) => `${c} ${String(v)}`);
    const line = `Add a ${shape}${where} (${String(edit.id)})${values.length > 0 ? `: ${values.join(", ")}` : ""}`;
    return edit.label ? `${edit.label}: ${line}` : line;
  }
  if (edit.op === "add_column") {
    const line = `Add a property ${edit.column}${where}, ${JSON.stringify(edit.value ?? null)} for every feature`;
    return edit.label ? `${edit.label}: ${line}` : line;
  }
  const by = key ? `${key} ` : "";
  const named = edit.where !== undefined ? `where ${edit.where}` : `${by}${idList(edit.ids ?? [])}`;
  const on = edit.where !== undefined ? named : `on ${named}`;
  const value = typeof edit.value === "string" ? edit.value : JSON.stringify(edit.value);
  let line: string;
  if (edit.op === "remove") line = `Remove ${named}${where}`;
  else if (edit.op === "restore") line = `Restore ${named}${where}`;
  else if (edit.op === "scale") line = `Scale ${edit.column} by ${value} ${on}${where}`;
  else if (edit.op === "offset") {
    const amount = typeof edit.value === "number" ? edit.value : 0;
    line = `${amount < 0 ? "Lower" : "Raise"} ${edit.column} by ${Math.abs(amount)} ${on}${where}`;
  } else if (edit.op === "expr") line = `Compute ${edit.column} as ${value} ${on}${where}`;
  else if (edit.op === "geometry") line = `Redraw ${named}${where}`;
  else line = `Set ${edit.column} to ${value} ${on}${where}`;
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
