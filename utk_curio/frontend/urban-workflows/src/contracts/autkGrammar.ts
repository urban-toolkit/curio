/**
 * What a grammar node calls its inputs, the views of an Autark document it
 * refuses, and the keys of a document it does not run, over the values in
 * autkGrammar.json, which the backend reads too (contracts.input_table_name,
 * autk_view_problem, autk_key_problem and autk_raster_pass_problem).
 * autkGrammar.cases.json holds the cases both sides run.
 */
import autkGrammar from "./autkGrammar.json";

/** The name a grammar node's input at *position* is read by: input_0, input_1, ... in circle order. */
export function inputTableName(position: number): string {
  return `${autkGrammar.inputTablePrefix}${position}`;
}

/** *value* as a list: none (or null) is an empty list, and one value a list of one. */
function listOf(value: unknown): unknown[] {
  if (value == null) return [];
  return Array.isArray(value) ? value : [value];
}

/** A view's own string field *key*, or undefined when it writes none. */
function fieldOf(view: unknown, key: string): string | undefined {
  if (view === null || typeof view !== "object" || Array.isArray(view)) return undefined;
  const value = (view as Record<string, unknown>)[key];
  return typeof value === "string" ? value : undefined;
}

/** The name autk-grammar knows a plot by: its `id`, else its `dataRef`. */
const plotNameOf = (plot: unknown): string | undefined => fieldOf(plot, "id") ?? fieldOf(plot, "dataRef");

/** A map layer's id in its map: its `title`, else its `dataRef`, as autk-grammar names it. */
const layerIdOf = (layer: unknown): string | undefined => fieldOf(layer, "title") ?? fieldOf(layer, "dataRef");

/**
 * What a document whose views autk-grammar refuses is told before anything
 * runs, in the grammar's own words (autkGrammar.json's `viewRules`), else
 * null. An id names one view: no id is empty, and no two maps or plots share
 * one. A plot without an id is known by its `dataRef`, so no two plots are
 * known by one name. Each link names a plot (its `id`, else its `dataRef`), a
 * map by its `id`, and a layer of that map: its `layer`, a layer's `title`,
 * else its `dataRef`, or without it a layer that draws the plot's table. The
 * grammar checks its ids as its run starts and its links once it drew, so a
 * node checks both before it loads anything. Links join views: a document
 * that draws none is told it runs nothing, not of its links.
 */
export function autkViewProblem(spec: unknown): string | null {
  if (spec === null || typeof spec !== "object" || Array.isArray(spec)) return null;
  const document = spec as Record<string, unknown>;
  const rules = autkGrammar.viewRules;
  const maps = listOf(document.map);
  const plots = listOf(document.plot);
  const ids = new Set<string>();
  for (const view of [...maps, ...plots]) {
    const id = fieldOf(view, "id");
    if (id === undefined) continue;
    if (id === "") return rules.emptyId;
    if (ids.has(id)) return fill(rules.sharedId, { id });
    ids.add(id);
  }
  const named = new Map<string, boolean>();
  for (const plot of plots) {
    const name = plotNameOf(plot);
    if (name === undefined) continue;
    const hasId = fieldOf(plot, "id") !== undefined;
    if (named.has(name)) {
      return !named.get(name) && !hasId
        ? fill(rules.plotsWithoutIds, { table: name })
        : fill(rules.plotIdIsDataRef, { id: name });
    }
    named.set(name, hasId);
  }
  const links = maps.length + plots.length > 0 && Array.isArray(document.links) ? document.links : [];
  for (const link of links) {
    const source = String(fieldOf(link, "source"));
    const target = String(fieldOf(link, "target"));
    const plot = plots.find((p) => plotNameOf(p) === source);
    if (plot === undefined) return fill(rules.linkSource, { source });
    const map = maps.find((m) => fieldOf(m, "id") === target);
    if (map === undefined) return fill(rules.linkTarget, { target });
    const layer = fieldOf(link, "layer");
    const table = fieldOf(plot, "dataRef");
    const layers = listOf((map as Record<string, unknown>).layerRefs);
    const drawn = layers.some((l) => (layer !== undefined ? layerIdOf(l) === layer : fieldOf(l, "dataRef") === table));
    if (!drawn) {
      return layer !== undefined
        ? fill(rules.linkLayer, { source, target, layer })
        : fill(rules.linkTable, { source, target, table: String(table) });
    }
  }
  return null;
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

/** A raster table: its name, and its workspace when it is not the default one. */
export type AutkRasterTable = { name: string; workspace?: string };

/**
 * The workspace *object* (a source, a pass or a raster) names, or undefined for
 * autk-db's default one (autkGrammar.json's `defaultWorkspace`), named or not.
 */
function workspaceOf(object: unknown): string | undefined {
  const workspace = object !== null && typeof object === "object"
    ? (object as Record<string, unknown>).workspace
    : undefined;
  return typeof workspace === "string" && workspace !== "" && workspace !== autkGrammar.defaultWorkspace
    ? workspace
    : undefined;
}

/**
 * What a document is told when one of its compute passes reads a raster, else
 * null: the first pass whose `dataRef`, in the pass's workspace, is one of
 * *rasters*, with where it is written, as a key a node does not run yet is told
 * (autkGrammar.json's `rasterPass`). A pass computes one value for each feature
 * of the table it reads, and a raster holds all its cells in one feature.
 */
export function autkRasterPassProblem(spec: unknown, rasters: Iterable<AutkRasterTable>): string | null {
  if (spec === null || typeof spec !== "object" || Array.isArray(spec)) return null;
  const held = [...rasters].map((raster) => ({ name: raster.name, workspace: workspaceOf(raster) }));
  for (const { path, object } of objectsAt(spec as Record<string, unknown>, "compute[]")) {
    const table = (object as Record<string, unknown> | null)?.dataRef;
    const workspace = workspaceOf(object);
    if (typeof table === "string" && held.some((raster) => raster.name === table && raster.workspace === workspace)) {
      return autkNotRunYet(fill(autkGrammar.rasterPass, { table }), path);
    }
  }
  return null;
}

/**
 * The tables *document*'s own data sources of autkGrammar.json's
 * `rasterSources` kinds write, its heatmaps and GeoTIFFs, each in its workspace.
 */
function ownRasters(document: Record<string, unknown>): AutkRasterTable[] {
  const rasters: AutkRasterTable[] = [];
  for (const { object } of objectsAt(document, "data[]")) {
    if (object === null || typeof object !== "object" || Array.isArray(object)) continue;
    const { type, outputTableName } = object as Record<string, unknown>;
    if (typeof type === "string" && autkGrammar.rasterSources.includes(type)
      && typeof outputTableName === "string" && outputTableName) {
      rasters.push({ name: outputTableName, workspace: workspaceOf(object) });
    }
  }
  return rasters;
}

/** The key of a table in a workspace: its name in the default one, `<workspace>/<name>` in another. */
const tableKeyIn = (workspace: string | undefined, name: string): string => (workspace ? `${workspace}/${name}` : name);

/**
 * What a document is told when its views read an OpenStreetMap table its own
 * data section loads both as OpenStreetMap elements (`osmElements`) and row
 * by row, else null: the first view that reads such a table otherwise than
 * the first view of it did, with where it is written, as a key a node does not
 * run yet is told (autkGrammar.json's `osmElementsMixed`). A node's loaders
 * read such a table one way, which every view of it then draws. Its tables are
 * an area's layers, `<outputTableName>_<layer>`, and tag sets,
 * `<outputTableName>_<name>_<type>`, each in the source's workspace; a view
 * reads its table in its own. A table of the node's input is read row by row,
 * whatever a view says. The maps' layers are read first, then the plots.
 */
export function autkOsmElementsProblem(spec: unknown): string | null {
  if (spec === null || typeof spec !== "object" || Array.isArray(spec)) return null;
  const document = spec as Record<string, unknown>;
  const own = new Set<string>();
  for (const { object } of objectsAt(document, "data[]")) {
    const source = object as Record<string, any> | null;
    if (source?.type !== "osm" || typeof source.outputTableName !== "string" || !source.outputTableName) continue;
    const out = source.outputTableName;
    const layers = listOf(source.autoLoadLayers?.layers).map((layer) => `${out}_${layer}`);
    const tagSets = listOf(source.tagSets)
      .filter((set: any) => set?.name && set?.type)
      .map((set: any) => `${out}_${set.name}_${set.type}`);
    for (const table of [...layers, ...tagSets]) own.add(tableKeyIn(workspaceOf(source), table));
  }
  // Each such table and the way its first view reads it, by key.
  const firstWay = new Map<string, boolean>();
  const readOtherwise = (view: unknown, reader: unknown): string | null => {
    const table = fieldOf(reader, "dataRef");
    if (table === undefined) return null;
    const key = tableKeyIn(workspaceOf(view), table);
    if (!own.has(key)) return null;
    const asElements = (reader as Record<string, unknown>).osmElements === true;
    if (!firstWay.has(key)) firstWay.set(key, asElements);
    return firstWay.get(key) === asElements ? null : key;
  };
  for (const { path, object: map } of objectsAt(document, "map[]")) {
    const layers = (map as Record<string, unknown> | null)?.layerRefs;
    for (const [i, layer] of listOf(layers).entries()) {
      const table = readOtherwise(map, layer);
      if (table !== null) {
        const at = Array.isArray(layers) ? `${path}.layerRefs[${i}]` : `${path}.layerRefs`;
        return autkNotRunYet(fill(autkGrammar.osmElementsMixed, { table }), at);
      }
    }
  }
  for (const { path, object: plot } of objectsAt(document, "plot[]")) {
    const table = readOtherwise(plot, plot);
    if (table !== null) return autkNotRunYet(fill(autkGrammar.osmElementsMixed, { table }), path);
  }
  return null;
}

/**
 * What a document that writes a key a node does not run is told, else null.
 * A key autk-grammar 5 renamed comes first, named with its new name; then a
 * key of autk-grammar 5 a node does not run yet. The first of autkGrammar.json's
 * keys the document writes is the one it is told of, with where it is written.
 * Then an OpenStreetMap table of its own read both as elements and row by row
 * (autkOsmElementsProblem). Last, a compute pass over a raster the document's
 * own data writes, which a node does not run either (autkRasterPassProblem).
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
  return autkOsmElementsProblem(document) ?? autkRasterPassProblem(document, ownRasters(document));
}
