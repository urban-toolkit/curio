/**
 * The one path from an input payload to the rows a Vega-Lite view renders.
 *
 * `useVega` and `vegaLiteAdapter` each had their own copy of this: validate the
 * dataType, fetch by path or read inline data, parse, stamp `__row_index__`.
 * Two copies of the data path is how the geometry handling would drift apart
 * again, so they share this one.
 *
 * **Several inputs (#662).** A node with several input circles reads each one as
 * its own dataset, named `input_0`, `input_1`, ... in circle order. A unit reads
 * the dataset its `"data": {"name": ...}` names, or the first input when it
 * names none, and each input's geometry handling touches only its own units.
 *
 * **Geometry is gated on the spec, not on the dataType.** A spec that does not
 * draw geometry never enters the geo path and its rows stay exactly what they
 * are today -- which matters, because shipped dataflows chart multi-megabyte
 * GeoJSON as bar charts and attaching geometry unconditionally would inline all
 * of it into `spec.data.values` and re-ship it on every brush. Gating on the
 * spec is also what lets a plain DataFrame carrying shapely objects be drawn.
 *
 * No `vega` / `vega-lite` import here, so it stays testable under jest.
 */
import { readGrammarInput, type GrammarFrame } from "./grammarInput";
import { parseDataframe, parseGeoDataframeWithGeometry } from "./parsing";
import type { NodeEmptyReason } from "./nodeEmptyState";
import { normalizeGeoSpec, specNeedsGeometry } from "./vegaGeoSpec";
import { namesDataset, usesNamedDatasets } from "./vegaDatasets";
import { inputTableName } from "../generated/autkGrammar";

export { usesNamedDatasets };

export type PreparedVegaInput = {
  values: any[];
  /** Set when the node has nothing to draw and should say why. */
  emptyReason?: NodeEmptyReason;
  /** A longer, spec-specific explanation, when there is one. */
  detail?: string;
};

/** One input as the dataset a spec reads. */
export type VegaDataset = { name: string; values: any[] };

export type PreparedVegaInputs = {
  /** One dataset per input, in circle order; empty when nothing arrived. */
  datasets: VegaDataset[];
  emptyReason?: NodeEmptyReason;
  detail?: string;
};

/**
 * One input's rows, ready for *spec*. With *dataset*, the geometry handling
 * touches only the units reading that dataset.
 */
function prepareFrame(frame: GrammarFrame, spec: any, dataset?: string): PreparedVegaInput {
  const { dataType, payload } = frame;
  const wantsGeometry = specNeedsGeometry(spec, dataset);
  let result: PreparedVegaInput;

  if (dataType === "geodataframe") {
    const parsed = parseGeoDataframeWithGeometry(payload, wantsGeometry);
    result = { values: parsed.values };
    if (wantsGeometry) {
      const geo = normalizeGeoSpec(spec, parsed.values, {
        geometryName: parsed.geometryName,
        crsName: parsed.crsName,
        dataset,
      });
      result.emptyReason = geo.emptyReason;
      result.detail = geo.detail;
    }
  } else {
    const values = parseDataframe(payload);
    result = { values };
    if (wantsGeometry) {
      // A plain DataFrame whose spec asks for geometry: the column is found by
      // sniffing the rows, since there is no declared geometry_name.
      const geo = normalizeGeoSpec(spec, values, { geometryName: null, dataset });
      result.emptyReason = geo.emptyReason;
      result.detail = geo.detail;
    }
  }

  // Positional, and stamped last so it survives the geo passes. The scenegraph
  // reads it back to map a vega tuple id to the original row.
  result.values.forEach((value: any, index: number) => {
    value.__row_index__ = index;
  });

  return result;
}

/**
 * Turn `data.input` into one dataset per input, render-ready for `spec`.
 *
 * Never throws for an input problem: a rejected input type comes back as an
 * `emptyReason` so the caller can render it in the node body.
 */
export async function prepareVegaInputs(input: any, spec: any): Promise<PreparedVegaInputs> {
  // The gate, the fetch and the refusal are the ones every grammar node uses.
  const read = await readGrammarInput(input, { label: "the 2D Plot (Vega-Lite)", circles: true });
  if (read.emptyReason) return { datasets: [], emptyReason: read.emptyReason, detail: read.detail };
  if (read.frames.length === 0) return { datasets: [] };
  if (read.frames.length === 1) {
    // One input reaches every unit, as it always has.
    const one = prepareFrame(read.frames[0], spec);
    return {
      datasets: [{ name: inputTableName(0), values: one.values }],
      ...(one.emptyReason ? { emptyReason: one.emptyReason, detail: one.detail } : {}),
    };
  }
  const datasets: VegaDataset[] = [];
  let problem: PreparedVegaInput | null = null;
  read.frames.forEach((frame, position) => {
    const name = inputTableName(position);
    const prepared = prepareFrame(frame, spec, name);
    // Which input a row came from, so a selection is matched only against the
    // first input's rows (`__row_index__` restarts for each).
    prepared.values.forEach((value: any) => {
      value.__input__ = position;
    });
    datasets.push({ name, values: prepared.values });
    if (prepared.emptyReason && problem === null) problem = prepared;
  });
  const first = problem as PreparedVegaInput | null;
  return first ? { datasets, emptyReason: first.emptyReason, detail: first.detail } : { datasets };
}

const isObject = (value: unknown): value is Record<string, any> =>
  value != null && typeof value === "object" && !Array.isArray(value);

/**
 * Put the node's inputs into *spec*. One input read by the whole spec becomes
 * its top-level `data`, named `input_0`. Otherwise every input becomes a named
 * dataset in `datasets`, and the top level reads the first input unless it
 * names another. Returns whether the inputs went in as named datasets.
 */
export function injectInputs(spec: any, datasets: VegaDataset[]): boolean {
  if (!usesNamedDatasets(spec, datasets.length)) {
    spec.data = { values: datasets[0]?.values ?? [], name: inputTableName(0) };
    return false;
  }
  spec.datasets = {
    ...(isObject(spec.datasets) ? spec.datasets : {}),
    ...Object.fromEntries(datasets.map((d) => [d.name, d.values])),
  };
  if (!namesDataset(spec.data)) spec.data = { name: inputTableName(0) };
  return true;
}

/**
 * Turn `data.input` into render-ready rows for `spec`: the first input's, for
 * callers that draw one dataset.
 *
 * Never throws for an input problem: a rejected input type comes back as an
 * `emptyReason` so the caller can render it in the node body. It used to be a
 * toast that the caller could not even catch, because `processData()` was not
 * awaited.
 */
export async function prepareVegaInput(
  input: any,
  spec: any,
): Promise<PreparedVegaInput> {
  const prepared = await prepareVegaInputs(input, spec);
  const values = prepared.datasets[0]?.values ?? [];
  return prepared.emptyReason
    ? { values, emptyReason: prepared.emptyReason, detail: prepared.detail }
    : { values };
}
