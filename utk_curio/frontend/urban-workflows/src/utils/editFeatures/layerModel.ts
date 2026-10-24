/**
 * What the Map Editor node reads off a layer to offer the right tools (#662):
 * the kind of geometry its features have, the properties a new feature of it
 * is asked for, the next id an added feature takes, and the layer's features,
 * shapes included, as the edit log leaves them (`applyEdits`).
 *
 * A property is read from the values the layer holds: a number column asks
 * for a number, a yes/no column for yes or no, a text column with a few
 * values that repeat offers them as choices, and a column no feature leaves
 * empty is required. The id column is never asked for: the node writes it.
 */
import type { SelectionId } from "../references/selectionTags";
import { applyFeatureEdits, type EditStatus } from "./applyEdits";
import {
  NEW_LAYER_KEY,
  type EditValue,
  type FeatureEdit,
  type Geometry,
  type NewLayerDef,
  type NewLayerGeometry,
  type PropertyDef,
  type PropertyType,
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
  status: EditStatus;
}

/** Whether *edit* applies to the layer *layerName* (null: the node's own layer). */
export function editsLayer(edit: FeatureEdit, layerName: string | null, nodeLayer: string | null): boolean {
  return (edit.layer ?? nodeLayer ?? null) === (layerName ?? null);
}

/**
 * The features of the layer *layerName* (null: the node's own layer) as the
 * edits of the log that apply to it leave them, shapes included: what the
 * node's tools pick, draw and reshape. Applied by `applyFeatureEdits`, the
 * one way the browser applies the log, as `curio_edit_features` does.
 */
export function editedFeatures(
  fc: { features?: any[] } | null | undefined,
  edits: readonly FeatureEdit[],
  key: string | undefined,
  layerName: string | null,
  nodeLayer: string | null,
): EditedFeature[] {
  const mine = key ? edits.filter((edit) => editsLayer(edit, layerName, nodeLayer)) : [];
  const { state, status } = applyFeatureEdits(fc?.features ?? [], mine, key ?? "", fc ?? undefined);
  const out: EditedFeature[] = [];
  state.forEach((feature, i) => {
    if (feature === null) return;
    const properties = (feature.properties ?? {}) as Record<string, unknown>;
    out.push({
      id: key ? ((properties[key] ?? null) as SelectionId | null) : null,
      geometry: (feature.geometry ?? null) as Geometry | null,
      properties,
      status: status[i],
    });
  });
  return out;
}

/** The id column of a new layer's features. */
export const newLayerKey = NEW_LAYER_KEY;

/** Whether *fc*'s coordinates are longitude-latitude. */
export function isGeographic(fc: { features?: any[]; crs?: any } | undefined): boolean {
  const name = String(fc?.crs?.properties?.name ?? "");
  if (/3395|3857|900913/.test(name)) return false;
  if (/4326|CRS84/.test(name)) return true;
  let geographic = true;
  let seen = 0;
  for (const f of (fc?.features ?? []).slice(0, 30)) {
    const walk = (v: any) => {
      if (!Array.isArray(v)) return;
      if (typeof v[0] === "number") {
        seen += 1;
        if (Math.abs(v[0]) > 180 || Math.abs(v[1]) > 90) geographic = false;
      } else v.forEach(walk);
    };
    walk(f?.geometry?.coordinates);
  }
  return seen > 0 && geographic;
}

/** The CRS name a drawn shape in *fc*'s coordinates is in. */
export function crsName(fc: { features?: any[]; crs?: any } | undefined): string {
  const name = String(fc?.crs?.properties?.name ?? "");
  const code = /EPSG::?(\d+)/.exec(name);
  if (code) return `EPSG:${code[1]}`;
  if (/CRS84/.test(name)) return "EPSG:4326";
  return isGeographic(fc) ? "EPSG:4326" : "EPSG:3395";
}

/**
 * *defs* with the columns the log's "Add a property" edits give the layer
 * *layerName*: a property added is one its features are asked for, and one
 * they are edited by, like the columns the layer came with.
 */
export function withAddedColumns(
  defs: PropertyDef[],
  edits: readonly FeatureEdit[],
  layerName: string,
  nodeLayer: string | null,
): PropertyDef[] {
  const out = [...defs];
  for (const edit of edits) {
    if (edit.op !== "add_column" || edit.enabled === false || !edit.column) continue;
    if ((edit.layer ?? nodeLayer ?? null) !== layerName || out.some((d) => d.name === edit.column)) continue;
    const type: PropertyType = typeof edit.value === "number" ? "number" : typeof edit.value === "boolean" ? "boolean" : "text";
    out.push({ name: edit.column, type });
  }
  return out;
}
