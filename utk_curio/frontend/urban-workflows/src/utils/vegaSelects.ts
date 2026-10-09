/**
 * The selects of a Vega-Lite chart, as its node hears them (#846), and the
 * values a point select over fields picked (#847).
 *
 * vega lets the page listen to a view's top-level signals only. Each select
 * holds its selection in one of them, `<name>`, wherever the spec declares it.
 * Its `<name>_modify` signal is top-level only in a single view: a select
 * inside a concatenation, a facet or a repeat keeps that one in its own view's
 * scope. So the selects are read from the spec.
 */
import { viewsOf } from "./vegaDatasets";
import type { PointValue } from "./selectionMatch";

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

/**
 * Whether a select's selection, *value*, names points rather than an
 * interval (#847): as the spec declares it, else by what vega reports. A
 * point select reports its rows' tuple ids (`_vgsid_`) or, over fields, also
 * lists each point under `vlPoint`; an interval reports field ranges only.
 */
export function isPointSelection(type: SelectType | undefined, value: Record<string, unknown>): boolean {
  if (type !== undefined) return type === "point";
  return "_vgsid_" in value || "vlPoint" in value;
}

/** What a point selection reports besides the values of its fields. */
const NOT_FIELDS = new Set(["_vgsid_", "vlPoint"]);

const isPoint = (entry: unknown): entry is PointValue =>
  entry != null && typeof entry === "object" && !Array.isArray(entry);

/**
 * The points a point selection over fields picked (#847), each as the value
 * it holds for each field: the ones vega lists under `vlPoint`
 * (`{unit_id: [103, 105], vlPoint: {or: [{unit_id: 103}, {unit_id: 105}]}}`),
 * or else every combination of the values it reports for each field. Whatever
 * reads the selection (a Data Pool, a linked chart, a selection tag) picks out
 * the rows that hold those values, in whatever order it holds its rows
 * (utils/selectionMatch).
 */
export function pointValues(value: Record<string, any>): PointValue[] {
  const listed = value.vlPoint?.or;
  if (Array.isArray(listed)) return listed.filter(isPoint).map((point) => ({ ...point }));
  const fields = Object.keys(value).filter((key) => !NOT_FIELDS.has(key));
  if (fields.length === 0) return [];
  return fields.reduce<PointValue[]>(
    (points, field) => {
      const held = Array.isArray(value[field]) ? value[field] : [value[field]];
      return points.flatMap((point) => held.map((one: unknown) => ({ ...point, [field]: one })));
    },
    [{}],
  );
}
