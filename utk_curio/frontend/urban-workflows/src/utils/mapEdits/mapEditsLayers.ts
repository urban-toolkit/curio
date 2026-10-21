/**
 * The Map Edits node's input, as its body and its map read it: the layers the
 * input carries, the layer the edits apply to and the column that identifies
 * its features, the document and the inline input its map draws, and the
 * feature a pick on that map names.
 *
 * The map draws the layer as the node's edits leave it (`applyMapEdits`), so a
 * pick names a row of that layer. `keptRows` says which row of the input each
 * of those rows is, so the panel shows the feature the map drew beside the
 * same feature as the input has it.
 */
import { featureRows, matchSelections, type SelectDetail } from "../selectionMatch";
import { idColumns, STABLE_ID_COLUMNS } from "../references/selectionTags";
import { isFeatureId, type FeatureId, type JsonValue, type MapEdits, type MapFeature } from "./mapEdits";

/** One layer of the input, by the table name its map reads it as. */
export interface InputLayer {
  /** The table name: the layer's own name, or `input_0` for an unnamed one. */
  table: string;
  /** The layer's own name, when the input names it. */
  name: string | null;
  layerType?: string;
  fc: { features?: any[] };
}

/** The columns the features of *fc* carry, in the order the first ones name them. */
export function featureColumns(fc: { features?: any[] } | null | undefined): string[] {
  const columns: string[] = [];
  for (const feature of (fc?.features ?? []).slice(0, 50)) {
    for (const column of Object.keys(feature?.properties ?? {})) if (!columns.includes(column)) columns.push(column);
  }
  return columns;
}

/**
 * The columns that can identify the features of *fc*: `osm_id` and
 * `building_id` when they have them, then every column whose values differ in
 * every feature (`idColumns`, as a selection tag offers them).
 */
export function keyColumns(fc: { features?: any[] } | null | undefined): string[] {
  return idColumns(featureRows(fc), featureColumns(fc));
}

/** The key the node starts with: `osm_id` or `building_id` when the layer has one. */
export function defaultKey(columns: readonly string[]): string | undefined {
  return STABLE_ID_COLUMNS.find((column) => columns.includes(column));
}

/** What the node says about a layer it cannot edit, or null when it can. */
export function keyRefusal(columns: readonly string[], layerLabel: string): string | null {
  if (columns.length > 0) return null;
  return (
    `${layerLabel} has no column that identifies its features: no osm_id or building_id, `
    + "and no column whose values differ in every feature. Map Edits matches features by such a column, "
    + "never by their place in the layer, which changes when rows change upstream. "
    + "Add an id column in the node that feeds it."
  );
}

/** The layer the edits apply to: the one *named*, else the first that has an id column. */
export function chosenLayer(layers: readonly InputLayer[], named: string | undefined): InputLayer | undefined {
  if (named) {
    const found = layers.find((layer) => layer.name === named);
    if (found) return found;
  }
  return layers.find((layer) => keyColumns(layer.fc).length > 0) ?? layers[0];
}

/** The document the map draws: every layer, the one to edit on top and pickable. */
export function mapDocument(layers: readonly InputLayer[], table: string): string {
  const refs: Record<string, unknown>[] = layers.filter((layer) => layer.table !== table).map((layer) => ({ dataRef: layer.table }));
  refs.push({ dataRef: table, isPick: true });
  return JSON.stringify({ map: { layerRefs: refs } }, null, 2);
}

/**
 * The input the map draws, inline: every layer as the `{name, type, geojson}`
 * record an Autark node hands on, each under its table name, and the layer
 * *table* with *features* in place of its own. The records sit in a `list`
 * envelope, which the Autark node's reader peels (utils/grammarInput).
 */
export function mapInput(
  layers: readonly InputLayer[],
  table: string,
  features: readonly MapFeature[],
): { dataType: "list"; data: Array<{ name: string; type?: string; geojson: unknown }> } {
  return {
    dataType: "list",
    data: layers.map((layer) => ({
      name: layer.table,
      ...(layer.layerType ? { type: layer.layerType } : {}),
      geojson: layer.table === table ? { ...layer.fc, features: [...features] } : layer.fc,
    })),
  };
}

const idKeyOf = (id: FeatureId): string => `${typeof id}:${id}`;

/**
 * The rows of *features* that *edits* keep, in order: the input row of each
 * feature `applyMapEdits` hands on. Every row, with no key or nothing removed.
 */
export function keptRows(features: readonly MapFeature[], edits: MapEdits): number[] {
  const rows = features.map((_, row) => row);
  const key = edits.key;
  if (!key || edits.remove.length === 0) return rows;
  const gone = new Set(edits.remove.filter(isFeatureId).map(idKeyOf));
  return rows.filter((row) => {
    const value = features[row]?.properties?.[key];
    return !(isFeatureId(value) && gone.has(idKeyOf(value)));
  });
}

/**
 * The first row of *features* a pick on the map names, as an Autark node
 * reports one (its drawn rows, or the values of its key columns), or null for
 * a pick on nothing.
 */
export function pickedRow(
  details: Record<string, SelectDetail> | null | undefined,
  features: readonly MapFeature[],
): number | null {
  if (!details) return null;
  const rows = matchSelections([{ details, priority: 1 }], featureRows({ features: [...features] }));
  const row = rows.find((r) => Number.isInteger(r) && r >= 0 && r < features.length);
  return row ?? null;
}

/**
 * A feature's properties as the panel shows them: as JSON, without a
 * `geometry` property, which is the feature's shape. A value JSON cannot hold
 * is shown as JSON writes it, so an untouched one never reads as a change.
 */
export function fieldProperties(properties: unknown): Record<string, JsonValue> {
  if (properties === null || typeof properties !== "object" || Array.isArray(properties)) return {};
  const { geometry: _geometry, ...rest } = properties as Record<string, unknown>;
  return JSON.parse(JSON.stringify(rest, (_name, value) => (typeof value === "bigint" ? Number(value) : value)));
}
