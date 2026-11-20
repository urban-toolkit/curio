/**
 * The Autark node's input, turned into the tables its document reads.
 *
 * Read through the same path as the Vega-Lite node's (utils/grammarInput): the
 * same gate, fetch, schema and geometry column, and the same refusals. Two
 * things are Autark's own. A document reads tables by name, so each input is
 * the table `input_0`, `input_1`, ... in circle order, the names Vega-Lite's
 * datasets have too (#662), while the layers an input carries keep their own
 * names. A layer chip on an input of one frame names its `input_<k>` table
 * (utils/references/codeReferences). And a table needs geometry to be drawn at
 * all, so a DataFrame becomes a FeatureCollection from its geometry column, or
 * is refused the way Vega refuses a geoshape over data with no geometry.
 *
 * A raster is a table too, under the same names, but it is not a geojson
 * source: it is listed in `rasters` with where it is, and the node loads it
 * (adapters/node/autkRasters).
 *
 * A table an upstream Autark node handed on from another workspace than the
 * default one keeps it (`workspace`), and the node loads it there. A document
 * reads a table in the workspace of the map, plot or pass that names it, so
 * tables are told apart by their key (`autkTableKey`): the name in the default
 * workspace, `<workspace>/<name>` in another.
 *
 * No autk import here: this stays testable under jest.
 */
import type { FeatureCollection } from "geojson";
import { inputTableName } from "../contracts/autkGrammar";
import {
  autkTableKey,
  autkWorkspaceOf,
  loadableFeatures,
  requestedLayerTables,
  sectionInputTables,
  sourcesAfterPasses,
  tablesReadBy,
} from "../adapters/node/autkDataCompile";
import { readableBuildingProperties } from "./buildingHeight";
import { detectCoordinateFormat } from "./geoCrs";
import { resolveGeometryField } from "./geometryField";
import { readGrammarInput, type GrammarFrame, type GrammarInput, type RasterPayload } from "./grammarInput";
import type { NodeEmptyReason } from "./nodeEmptyState";
import { toRows } from "./rowSource";
import type { PointValue } from "./selectionMatch";

export const AUTK_INPUT_LABEL = "the Autark node";

export type AutkSource = {
  type: "geojson";
  geojsonObject: FeatureCollection;
  outputTableName: string;
  coordinateFormat: string;
  layerType?: string;
  /** The workspace it is loaded into, when it is not the default one. */
  workspace?: string;
};

/** A raster the input provides, by the table name the document reads it by. */
export type AutkRasterInput = {
  outputTableName: string;
  payload: RasterPayload;
  /** The workspace it is loaded into, when it is not the default one. */
  workspace?: string;
};

/** The key a source, a raster or a table of a document is told apart by (`autkTableKey`). */
export function tableKeyOf(table: { outputTableName?: unknown; workspace?: unknown }): string {
  return autkTableKey(autkWorkspaceOf(table), typeof table?.outputTableName === "string" ? table.outputTableName : "");
}

export type PreparedAutkInput = {
  /** One geojson source per table the input provides, plus `input_<k>` for an
   * input holding one named layer, when the document names it. */
  sources: AutkSource[];
  /** The rasters the input provides, named as the geojson sources are. */
  rasters: AutkRasterInput[];
  /** The tables the input provides, by key. */
  tables: string[];
  /** Tables the input names but cannot provide, because they cannot be drawn, by key. */
  unusable: string[];
  /** Features that can be drawn. `undefined` when nothing arrived. */
  rowsIn?: number;
  /** Why some or all of the input cannot be drawn, in one sentence. */
  inputProblem?: string;
  /** The state the node's body shows when none of it can be drawn. */
  emptyReason?: NodeEmptyReason;
  detail?: string;
};

function asList<T>(value: T | T[] | undefined | null): T[] {
  if (value == null) return [];
  return Array.isArray(value) ? value : [value];
}

/**
 * Every table the document reads in the browser, by key (`autkTableKey`): map
 * layers and the raster a map's `terrain` raises its ground to, plots (and the
 * map a plot links to), and compute passes: a GPGPU, windows or clusters
 * pass's table and a GPGPU pass's `fromFeature` uniforms, a render pass's
 * viewpoints and the tables of its layers, each in the workspace of the map,
 * plot or pass that names it; and the tables a source that runs in the browser
 * after the passes reads (`sourcesAfterPasses`, `tablesReadBy`), in its own
 * workspace.
 */
export function documentTableRefs(spec: any): string[] {
  const names = new Set<string>();
  const add = (entry: unknown, name: unknown) => {
    if (typeof name === "string" && name) names.add(autkTableKey(autkWorkspaceOf(entry), name));
  };
  for (const map of asList(spec?.map)) {
    for (const ref of asList((map as any)?.layerRefs)) add(map, (ref as any)?.dataRef);
    add(map, (map as any)?.terrain?.dataRef);
  }
  for (const plot of asList(spec?.plot)) {
    add(plot, (plot as any)?.dataRef);
    add(plot, (plot as any)?.mapRef);
  }
  for (const block of asList(spec?.compute)) {
    add(block, (block as any)?.dataRef);
    add(block, (block as any)?.viewpoints?.dataRef);
    for (const layer of asList((block as any)?.layers)) add(block, (layer as any)?.dataRef);
    for (const group of [(block as any)?.uniforms, (block as any)?.uniformMatrices]) {
      if (group == null || typeof group !== "object") continue;
      for (const value of Object.values(group)) add(block, (value as any)?.fromFeature?.layer);
    }
  }
  for (const source of sourcesAfterPasses(spec)) {
    for (const table of tablesReadBy(source)) add(source, table);
  }
  return Array.from(names);
}

/** The layer type autk-db gives an OSM load's surface, and how its name ends. */
const OSM_SURFACE = "surface";
const OSM_SURFACE_SUFFIX = `_${OSM_SURFACE}`;
/** The layers an OSM load makes, each typed as it is named. */
const OSM_LAYERS: ReadonlySet<string> = new Set([OSM_SURFACE, "parks", "water", "roads", "buildings"]);

/**
 * The tables a node that draws hands autk-db, in the order it loads them, out
 * of *tables*, those at hand (its input's, then its own data section's,
 * *own*). autk-db makes the first table it loads the workspace's extent, and
 * the first polygon table its crop layer, and clips every later table to both
 * (#886). So of the input's tables only those the document names go: one it
 * does not draw would cut the ones it does. Every table of its own data
 * section goes. And a table the document names that is a layer of an OSM load
 * brings that load's surface, when it is at hand, loaded first, so the map is
 * cropped to the load's query area and no layer of the load cuts another.
 *
 * An OSM load named `X` makes the tables `X_surface`, `X_parks`, `X_water`,
 * `X_roads` and `X_buildings`, and `X_<set>_<type>` for its tag sets
 * (autk-db's names, which `requestedLayerTables` writes too), and autk-db
 * types its surface `surface`. So a table of type `surface` named `X_surface`
 * is the surface of load `X`, and a table is a layer of the load whose name,
 * with `_` after it, is the longest one that starts its own. The layers of a
 * Discovery Catalog OpenStreetMap download carry no load name: its group's
 * loader keys them `surface`, `parks`, `water`, `roads` and `buildings`, each
 * typed as it is named. So a table `surface` of type `surface` is the surface
 * of such a load, and its layers are the tables named and typed as they are.
 * A load's layers and its surface are in one workspace, so a layer brings
 * the surface of its own workspace only.
 */
export function tablesToLoad<T extends { outputTableName?: unknown; layerType?: unknown; workspace?: unknown }>(
  tables: readonly T[],
  spec: any,
  own: readonly T[] = [],
): T[] {
  const named = new Set(documentTableRefs(spec));
  const nameOf = (table: T): string => (typeof table?.outputTableName === "string" ? table.outputTableName : "");
  // The load a surface is of: `X` for `X_surface`, "" for a surface named
  // `surface` alone, and null for any other table.
  const surfaceLoad = (table: T): string | null => {
    const name = nameOf(table);
    if (table?.layerType !== OSM_SURFACE) return null;
    if (name === OSM_SURFACE) return "";
    return name.endsWith(OSM_SURFACE_SUFFIX) && name.length > OSM_SURFACE_SUFFIX.length
      ? name.slice(0, -OSM_SURFACE_SUFFIX.length)
      : null;
  };
  const loads = tables.flatMap((table) => {
    const load = surfaceLoad(table);
    return load === null ? [] : [{ load, workspace: autkWorkspaceOf(table) }];
  });
  // The load a table is a layer of, in its own workspace, or null.
  const layerLoad = (table: T): string | null => {
    const name = nameOf(table);
    const workspace = autkWorkspaceOf(table);
    let load: string | null = null;
    for (const { load: prefix, workspace: at } of loads) {
      if (at !== workspace) continue;
      const isLayer = prefix === ""
        ? OSM_LAYERS.has(name) && table?.layerType === name
        : name.startsWith(`${prefix}_`);
      if (isLayer && (load === null || prefix.length > load.length)) load = prefix;
    }
    return load;
  };
  // The surfaces of the loads the document names a layer of, by key.
  const surfaces = new Set<string>();
  for (const table of tables) {
    if (!named.has(tableKeyOf(table))) continue;
    const load = layerLoad(table);
    if (load !== null) {
      surfaces.add(autkTableKey(autkWorkspaceOf(table), load === "" ? OSM_SURFACE : load + OSM_SURFACE_SUFFIX));
    }
  }
  const brought = (table: T) => surfaceLoad(table) !== null && surfaces.has(tableKeyOf(table));
  const loaded = tables.filter((table) => own.includes(table) || named.has(tableKeyOf(table)) || brought(table));
  return [...loaded.filter(brought), ...loaded.filter((table) => !brought(table))];
}

/** A table a compute pass of the document writes. */
export type WrittenTable = {
  /** Its name: the pass's `outputTableName`, else its `dataRef`. */
  name: string;
  /**
   * The table the pass computes over: a GPGPU, windows or clusters pass's
   * `dataRef`, a render pass's viewpoints. The table it writes is empty when
   * this one is.
   */
  from: string;
  /**
   * Whether it holds the rows of `from`, one feature each: every pass's table
   * but a windows pass's and a render pass's over building windows, which hold
   * one point per window.
   */
  holdsRows: boolean;
  /**
   * The type the pass draws and hands it on as (`layerType`), read only with an
   * `outputTableName`, or the `points` of windows.
   */
  layerType?: string;
  /** The pass's workspace, where it reads `from` and writes the table, when it is not the default one. */
  workspace?: string;
};

/**
 * A compute pass's kind: `render`; `windows` and `clusters`, which autk-grammar
 * runs on the CPU; `gpgpu` for the default; or null for none of them.
 */
function passKind(pass: any): "gpgpu" | "render" | "windows" | "clusters" | null {
  if (pass == null || typeof pass !== "object") return null;
  if (pass.type === "render" || pass.type === "windows" || pass.type === "clusters") return pass.type;
  return pass.type == null || pass.type === "gpgpu" ? "gpgpu" : null;
}

/** The table a compute pass computes over: a GPGPU, windows or clusters pass's `dataRef`, a render pass's viewpoints. */
function passSource(pass: any): unknown {
  return passKind(pass) === "render" ? pass.viewpoints?.dataRef : pass?.dataRef;
}

/**
 * Whether a pass writes windows, one point a window: a windows pass, and a
 * render pass that looks out from building windows.
 */
function overWindows(pass: any): boolean {
  const kind = passKind(pass);
  return kind === "windows" || (kind === "render" && pass.viewpoints?.strategy?.type === "building-windows");
}

/**
 * The tables the document's compute passes write, in pass order, so a table a
 * pass writes from another's comes after it: each under the pass's
 * `outputTableName`, else in place of the table it computes over, as
 * autk-grammar's compute adapter keeps them (`store`), in the pass's
 * workspace; a windows pass writes only under its own name. A map or a plot
 * draws a table a pass wrote from that result, which holds every feature of
 * the table the pass computed over, in the order autk-db stores them, but for
 * windows, whose table holds one point per window. A table a pass names is
 * drawn as its `layerType`, else as `points` for windows, else as the table it
 * is computed from.
 */
export function writtenTables(spec: any): WrittenTable[] {
  const written: WrittenTable[] = [];
  for (const pass of asList<any>(spec?.compute)) {
    const kind = passKind(pass);
    if (kind === null) continue;
    const { outputTableName, layerType } = pass;
    const from = passSource(pass);
    if (typeof from !== "string" || !from) continue;
    const named = typeof outputTableName === "string" && outputTableName !== "";
    if (kind === "windows" && !named) continue;
    const windows = overWindows(pass);
    const workspace = autkWorkspaceOf(pass);
    written.push({
      name: named ? outputTableName : from,
      from,
      holdsRows: !windows,
      ...(named && typeof layerType === "string" && layerType ? { layerType } : named && windows ? { layerType: "points" } : {}),
      ...(workspace ? { workspace } : {}),
    });
  }
  return written;
}

/**
 * The tables the document's passes make, by key (`autkTableKey`): those
 * written under a name other than the table they are computed from.
 */
export function madeTables(spec: any): string[] {
  return writtenTables(spec)
    .filter((table) => table.name !== table.from)
    .map((table) => autkTableKey(table.workspace, table.name));
}

/**
 * The document's compute passes as they run over the tables at hand, each
 * table by key (`autkTableKey`), in the workspace of the pass that names it:
 * of *known*, every table the node has, those in *atHand*, which have rows.
 * autk-db holds no table without rows, so a pass whose own table (a GPGPU
 * pass's `dataRef`, a render pass's viewpoints) has none does not run, and
 * neither does a pass over the table one that does not run would write. A
 * render layer whose table has no rows draws nothing in the frames: its pass
 * runs without it, and does not run with no layer left. A table not in
 * *known* is left as the document writes it, for the run to name.
 */
export function passesAtHand(passes: readonly any[], known: ReadonlySet<string>, atHand: ReadonlySet<string>): any[] {
  const present = new Set(atHand);
  const kept: any[] = [];
  for (const pass of passes) {
    const kind = passKind(pass);
    if (kind === null) {
      kept.push(pass);
      continue;
    }
    const workspace = autkWorkspaceOf(pass);
    const keyOf = (name: unknown) => (typeof name === "string" && name ? autkTableKey(workspace, name) : null);
    const emptied = (name: unknown) => {
      const key = keyOf(name);
      return key !== null && known.has(key) && !present.has(key);
    };
    const source = passSource(pass);
    if (emptied(source)) continue;
    let runs = pass;
    if (kind === "render" && Array.isArray(pass.layers)) {
      const layers = pass.layers.filter((layer: any) => !emptied(layer?.dataRef));
      if (layers.length < pass.layers.length) {
        if (layers.length === 0) continue;
        runs = { ...pass, layers };
      }
    }
    kept.push(runs);
    const writes = keyOf(typeof pass.outputTableName === "string" && pass.outputTableName ? pass.outputTableName : source);
    if (writes !== null) present.add(writes);
  }
  return kept;
}

/** The tables the document's own data section creates, by key. */
export function ownTableNames(spec: any): string[] {
  const sources: any[] = Array.isArray(spec?.data) ? spec.data : [];
  return requestedLayerTables(sources);
}

/**
 * Whether the document reads its input at all: a compute-only document works
 * on what arrives, and any other reads it when it names a table that neither
 * its own data section nor one of its compute passes creates. A document that
 * makes everything it draws does not, so it never says "connect something".
 */
export function autkNeedsInput(spec: any): boolean {
  if (spec == null || typeof spec !== "object") return false;
  const hasRender = spec.map != null || spec.plot != null;
  const hasCompute = asList(spec.compute).length > 0;
  const hasData = Array.isArray(spec.data) && spec.data.length > 0;
  if (hasCompute && !hasRender && !hasData) return true;
  const own = new Set([...ownTableNames(spec), ...madeTables(spec)]);
  return documentTableRefs(spec).some((name) => !own.has(name));
}

/**
 * The tables of the input the document's data section reads, by key: each a
 * heatmap or a join of the section reads that none of its own sources loads
 * (`sectionInputTables`). The node finds them among its input's tables by the
 * names it reads its input by, as it finds a map's.
 */
export function sectionInputRefs(spec: any): string[] {
  return sectionInputTables(Array.isArray(spec?.data) ? spec.data : [])
    .map((table) => autkTableKey(table.workspace, table.name));
}

/**
 * Whether the document needs the node's input: when it names a table it does
 * not make (`autkNeedsInput`), or when its data section reads tables of the
 * input (`sectionInputRefs`). Until one arrives, the node says what feeds it,
 * as any node that reads its input does.
 */
export function autkReadsInput(spec: any): boolean {
  return autkNeedsInput(spec) || sectionInputRefs(spec).length > 0;
}

/** The table a frame becomes: its own name, else `input_<k>`, after its place
 * among the node's inputs (or in the one bundle it arrived in). */
export function autkTableName(frame: GrammarFrame): string {
  if (frame.name) return frame.name;
  return inputTableName(frame.fromBundle ? frame.index : 0);
}

type FrameResult =
  | { fc: FeatureCollection }
  | { reason: NodeEmptyReason; detail: string };

const hasGeometry = (feature: any) => feature?.geometry != null;

/**
 * The frame as a FeatureCollection, every row kept in its place: a map pick and
 * a Data Pool's flags address features by position, so a row without geometry
 * stays where it is and simply draws nothing.
 */
function featuresOf(frame: GrammarFrame, name: string): FrameResult {
  let fc: FeatureCollection;
  if (frame.dataType === "geodataframe") {
    fc = frame.payload;
  } else {
    // A DataFrame: its geometry column, found the way the Vega-Lite node finds it.
    const rows = toRows({ data: frame.payload });
    const { field, candidates } = resolveGeometryField(rows, null);
    if (!field) {
      return candidates.length === 0
        ? {
            reason: "geometry-unresolved",
            detail: `${name} has no geometry column, so there is nothing to draw. Return a GeoDataFrame.`,
          }
        : {
            reason: "geometry-ambiguous",
            detail: `${name} has several geometry columns (${candidates.join(", ")}). `
              + "Return a GeoDataFrame with its active geometry set.",
          };
    }
    fc = {
      type: "FeatureCollection",
      features: rows.map((row) => {
        const cell = row[field] as any;
        const { [field]: _geometry, ...properties } = row;
        return { type: "Feature", geometry: cell?.type === "Feature" ? cell.geometry : cell ?? null, properties };
      }),
    } as FeatureCollection;
  }
  const features: any[] = Array.isArray((fc as any)?.features) ? (fc as any).features : [];
  if (features.length > 0 && !features.some(hasGeometry)) {
    return {
      reason: "geometry-unresolved",
      detail: `No row of ${name} has a geometry, so there is nothing to draw.`,
    };
  }
  return { fc };
}

/**
 * A buildings table whose heights autk-map and a compute can read, one feature
 * per row as it came: a feature autk-map would misread, or one with no
 * `height`, gets its `height` written, and every other one is the same object.
 * A node reads its input's buildings and those its own data section loads
 * through it.
 */
export function withReadableHeights(fc: FeatureCollection): FeatureCollection {
  const features: any[] = Array.isArray((fc as any)?.features) ? (fc as any).features : [];
  let changed = false;
  const next = features.map((feature) => {
    const properties = feature?.properties;
    const readable = readableBuildingProperties(properties);
    if (readable === properties) return feature;
    changed = true;
    return { ...feature, properties: readable };
  });
  return changed ? ({ ...fc, features: next } as FeatureCollection) : fc;
}

/**
 * Which input row each position of a loaded table stands for. `load` is the
 * table as Curio hands it to autk-db (what a plot reads and selects in); `map`
 * is the table as autk-db stores it, for a layer whose drawn rows cannot be
 * read back (`drawnRows`). `null` means positions and input rows agree.
 */
export type LoadOrder = { load: number[] | null; map: number[] | null };

/**
 * The property each feature handed to autk-db for a map carries: its input
 * row. A map draws a layer as autk-db exports it (`getLayer`), which can leave
 * rows out and keep the others in an order of its own, so the rows a map draws
 * are read back from what it exported (`drawnRows`).
 */
export const INPUT_ROW = "__curio_row";

/**
 * The source as autk-db will load it, and the order that lets a pick or a
 * highlight still name the input's rows. The rows go through
 * `loadableFeatures`: a row with no geometry gets an empty one, and a first row
 * with none trades places with the first that has one. autk-db then stores the
 * rows whose geometry is empty before the others, each in the order handed. A
 * source for a map (*tagRows*) has each feature carry its input row
 * (`INPUT_ROW`), by which the rows the map draws are read back.
 */
export function loadableSource(
  source: AutkSource,
  { tagRows = false }: { tagRows?: boolean } = {},
): { source: AutkSource; order: LoadOrder } {
  const features: any[] = (source.geojsonObject as any)?.features ?? [];
  const loadable = loadableFeatures(features);
  const load = loadable.order;
  const rows = load ?? features.map((_, i) => i);
  const empty = rows.filter((i) => !hasGeometry(features[i]));
  const map = empty.length > 0 ? [...empty, ...rows.filter((i) => hasGeometry(features[i]))] : load;
  const handed = tagRows
    ? loadable.features.map((feature: any, at: number) => ({ ...feature, properties: { ...(feature?.properties ?? {}), [INPUT_ROW]: rows[at] } }))
    : loadable.features;
  return {
    source: handed === features
      ? source
      : { ...source, geojsonObject: { ...source.geojsonObject, features: handed } as FeatureCollection },
    order: { load, map },
  };
}

/**
 * The features of a layer autk-db exported (`getLayer`) as autk-grammar hands
 * them to a map: those with a geometry, in the export's order.
 */
export function drawnFeatures(exported: { features?: any[] } | null | undefined): any[] {
  const features: any[] = Array.isArray(exported?.features) ? exported!.features! : [];
  return features.filter((feature) => feature?.geometry != null);
}

/** What autk-map draws a feature it was handed as: one component, which names the feature by its index. */
export type DrawnComponent = { featureIndex?: number };

/**
 * The input row each position of a map layer stands for, from the features it
 * was handed (*features*, `drawnFeatures`). autk-map draws each one as one
 * component, in their order, and none for a feature with nothing to draw; a
 * component names its feature (*components*, autk-map's `featureIndex`), and
 * the feature carries its input row (`INPUT_ROW`). Without *components*, each
 * feature is a position. Null when a feature drawn carries no row, as one a
 * document loads itself does not.
 */
export function drawnRows(
  features: readonly any[] | null | undefined,
  components?: readonly DrawnComponent[] | null,
): number[] | null {
  if (!features || features.length === 0) return null;
  const count = Array.isArray(components) ? components.length : features.length;
  const rows: number[] = [];
  for (let position = 0; position < count; position++) {
    const index = components?.[position]?.featureIndex;
    const row = features[Number.isInteger(index) ? index! : position]?.properties?.[INPUT_ROW];
    if (!Number.isInteger(row)) return null;
    rows.push(row);
  }
  return rows;
}

/** The input row a table position stands for. */
export function inputRow(position: number, order: number[] | null | undefined): number {
  return order ? order[position] ?? position : position;
}

/** The table positions of these input rows; a row that is not drawn has none. */
export function tablePositions(rows: number[], order: number[] | null | undefined): number[] {
  if (!order) return rows;
  const at = new Map(order.map((row, position) => [row, position]));
  return rows.flatMap((row) => (at.has(row) ? [at.get(row)!] : []));
}

/**
 * The key columns a map layer or a plot names its rows by (`selectFields`): a
 * pick or a brush on it sends their values. Null when it names none.
 */
export function selectFieldsOf(view: any): string[] | null {
  const fields = view?.selectFields;
  return Array.isArray(fields) && fields.length > 0 && fields.every((f) => typeof f === "string" && f !== "")
    ? fields
    : null;
}

/**
 * Why a pick or a brush could not send the key columns a document names
 * (`selectFields`), or null when it can. They are read from the features of
 * the node's input, the rows the charts linked to it hold. A table the
 * document loads itself is not among them: the map draws it with the features
 * that have no geometry left out, so its picks name none of these rows. And a
 * column that no feature of its table has names nothing.
 */
export function selectFieldsProblem(spec: any, sources: readonly AutkSource[]): string | null {
  const own = new Set([
    ...ownTableNames(spec),
    ...asList<any>(spec?.data).filter((source) => typeof source?.outputTableName === "string").map(tableKeyOf),
  ]);
  // Each layer and plot, with the workspace its table is read from: its map's, or the plot's own.
  const views = [
    ...asList<any>(spec?.map).flatMap((map) => asList<any>(map?.layerRefs).map((view) => ({ view, workspace: autkWorkspaceOf(map) }))),
    ...asList<any>(spec?.plot).map((view) => ({ view, workspace: autkWorkspaceOf(view) })),
  ];
  for (const { view, workspace } of views) {
    const fields = selectFieldsOf(view);
    if (!fields || typeof view?.dataRef !== "string") continue;
    const table = autkTableKey(workspace, view.dataRef);
    const source = sources.find((s) => tableKeyOf(s) === table);
    if (!source) {
      if (!own.has(table)) continue;
      return `selectFields needs ${table} to come from this node's input, but this document loads it. `
        + `Load ${table} in an upstream node and connect that node here.`;
    }
    const features: any[] = (source.geojsonObject as any)?.features ?? [];
    // An empty table is reported as one when the node draws.
    if (features.length === 0) continue;
    const missing = fields.find((field) => !features.some(
      (feature) => feature?.properties != null && Object.prototype.hasOwnProperty.call(feature.properties, field),
    ));
    if (missing) return `selectFields names ${missing}, which no feature of ${table} has.`;
  }
  return null;
}

/**
 * The values input *rows* hold for *fields*, one point per row, as a Vega-Lite
 * point select over fields sends them (#847): `{unit_id: 103}`. Each is sent
 * once, in row order, and a row that holds no value for one of them is left
 * out. Whatever reads them marks every row holding those values, in its own
 * rows (utils/selectionMatch).
 */
export function keyValues(rows: number[], features: readonly any[], fields: string[]): PointValue[] {
  const own = (properties: any, field: string) =>
    properties != null && Object.prototype.hasOwnProperty.call(properties, field) ? properties[field] : undefined;
  // The values sent so far, field by field.
  const sent = new Map<unknown, any>();
  const points: PointValue[] = [];
  for (const row of rows) {
    const values = fields.map((field) => own(features[row]?.properties, field));
    if (values.some((value) => value === undefined)) continue;
    let level = sent;
    let isNew = false;
    for (const value of values) {
      if (!level.has(value)) {
        level.set(value, new Map());
        isNew = true;
      }
      level = level.get(value);
    }
    if (isNew) points.push(Object.fromEntries(fields.map((field, i) => [field, values[i]])));
  }
  return points;
}

/** What a frame becomes under a name: a geojson source and its rows, a
 * raster, or the reason it cannot be drawn. */
type FrameTable =
  | { source: AutkSource; rows: number }
  | { raster: AutkRasterInput }
  | { refusal: { reason: NodeEmptyReason; detail: string } };

function frameTable(frame: GrammarFrame, name: string): FrameTable {
  // A table handed on from another workspace than the default one is loaded there.
  const workspace = frame.workspace ? { workspace: frame.workspace } : {};
  if (frame.dataType === "raster") return { raster: { outputTableName: name, payload: frame.payload, ...workspace } };
  const result = featuresOf(frame, name);
  if ("reason" in result) return { refusal: result };
  // A layer an Autark data node stored empty comes back with no feature
  // list: it has no rows, and the render leaves it out like any empty table.
  const features = (result.fc as any).features;
  const geojsonObject = frame.layerType === "buildings" ? withReadableHeights(result.fc) : result.fc;
  return {
    source: {
      type: "geojson",
      geojsonObject,
      outputTableName: name,
      coordinateFormat: detectCoordinateFormat(geojsonObject as any),
      ...(frame.layerType ? { layerType: frame.layerType } : {}),
      ...workspace,
    },
    rows: Array.isArray(features) ? features.length : 0,
  };
}

/** Read the Autark node's input: the fetch, done once per input object. */
export function readAutkInput(input: any, opts: { preview?: boolean } = {}): Promise<GrammarInput> {
  return readGrammarInput(input, { label: AUTK_INPUT_LABEL, bundles: true, rasters: true, preview: opts.preview });
}

/**
 * The geojson sources a document reads from an input already read.
 * `alias: false` leaves the `input_<k>` names of named layers out: a compute
 * step passes its layers on under their own names.
 */
export function autkSourcesFrom(
  read: GrammarInput,
  spec: any,
  opts: { alias?: boolean } = {},
): PreparedAutkInput {
  if (read.emptyReason) {
    return {
      sources: [],
      rasters: [],
      tables: [],
      unusable: [inputTableName(0)],
      emptyReason: read.emptyReason,
      detail: read.detail,
      inputProblem: read.detail,
    };
  }
  if (read.frames.length === 0) return { sources: [], rasters: [], tables: [], unusable: [] };

  const sources: AutkSource[] = [];
  const rasters: AutkRasterInput[] = [];
  const unusable: string[] = [];
  const problems: string[] = [];
  let firstRefusal: { reason: NodeEmptyReason; detail: string } | null = null;
  let rowsIn = 0;
  // Which input brought each table, so a name two inputs bring is caught.
  const broughtBy = new Map<string, number>();
  // What each frame became, so an input's `input_<k>` reads the frame that
  // input brought, also when an earlier input took its layer's name (#744).
  const became = new Map<GrammarFrame, { table: FrameTable; taken: boolean }>();
  // Names two inputs bring, and where their message goes among the problems:
  // it says where the second layer is, which is known once every frame is in.
  const clashes: Array<{ at: number; earlier: number; frame: GrammarFrame; name: string }> = [];

  for (const frame of read.frames) {
    let name = autkTableName(frame);
    // Two tables of one name are two tables when they are in two workspaces.
    const keyOf = (table: string) => autkTableKey(frame.workspace, table);
    let taken = false;
    const earlier = broughtBy.get(keyOf(name));
    if (earlier !== undefined) {
      if (!frame.name) {
        // Several unnamed frames on one input are told apart by count.
        let n = 1;
        while (broughtBy.has(keyOf(`${name}_${n}`))) n += 1;
        name = `${name}_${n}`;
      } else {
        // The name stays the earlier input's layer.
        clashes.push({ at: problems.length, earlier, frame, name });
        problems.push("");
        taken = true;
      }
    }
    if (!taken) broughtBy.set(keyOf(name), frame.circle);
    const table = frameTable(frame, name);
    became.set(frame, { table, taken });
    if (taken) continue;
    if ("raster" in table) {
      rasters.push(table.raster);
    } else if ("refusal" in table) {
      unusable.push(keyOf(name));
      problems.push(table.refusal.detail);
      firstRefusal ??= table.refusal;
    } else {
      rowsIn += table.rows;
      sources.push(table.source);
    }
  }

  if (read.skipped?.length) problems.push(`Left out: ${read.skipped.join(", ")}.`);

  // `input_<k>` also names an input that holds one named layer, unless one of
  // the input's tables already has that name. An input of several layers keeps
  // their names, and `alias: false` passes layers on under their own names.
  const byCircle = new Map<number, GrammarFrame[]>();
  for (const frame of read.frames) byCircle.set(frame.circle, [...(byCircle.get(frame.circle) ?? []), frame]);
  // The alias is the same table under another name, so it is in that table's workspace.
  const aliasOf = (circle: number): string | null => {
    const frames = byCircle.get(circle) ?? [];
    if (opts.alias === false || frames.length !== 1 || !frames[0].name) return null;
    const alias = inputTableName(circle);
    const key = autkTableKey(frames[0].workspace, alias);
    const named = sources.some((s) => tableKeyOf(s) === key) || rasters.some((r) => tableKeyOf(r) === key);
    return named ? null : alias;
  };

  for (const { at, earlier, frame, name } of clashes) {
    const alias = aliasOf(frame.circle);
    problems[at] = `input_${earlier} and input_${frame.circle} both bring a layer named ${name}: `
      + `${name} means the one from input_${earlier}, and `
      + (alias
        ? `${alias} means the one from input_${frame.circle}.`
        : `the one from input_${frame.circle} is left out. Rename one of them.`);
  }

  // The alias is added only when the document reads it, as the Vega-Lite node
  // attaches geometry only when the spec draws it: in a map, a plot or a pass,
  // or in a heatmap or a join of its data section.
  const refs = new Set([...documentTableRefs(spec), ...sectionInputRefs(spec)]);
  byCircle.forEach((frames, circle) => {
    const alias = aliasOf(circle);
    const key = alias === null ? null : autkTableKey(frames[0].workspace, alias);
    if (!alias || !key || !refs.has(key)) return;
    const { table, taken } = became.get(frames[0])!;
    if ("source" in table) {
      sources.unshift({ ...table.source, outputTableName: alias });
      if (taken) rowsIn += table.rows;
    } else if ("raster" in table) {
      rasters.unshift({ ...table.raster, outputTableName: alias });
    } else if (!unusable.includes(key)) {
      unusable.push(key);
      if (taken) {
        problems.push(table.refusal.detail);
        firstRefusal ??= table.refusal;
      }
    }
  });

  const prepared: PreparedAutkInput = {
    sources,
    rasters,
    tables: [...sources.map(tableKeyOf), ...rasters.map(tableKeyOf)],
    unusable,
    rowsIn,
    ...(problems.length ? { inputProblem: problems.join(" ") } : {}),
  };
  if (sources.length === 0 && rasters.length === 0 && firstRefusal) {
    prepared.emptyReason = firstRefusal.reason;
    prepared.detail = firstRefusal.detail;
  }
  return prepared;
}

/** Turn `data.input` into the geojson sources an Autark document reads. */
export async function prepareAutkInput(
  input: any,
  spec: any,
  opts: { preview?: boolean; alias?: boolean } = {},
): Promise<PreparedAutkInput> {
  return autkSourcesFrom(await readAutkInput(input, opts), spec, opts);
}
