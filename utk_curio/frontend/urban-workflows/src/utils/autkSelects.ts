/**
 * The selects an Autark node sends, as a Vega-Lite chart sends one per param:
 * one per view. A node of one view sends its select under `autk_selection`.
 * A node of several sends each view's under `autk_selection@<id>` for a view
 * with an `id`, else `autk_selection#<n>`, n the view's place among the
 * node's views, maps first (autk-grammar's `arrangeViews` order). The `@` is
 * the mark a view's interaction handle carries (contracts/interactionEdges.json
 * `viewMark`, as in `in/out@heights`). The `#` keeps a place's key apart from
 * every id's, whatever the id holds, as autk-grammar keeps a map's index (a
 * number) apart from its `id` (a string): `autk_selection@1` is the view whose
 * `id` is "1", `autk_selection#1` the view without one at place 1.
 *
 * Each select names the table it was made on (`layerRef`). Every reader of an
 * Autark selection reads it here: the Data Pool's buckets by layer, the
 * selection tags, the Autark node's own highlights and the Map Editor's picks.
 */
import interactionEdges from "../contracts/interactionEdges.json";
import type { SelectDetail } from "./selectionMatch";

/** The key a node of one view sends its select under. */
export const AUTK_SELECTION = "autk_selection";

/** An Autark select: a select, with the table it was made on and the node type that sent it. */
export type AutkSelect = SelectDetail & { source?: string; layerRef?: string };

/** What a view's key starts with when it names the view by its `id`. */
const BY_ID = `${AUTK_SELECTION}${interactionEdges.viewMark}`;
/** What a view's key starts with when it names a view without an `id` by its place: `#` where an id's key has `@`. */
const BY_PLACE = `${AUTK_SELECTION}#`;

/**
 * The key a view sends its select under: *view* is its `id`, a string, or its
 * place among the node's views, a number, for a view without an `id`, as
 * autk-grammar names a map by its `id` or by its index; none, a node's one
 * view.
 */
export function autkSelectionKey(view?: string | number | null): string {
  if (view === undefined || view === null) return AUTK_SELECTION;
  return typeof view === "number" ? `${BY_PLACE}${view}` : `${BY_ID}${view}`;
}

/** Whether *key* is the key of an Autark select: a node's one view's, or a view's of several, by its `id` or its place. */
export function isAutkSelectionKey(key: string): boolean {
  return key === AUTK_SELECTION
    || (key.startsWith(BY_ID) && key.length > BY_ID.length)
    || (key.startsWith(BY_PLACE) && /^\d+$/.test(key.slice(BY_PLACE.length)));
}

/**
 * The `id` of the view an Autark select's *key* names; null for a node's one
 * view and for a view without an `id`, whose key names its place.
 */
export function autkSelectionView(key: string): string | null {
  return key.startsWith(BY_ID) && key.length > BY_ID.length ? key.slice(BY_ID.length) : null;
}

/** Each Autark select of *details*, in its order: its key, the `id` of the view it names (`autkSelectionView`), and the select. */
export function autkSelects(details: unknown): Array<{ key: string; view: string | null; select: AutkSelect }> {
  if (!details || typeof details !== "object") return [];
  return Object.entries(details as Record<string, unknown>)
    .filter(([key, select]) => isAutkSelectionKey(key) && !!select && typeof select === "object")
    .map(([key, select]) => ({ key, view: autkSelectionView(key), select: select as AutkSelect }));
}

/** The table an Autark select names, when it names one. */
function layerOf(select: AutkSelect | undefined): string | undefined {
  const layer = select?.layerRef;
  return typeof layer === "string" && layer ? layer : undefined;
}

/**
 * The Autark select of *details* that stands for the node's selection: the
 * newest (at priority 1), else the first that holds a selection, else the
 * first. Undefined when *details* holds none.
 */
export function newestAutkSelect(details: unknown): AutkSelect | undefined {
  const selects = autkSelects(details).map(({ select }) => select);
  const holds = (select: AutkSelect) => (Array.isArray(select.data) ? select.data.length > 0 : !!select.data
    && typeof select.data === "object" && Object.keys(select.data).length > 0);
  return selects.find((select) => select.priority === 1) ?? selects.find(holds) ?? selects[0];
}

/** The table the newest Autark select of *details* names (`newestAutkSelect`), when it names one. */
export function autkSelectionLayer(details: unknown): string | undefined {
  return layerOf(newestAutkSelect(details));
}

/**
 * *details* with only the Autark selects made on the table *layer*: each other
 * select of another view is left out, and so is every select when *layer* is
 * undefined and the details name tables. Each view's select is that view's
 * selection of its table, so the newest of those kept is the one at priority
 * 1: the one sent at 1, else the last, since a node sends its views' selects
 * oldest first. Details that hold no Autark select (a Vega-Lite chart's) are
 * as they were.
 */
export function selectsOnLayer<T>(details: T, layer: string | undefined): T {
  const selects = autkSelects(details);
  if (selects.length === 0) return details;
  const kept = selects.filter(({ select }) => layerOf(select) === layer);
  const newest = kept.find(({ select }) => select.priority === 1) ?? kept[kept.length - 1];
  return Object.fromEntries(kept.map(({ key, select }) => [key, { ...select, priority: key === newest.key ? 1 : 0 }])) as T;
}

/**
 * *details* with only the select the view *view* (its `id`) sent, as an
 * interaction edge on that view's dot carries it (`in/out@<id>`,
 * providers/flow/interactionRoutes): of a node of several views, that view's
 * select alone, at priority 1, its own selection though another view's is
 * newer; nothing when the view sent none. A node of one view sends its one
 * view's select under `autk_selection`, which a dot of any view carries.
 * Details that hold no Autark select, another node's, carry nothing.
 */
export function selectsOfView(details: unknown, view: string): Record<string, AutkSelect> {
  const selects = autkSelects(details);
  const one = selects.find(({ key }) => key === AUTK_SELECTION);
  if (one) return { [AUTK_SELECTION]: one.select };
  // The view's own key: a view without an id, keyed by its place, is never the view whose id reads as that place.
  const own = selects.find(({ key }) => key === autkSelectionKey(view));
  return own ? { [own.key]: own.select.priority === 1 ? own.select : { ...own.select, priority: 1 } } : {};
}

/**
 * *selections*, each one source's, with an Autark source's selects told apart
 * by table: one selection for each table its selects name, holding the
 * selects made on it, the newest at priority 1 (`selectsOnLayer`), with that
 * table. A selection with no Autark select (a Vega-Lite chart's) is one, of
 * no table.
 */
export function byAutkLayer<S extends { details?: unknown }>(selections: readonly S[]): Array<{ layer: string | undefined; selection: S }> {
  const out: Array<{ layer: string | undefined; selection: S }> = [];
  for (const selection of selections) {
    const selects = autkSelects(selection?.details);
    if (selects.length === 0) {
      out.push({ layer: undefined, selection });
      continue;
    }
    const layers = [...new Set(selects.map(({ select }) => layerOf(select)))];
    for (const layer of layers) {
      out.push({ layer, selection: { ...selection, details: selectsOnLayer(selection.details, layer) } });
    }
  }
  return out;
}
