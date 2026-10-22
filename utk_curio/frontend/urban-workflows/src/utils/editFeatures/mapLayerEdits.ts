/**
 * An Interaction node linked to an Autark map (#662): the data goes Data →
 * Interaction → map on data edges, and an interaction edge (the in/out dots,
 * as two Autark views are linked) joins the node and the map both ways. A
 * pick on the map reaches the node, and the node's picks and edits show on
 * the map before Commit edits.
 *
 * The node's run hands on its inputs with its log applied, every layer under
 * its name (`curio_edit_features`, `by_input`). The map it feeds draws the
 * node's own inputs with the node's live log instead (`interactionOn`'s
 * `drawFrom`), so an edit shows at once, and hands on what it was fed: the
 * edits the last Commit ran. A map linked to a node that does not feed it
 * applies the log to its own layers, and hands those on.
 */
import { EdgeType, NodeType } from "../../constants";
import { getUnversionedFlowNodeType } from "../flowNodeCanonicalType";
import {
  NEW_LAYER_KEY,
  readEditFeaturesCode,
  type EditFeaturesSettings,
  type NewLayerGeometry,
} from "./editFeatures";
import { editedFeatures } from "./layerModel";

/** The circle an edge goes into: `in` is 0, `in_<k>` is k. */
export function circleOf(handle: unknown): number {
  const m = /^in_(\d+)$/.exec(String(handle ?? ""));
  return m ? Number(m[1]) : 0;
}

export const isAutkMap = (node: any) => !!node && getUnversionedFlowNodeType(node) === NodeType.AUTK_GRAMMAR;
/** Whether *node* is an Interaction node (its type id is still Edit Features'). */
export const isInteraction = (node: any) => !!node && getUnversionedFlowNodeType(node) === NodeType.EDIT_FEATURES;

/** Whether *edge* is an interaction edge: the in/out link, not a data edge. */
export function isInteractionEdge(edge: any): boolean {
  return edge?.type === EdgeType.BIDIRECTIONAL_EDGE || (edge?.sourceHandle === "in/out" && edge?.targetHandle === "in/out");
}

/** The node an interaction edge joins to *nodeId*, either way round. */
function linkedTo(nodeId: string, edges: readonly any[], wanted: (node: any) => boolean, nodes: readonly any[]): any | null {
  for (const edge of edges) {
    if (!isInteractionEdge(edge)) continue;
    const other = edge.source === nodeId ? edge.target : edge.target === nodeId ? edge.source : null;
    if (other == null) continue;
    const node = nodes.find((n) => n.id === other);
    if (wanted(node)) return node;
  }
  return null;
}

export interface LinkedInteraction {
  nodeId: string;
  settings: EditFeaturesSettings | undefined;
  /** Whether the node feeds the map on a data edge. */
  feeds: boolean;
  /**
   * The input the map draws, the node's own, when the node is all that feeds
   * the map: drawn with the live log, so it is never edited twice.
   */
  drawFrom?: unknown;
}

/** The Interaction node linked to the map *mapId* by an interaction edge, and its log. */
export function interactionOn(mapId: string, nodes: readonly any[], edges: readonly any[]): LinkedInteraction | null {
  const node = linkedTo(mapId, edges, isInteraction, nodes);
  if (!node) return null;
  const into = edges.filter((e) => e.target === mapId && !isInteractionEdge(e));
  const feeds = into.some((e) => e.source === node.id);
  const only = feeds && into.every((e) => e.source === node.id);
  return {
    nodeId: node.id,
    settings: nodeSettings(node),
    feeds,
    ...(only ? { drawFrom: node.data?.input } : {}),
  };
}

/** The code a node's data holds: what its editor floats, else what it loaded with. */
export function nodeCode(data: any): string {
  return typeof data?.code === "string" && data.code !== "" ? data.code : String(data?.defaultCode ?? "");
}

/** The edits an Interaction node's code holds, or undefined when the node cannot read its code. */
export function nodeSettings(node: any): EditFeaturesSettings | undefined {
  const read = readEditFeaturesCode(nodeCode(node?.data));
  return "problem" in read ? undefined : read.settings;
}

/** How many circles feed *nodeId*: one past the highest a data edge goes into. */
export function circlesInto(nodeId: string, edges: readonly any[]): number {
  let circles = 0;
  for (const edge of edges) {
    if (edge.target !== nodeId || isInteractionEdge(edge)) continue;
    circles = Math.max(circles, circleOf(edge.targetHandle) + 1);
  }
  return Math.max(circles, 1);
}

/** Whether a data edge goes from *source* into *target*. */
export function feeds(source: string, target: string, edges: readonly any[]): boolean {
  return edges.some((edge) => edge.source === source && edge.target === target && !isInteractionEdge(edge));
}

/**
 * The Autark map the Interaction node *nodeId* edits on: one it feeds on a
 * data edge and is linked to by an interaction edge, the first such link
 * when there are several. Null when there is none: a map linked but not fed
 * is not one.
 */
export function mapFedBy(nodeId: string, nodes: readonly any[], edges: readonly any[]): string | null {
  return linkedMaps(nodeId, nodes, edges)[0] ?? null;
}

/** Every Autark map *nodeId* feeds and is linked to, in the order of their links. */
export function linkedMaps(nodeId: string, nodes: readonly any[], edges: readonly any[]): string[] {
  const out: string[] = [];
  for (const edge of edges) {
    if (!isInteractionEdge(edge)) continue;
    const other = edge.source === nodeId ? edge.target : edge.target === nodeId ? edge.source : null;
    if (other == null || out.includes(other) || !feeds(nodeId, other, edges)) continue;
    if (isAutkMap(nodes.find((n) => n.id === other))) out.push(other);
  }
  return out;
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

/** What each circle of *nodeId* brought: the name of the node it came from. */
export function circleTitles(nodeId: string, nodes: readonly any[], edges: readonly any[]): Record<number, string> {
  const out: Record<number, string> = {};
  for (const edge of edges) {
    if (edge.target !== nodeId || isInteractionEdge(edge)) continue;
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
