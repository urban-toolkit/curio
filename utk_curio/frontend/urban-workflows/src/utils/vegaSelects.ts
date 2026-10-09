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

/** One point of a selection: for each field, the values it allows. */
type Point = Array<[field: string, allowed: unknown[]]>;

const comparable = (value: unknown) => (value instanceof Date ? value.getTime() : value);

/**
 * Whether a row's *value* is one a point *allowed*: the same value, or for a
 * binned field, inside the bin, which vega reports as [start, end).
 */
function allows(allowed: unknown, value: unknown): boolean {
  if (Array.isArray(allowed) && allowed.length === 2) {
    const [start, end, held] = [comparable(allowed[0]), comparable(allowed[1]), comparable(value)];
    return typeof held === "number" && typeof start === "number" && typeof end === "number"
      && start <= held && held < end;
  }
  return comparable(allowed) === comparable(value);
}

/**
 * The points a selection over fields holds: each one vega lists under
 * `vlPoint` (`{or: [{zip: 60614}, {zip: 60622}]}`), or else one point that
 * allows each value reported for each field (`{zip: [60614, 60622]}`).
 */
function pointsOf(value: Record<string, any>): Point[] {
  const listed = value.vlPoint?.or;
  if (Array.isArray(listed)) {
    return listed
      .filter((point) => point != null && typeof point === "object")
      .map((point) => Object.entries(point).map(([field, held]): [string, unknown[]] => [field, [held]]));
  }
  const fields = Object.keys(value).filter((key) => !NOT_FIELDS.has(key));
  return [fields.map((field): [string, unknown[]] => [field, Array.isArray(value[field]) ? value[field] : [value[field]]])];
}

/**
 * The rows a point selection over fields picks (#847), as their positions
 * among *rows* (a row's `__row_index__`), which is how a point selection by
 * vega's tuple ids reaches a Data Pool or a selection tag too. vega reports a
 * select over fields by the values of those fields: a row is picked when it
 * holds a point's value for each of the point's fields.
 */
export function pointRows(value: Record<string, any>, rows: readonly any[]): number[] {
  const points = pointsOf(value).filter((point) => point.length > 0);
  const picked: number[] = [];
  rows.forEach((row, position) => {
    const holds = (point: Point) =>
      point.every(([field, allowed]) => allowed.some((one) => allows(one, row?.[field])));
    if (points.some(holds)) picked.push(typeof row?.__row_index__ === "number" ? row.__row_index__ : position);
  });
  return picked;
}
