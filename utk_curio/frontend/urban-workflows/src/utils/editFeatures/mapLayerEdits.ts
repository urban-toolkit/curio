/**
 * An Interaction node plugged into an Autark map (#662): the map's other
 * inputs are the layers the node edits, and its edit log is how the map
 * draws them, and hands them on.
 *
 * The node sits on one of the map's input circles. It hands on nothing the
 * map draws: the map reads its setting (`editFeatures`) off the node, leaves
 * its circle out of what it reads, applies the log to each layer an edit
 * names (`editedFeatures`, the same ops as `curio_edit_features`) and adds
 * the node's new layers that have features.
 */
import { getUnversionedFlowNodeType } from "../flowNodeCanonicalType";
import {
  EDIT_FEATURES_NODE_TYPE,
  NEW_LAYER_KEY,
  normalizeEditFeatures,
  type EditFeaturesSettings,
  type NewLayerGeometry,
} from "./editFeatures";
import { editedFeatures } from "./layerModel";

/** The circle an edge goes into: `in` is 0, `in_<k>` is k. */
export function circleOf(handle: unknown): number {
  const m = /^in_(\d+)$/.exec(String(handle ?? ""));
  return m ? Number(m[1]) : 0;
}

const isAutkMap = (node: any) => !!node && getUnversionedFlowNodeType(node) === "curio.builtin/autk-grammar";
const isInteraction = (node: any) => !!node && getUnversionedFlowNodeType(node) === EDIT_FEATURES_NODE_TYPE;

/** The Interaction node plugged into the map *mapId*, its circle and its log. */
export function interactionOn(
  mapId: string,
  nodes: readonly any[],
  edges: readonly any[],
): { nodeId: string; circle: number; settings: EditFeaturesSettings | undefined } | null {
  for (const edge of edges) {
    if (edge.target !== mapId) continue;
    const source = nodes.find((n) => n.id === edge.source);
    if (!isInteraction(source)) continue;
    return { nodeId: source.id, circle: circleOf(edge.targetHandle), settings: normalizeEditFeatures(source.data?.editFeatures) };
  }
  return null;
}

/** The Autark map the Interaction node *nodeId* is plugged into, if any. */
export function mapFedBy(nodeId: string, nodes: readonly any[], edges: readonly any[]): string | null {
  for (const edge of edges) {
    if (edge.source !== nodeId) continue;
    if (isAutkMap(nodes.find((n) => n.id === edge.target))) return edge.target;
  }
  return null;
}

/**
 * The map's input without the Interaction node's circle: a run of the node
 * hands on its log, which is no layer. The other circles keep their places,
 * so each layer keeps the table name (`input_<k>`) the map's document reads.
 */
export function withoutCircle(input: any, circle: number): any {
  if (input && typeof input === "object" && input.dataType === "outputs" && Array.isArray(input.data)) {
    if (circle >= input.data.length) return input;
    const data = [...input.data];
    data[circle] = null;
    return { ...input, data };
  }
  // A map whose only input is the node has no layers.
  return circle === 0 ? null : input;
}

/**
 * What a node is called on the canvas: its header, as renamed
 * (`packageTemplateLabel`, what `nodeDisplayLabel` reads first), else the
 * title the dataflow gave it.
 */
export function nodeName(node: any): string {
  for (const value of [node?.data?.packageTemplateLabel, node?.data?.title]) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

/** What each circle brought: the name of the node it came from. */
export function circleTitles(mapId: string, nodes: readonly any[], edges: readonly any[]): Record<number, string> {
  const out: Record<number, string> = {};
  for (const edge of edges) {
    if (edge.target !== mapId) continue;
    const name = nodeName(nodes.find((n) => n.id === edge.source));
    if (name) out[circleOf(edge.targetHandle)] = name;
  }
  return out;
}

const LAYER_TYPE: Record<NewLayerGeometry, string> = { Point: "points", LineString: "polylines", Polygon: "polygons" };

export interface EditableSource {
  outputTableName: string;
  geojsonObject: any;
  layerType?: string;
}

/** Whether *settings* change anything a map draws. */
export function editsAnything(settings: EditFeaturesSettings | undefined): boolean {
  return (settings?.edits ?? []).some((e) => e.enabled !== false);
}

/** A key for what *settings* make the map draw, so it draws again when it changes. */
export function editsVersion(settings: EditFeaturesSettings | undefined): string {
  if (!settings) return "";
  return JSON.stringify([settings.edits ?? [], settings.newLayers ?? [], settings.keys ?? {}, settings.layer ?? null, settings.key ?? null]);
}

/**
 * *sources* as the log of *settings* leaves them, and the node's new layers
 * that have features. *names* maps a table to the layer's own name, which
 * the log names it by (an unnamed layer goes by its table).
 */
export function editSources<S extends EditableSource>(
  sources: readonly S[],
  settings: EditFeaturesSettings | undefined,
): { sources: S[]; added: EditableSource[] } {
  const edits = (settings?.edits ?? []).filter((e) => e.enabled !== false);
  if (!settings || edits.length === 0) return { sources: [...sources], added: [] };
  const nodeLayer = settings.layer ?? null;
  const named = (name: string) => edits.some((e) => (e.layer ?? nodeLayer) === name);
  const out = sources.map((source) => {
    const name = source.outputTableName;
    if (!named(name)) return source;
    const key = settings.keys?.[name] ?? (name === nodeLayer ? settings.key : undefined);
    if (!key) return source;
    const fc = source.geojsonObject ?? {};
    const features = editedFeatures(fc, edits, key, name, nodeLayer).map((f) => ({ type: "Feature", geometry: f.geometry, properties: f.properties }));
    return { ...source, geojsonObject: { ...fc, type: "FeatureCollection", features } };
  });
  const crs = sources.find((s) => s.geojsonObject?.crs)?.geojsonObject?.crs;
  const added: EditableSource[] = [];
  for (const def of settings.newLayers ?? []) {
    const features = editedFeatures({ features: [] }, edits, NEW_LAYER_KEY, def.name, nodeLayer).map((f) => ({ type: "Feature", geometry: f.geometry, properties: f.properties }));
    if (features.length === 0) continue;
    added.push({
      outputTableName: def.name,
      layerType: LAYER_TYPE[def.geometry],
      geojsonObject: { type: "FeatureCollection", features, ...(crs ? { crs } : {}) },
    });
  }
  return { sources: out, added };
}
