/**
 * The datasets a Vega view holds, for the tests' stand-ins of `vega` whose
 * `vega-lite` compiles a spec to itself, so a view is built from the Vega-Lite
 * spec the chart compiled.
 *
 * vega-lite builds only the datasets a spec reads: the top level's data, each
 * view's (a layer, a concatenated view, a facet's or a repeat's), and a
 * lookup's. A dataset the spec only lists in `datasets` is not in the view, and
 * vega throws for a change to a dataset its view does not hold, as
 * `unrecognizedDataset` does.
 */
export function datasetsRead(spec: unknown): Set<string> {
  const names = new Set<string>();
  const visit = (node: unknown) => {
    if (Array.isArray(node)) {
      node.forEach(visit);
      return;
    }
    if (node === null || typeof node !== "object") return;
    const view = node as Record<string, any>;
    if (view.data && typeof view.data === "object" && typeof view.data.name === "string") names.add(view.data.name);
    for (const transform of Array.isArray(view.transform) ? view.transform : []) {
      const from = transform?.from?.data;
      if (from && typeof from === "object" && typeof from.name === "string") names.add(from.name);
    }
    for (const key of ["layer", "hconcat", "vconcat", "concat", "spec"]) visit(view[key]);
  };
  visit(spec);
  return names;
}

/** What vega throws for a change to a dataset its view does not hold. */
export function unrecognizedDataset(name: string): Error {
  return new Error(`Unrecognized data set: ${name}`);
}
