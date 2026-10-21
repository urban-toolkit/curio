/**
 * What the Interaction node reads off a layer to offer the right tools (#662):
 * the kind of geometry its features have, the properties a new feature of it
 * is asked for, the next id an added feature takes, and the layer's features,
 * shapes included, as the edit log leaves them (for the node's edit map).
 *
 * A property is read from the values the layer holds: a number column asks
 * for a number, a yes/no column for yes or no, a text column with a few
 * values that repeat offers them as choices, and a column no feature leaves
 * empty is required. The id column is never asked for: the node writes it.
 */
import type { SelectionId } from "../references/selectionTags";
import { evaluate, parseExpr, truthy } from "./editExpr";
import {
  NEW_LAYER_KEY,
  type EditValue,
  type FeatureEdit,
  type Geometry,
  type NewLayerDef,
  type NewLayerGeometry,
  type PropertyDef,
} from "./editFeatures";

/** The kinds of geometry the node draws and edits. */
export type GeometryKind = "points" | "lines" | "areas";

export const KIND_LABEL: Record<GeometryKind, string> = { points: "Points", lines: "Lines", areas: "Areas" };
export const KIND_GEOMETRY: Record<GeometryKind, NewLayerGeometry> = { points: "Point", lines: "LineString", areas: "Polygon" };
export const GEOMETRY_KIND: Record<NewLayerGeometry, GeometryKind> = { Point: "points", LineString: "lines", Polygon: "areas" };
/** What one feature of a kind is called. */
export const KIND_NOUN: Record<GeometryKind, string> = { points: "point", lines: "line", areas: "area" };

/** The kind of *geometry*, or null for one the node does not draw. */
export function kindOf(geometry: { type?: string } | null | undefined): GeometryKind | null {
  const type = String(geometry?.type ?? "").replace(/^Multi/, "");
  if (type === "Point") return "points";
  if (type === "LineString") return "lines";
  if (type === "Polygon") return "areas";
  return null;
}

/** How many features of each kind *fc* holds, most first. */
export function geometryKinds(fc: { features?: any[] } | null | undefined): { kind: GeometryKind; count: number }[] {
  const counts = new Map<GeometryKind, number>();
  for (const feature of fc?.features ?? []) {
    const kind = kindOf(feature?.geometry);
    if (kind) counts.set(kind, (counts.get(kind) ?? 0) + 1);
  }
  return [...counts.entries()].map(([kind, count]) => ({ kind, count })).sort((a, b) => b.count - a.count);
}

/** A layer's main kind: the one most of its features have. */
export function mainKind(fc: { features?: any[] } | null | undefined): GeometryKind | null {
  return geometryKinds(fc)[0]?.kind ?? null;
}

/** At most this many distinct texts make a column a choice. */
const MAX_CHOICES = 15;
/** Columns a view adds, never asked for. */
const SKIP = new Set(["interacted", "linked", "__row_index__", "__input__", "_vgsid_"]);

/** The properties a new feature of *fc* is asked for, read from the values it holds. */
export function inferProperties(fc: { features?: any[] } | null | undefined, key: string | undefined): PropertyDef[] {
  const features = fc?.features ?? [];
  const columns: string[] = [];
  for (const feature of features.slice(0, 200)) {
    for (const column of Object.keys(feature?.properties ?? {})) if (!columns.includes(column)) columns.push(column);
  }
  const out: PropertyDef[] = [];
  for (const column of columns) {
    if (column === key || SKIP.has(column)) continue;
    const values = features.map((f) => f?.properties?.[column]);
    const present = values.filter((v) => v !== null && v !== undefined && v !== "");
    const required = features.length > 0 && present.length === features.length;
    const sample = present[0];
    if (typeof sample === "number") {
      out.push({ name: column, type: "number", ...(required ? { required } : {}) });
      continue;
    }
    if (typeof sample === "boolean") {
      out.push({ name: column, type: "boolean", ...(required ? { required } : {}) });
      continue;
    }
    const counts = new Map<string, number>();
    for (const value of present) counts.set(String(value), (counts.get(String(value)) ?? 0) + 1);
    const repeats = present.length > counts.size;
    if (counts.size > 0 && counts.size <= MAX_CHOICES && repeats) {
      const choices = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([value]) => value);
      out.push({ name: column, type: "choice", choices, ...(required ? { required } : {}) });
      continue;
    }
    out.push({ name: column, type: "text", ...(required ? { required } : {}) });
  }
  return out;
}

/** The properties a layer's new feature is asked for: a new layer's own, else read off its features. */
export function propertiesFor(
  fc: { features?: any[] } | null | undefined,
  key: string | undefined,
  newLayer?: NewLayerDef,
): PropertyDef[] {
  return newLayer ? newLayer.properties ?? [] : inferProperties(fc, key);
}

/**
 * The id the next added feature takes: one more than the largest number the
 * layer's id column holds, when it holds numbers; else `new-1`, `new-2`, ...,
 * the first no feature and no add of the log has.
 */
export function nextId(
  fc: { features?: any[] } | null | undefined,
  edits: readonly FeatureEdit[],
  key: string,
  layerName?: string,
): SelectionId {
  const taken: SelectionId[] = (fc?.features ?? []).map((f) => f?.properties?.[key]).filter((v) => v !== null && v !== undefined);
  for (const edit of edits) if (edit.op === "add" && edit.id !== undefined && (edit.layer ?? undefined) === layerName) taken.push(edit.id);
  const numbers = taken.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (numbers.length > 0 && numbers.length === taken.length) return Math.max(...numbers) + 1;
  const used = new Set(taken.map(String));
  for (let n = 1; ; n += 1) {
    const id = `new-${n}`;
    if (!used.has(id)) return id;
  }
}

/** What a form's text for *def* stands for, or undefined for text that is not one (a number column given words). */
export function formValue(def: PropertyDef, text: string): EditValue | undefined {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  if (def.type === "number") {
    const number = Number(trimmed);
    return Number.isFinite(number) ? number : undefined;
  }
  if (def.type === "boolean") {
    if (/^(true|yes|1)$/i.test(trimmed)) return true;
    if (/^(false|no|0)$/i.test(trimmed)) return false;
    return undefined;
  }
  return trimmed;
}

/** What is wrong with *values* for *defs*: the required properties left empty and the values of the wrong kind. */
export function formProblems(defs: readonly PropertyDef[], texts: Record<string, string>): string[] {
  const problems: string[] = [];
  for (const def of defs) {
    const value = formValue(def, texts[def.name] ?? "");
    if (value === undefined) problems.push(`${def.name} takes ${def.type === "number" ? "a number" : "yes or no"}`);
    else if (def.required && (value === null || value === "")) problems.push(`${def.name} is required`);
  }
  return problems;
}

/** *texts* read as the values *defs* take; empty ones left out. */
export function formValues(defs: readonly PropertyDef[], texts: Record<string, string>): Record<string, EditValue> {
  const out: Record<string, EditValue> = {};
  for (const def of defs) {
    const value = formValue(def, texts[def.name] ?? "");
    if (value !== undefined && value !== null) out[def.name] = value;
  }
  return out;
}

/** The first texts a form shows: each property's default. */
export function formDefaults(defs: readonly PropertyDef[]): Record<string, string> {
  return Object.fromEntries(defs.map((def) => [def.name, def.default === undefined || def.default === null ? "" : String(def.default)]));
}

export interface EditedFeature {
  id: SelectionId | null;
  geometry: Geometry | null;
  properties: Record<string, unknown>;
  /** Added by the log, redrawn by it, or as the input has it. */
  status: "input" | "added" | "redrawn" | "changed";
}

function idKey(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? `n:${value}` : null;
  if (typeof value === "boolean") return `b:${value}`;
  return `s:${String(value)}`;
}

/**
 * The features of the layer *layerName* (null: the node's own layer) as the
 * edits of the log that apply to it leave them, shapes included: what the
 * node's edit map draws. The same ops, in the same order, as
 * `curio_edit_features`.
 */
export function editedFeatures(
  fc: { features?: any[] } | null | undefined,
  edits: readonly FeatureEdit[],
  key: string | undefined,
  layerName: string | null,
  nodeLayer: string | null,
): EditedFeature[] {
  const input: EditedFeature[] = (fc?.features ?? []).map((f) => ({
    id: key ? ((f?.properties?.[key] ?? null) as SelectionId | null) : null,
    geometry: (f?.geometry ?? null) as Geometry | null,
    properties: (f?.properties ?? {}) as Record<string, unknown>,
    status: "input",
  }));
  const base: (EditedFeature | null)[] = [...input];
  const state: (EditedFeature | null)[] = [...input];
  const known = new Set(input.map((f) => idKey(f.id)).filter((id): id is string => id !== null));
  const mine = (edit: FeatureEdit) => (edit.layer ?? nodeLayer ?? null) === (layerName ?? null);
  for (const edit of edits) {
    if (edit.enabled === false || !mine(edit) || !key) continue;
    if (edit.op === "add") {
      const id = idKey(edit.id);
      if (id === null || known.has(id) || !edit.geometry) continue;
      known.add(id);
      base.push(null);
      state.push({ id: edit.id as SelectionId, geometry: edit.geometry, properties: { ...(edit.values ?? {}), [key]: edit.id }, status: "added" });
      continue;
    }
    if (edit.op === "add_column") {
      const column = edit.column as string;
      state.forEach((f, i) => {
        if (f && (f.properties[column] === null || f.properties[column] === undefined)) {
          state[i] = { ...f, properties: { ...f.properties, [column]: edit.value ?? null }, status: f.status === "input" ? "changed" : f.status };
        }
      });
      continue;
    }
    let targets: number[];
    if (edit.where !== undefined) {
      const condition = parseExpr(edit.where);
      const source = edit.op === "restore" ? base : state;
      targets = source.flatMap((f, i) => (f !== null && truthy(evaluate(condition, f.properties as any)) ? [i] : []));
    } else {
      const wanted = new Set((edit.ids ?? []).map(idKey));
      targets = state.flatMap((f, i) => {
        const id = idKey((f ?? base[i])?.id);
        return id !== null && wanted.has(id) ? [i] : [];
      });
    }
    for (const i of targets) {
      const current = state[i];
      if (edit.op === "remove") state[i] = null;
      else if (edit.op === "restore") state[i] = base[i];
      else if (!current) continue;
      else if (edit.op === "geometry" && edit.geometry) state[i] = { ...current, geometry: edit.geometry, status: current.status === "added" ? "added" : "redrawn" };
      else if (edit.op === "set" && edit.column) {
        state[i] = { ...current, properties: { ...current.properties, [edit.column]: edit.value ?? null }, status: current.status === "input" ? "changed" : current.status };
      }
    }
  }
  return state.filter((f): f is EditedFeature => f !== null);
}

/** The id column of a new layer's features. */
export const newLayerKey = NEW_LAYER_KEY;
