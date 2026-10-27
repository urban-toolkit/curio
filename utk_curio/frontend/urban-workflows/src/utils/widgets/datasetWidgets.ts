/**
 * Dataset widgets: a widget of kind `dataset` holds the id of a Data Catalog
 * dataset, a layer group or a collection, and a file or a dataset dropped on
 * its node sets it. The node's code reads it as `[!! name !!]`, which a run
 * writes as the id, so `curio_load_data([!! data !!])` loads what was dropped.
 */
import { effectiveValue, normalizeWidgets, type WidgetDef } from "./widgetModel";

/** Whether *code* places a reference to the widget *name*. */
function reads(code: string, name: string): boolean {
  // A widget name is letters, digits and underscores (WIDGET_NAME_RE), so it
  // needs no escaping in a pattern.
  return new RegExp(String.raw`\[!!\s*${name}\s*!!\]`).test(code);
}

/** The first dataset widget among *widgets* that *code* reads: the one a
 * file or a dataset dropped on the node sets. Null when there is none, and a
 * drop then writes loader code into the node as it always did. */
export function datasetWidgetReadBy(widgets: unknown, code: unknown): WidgetDef | null {
  if (typeof code !== "string" || code === "") return null;
  return normalizeWidgets(widgets).find((w) => w.type === "dataset" && reads(code, w.name)) ?? null;
}

/** Whether *code* reads any of *widgets*: a node whose template opens on its
 * Widgets tab opens there when it does (NodeEditor). */
export function readsAWidget(widgets: unknown, code: unknown): boolean {
  if (typeof code !== "string" || code === "") return false;
  return normalizeWidgets(widgets).some((w) => reads(code, w.name));
}

/** The first dataset widget among *widgets*, read by the code or not. */
export function firstDatasetWidget(widgets: unknown): WidgetDef | null {
  return normalizeWidgets(widgets).find((w) => w.type === "dataset") ?? null;
}

/** The ids the dataset widgets among *widgets* hold, each once. */
export function datasetWidgetIds(widgets: unknown): string[] {
  const ids = new Set<string>();
  for (const widget of normalizeWidgets(widgets)) {
    if (widget.type !== "dataset") continue;
    const value = effectiveValue(widget);
    if (typeof value === "string" && value !== "") ids.add(value);
  }
  return Array.from(ids);
}

/** What a dataset widget was last set to by a drop: the dataset's id, title
 * and format, which its control shows, and the ids it bound on its node (a
 * layer group's member layers). A node keeps them by widget name in its data's
 * `datasetWidgets`, saved at `metadata.datasetWidgets`. */
export interface DatasetWidgetBinding {
  id: string;
  title: string;
  format: string;
  refs: string[];
}

/** The well-formed dataset widget bindings of a node's *data*, by widget name. */
export function datasetWidgetBindings(data: any): Record<string, DatasetWidgetBinding> {
  const out: Record<string, DatasetWidgetBinding> = {};
  const raw = data?.datasetWidgets;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const [name, entry] of Object.entries(raw)) {
    const b = entry as Partial<DatasetWidgetBinding> | null;
    if (!b || typeof b.id !== "string" || !Array.isArray(b.refs)) continue;
    out[name] = {
      id: b.id,
      title: typeof b.title === "string" ? b.title : b.id,
      format: typeof b.format === "string" ? b.format : "",
      refs: b.refs.filter((ref): ref is string => typeof ref === "string" && ref !== ""),
    };
  }
  return out;
}

/** *widgets* with the widget *name* holding *datasetId*, the others as they are. */
export function withDatasetValue(widgets: unknown, name: string, datasetId: string): WidgetDef[] {
  return normalizeWidgets(widgets).map((widget) =>
    widget.name === name ? { ...widget, value: datasetId } : widget,
  );
}
