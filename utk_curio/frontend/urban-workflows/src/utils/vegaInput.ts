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
 * A layer chip on an input of one frame names that input's dataset
 * (utils/references/codeReferences).
 *
 * **Every input stacked.** A spec that names the dataset `inputs` also gets
 * every input's rows in it, in circle order, each named by the scenario box its
 * input comes from (utils/scenarios/stackedInputs), and takes inputs that are
 * values, which only that dataset draws. Its rows never carry geometry: a view
 * draws a map from `input_<k>`. Which input a frame came in on is the graph's
 * to say (the labels, one per wired input): with one input wired, every frame
 * and value that arrived is its own, as a tuple's parts are. Inputs that cannot
 * be stacked are an `emptyReason` the node shows.
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
import { readGrammarInput, type GrammarFrame, type GrammarInput } from "./grammarInput";
import { parseDataframe, parseGeoDataframeWithGeometry } from "./parsing";
import type { NodeEmptyReason } from "./nodeEmptyState";
import { normalizeGeoSpec, specNeedsGeometry } from "./vegaGeoSpec";
import { INPUTS_DATASET, namesDataset, readsInputs, usesNamedDatasets } from "./vegaDatasets";
import { inputTableName } from "../generated/autkGrammar";
import type { ScenarioLabel } from "./scenarios/scenarioColors";
import { inputRows, isFrameEnvelope, stackInputs, type StackEntry } from "./scenarios/stackedInputs";

export { usesNamedDatasets };

const VEGA_LABEL = "the 2D Plot (Vega-Lite)";

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
  /** One dataset per input, in circle order, then `inputs` for a spec that
   * reads it; empty when nothing arrived. */
  datasets: VegaDataset[];
  /** For a spec that reads `inputs`: its rows, none when the inputs could
   * not be stacked. */
  stacked?: any[];
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
 * Turn `data.input` into one dataset per input, render-ready for `spec`, and,
 * for a spec that reads `inputs`, that dataset too, its rows named by
 * *labels*: each wired input's label, in circle order
 * (utils/scenarios/inputScenarios), one per input the graph wires.
 *
 * Never throws for an input problem: a rejected input type, or inputs that
 * cannot be stacked, come back as an `emptyReason` so the caller can render
 * it in the node body.
 */
export async function prepareVegaInputs(
  input: any,
  spec: any,
  labels: readonly ScenarioLabel[] = [],
): Promise<PreparedVegaInputs> {
  // A spec that stacks its inputs takes values too, which only `inputs` draws.
  const stacks = readsInputs(spec);
  // The gate, the fetch and the refusal are the ones every grammar node uses.
  const read = await readGrammarInput(input, { label: VEGA_LABEL, circles: true, values: stacks });
  if (read.emptyReason) return { datasets: [], emptyReason: read.emptyReason, detail: read.detail };
  if (read.skipped?.length) {
    // A spec reads an input by its circle's name, so one left out would leave
    // a name pointing nowhere, or at the next input's rows.
    return {
      datasets: [],
      emptyReason: "input-type-rejected",
      detail: `${read.skipped.join(", ")} is not a valid input for ${VEGA_LABEL}.`,
    };
  }
  const values = read.values ?? [];
  let prepared: PreparedVegaInputs;
  if (read.frames.length === 1 && values.length === 0) {
    // One input reaches every unit, as it always has; for a spec that stacks
    // it, every unit but those reading `inputs`, whose rows carry no geometry.
    const one = prepareFrame(read.frames[0], spec, stacks ? inputTableName(0) : undefined);
    prepared = {
      datasets: [{ name: inputTableName(0), values: one.values }],
      ...(one.emptyReason ? { emptyReason: one.emptyReason, detail: one.detail } : {}),
    };
  } else {
    const several = read.frames.length + values.length > 1;
    const circles = [
      ...read.frames.map((frame) => ({ circle: frame.circle, frame, value: undefined as unknown })),
      ...values.map(({ circle, value }) => ({ circle, frame: null, value })),
    ].sort((a, b) => a.circle - b.circle);
    const datasets: VegaDataset[] = [];
    let problem: PreparedVegaInput | null = null;
    for (const { circle, frame, value } of circles) {
      const name = inputTableName(circle);
      const one: PreparedVegaInput = frame ? prepareFrame(frame, spec, name) : { values: valueRows(value) };
      // Which input a row came from, so a selection is matched only against the
      // first input's rows (`__row_index__` restarts for each).
      if (several) {
        one.values.forEach((row: any) => {
          row.__input__ = circle;
        });
      }
      datasets.push({ name, values: one.values });
      if (one.emptyReason && problem === null) problem = one;
    }
    const first = problem as PreparedVegaInput | null;
    prepared = first ? { datasets, emptyReason: first.emptyReason, detail: first.detail } : { datasets };
  }
  return stacks ? withStackedInputs(prepared, stackEntries(read, labels)) : prepared;
}

/** A value's rows, as `inputs` stacks it, each stamped with its place. */
function valueRows(value: unknown): any[] {
  return inputRows(value).map((row, index) => ({ ...row, __row_index__: index }));
}

/** *frame* as the sandbox writes one, for `inputs` to read its rows from. */
const asEnvelope = (frame: GrammarFrame) => ({
  dataType: frame.dataType,
  data: frame.payload,
  ...(frame.name ? { layerName: frame.name } : {}),
});

/**
 * What `inputs` stacks from *read*: one entry per wired input, in circle
 * order, named by its label (by its circle when it has none). A frame is
 * handed on as the sandbox writes it, so one with no rows is a table still and
 * its geometry is never read (utils/scenarios/stackedInputs); a value as the
 * plain value it holds. The graph says how many inputs are wired, one label
 * each: when one is, every frame and value that arrived is its own, as a
 * tuple's parts or an Autark node's layers are, and it is one entry carrying
 * them all. With no labels, each output of a bundle is an input of its own.
 */
function stackEntries(read: GrammarInput, labels: readonly ScenarioLabel[]): StackEntry[] {
  const parts = [
    ...read.frames.map((frame) => ({ circle: frame.circle, value: asEnvelope(frame) as unknown })),
    ...(read.values ?? []).map(({ circle, value }) => ({ circle, value })),
  ].sort((a, b) => a.circle - b.circle);
  const entry = (circle: number, value: unknown): StackEntry => ({
    scenario: labels[circle]?.scenario ?? null,
    name: labels[circle]?.name ?? inputTableName(circle),
    value,
  });
  if (labels.length === 1 && parts.length > 1) {
    return [entry(0, { dataType: "outputs", data: parts.map((part) => part.value) })];
  }
  return parts.map((part) => entry(part.circle, part.value));
}

/**
 * *rows*, the stacked rows of *entries*, each of a frame's stamped with its
 * place among that frame's rows, which a selection reads back as the input's
 * `__row_index__` does.
 */
function withRowIndexes(rows: Record<string, unknown>[], entries: readonly StackEntry[]): Record<string, unknown>[] {
  const counts = new Map<unknown, number>();
  for (const row of rows) {
    const position = row.__input__;
    if (!isFrameEnvelope(entries[position as number]?.value)) continue;
    const index = counts.get(position) ?? 0;
    row.__row_index__ = index;
    counts.set(position, index + 1);
  }
  return rows;
}

/**
 * *prepared* with the dataset `inputs`: every input's rows (a frame's) or
 * value, stacked in circle order under its circle's label. Inputs that cannot
 * be stacked leave it empty, and the node says why.
 */
function withStackedInputs(prepared: PreparedVegaInputs, entries: readonly StackEntry[]): PreparedVegaInputs {
  const stacked = stackInputs(entries);
  const rows = "rows" in stacked ? withRowIndexes(stacked.rows, entries) : [];
  const out: PreparedVegaInputs = {
    ...prepared,
    datasets: [...prepared.datasets, { name: INPUTS_DATASET, values: rows }],
    stacked: rows,
  };
  if ("refusal" in stacked && out.emptyReason == null) {
    out.emptyReason = "input-type-rejected";
    out.detail = stacked.refusal;
  }
  return out;
}

const isObject = (value: unknown): value is Record<string, any> =>
  value != null && typeof value === "object" && !Array.isArray(value);

/**
 * Put the node's inputs into *spec*. One input read by the whole spec becomes
 * its top-level `data`, named `input_0`. Otherwise every input becomes a named
 * dataset in `datasets`, `inputs` among them for a spec that reads it, and the
 * top level reads the first input unless it names another. Returns whether
 * the inputs went in as named datasets.
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
  if (!namesDataset(spec.data)) {
    spec.data = { name: inputTableName(0) };
    // With nothing arrived, the first input is no rows, as one read whole is.
    if (!(inputTableName(0) in spec.datasets)) spec.datasets[inputTableName(0)] = [];
  }
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
