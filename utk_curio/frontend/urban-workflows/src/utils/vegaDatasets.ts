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
 * A spec's views: the spec itself, then every view below it, in a layer, a
 * concatenation, or a facet's or a repeat's inner spec.
 */
export function viewsOf(spec: any): Record<string, any>[] {
  const views: Record<string, any>[] = [];
  const visit = (node: any) => {
    if (Array.isArray(node)) return node.forEach(visit);
    if (!isObject(node)) return;
    views.push(node);
    for (const key of ["layer", "concat", "hconcat", "vconcat", "spec"]) visit(node[key]);
  };
  visit(spec);
  return views;
}

/**
 * Whether anything below the spec's top level reads a dataset by name: a
 * layer's or a concatenated view's `data`, a facet's inner spec, or a lookup's
 * `from.data`.
 */
function readsNamedDataBelowTop(spec: any): boolean {
  return viewsOf(spec).some(
    (view) =>
      (view !== spec && namesDataset(view.data)) ||
      (Array.isArray(view.transform) ? view.transform : []).some(
        (step: any) => isObject(step?.from) && namesDataset(step.from.data),
      ),
  );
}

/** Whether a spec reads a node's *inputCount* inputs as named datasets. */
export function usesNamedDatasets(spec: any, inputCount: number): boolean {
  return inputCount > 1 || readsNamedDataBelowTop(spec);
}
