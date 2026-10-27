import { loadsData } from "../../registry/declaredNodes";
import { currentCode } from "../codeOnlyUsage";
import {
  DatasetCatalogItem,
  DatasetDragPayload,
  DatasetGroupLayerRef,
  DatasetNodeSource,
  isLayerGroupId,
} from "./datasetCatalogTypes";
import {
  buildDatasetLoaderCode,
  datasetIdsInCode,
  mergeDatasetLoaderCode,
  widgetLoaderCode,
} from "./datasetLoaderSnippets";
import { createLayerGroupDragPayload } from "./datasetPaletteGrouping";
import { isSavedOutputOfDataflow } from "./producerLinkage";
import {
  datasetWidgetBindings,
  datasetWidgetIds,
  firstDatasetWidget,
  withDatasetValue,
  type DatasetWidgetBinding,
} from "../../utils/widgets/datasetWidgets";
import { normalizeWidgets, type WidgetDef } from "../../utils/widgets/widgetModel";

type AppliedDataset = { id: string; title: string; uri: string; path?: string | null; format: string };

/** The real datasets a dropped payload applies to: the OSM group's per-layer
 * members when present, else the single dataset itself. Keeps the synthetic
 * group id out of the node's ``datasetRefs`` / ``appliedDatasets`` (and thus out
 * of the saved ``dataflow.datasets``). */
function appliedDatasetsForPayload(
  dataset: DatasetLike,
): { refs: string[]; applied: Record<string, AppliedDataset> } {
  const layers =
    "groupLayers" in dataset && dataset.groupLayers && dataset.groupLayers.length > 0
      ? dataset.groupLayers
      : null;
  const sources: Array<AppliedDataset> = layers
    ? layers.map((layer: DatasetGroupLayerRef) => ({
        id: layer.id,
        title: layer.title,
        uri: layer.uri,
        path: layer.path,
        format: layer.format,
      }))
    : [
        {
          id: datasetIdOf(dataset),
          title: dataset.title,
          uri: dataset.uri,
          path: dataset.path,
          format: dataset.format,
        },
      ];
  const applied: Record<string, AppliedDataset> = {};
  for (const source of sources) applied[source.id] = source;
  return { refs: sources.map((source) => source.id), applied };
}

export type DatasetLoaderNodeOptions = {
  position: { x: number; y: number };
  code: string;
  datasetRefs: string[];
  appliedDatasets: Record<string, { id: string; title: string; uri: string; path?: string | null; format: string }>;
  /** Linkage marker — present only on palette-created nodes (see ``DatasetNodeSource``). */
  datasetSource: DatasetNodeSource;
};

function datasetIdOf(dataset: DatasetLike): string {
  return "datasetId" in dataset ? dataset.datasetId : dataset.id;
}

/** Build the linkage marker for a node created from the dataset palette. */
function buildDatasetSource(dataset: DatasetLike): DatasetNodeSource {
  return {
    datasetId: datasetIdOf(dataset),
    title: dataset.title,
    format: dataset.format,
    // Drag payloads created before ``origin`` was carried fall back to "imported".
    origin: dataset.origin ?? "imported",
  };
}

/** Options for ``createCodeNode(NodeType.DATA_LOADING, …)`` after a dataset drop. */
export function buildDatasetLoaderNodeOptions(
  dataset: DatasetLike,
  position: { x: number; y: number },
): DatasetLoaderNodeOptions {
  const { refs, applied } = appliedDatasetsForPayload(dataset);
  return {
    position,
    code: buildDatasetLoaderCode(dataset),
    datasetRefs: refs,
    appliedDatasets: applied,
    datasetSource: buildDatasetSource(dataset),
  };
}

/**
 * Options for ``createCodeNode`` of a template with a dataset widget (Data
 * Loading's Data, in *widgets*) after a dataset drop on the empty canvas: the
 * node a drop on a fresh node of it makes. Its first dataset widget holds the
 * dataset (``applyDatasetToWidget``), and its code is what a drop writes from
 * *starter*, the template's (``widgetLoaderCode``): the starter, naming a
 * GeoTIFF's bounds, or for a dataset whose value cannot leave the node, the
 * loader that keeps it in the code. With no *starter* yet, the code is left
 * out, and the node takes its template's starter when it mounts. Null when
 * *widgets* hold no dataset widget.
 */
export function buildDatasetWidgetNodeOptions(
  dataset: DatasetLike,
  position: { x: number; y: number },
  widgets: unknown,
  starter: string | undefined,
): (Omit<DatasetLoaderNodeOptions, "code"> & {
  code?: string;
  widgets: WidgetDef[];
  datasetWidgets: Record<string, DatasetWidgetBinding>;
}) | null {
  const widget = firstDatasetWidget(widgets);
  if (!widget) return null;
  const data = applyDatasetToWidget(
    { widgets: normalizeWidgets(widgets), datasetSource: buildDatasetSource(dataset) },
    widget.name,
    dataset,
  );
  const code = widgetLoaderCode(dataset, widget.name, starter);
  return {
    position,
    ...(code !== undefined ? { code } : {}),
    widgets: data.widgets,
    datasetRefs: data.datasetRefs,
    appliedDatasets: data.appliedDatasets,
    datasetWidgets: data.datasetWidgets,
    datasetSource: data.datasetSource,
  };
}

/** True when a node was created from the dataset palette (carries the linkage marker). */
export function isDatasetPaletteNode(data: any): boolean {
  return !!data?.datasetSource?.datasetId;
}

/**
 * The DATASET pill of a node a dataset was dropped onto (#442), or ``null``.
 *
 * Such a node is not a palette node: it keeps its own code and its save
 * toggle, so it carries no ``datasetSource``. Its pill names the first dataset
 * it references (``datasetRefs``, which a save keeps) and counts the rest.
 * Title and format come from *lookup*, then from this session's
 * ``appliedDatasets``, then the id itself.
 */
export function droppedDatasetSource(
  data: any,
  lookup?: (datasetId: string) => Partial<Pick<DatasetNodeSource, "title" | "format" | "origin">> | undefined,
): DatasetNodeSource | null {
  if (isDatasetPaletteNode(data)) return null;
  const refs: string[] = Array.from(
    new Set((data?.datasetRefs || []).filter((ref: unknown) => typeof ref === "string" && ref)),
  );
  if (refs.length === 0) return null;
  const first = refs[0];
  const listed = lookup?.(first);
  const applied = data?.appliedDatasets?.[first];
  const title = listed?.title || applied?.title || first;
  return {
    datasetId: first,
    title: refs.length > 1 ? `${title} +${refs.length - 1}` : title,
    format: (listed?.format ?? applied?.format) as DatasetNodeSource["format"],
    origin: listed?.origin ?? "imported",
  };
}

/** The installed-dataset id a palette node is linked to, or ``null``. */
export function getDatasetSourceId(data: any): string | null {
  return data?.datasetSource?.datasetId ?? null;
}

/**
 * The dataset ids a canvas node is bound to: the palette-creation marker
 * (``datasetSource``) plus every applied/referenced dataset (``datasetRefs`` /
 * ``appliedDatasets``), which the drag gestures write and a save keeps.
 */
export function nodeBoundDatasetIds(data: any): string[] {
  const ids = new Set<string>();
  const source = getDatasetSourceId(data);
  if (source) ids.add(source);
  for (const ref of data?.datasetRefs || []) {
    if (typeof ref === "string" && ref) ids.add(ref);
  }
  for (const applied of Object.values(data?.appliedDatasets || {})) {
    const id = (applied as any)?.id;
    if (typeof id === "string" && id) ids.add(id);
  }
  // A dataset widget names what the node loads, whatever set it: a drop, the
  // Widgets tab or an agent.
  for (const id of datasetWidgetIds(data?.widgets)) ids.add(id);
  return Array.from(ids);
}

/**
 * *data*, a node's data, with its dataset widget *widgetName* holding
 * *dataset*: the widget holds the dataset's id (a layer group's own id), and
 * the node's bindings (``datasetRefs``, ``appliedDatasets``) trade the ones the
 * widget bound before for the dataset's, a group's member layers as a drop
 * writes them. So a save puts the dataset in ``dataflow.datasets``, and usage
 * counts and Remove from project see what the widget loads.
 * ``datasetWidgets`` keeps what each widget bound, which a save keeps too, so
 * the next dataset takes its place.
 */
export function applyDatasetToWidget(data: any, widgetName: string, dataset: DatasetLike): any {
  const { refs, applied } = appliedDatasetsForPayload(dataset);
  const bound = datasetWidgetBindings(data);
  const elsewhere = new Set(
    Object.entries(bound).flatMap(([name, binding]) => (name === widgetName ? [] : binding.refs)),
  );
  const dropped = new Set(
    (bound[widgetName]?.refs || []).filter((id) => !elsewhere.has(id) && !refs.includes(id)),
  );
  bound[widgetName] = { id: datasetIdOf(dataset), title: dataset.title, format: dataset.format, refs };
  const appliedDatasets = Object.fromEntries(
    Object.entries({ ...(data?.appliedDatasets || {}), ...applied }).filter(([id]) => !dropped.has(id)),
  );
  return {
    ...data,
    widgets: withDatasetValue(data?.widgets, widgetName, datasetIdOf(dataset)),
    datasetRefs: Array.from(
      new Set([...(data?.datasetRefs || []).filter((id: string) => !dropped.has(id)), ...refs]),
    ),
    appliedDatasets,
    datasetWidgets: bound,
    // A node made from a dataset dropped on the canvas names it in its
    // DATASET chip: the chip follows what the widget now loads.
    ...(data?.datasetSource ? { datasetSource: buildDatasetSource(dataset) } : {}),
  };
}

/**
 * Whether the canvas *nodes* of the dataflow *dataflowId* use *dataset* only
 * through node code, once the dataflow's own ref to it is gone: the code a
 * node runs names it, and no node keeps it, by a binding
 * ({@link nodeBoundDatasetIds}) or by having saved it as its output. A usage
 * read marks a saved dataflow `codeOnly` by the same rule, and the Data
 * Catalog's Remove names this dataflow when it holds (`codeOnlyDataflows`).
 */
export function canvasLoadsDatasetInCodeOnly(
  nodes: ReadonlyArray<{ id: string; data?: any }>,
  dataset: DatasetCatalogItem,
  dataflowId: string | null | undefined,
): boolean {
  const producer = isSavedOutputOfDataflow(dataset, dataflowId) ? dataset.producerNodeId : undefined;
  const kept = nodes.some(
    ({ id, data }) => (!!producer && id === producer) || nodeBoundDatasetIds(data).includes(dataset.id),
  );
  return !kept && nodes.some(({ data }) => datasetIdsInCode(currentCode(data)).includes(dataset.id));
}

/**
 * Every dataset id a canvas node is linked to: the ones it is bound to
 * ({@link nodeBoundDatasetIds}) and the ones its code names. This is the
 * single source of truth for palette↔canvas highlighting, so a node created by
 * dragging a *group* (whose ``datasetSource`` is the synthetic group id but
 * whose ``datasetRefs`` are the real per-layer ids) is matched when
 * interacting with either the group or one of its layers.
 */
export function nodeLinkedDatasetIds(data: any): string[] {
  const ids = new Set<string>(nodeBoundDatasetIds(data));
  // Plus whatever the node's CODE references. The bindings above are written
  // only by the two drag gestures; a loader whose ``curio_data_path`` call
  // was typed, pasted, edited or generated by an agent has no binding at all,
  // so "no nodes on the canvas use this dataset" was reported for a node
  // visibly loading it (#205). The call is the portable, canonical reference --
  // the backend resolves it per execution -- so it is at least as good a
  // statement of use as a binding.
  for (const id of datasetIdsInCode(data?.code)) ids.add(id);
  // ``defaultCode`` is what a palette-created node carries before the user
  // edits it, and the editor renders it, so a node showing a loader call it
  // never had typed into it still counts as using that dataset.
  for (const id of datasetIdsInCode(data?.defaultCode)) ids.add(id);
  return Array.from(ids);
}

/** True when *data* is linked to any of *datasetIds* (see {@link nodeLinkedDatasetIds}). */
export function isNodeLinkedToAnyDataset(data: any, datasetIds: Iterable<string>): boolean {
  const linked = new Set(nodeLinkedDatasetIds(data));
  for (const id of datasetIds) {
    if (id && linked.has(id)) return true;
  }
  return false;
}

export const DATASET_DRAG_MIME = "application/x-curio-dataset";
const DATASET_DRAG_PLAIN_PREFIX = "curio-dataset:";

type DatasetLike = DatasetCatalogItem | DatasetDragPayload;

/** In-memory payload for the current drag (HTML5 getData is unreliable for custom MIME). */
let activeDatasetDrag: DatasetDragPayload | null = null;

export function createDatasetDragPayload(dataset: DatasetCatalogItem): DatasetDragPayload {
  // The Data Catalog drawer lists a layer group as one card: it drags as the
  // palette's group row does, loading and referencing each layer.
  if (isLayerGroupId(dataset.id) && dataset.groupLayers && dataset.groupLayers.length > 0) {
    return createLayerGroupDragPayload({
      groupId: dataset.id,
      title: dataset.title,
      format: dataset.format,
      origin: dataset.origin,
      layers: dataset.groupLayers,
    });
  }
  return {
    datasetId: dataset.id,
    title: dataset.title,
    uri: dataset.uri,
    path: dataset.path,
    format: dataset.format,
    origin: dataset.origin,
    loaderSnippet: dataset.loaderSnippet,
  };
}

function parseDatasetDragJson(raw: string): DatasetDragPayload | null {
  if (!raw) return null;
  try {
    const payload = JSON.parse(raw) as Partial<DatasetDragPayload>;
    if (!payload.datasetId || !payload.title || !payload.uri || !payload.format) {
      return null;
    }
    return payload as DatasetDragPayload;
  } catch {
    return null;
  }
}

/** Call from ``dragStart`` on dataset rows/cards. */
export function beginDatasetDrag(dataset: DatasetCatalogItem): DatasetDragPayload {
  const payload = createDatasetDragPayload(dataset);
  activeDatasetDrag = payload;
  return payload;
}

/** Begin a drag from a prebuilt payload (e.g. an OSM group parent). */
export function beginDatasetDragWith(payload: DatasetDragPayload): DatasetDragPayload {
  activeDatasetDrag = payload;
  return payload;
}

/** Call from ``dragEnd`` so stale payloads are not reused. */
export function endDatasetDrag(): void {
  activeDatasetDrag = null;
}

/** Write drag data (custom MIME + text/plain fallback for the drop handler). */
export function writeDatasetDragData(dataTransfer: DataTransfer, payload: DatasetDragPayload): void {
  const json = JSON.stringify(payload);
  dataTransfer.setData(DATASET_DRAG_MIME, json);
  dataTransfer.setData("text/plain", `${DATASET_DRAG_PLAIN_PREFIX}${json}`);
  dataTransfer.effectAllowed = "copy";
}

export function readDatasetDragPayload(dataTransfer: DataTransfer): DatasetDragPayload | null {
  if (activeDatasetDrag) return activeDatasetDrag;
  const fromMime = parseDatasetDragJson(dataTransfer.getData(DATASET_DRAG_MIME));
  if (fromMime) return fromMime;
  const plain = dataTransfer.getData("text/plain");
  if (plain.startsWith(DATASET_DRAG_PLAIN_PREFIX)) {
    return parseDatasetDragJson(plain.slice(DATASET_DRAG_PLAIN_PREFIX.length));
  }
  return null;
}

export function hasDatasetDrag(dataTransfer: DataTransfer): boolean {
  if (activeDatasetDrag) return true;
  const types = Array.from(dataTransfer.types || []);
  return types.includes(DATASET_DRAG_MIME);
}

/** Whether a dataset dropped on a node applies to it: a node whose template
 * declares ``loadsDataset``, as Data Loading does (``loadsData``,
 * registry/declaredNodes), or any node with code to write the dataset's read
 * into. */
export function canApplyDatasetToNode(data: any): boolean {
  const nodeType = data?.nodeType;
  if (!nodeType) return false;
  if (typeof nodeType === "string" && loadsData(nodeType)) return true;
  if (typeof data?.defaultCode === "string" || typeof data?.code === "string") return true;
  return false;
}

export function applyDatasetToNodeData(
  data: any,
  currentCode: string | undefined,
  dataset: DatasetLike,
): { data: any; code: string } {
  // Expand an OSM group to its real per-layer datasets so the node references
  // resolvable ids (never the synthetic group id).
  const { refs, applied } = appliedDatasetsForPayload(dataset);
  const datasetRefs = Array.from(new Set([...(data?.datasetRefs || []), ...refs]));
  const code = mergeDatasetLoaderCode(currentCode, dataset);
  return {
    code,
    data: {
      ...data,
      code,
      defaultCode: code,
      datasetRefs,
      appliedDatasets: {
        ...(data?.appliedDatasets || {}),
        ...applied,
      },
    },
  };
}
