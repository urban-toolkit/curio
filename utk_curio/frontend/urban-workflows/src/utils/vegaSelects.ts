/**
 * The selects of a Vega-Lite chart, as its node hears them (#846), the
 * values a point select over fields picked (#847), and what a view of the
 * chart built again takes to hold the selections made in it, or the one its
 * selection tags hold (#884).
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

/** A view's state, as vega's `getState` gives it and `setState` takes it. */
export interface ViewState {
  signals?: Record<string, unknown>;
  data?: Record<string, unknown>;
  subcontext?: ViewState[];
}

/**
 * What a view of *spec* built again takes from *view*, a view of the same
 * chart, to hold the selections made in it, from vega's view state (the
 * scopes of its views included): each select's store of what it picked
 * (`<name>_store`), which the new view reads the select's own signal off, a
 * zoom's included, and a brush's extent on the chart (`<name>_x`, `<name>_y`),
 * which it draws the brush from. Nothing else: the new view's size and vega's
 * id counter are its own, and what a select holds between the events of a
 * gesture would run its pan and zoom with no gesture behind them, which vega
 * fails on. Null when there is no view, or the spec has no select.
 */
export function carriedSelections(view: any, spec: unknown): ViewState | null {
  if (!view) return null;
  const names = [...viewSelects(spec, Object.keys(view.getState().signals ?? {})).keys()];
  if (names.length === 0) return null;
  return view.getState({
    signals: (signal: string) => names.some((name) => signal === `${name}_x` || signal === `${name}_y`),
    data: (data: string) => names.some((name) => data === `${name}_store`),
    recurse: true,
  });
}

/** A field a point select over fields or encodings holds in its tuples, as
 * vega-lite writes it: `{type: "E", field}`, and the channel of an encoding. */
export interface PointStoreField {
  type: string;
  field: string;
  channel?: string;
}

/** How a point select's store holds what it picked: the unit its tuples name,
 * and the fields whose values they hold, or none when they hold `_vgsid_`. */
export interface PointStore {
  unit: string;
  fields?: PointStoreField[];
}

/** What vega-lite's tuple for a click starts with: `{unit: "concat_0", _vgsid_: ...`
 * or `{unit: "", fields: ...`. A unit built per facet cell is no literal. */
const TUPLE_START = /\{unit: ("(?:[^"\\]|\\.)*"), (_vgsid_|fields):/;

/** Every signal of a compiled vega spec, its group marks' own included. */
function vegaSignals(spec: any): any[] {
  if (!spec || typeof spec !== "object") return [];
  const own = Array.isArray(spec.signals) ? spec.signals : [];
  const marks = Array.isArray(spec.marks) ? spec.marks : [];
  return [...own, ...marks.flatMap((mark: any) => vegaSignals(mark))];
}

/**
 * How the point select *name* of a compiled chart (*vegaSpec*, what
 * `lite.compile` gives) holds what it picked, read off the tuple vega-lite
 * builds for a click on it (`<name>_tuple`): the unit the tuple names, and,
 * for a select over fields or encodings, the fields it holds
 * (`<name>_tuple_fields`). A store set to tuples of that form selects what
 * clicks on the same rows would have (#884). Null when the select's selection
 * is not a top-level signal, its unit is built per facet cell, or a field is
 * held as a range (a binned field).
 */
export function pointStoreOf(vegaSpec: unknown, name: string): PointStore | null {
  const top = Array.isArray((vegaSpec as any)?.signals) ? (vegaSpec as any).signals : [];
  if (!top.some((signal: any) => signal?.name === name)) return null;
  const signals = vegaSignals(vegaSpec);
  const tuple = signals.find((signal) => signal?.name === `${name}_tuple`);
  const updates: unknown[] = (Array.isArray(tuple?.on) ? tuple.on : []).map((on: any) => on?.update);
  const start = updates
    .map((update) => (typeof update === "string" ? TUPLE_START.exec(update) : null))
    .find((match) => match !== null);
  if (!start) return null;
  let unit: unknown;
  try {
    unit = JSON.parse(start[1]);
  } catch {
    return null;
  }
  if (typeof unit !== "string") return null;
  if (start[2] === "_vgsid_") return { unit };
  const fields = signals.find((signal) => signal?.name === `${name}_tuple_fields`)?.value;
  if (!Array.isArray(fields) || fields.length === 0) return null;
  if (!fields.every((field: any) => field?.type === "E" && typeof field.field === "string")) return null;
  return { unit, fields: fields.map((field: PointStoreField) => ({ ...field })) };
}

/**
 * The tuples of a store *store* describes that pick the rows *picked*
 * (positions among *rows*, the rows the view draws): each row's `_vgsid_` in
 * the view (*idOfRow*), sorted as vega keeps them, or else its values of the
 * select's fields, each set of values once. A row with no id, or with no value
 * for a field, is left out.
 */
export function pointStoreTuples(
  store: PointStore,
  picked: readonly number[],
  rows: readonly any[],
  idOfRow: ReadonlyMap<number, number>,
): Record<string, unknown>[] {
  if (!store.fields) {
    const ids = new Set<number>();
    for (const row of picked) {
      const id = idOfRow.get(row);
      if (id !== undefined) ids.add(id);
    }
    return [...ids].sort((a, b) => a - b).map((id) => ({ unit: store.unit, _vgsid_: id }));
  }
  const fields = store.fields;
  const seen = new Set<string>();
  const tuples: Record<string, unknown>[] = [];
  for (const row of picked) {
    const values = fields.map((field) => rows[row]?.[field.field]);
    if (values.some((value) => value === undefined)) continue;
    const key = JSON.stringify(values);
    if (seen.has(key)) continue;
    seen.add(key);
    tuples.push({ unit: store.unit, fields: fields.map((field) => ({ ...field })), values });
  }
  return tuples;
}

/**
 * *state* with the ids its stores hold (vega's `_vgsid_`, by which a point
 * select over no fields picks) moved to the ids a new view gives the same
 * rows: *before* gives the row of each id the old view draws, *after* the new
 * view's. New rows reaching a drawn chart are numbered after the rows it held
 * (#535), and a view built again numbers its rows from 1, so an id kept as it
 * was would name another row there, or none. An id whose row either view does
 * not draw is kept.
 */
export function withMovedIds(
  state: ViewState,
  before: ReadonlyMap<number, number>,
  after: ReadonlyMap<number, number>,
): ViewState {
  const idOfRow = new Map([...after].map(([id, row]) => [row, id]));
  const moved = (tuple: any) => {
    const row = before.get(tuple?._vgsid_);
    const id = row === undefined ? undefined : idOfRow.get(row);
    return id === undefined || id === tuple._vgsid_ ? tuple : { ...tuple, _vgsid_: id };
  };
  const data = state.data
    ? Object.fromEntries(
        Object.entries(state.data).map(([name, tuples]) => [name, Array.isArray(tuples) ? tuples.map(moved) : tuples]),
      )
    : undefined;
  return {
    ...state,
    ...(data ? { data } : {}),
    ...(state.subcontext ? { subcontext: state.subcontext.map((inner) => withMovedIds(inner, before, after)) } : {}),
  };
}
