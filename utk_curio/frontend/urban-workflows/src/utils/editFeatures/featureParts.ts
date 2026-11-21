/**
 * A feature of several rows (#1092). OSM's buildings load one row per part:
 * each part holds its building's id, `building_id`, the layer's key, and an
 * `osm_id` of its own. An edit by the key names every row that holds it, the
 * whole building. The map's tools change one part at a time, so an edit of
 * one part names that row alone, by the key and its own `osm_id`, through the
 * edit's `where`:
 *
 *     {"op": "geometry", "where": "building_id == 29623484 and osm_id == 236608503", ...}
 *
 * A feature of one row is named by its id, as every other edit names it. A
 * feature whose rows no `osm_id` tells apart keeps its shape: the tools are
 * off for it.
 *
 * The node's form edits a feature's values on all its rows at once, or on one
 * chosen in its parts menu, named the same way (`partsForm`, #1110).
 */
import type { SelectionId } from "../references/selectionTags";
import { deriveBuildingHeight } from "../buildingHeight";
import { idKey } from "./applyEdits";
import { evaluate, parseExpr, truthy } from "./editExpr";
import type { FeatureEdit, Geometry } from "./editFeatures";
import type { EditedFeature } from "./layerModel";

/** The column that tells a feature's rows apart: each part's own OSM id. */
export const PART_COLUMN = "osm_id";

/** A row of a layer: its feature's id, and its properties. */
type Row = Pick<EditedFeature, "id" | "properties">;

/** The rows of *features* that are the feature *id*: its parts, in the layer's order. */
export function rowsOf<F extends Row>(features: readonly F[], id: SelectionId | null | undefined): F[] {
  if (id === null || id === undefined) return [];
  return features.filter((feature) => feature.id !== null && String(feature.id) === String(id));
}

/** Whether *a* and *b* are one row: of the same feature, with the same osm_id. */
export function samePart(a: Row | null | undefined, b: Row | null | undefined): boolean {
  if (!a || !b || a.id === null || b.id === null || String(a.id) !== String(b.id)) return false;
  return idKey(a.properties[PART_COLUMN]) === idKey(b.properties[PART_COLUMN]);
}

const KEYWORDS = new Set(["and", "or", "not", "true", "false", "null"]);

/** A column as a condition names it: by its name, or in backticks; null when it cannot be named. */
function columnRef(name: string): string | null {
  if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(name) && !KEYWORDS.has(name)) return name;
  return name === "" || name.includes("`") ? null : `\`${name}\``;
}

/** A value as a condition reads it: a number, true or false as it is, a text in quotes; null for any other. */
function literal(value: unknown): string | null {
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : null;
  if (typeof value === "boolean") return String(value);
  if (typeof value === "string") return `"${value.replace(/[\\"]/g, "\\$&")}"`;
  return null;
}

/**
 * The condition that names each of *rows*, the rows of one feature, whose
 * column *key* holds its id: `<key> == <id> and osm_id == <its osm_id>`, in
 * their order. Null when they cannot be told apart: fewer than two rows, a
 * row with no osm_id, or a condition that names another of the rows too.
 */
export function partConditions(rows: readonly Row[], key: string): string[] | null {
  const name = columnRef(key);
  if (rows.length < 2 || name === null || key === PART_COLUMN) return null;
  const conditions: string[] = [];
  for (const row of rows) {
    const id = literal(row.properties[key]);
    const part = literal(row.properties[PART_COLUMN]);
    if (id === null || part === null) return null;
    conditions.push(`${name} == ${id} and ${PART_COLUMN} == ${part}`);
  }
  // Each condition names its own row, and none of the others.
  try {
    const alone = conditions.every((condition, i) => {
      const parsed = parseExpr(condition);
      return rows.every((row, j) => truthy(evaluate(parsed, row.properties as Record<string, unknown>)) === (i === j));
    });
    return alone ? conditions : null;
  } catch {
    return null;
  }
}

/** Whether each of a feature's *rows* can be changed alone: one row, or rows `partConditions` tells apart. */
export function partsToldApart(rows: readonly Row[], key: string | undefined): boolean {
  return rows.length <= 1 || (key !== undefined && partConditions(rows, key) !== null);
}

/** Why a feature of *rows* keeps its shape on the map, or null when each of them can be changed alone. */
export function partsRefusal(rows: readonly Row[], key: string | undefined): string | null {
  if (partsToldApart(rows, key)) return null;
  return `Its ${rows.length} parts have no ${PART_COLUMN} of their own to tell them apart, so its shape cannot be changed on the map.`;
}

/**
 * The edit that gives *row*, one row of a feature among *features*, the shape
 * *geometry*: by its id when the feature is that one row, else by its own
 * condition (`partConditions`), so the feature's other rows keep theirs.
 * Null when the feature's rows cannot be told apart, or *row* is not one of
 * them.
 */
export function partRedraw(features: readonly Row[], row: Row, key: string | undefined, geometry: Geometry): FeatureEdit | null {
  if (row.id === null) return null;
  const rows = rowsOf(features, row.id);
  if (rows.length <= 1) return { op: "geometry", ids: [row.id], geometry };
  const conditions = key === undefined ? null : partConditions(rows, key);
  const at = rows.findIndex((other) => samePart(other, row));
  return conditions && at >= 0 ? { op: "geometry", where: conditions[at], geometry } : null;
}

/** A value as a form's field holds it: its text, empty for none. */
export function valueText(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

/** A value as a note or a part's name says it: its text, or "empty". */
const said = (value: unknown) => valueText(value) || "empty";

/**
 * The value a row is drawn at for a property it holds no value in, or null:
 * the default a layer gives the row where it uses the property.
 */
export type ValueDefault = (name: string, properties: Record<string, unknown>) => number | null;

/**
 * A buildings layer's default: a part with no height is drawn
 * `DEFAULT_BUILDING_HEIGHT` m above its base (utils/buildingHeight
 * `deriveBuildingHeight`). Null for another property, or for a part whose
 * `height` holds a value.
 */
export const buildingDefault: ValueDefault = (name, properties) => (
  name === "height" && valueText(properties.height) === "" ? deriveBuildingHeight(properties) : null
);

/** A default as the form shows it, marked: "6 (default)". */
export const defaultText = (value: number) => `${value} (default)`;

/** At most this many values a note lists, before it says how many more there are. */
const LISTED = 3;

/** The note beside a property a feature's parts differ in, *texts* their values each once: "2 values: 20, 30". */
function valuesNote(texts: readonly string[]): string {
  const more = texts.length > LISTED ? `, and ${texts.length - LISTED} more` : "";
  return `${texts.length} values: ${texts.slice(0, LISTED).map(said).join(", ")}${more}`;
}

/** What the form of a feature of several rows shows of its properties. */
export interface PartsForm {
  /** Each property's value the form starts from: the chosen part's, else the one all the parts hold. */
  values: Record<string, unknown>;
  /** For each property the parts differ in, while the form is on all of them, the note that lists their values. */
  mixed: Record<string, string>;
  /** For each property that cannot be changed, what the form shows of it: osm_id, which tells the parts apart. */
  fixed: Record<string, string>;
  /** Each part's name in the parts menu, in the rows' order: its osm_id, then the values it differs in. */
  labels: string[];
  /**
   * For each property whose field shows no value where the row is drawn at a
   * default (`ValueDefault`): that default, marked (`defaultText`), which the
   * field shows in its place.
   */
  defaults: Record<string, string>;
}

/**
 * The form of a feature of *rows*, of the properties *names*, on all its
 * parts or on the one *chosen*. On all of them, a property they share shows
 * its value and one they differ in shows none, but a note that lists them.
 * osm_id, which tells the parts apart, cannot be changed. A feature of one row
 * is that row. With *defaultOf*, a row that holds no value of a property the
 * layer draws it at a default for shows that default, marked, in the note,
 * the parts menu and the field, whose value stays empty.
 */
export function partsForm(
  rows: readonly Row[],
  names: readonly string[],
  chosen: Row | null = null,
  defaultOf?: ValueDefault,
): PartsForm {
  const first = rows[0]?.properties ?? {};
  // A row's value of *name* as the form says it: its own, else its default, marked.
  const shownText = (properties: Record<string, unknown>, name: string): string => {
    const text = valueText(properties[name]);
    const drawn = text === "" && defaultOf ? defaultOf(name, properties) : null;
    return drawn === null ? text : defaultText(drawn);
  };
  // The defaults the fields show where one row's values are shown.
  const defaultsOf = (properties: Record<string, unknown>) => Object.fromEntries(names.flatMap((name) => {
    const text = shownText(properties, name);
    return text !== valueText(properties[name]) ? [[name, text]] : [];
  }));
  if (rows.length <= 1) return { values: { ...first }, mixed: {}, fixed: {}, labels: [], defaults: defaultsOf(first) };
  const textsOf = (name: string) => [...new Set(rows.map((row) => shownText(row.properties, name)))];
  const values: Record<string, unknown> = {};
  const mixed: Record<string, string> = {};
  const fixed: Record<string, string> = {};
  for (const name of names) {
    const texts = textsOf(name);
    if (name === PART_COLUMN) {
      fixed[name] = `${chosen ? said(chosen.properties[name]) : texts.length > 1 ? `${texts.length} values` : said(first[name])}, cannot be changed`;
    } else if (chosen) values[name] = chosen.properties[name];
    else if (texts.length > 1) mixed[name] = valuesNote(texts);
    else values[name] = first[name];
  }
  const shared = defaultsOf(chosen ? chosen.properties : first);
  const defaults = Object.fromEntries(Object.entries(shared).filter(([name]) => !(name in mixed)));
  const differ = names.filter((name) => name !== PART_COLUMN && textsOf(name).length > 1);
  const labels = rows.map((row) => [PART_COLUMN, ...differ].map((name) => `${name} ${said(shownText(row.properties, name))}`).join(", "));
  return { values, mixed, fixed, labels, defaults };
}
