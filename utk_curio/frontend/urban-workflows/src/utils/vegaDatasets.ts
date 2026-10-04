/**
 * How a Vega-Lite spec reads a node's inputs (#662): each input is the dataset
 * `input_0`, `input_1`, ... in circle order. One input read by the whole spec
 * stays the spec's own top-level `data`, as it always has; several inputs, or a
 * part of the spec that names one, read them as named datasets.
 *
 * Pure, so the canvas (utils/vegaInput) and the notebook export share it.
 */

const isObject = (value: unknown): value is Record<string, any> =>
  value != null && typeof value === "object" && !Array.isArray(value);

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

/** Whether a spec reads a node's *inputCount* inputs as named datasets. */
export function usesNamedDatasets(spec: any, inputCount: number): boolean {
  return inputCount > 1 || readsNamedDataBelowTop(spec);
}
