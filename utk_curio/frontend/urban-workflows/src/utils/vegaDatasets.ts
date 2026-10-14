/**
 * How a Vega-Lite spec reads a node's inputs (#662): each input is the dataset
 * `input_0`, `input_1`, ... in circle order, and `inputs` is all of them
 * stacked, each row's `__input__` its circle, for a chart over several at once
 * (a comparison of scenarios: the spec names them from `__input__`). One input
 * read by the whole spec stays the spec's own top-level `data`, as it always
 * has; several inputs, or a spec that names a dataset, read them as named
 * datasets.
 *
 * Pure, so the canvas (utils/vegaInput) and the notebook export share it.
 */

const isObject = (value: unknown): value is Record<string, any> =>
  value != null && typeof value === "object" && !Array.isArray(value);

/** The dataset that is all of a node's inputs stacked. */
export const INPUTS_DATASET = "inputs";

/** Whether *data* reads a named dataset (and brings no rows of its own). */
export const namesDataset = (data: unknown): boolean =>
  isObject(data) && typeof data.name === "string" && data.url === undefined && data.values === undefined;

/**
 * Whether anything below the spec's top level reads a dataset by name: a
 * layer's or a concatenated view's `data`, a facet's inner spec, or a lookup's
 * `from.data`.
 */
function readsNamedDataBelowTop(spec: any): boolean {
  const visit = (node: any, top: boolean): boolean => {
    if (Array.isArray(node)) return node.some((child) => visit(child, false));
    if (!isObject(node)) return false;
    if (!top && namesDataset(node.data)) return true;
    for (const step of Array.isArray(node.transform) ? node.transform : []) {
      if (isObject(step?.from) && namesDataset(step.from.data)) return true;
    }
    return ["layer", "concat", "hconcat", "vconcat", "spec"].some((key) => visit(node[key], false));
  };
  return visit(spec, true);
}

/** Whether a spec reads a node's *inputCount* inputs as named datasets: it
 * has several, or names one below its top level, or reads `inputs`, all of
 * them stacked, at its top. */
export function usesNamedDatasets(spec: any, inputCount: number): boolean {
  return inputCount > 1
    || readsNamedDataBelowTop(spec)
    || (isObject(spec) && namesDataset(spec.data) && spec.data.name === INPUTS_DATASET);
}

/** Whether any part of *spec* reads `inputs`, all the node's inputs stacked. */
export function readsAllInputs(spec: any): boolean {
  const visit = (node: any): boolean => {
    if (Array.isArray(node)) return node.some(visit);
    if (!isObject(node)) return false;
    if (namesDataset(node.data) && node.data.name === INPUTS_DATASET) return true;
    return Object.entries(node).some(([key, value]) => key !== "datasets" && visit(value));
  };
  return visit(spec);
}

/** The circle of the dataset `input_<circle>`, or -1. */
const circleOf = (name: string): number => {
  const match = /^input_(\d+)$/.exec(name);
  return match ? Number(match[1]) : -1;
};

/** The node's inputs as one table, `inputs`: their rows in circle order, each
 * row's `__input__` its circle. */
export function stackInputs(datasets: readonly { name: string; values: any[] }[]): { name: string; values: any[] } {
  const values = datasets
    .map((dataset) => ({ dataset, circle: circleOf(dataset.name) }))
    .filter(({ circle }) => circle >= 0)
    .sort((a, b) => a.circle - b.circle)
    .flatMap(({ dataset, circle }) =>
      (Array.isArray(dataset.values) ? dataset.values : []).map((row) => ({
        ...(isObject(row) ? row : { value: row }),
        __input__: circle,
      })),
    );
  return { name: INPUTS_DATASET, values };
}
