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
 * No autk import here: this stays testable under jest.
 */
import type { FeatureCollection } from "geojson";
import { inputTableName } from "../generated/autkGrammar";
import { loadableFeatures, requestedLayerTables } from "../adapters/node/autkDataCompile";
import { readableBuildingProperties } from "./buildingHeight";
import { detectCoordinateFormat } from "./geoCrs";
import { resolveGeometryField } from "./geometryField";
import { readGrammarInput, type GrammarFrame, type GrammarInput, type RasterPayload } from "./grammarInput";
import type { NodeEmptyReason } from "./nodeEmptyState";
import { toRows } from "./rowSource";

export const AUTK_INPUT_LABEL = "the Autark node";

export type AutkSource = {
  type: "geojson";
  geojsonObject: FeatureCollection;
  outputTableName: string;
  coordinateFormat: string;
  layerType?: string;
};

/** A raster the input provides, by the table name the document reads it by. */
export type AutkRasterInput = {
  outputTableName: string;
  payload: RasterPayload;
};

export type PreparedAutkInput = {
  /** One geojson source per table the input provides, plus `input_<k>` for an
   * input holding one named layer, when the document names it. */
  sources: AutkSource[];
  /** The rasters the input provides, named as the geojson sources are. */
  rasters: AutkRasterInput[];
  /** The tables the input provides, by name. */
  tables: string[];
  /** Tables the input names but cannot provide, because they cannot be drawn. */
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
 * Every table name the document reads in the browser: map layers, plots (and
 * the map a plot links to), compute blocks and their `fromFeature` uniforms.
 */
export function documentTableRefs(spec: any): string[] {
  const names = new Set<string>();
  const add = (name: unknown) => {
    if (typeof name === "string" && name) names.add(name);
  };
  for (const map of asList(spec?.map)) {
    for (const ref of asList((map as any)?.layerRefs)) add((ref as any)?.dataRef);
  }
  for (const plot of asList(spec?.plot)) {
    add((plot as any)?.dataRef);
    add((plot as any)?.mapRef);
  }
  for (const block of asList(spec?.compute)) {
    add((block as any)?.dataRef);
    for (const group of [(block as any)?.uniforms, (block as any)?.uniformMatrices]) {
      if (group == null || typeof group !== "object") continue;
      for (const value of Object.values(group)) add((value as any)?.fromFeature?.layer);
    }
  }
  return Array.from(names);
}

/** The tables the document's own data section creates. */
export function ownTableNames(spec: any): string[] {
  const sources: any[] = Array.isArray(spec?.data) ? spec.data : [];
  const names = new Set(requestedLayerTables(sources));
  // A heatmap makes a table too; the sandbox does not run it, so the load
  // contract does not list it.
  for (const source of sources) {
    if (source?.type === "heatmap" && source.outputTableName) names.add(source.outputTableName);
  }
  return Array.from(names);
}

/**
 * Whether the document reads its input at all: a compute-only document works
 * on what arrives, and any other reads it when it names a table its own data
 * section does not create. A document that loads everything it draws does not,
 * so it never says "connect something".
 */
export function autkNeedsInput(spec: any): boolean {
  if (spec == null || typeof spec !== "object") return false;
  const hasRender = spec.map != null || spec.plot != null;
  const hasCompute = asList(spec.compute).length > 0;
  const hasData = Array.isArray(spec.data) && spec.data.length > 0;
  if (hasCompute && !hasRender && !hasData) return true;
  const own = new Set(ownTableNames(spec));
  return documentTableRefs(spec).some((name) => !own.has(name));
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
 */
function withReadableHeights(fc: FeatureCollection): FeatureCollection {
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
 * is the table as autk-db stores it, which a map draws. `null` means positions
 * and input rows agree.
 */
export type LoadOrder = { load: number[] | null; map: number[] | null };

/**
 * The source as autk-db will load it, and the order that lets a pick or a
 * highlight still name the input's rows. The rows go through
 * `loadableFeatures`: a row with no geometry gets an empty one, and a first row
 * with none trades places with the first that has one. autk-db then stores the
 * rows whose geometry is empty before the others, each in the order handed, and
 * a map draws the table as stored: nothing for such a row, every other row in
 * its place.
 */
export function loadableSource(source: AutkSource): { source: AutkSource; order: LoadOrder } {
  const features: any[] = (source.geojsonObject as any)?.features ?? [];
  const loadable = loadableFeatures(features);
  const load = loadable.order;
  const rows = load ?? features.map((_, i) => i);
  const empty = rows.filter((i) => !hasGeometry(features[i]));
  const map = empty.length > 0 ? [...empty, ...rows.filter((i) => hasGeometry(features[i]))] : load;
  return {
    source: loadable.features === features
      ? source
      : { ...source, geojsonObject: { ...source.geojsonObject, features: loadable.features } as FeatureCollection },
    order: { load, map },
  };
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

/** What a frame becomes under a name: a geojson source and its rows, a
 * raster, or the reason it cannot be drawn. */
type FrameTable =
  | { source: AutkSource; rows: number }
  | { raster: AutkRasterInput }
  | { refusal: { reason: NodeEmptyReason; detail: string } };

function frameTable(frame: GrammarFrame, name: string): FrameTable {
  if (frame.dataType === "raster") return { raster: { outputTableName: name, payload: frame.payload } };
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
    let taken = false;
    const earlier = broughtBy.get(name);
    if (earlier !== undefined) {
      if (!frame.name) {
        // Several unnamed frames on one input are told apart by count.
        let n = 1;
        while (broughtBy.has(`${name}_${n}`)) n += 1;
        name = `${name}_${n}`;
      } else {
        // The name stays the earlier input's layer.
        clashes.push({ at: problems.length, earlier, frame, name });
        problems.push("");
        taken = true;
      }
    }
    if (!taken) broughtBy.set(name, frame.circle);
    const table = frameTable(frame, name);
    became.set(frame, { table, taken });
    if (taken) continue;
    if ("raster" in table) {
      rasters.push(table.raster);
    } else if ("refusal" in table) {
      unusable.push(name);
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
  const aliasOf = (circle: number): string | null => {
    const frames = byCircle.get(circle) ?? [];
    if (opts.alias === false || frames.length !== 1 || !frames[0].name) return null;
    const alias = inputTableName(circle);
    const named = sources.some((s) => s.outputTableName === alias) || rasters.some((r) => r.outputTableName === alias);
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
  // attaches geometry only when the spec draws it.
  const refs = new Set(documentTableRefs(spec));
  byCircle.forEach((frames, circle) => {
    const alias = aliasOf(circle);
    if (!alias || !refs.has(alias)) return;
    const { table, taken } = became.get(frames[0])!;
    if ("source" in table) {
      sources.unshift({ ...table.source, outputTableName: alias });
      if (taken) rowsIn += table.rows;
    } else if ("raster" in table) {
      rasters.unshift({ ...table.raster, outputTableName: alias });
    } else if (!unusable.includes(alias)) {
      unusable.push(alias);
      if (taken) {
        problems.push(table.refusal.detail);
        firstRefusal ??= table.refusal;
      }
    }
  });

  const prepared: PreparedAutkInput = {
    sources,
    rasters,
    tables: [...sources.map((s) => s.outputTableName), ...rasters.map((r) => r.outputTableName)],
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
