/**
 * The setters of nodes' settings, by node id and setting.
 *
 * A node keeps choices its body offers (a Data Pool's conflict modes, a
 * Simple View's image column) and the values of its widgets, a Spatial Join's
 * operation and output among them, and the control that changes one makes the
 * change its own way: the pool resolves its selections again, a widget's new
 * value leaves its node out of date and runs it when automatic runs are on.
 * A node registers each of its setters here while it is on the canvas, so a
 * setting changed from outside the node, an agent's applied
 * change (`applyNodeSettings`), is made the way a pick in the node makes it,
 * as `nodeCodeWriters` does for a node whose code is its state.
 *
 * A widget whose control a node's body draws itself (`ownWidgets`, such as
 * Simple View's Time column) can have a setter of its own, which a change of
 * that widget's value goes through before the node's widgets setter.
 *
 * A setting no setter takes goes into the node's data, as a load of its
 * metadata puts it there. A settings change files no entry in the node's
 * Provenance drawer: an entry holds code, so putting one back could not put
 * back a setting.
 */
import { tryGetNodeDescriptor } from "../registry/nodeRegistry";
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
  widgets?: Record<string, unknown>;
}

export type NodeSettingKey = keyof NodeSettings;

/** Makes the change *setting* says, as a pick in the node makes it. */
export type NodeSettingWriter<K extends NodeSettingKey> = (setting: NonNullable<NodeSettings[K]>) => void;

/** The settings, in the order a change makes them. */
const KEYS: readonly NodeSettingKey[] = ["dataPool", "simpleVis", "widgets"];

type AnyWriter = (setting: any) => void;
const writers = new Map<string, Partial<Record<NodeSettingKey, AnyWriter>>>();

/** Sets one widget's value as the node's own control for it sets one. */
export type NodeWidgetWriter = (value: unknown) => void;
const widgetWriters = new Map<string, Map<string, NodeWidgetWriter>>();

/** Registers *writer* for the widget *name* of *nodeId*, one whose control
 * the node's body draws itself; the function it returns takes it off again. */
export function registerNodeWidgetWriter(nodeId: string, name: string, writer: NodeWidgetWriter): () => void {
  const held = widgetWriters.get(nodeId) ?? new Map<string, NodeWidgetWriter>();
  held.set(name, writer);
  widgetWriters.set(nodeId, held);
  return () => {
    const now = widgetWriters.get(nodeId);
    if (!now || now.get(name) !== writer) return;
    now.delete(name);
    if (now.size === 0) widgetWriters.delete(nodeId);
  };
}

/**
 * Whether a new value of a widget of a node of *nodeType* can change what the
 * node makes: a template with code or a spec places its widgets there. A
 * template with neither, Simple View, reads its widgets in its body alone (its
 * Time column names the column its player's range is on), so a new value
 * leaves the node current and runs nothing, and a node of it that holds none of
 * them yet, one saved before its template declared it, takes its template's.
 * An unknown template's widgets count as read by its code.
 */
export function widgetsChangeOutput(nodeType: unknown): boolean {
  const descriptor = typeof nodeType === "string" ? tryGetNodeDescriptor(nodeType) : undefined;
  return !descriptor || Boolean(descriptor.hasCode || descriptor.hasGrammar);
}

/** *widgets*, a node's, with each one *values* names given that value, as
 * the Widgets tab sets a value, then each of *declared*, its template's
 * widgets, that the node holds none of and *values* names, with that value:
 * a node saved before its template declared one takes the template's. */
export function withDeclaredWidgetValues(
  widgets: WidgetDef[],
  values: Record<string, unknown>,
  declared: readonly WidgetDef[],
): WidgetDef[] {
  const held = new Set(widgets.map((widget) => widget.name));
  const added = declared
    .filter((widget) => !held.has(widget.name) && Object.prototype.hasOwnProperty.call(values, widget.name))
    .map((widget) => ({ ...widget, value: values[widget.name] as WidgetValue }));
  return [...withWidgetValues(widgets, values), ...added];
}

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
 * the change names given its value, its template's on a node whose widgets
 * change no output that holds none of it yet (`widgetsChangeOutput`). */
export function withNodeSettings(data: Record<string, any>, settings: NodeSettings): Record<string, any> {
  const next: Record<string, any> = { ...data };
  if (settings.dataPool) next.dataPool = { ...(data.dataPool ?? {}), ...settings.dataPool };
  if (settings.simpleVis) {
    const simpleVis = { ...(data.simpleVis ?? {}) };
    if (settings.simpleVis.imageColumn) simpleVis.imageColumn = settings.simpleVis.imageColumn;
    else delete simpleVis.imageColumn;
    next.simpleVis = simpleVis;
  }
  if (settings.widgets) {
    const declared = widgetsChangeOutput(data.nodeType) ? [] : tryGetNodeDescriptor(data.nodeType)?.widgets ?? [];
    next.widgets = withDeclaredWidgetValues(normalizeWidgets(data.widgets), settings.widgets, declared);
  }
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

/** The values of *values* no setter of *nodeId*'s own widgets takes, once
 * each one a setter takes is set through it (`registerNodeWidgetWriter`);
 * undefined when every one was. */
function writeOwnWidgets(nodeId: string, values: Record<string, unknown>): Record<string, unknown> | undefined {
  const own = widgetWriters.get(nodeId);
  if (!own) return values;
  const others: Record<string, unknown> = {};
  for (const [name, value] of Object.entries(values)) {
    const writer = own.get(name);
    if (writer) writer(value);
    else others[name] = value;
  }
  return Object.keys(others).length > 0 ? others : undefined;
}

/**
 * Makes the change *settings* on node *nodeId*: each setting through the
 * setter the node registered for it, as a pick in the node makes it, a value
 * of a widget its body draws itself through that widget's own setter, and the
 * rest into the node's data through *canvas*'s `updateDataNode`. A widget's
 * new value made there still does what the Widgets tab's does: the node is
 * out of date, the dataflow Unsaved, and an automatic run takes the node,
 * unless its widgets change no output (`widgetsChangeOutput`).
 */
export function writeNodeSettings(canvas: NodeSettingsCanvas, nodeId: string, settings: NodeSettings): void {
  const rest: NodeSettings = {};
  for (const key of KEYS) {
    let setting = settings[key];
    if (setting === undefined) continue;
    if (key === "widgets") {
      setting = writeOwnWidgets(nodeId, setting as Record<string, unknown>);
      if (setting === undefined) continue;
    }
    const writer = writers.get(nodeId)?.[key];
    if (writer) writer(setting);
    else (rest as Record<string, unknown>)[key] = setting;
  }
  if (Object.keys(rest).length === 0) return;
  const nodes = canvas.nodes();
  const node = nodes.find((n) => n.id === nodeId);
  if (!node) return;
  canvas.updateDataNode(nodeId, withNodeSettings(node.data ?? {}, rest));
  if (!rest.widgets || !widgetsChangeOutput(node.data?.nodeType)) return;
  canvas.markNodeStale?.(nodeId);
  canvas.markDirty?.();
  canvas.requestAutoRun?.([nodeId]);
}
