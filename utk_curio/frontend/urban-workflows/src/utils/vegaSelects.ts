/**
 * The selects of a Vega-Lite chart, as its node hears them (#846).
 *
 * vega lets the page listen to a view's top-level signals only. Each select
 * holds its selection in one of them, `<name>`, wherever the spec declares it.
 * Its `<name>_modify` signal is top-level only in a single view: a select
 * inside a concatenation, a facet or a repeat keeps that one in its own view's
 * scope. So the selects are read from the spec.
 */
import { viewsOf } from "./vegaDatasets";

/** What a select picks, as its spec declares it. */
export type SelectType = "point" | "interval";

const MODIFY = "_modify";

/**
 * Every select of a chart, by name, with the type its spec declares: each
 * param with a `select`, on the spec or on any view below it. Then any other
 * select a top-level `<name>_modify` signal names, with no type: one the spec
 * does not declare as a param, as Vega-Lite's older `selection` form does. A
 * name may hold "_".
 */
export function viewSelects(spec: unknown, signals: readonly string[]): Map<string, SelectType | undefined> {
  const selects = new Map<string, SelectType | undefined>();
  for (const view of viewsOf(spec)) {
    for (const param of Array.isArray(view.params) ? view.params : []) {
      if (typeof param?.name !== "string" || param.select == null) continue;
      const type = typeof param.select === "string" ? param.select : param.select.type;
      if (selects.get(param.name) === undefined) {
        selects.set(param.name, type === "point" || type === "interval" ? type : undefined);
      }
    }
  }
  for (const signal of signals) {
    const name = signal.endsWith(MODIFY) ? signal.slice(0, -MODIFY.length) : "";
    if (name && !selects.has(name)) selects.set(name, undefined);
  }
  return selects;
}
