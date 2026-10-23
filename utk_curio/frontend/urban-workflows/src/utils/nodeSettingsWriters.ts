/**
 * The setters of nodes' settings, by node id and setting.
 *
 * A node keeps choices its body offers (a Data Pool's conflict modes, a
 * Simple View's image column, a Spatial Join's operation and output) and the
 * values of its widgets, and the control that changes one makes the change its
 * own way: the pool resolves its selections again, the join joins again, a
 * widget's new value leaves its node out of date and runs it when automatic
 * runs are on. A node registers each of its setters here while it is on the
 * canvas, so a setting changed from outside the node, an agent's applied
 * change (`applyNodeSettings`), is made the way a pick in the node makes it,
 * as `nodeCodeWriters` does for a node whose code is its state.
 *
 * A setting no setter takes goes into the node's data, as a load of its
 * metadata puts it there. A settings change files no entry in the node's
 * Provenance drawer: an entry holds code, so putting one back could not put
 * back a setting.
 */
import { isParameterNode, nodesUsingShared } from "./references/sharedParameters";
import { normalizeWidgets, type WidgetDef, type WidgetValue } from "./widgets/widgetModel";

/**
 * A change of a node's settings, by the key the node keeps each at. Each key
 * a setting gives is picked as the node's select picks it and a key it leaves
 * out stays, so a Simple View's setting without a column picks every image
 * column; widget values are by widget name.
 */
export interface NodeSettings {
  dataPool?: { insideChart?: string; betweenCharts?: string };
  simpleVis?: { imageColumn?: string };
  spatialJoin?: { predicate?: string; output?: string };
  widgets?: Record<string, unknown>;
}

export type NodeSettingKey = keyof NodeSettings;

/** Makes the change *setting* says, as a pick in the node makes it. */
export type NodeSettingWriter<K extends NodeSettingKey> = (setting: NonNullable<NodeSettings[K]>) => void;

/** The settings, in the order a change makes them. */
const KEYS: readonly NodeSettingKey[] = ["spatialJoin", "dataPool", "simpleVis", "widgets"];

type AnyWriter = (setting: any) => void;
const writers = new Map<string, Partial<Record<NodeSettingKey, AnyWriter>>>();

/** Registers *writer* for the setting *key* of *nodeId*; the function it
 * returns takes it off again. */
export function registerNodeSettingWriter<K extends NodeSettingKey>(
  nodeId: string,
  key: K,
  writer: NodeSettingWriter<K>,
): () => void {
  const held = writers.get(nodeId) ?? {};
  held[key] = writer as AnyWriter;
  writers.set(nodeId, held);
  return () => {
    const now = writers.get(nodeId);
    if (!now || now[key] !== writer) return;
    delete now[key];
    if (Object.keys(now).length === 0) writers.delete(nodeId);
  };
}

/** The writer *nodeId*'s node registered for the setting *key*, if any. */
export function nodeSettingWriter<K extends NodeSettingKey>(nodeId: string, key: K): NodeSettingWriter<K> | undefined {
  return writers.get(nodeId)?.[key] as NodeSettingWriter<K> | undefined;
}

/** *widgets* with each one *values* names given that value, as the Widgets
 * tab sets a value; the others as they are. */
export function withWidgetValues(widgets: WidgetDef[], values: Record<string, unknown>): WidgetDef[] {
  return widgets.map((widget) =>
    Object.prototype.hasOwnProperty.call(values, widget.name)
      ? { ...widget, value: values[widget.name] as WidgetValue }
      : widget,
  );
}

/** *data*, a node's data, with *settings* in it as a load of the node's
 * metadata puts them there: each key a setting gives over the ones the node
 * holds, a Simple View's column gone for every image column, and each widget
 * the change names given its value. */
export function withNodeSettings(data: Record<string, any>, settings: NodeSettings): Record<string, any> {
  const next: Record<string, any> = { ...data };
  if (settings.dataPool) next.dataPool = { ...(data.dataPool ?? {}), ...settings.dataPool };
  if (settings.spatialJoin) next.spatialJoin = { ...(data.spatialJoin ?? {}), ...settings.spatialJoin };
  if (settings.simpleVis) {
    const simpleVis = { ...(data.simpleVis ?? {}) };
    if (settings.simpleVis.imageColumn) simpleVis.imageColumn = settings.simpleVis.imageColumn;
    else delete simpleVis.imageColumn;
    next.simpleVis = simpleVis;
  }
  if (settings.widgets) next.widgets = withWidgetValues(normalizeWidgets(data.widgets), settings.widgets);
  return next;
}

/** What a change of a node's settings needs of the canvas for a setting no
 * setter of the node's own takes. */
export interface NodeSettingsCanvas {
  /** The nodes on the canvas now. */
  nodes: () => readonly { id: string; type?: string | null; data?: any }[];
  updateDataNode: (nodeId: string, data: any) => void;
  markNodeStale?: (nodeId: string) => void;
  markDirty?: () => void;
  requestAutoRun?: (nodeIds: readonly string[]) => void;
}

/**
 * Makes the change *settings* on node *nodeId*: each setting through the
 * setter the node registered for it, as a pick in the node makes it, and the
 * rest into the node's data through *canvas*'s `updateDataNode`. A widget's
 * new value made there still does what the Widgets tab's does: what reads it
 * is out of date, the dataflow Unsaved, and an automatic run takes it, the
 * node itself, or the nodes that use a Parameter node's value.
 */
export function writeNodeSettings(canvas: NodeSettingsCanvas, nodeId: string, settings: NodeSettings): void {
  const rest: NodeSettings = {};
  for (const key of KEYS) {
    const setting = settings[key];
    if (setting === undefined) continue;
    const writer = writers.get(nodeId)?.[key];
    if (writer) writer(setting);
    else (rest as Record<string, unknown>)[key] = setting;
  }
  if (Object.keys(rest).length === 0) return;
  const nodes = canvas.nodes();
  const node = nodes.find((n) => n.id === nodeId);
  if (!node) return;
  canvas.updateDataNode(nodeId, withNodeSettings(node.data ?? {}, rest));
  if (!rest.widgets) return;
  const names = Object.keys(rest.widgets);
  const readers = isParameterNode(node)
    ? Array.from(new Set(names.flatMap((name) => nodesUsingShared(nodes, name).map((reader) => reader.id))))
    : [nodeId];
  for (const id of readers) canvas.markNodeStale?.(id);
  canvas.markDirty?.();
  canvas.requestAutoRun?.(readers);
}
