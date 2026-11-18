/**
 * What a grammar node calls its inputs, the one view an Autark node draws, and
 * the keys of a document it does not run, over the values in autkGrammar.json,
 * which the backend reads too (contracts.input_table_name,
 * autk_one_view_problem, autk_key_problem and autk_raster_pass_problem).
 * autkGrammar.cases.json holds the cases both sides run.
 */
import autkGrammar from "./autkGrammar.json";

/** The name a grammar node's input at *position* is read by: input_0, input_1, ... in circle order. */
export function inputTableName(position: number): string {
  return `${autkGrammar.inputTablePrefix}${position}`;
}

/**
 * What a document with more than one view is told, when *spec* has a map and a
 * plot, or lists more than one map or more than one plot; else null. A list of
 * one map or one plot is that view.
 */
export function autkOneViewProblem(spec: unknown): string | null {
  if (spec === null || typeof spec !== "object" || Array.isArray(spec)) return null;
  const { map, plot } = spec as { map?: unknown; plot?: unknown };
  const views = [map, plot];
  const both = views.every((view) => view != null);
  const several = views.some((view) => Array.isArray(view) && view.length > 1);
  return both || several ? autkGrammar.oneView : null;
}

/**
 * A key autkGrammar.json names, where it is written: `in` is "" for the
 * document, or a section, whose one object or each object of its list holds
 * the key ("map[]" a map, "compute[]" a pass); with `value`, only that value
 * of the key counts.
 */
type KeyRule = { in: string; key: string; value?: string };

/** Each object *spec* holds where *place* says, with its path ("map", "compute[0]"). */
function objectsAt(spec: Record<string, unknown>, place: string): Array<{ path: string; object: unknown }> {
  if (place === "") return [{ path: "", object: spec }];
  const section = place.replace(/\[\]$/, "");
  const held = spec[section];
  if (held == null) return [];
  if (Array.isArray(held)) return held.map((object, i) => ({ path: `${section}[${i}]`, object }));
  return [{ path: section, object: held }];
}

/** The path of the first object of *spec* that writes *rule*'s key, or null. */
function written(spec: Record<string, unknown>, rule: KeyRule): string | null {
  for (const { path, object } of objectsAt(spec, rule.in)) {
    if (object === null || typeof object !== "object" || Array.isArray(object)) continue;
    const value = (object as Record<string, unknown>)[rule.key];
    if (value == null) continue;
    if (rule.value !== undefined && value !== rule.value) continue;
    return path;
  }
  return null;
}

/** *template* with each `{name}` replaced by its value. */
function fill(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => values[name] ?? whole);
}

/**
 * What a document is told of *what* it uses that a node does not run yet,
 * written at *path* ("" for the document itself): autkGrammar.json's
 * `notRunYetKey`, filled.
 */
export function autkNotRunYet(what: string, path: string): string {
  return fill(autkGrammar.notRunYetKey, { what, at: path ? fill(autkGrammar.keyAt, { path }) : "" });
}

/**
 * What a document is told when one of its compute passes reads a raster, else
 * null: the first pass whose `dataRef` is one of *rasters*, with where it is
 * written, as a key a node does not run yet is told (autkGrammar.json's
 * `rasterPass`). A pass computes one value for each feature of the table it
 * reads, and a raster holds all its cells in one feature.
 */
export function autkRasterPassProblem(spec: unknown, rasters: Iterable<string>): string | null {
  if (spec === null || typeof spec !== "object" || Array.isArray(spec)) return null;
  const names = new Set(rasters);
  for (const { path, object } of objectsAt(spec as Record<string, unknown>, "compute[]")) {
    const table = (object as Record<string, unknown> | null)?.dataRef;
    if (typeof table === "string" && names.has(table)) {
      return autkNotRunYet(fill(autkGrammar.rasterPass, { table }), path);
    }
  }
  return null;
}

/** The tables *document*'s own data sources of autkGrammar.json's `rasterSources` kinds write: its heatmaps and GeoTIFFs. */
function ownRasters(document: Record<string, unknown>): string[] {
  const names: string[] = [];
  for (const { object } of objectsAt(document, "data[]")) {
    if (object === null || typeof object !== "object" || Array.isArray(object)) continue;
    const { type, outputTableName } = object as Record<string, unknown>;
    if (typeof type === "string" && autkGrammar.rasterSources.includes(type)
      && typeof outputTableName === "string" && outputTableName) names.push(outputTableName);
  }
  return names;
}

/**
 * What a document that writes a key a node does not run is told, else null.
 * A key autk-grammar 5 renamed comes first, named with its new name; then a
 * key of autk-grammar 5 a node does not run yet. The first of autkGrammar.json's
 * keys the document writes is the one it is told of, with where it is written.
 * Last, a compute pass over a raster the document's own data writes, which a
 * node does not run either (autkRasterPassProblem).
 */
export function autkKeyProblem(spec: unknown): string | null {
  if (spec === null || typeof spec !== "object" || Array.isArray(spec)) return null;
  const document = spec as Record<string, unknown>;
  const at = (path: string) => (path ? fill(autkGrammar.keyAt, { path }) : "");
  for (const rule of autkGrammar.renamedKeys) {
    const path = written(document, rule);
    if (path !== null) return fill(autkGrammar.renamedKey, { key: rule.key, at: at(path), renamedTo: rule.renamedTo });
  }
  for (const rule of autkGrammar.notRunYet as Array<KeyRule & { what: string }>) {
    const path = written(document, rule);
    if (path !== null) return autkNotRunYet(rule.what, path);
  }
  return autkRasterPassProblem(document, ownRasters(document));
}
