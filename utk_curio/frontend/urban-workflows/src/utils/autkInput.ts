/**
 * The Autark node's input, turned into the tables its document reads.
 *
 * Read through the same path as the Vega-Lite node's (utils/grammarInput): the
 * same gate, fetch, schema and geometry column, and the same refusals. Two
 * things are Autark's own. A document reads tables by name, so a single frame is
 * the table `upstream` and a bundle's layers keep their names. And a table needs
 * geometry to be drawn at all, so a DataFrame becomes a FeatureCollection from
 * its geometry column, or is refused the way Vega refuses a geoshape over data
 * with no geometry.
 *
 * No autk import here: this stays testable under jest.
 */
import type { FeatureCollection } from "geojson";
import { AUTK_UPSTREAM_LAYER } from "../generated/autkGrammar";
import { requestedLayerTables } from "../adapters/node/autkDataCompile";
import { detectCoordinateFormat } from "./geoCrs";
import { resolveGeometryField } from "./geometryField";
import { readGrammarInput, type GrammarFrame, type GrammarInput } from "./grammarInput";
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

export type PreparedAutkInput = {
  /** One geojson source per table the input provides, plus `upstream` when the document names it. */
  sources: AutkSource[];
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

/** The table a frame becomes: its own name, else `upstream` (`upstream_<i>` in a bundle). */
export function autkTableName(frame: GrammarFrame): string {
  if (frame.name) return frame.name;
  return frame.fromBundle ? `${AUTK_UPSTREAM_LAYER}_${frame.index}` : AUTK_UPSTREAM_LAYER;
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
 * Which input row each position of a loaded table stands for. `load` is the
 * table as autk-db holds it (what a plot reads and selects in); `map` is what a
 * map draws, which leaves out every feature without a geometry. `null` means
 * positions and input rows agree.
 */
export type LoadOrder = { load: number[] | null; map: number[] | null };

/**
 * The source as autk-db will load it, and the order that lets a pick or a
 * highlight still name the input's rows. autk-db refuses a collection whose
 * first feature has no geometry, so that one trades places with the first that
 * has one; a map then leaves out the features without geometry.
 */
export function loadableSource(source: AutkSource): { source: AutkSource; order: LoadOrder } {
  const features: any[] = (source.geojsonObject as any)?.features ?? [];
  let load: number[] | null = null;
  if (features.length > 0 && !hasGeometry(features[0])) {
    const j = features.findIndex(hasGeometry);
    if (j > 0) {
      load = features.map((_, i) => i);
      [load[0], load[j]] = [load[j], load[0]];
    }
  }
  const rows = load ?? features.map((_, i) => i);
  const map = features.some((f) => !hasGeometry(f)) ? rows.filter((i) => hasGeometry(features[i])) : load;
  return {
    source: load
      ? { ...source, geojsonObject: { ...source.geojsonObject, features: load.map((i) => features[i]) } }
      : source,
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

/** Read the Autark node's input: the fetch, done once per input object. */
export function readAutkInput(input: any, opts: { preview?: boolean } = {}): Promise<GrammarInput> {
  return readGrammarInput(input, { label: AUTK_INPUT_LABEL, bundles: true, preview: opts.preview });
}

/**
 * The geojson sources a document reads from an input already read.
 * `alias: false` leaves `upstream` out: a compute step passes its layers on
 * under their own names.
 */
export function autkSourcesFrom(
  read: GrammarInput,
  spec: any,
  opts: { alias?: boolean } = {},
): PreparedAutkInput {
  if (read.emptyReason) {
    return {
      sources: [],
      tables: [],
      unusable: [AUTK_UPSTREAM_LAYER],
      emptyReason: read.emptyReason,
      detail: read.detail,
      inputProblem: read.detail,
    };
  }
  if (read.frames.length === 0) return { sources: [], tables: [], unusable: [] };

  const sources: AutkSource[] = [];
  const unusable: string[] = [];
  const problems: string[] = [];
  let firstRefusal: { reason: NodeEmptyReason; detail: string } | null = null;
  let rowsIn = 0;

  for (const frame of read.frames) {
    const name = autkTableName(frame);
    const result = featuresOf(frame, name);
    if ("reason" in result) {
      unusable.push(name);
      problems.push(result.detail);
      firstRefusal ??= result;
      continue;
    }
    // A layer an Autark data node stored empty comes back with no feature
    // list: it has no rows, and the render leaves it out like any empty table.
    const features = (result.fc as any).features;
    rowsIn += Array.isArray(features) ? features.length : 0;
    sources.push({
      type: "geojson",
      geojsonObject: result.fc,
      outputTableName: name,
      coordinateFormat: detectCoordinateFormat(result.fc as any),
      ...(frame.layerType ? { layerType: frame.layerType } : {}),
    });
  }

  if (read.skipped?.length) problems.push(`Left out: ${read.skipped.join(", ")}.`);

  // `upstream` names the node's own input when that input is a single frame.
  // It is added only when the document reads it, as the Vega-Lite node attaches
  // geometry only when the spec draws it. Several layers keep their own names.
  const refs = new Set(documentTableRefs(spec));
  if (opts.alias !== false && read.frames.length === 1 && refs.has(AUTK_UPSTREAM_LAYER)
      && !sources.some((s) => s.outputTableName === AUTK_UPSTREAM_LAYER)) {
    if (sources.length > 0) sources.unshift({ ...sources[0], outputTableName: AUTK_UPSTREAM_LAYER });
    else if (unusable.length > 0 && !unusable.includes(AUTK_UPSTREAM_LAYER)) unusable.push(AUTK_UPSTREAM_LAYER);
  }

  const prepared: PreparedAutkInput = {
    sources,
    tables: sources.map((s) => s.outputTableName),
    unusable,
    rowsIn,
    ...(problems.length ? { inputProblem: problems.join(" ") } : {}),
  };
  if (sources.length === 0 && firstRefusal) {
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
