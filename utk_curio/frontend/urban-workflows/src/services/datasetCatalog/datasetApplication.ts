import { NodeType } from "../../constants";
import {
  DatasetCatalogItem,
  DatasetDragPayload,
  DatasetGroupLayerRef,
  DatasetNodeSource,
} from "./datasetCatalogTypes";
import { buildDatasetLoaderCode, mergeDatasetLoaderCode } from "./datasetLoaderSnippets";

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

/** True when a node was created from the dataset palette (carries the linkage marker). */
export function isDatasetPaletteNode(data: any): boolean {
  return !!data?.datasetSource?.datasetId;
}

/** The installed-dataset id a palette node is linked to, or ``null``. */
export function getDatasetSourceId(data: any): string | null {
  return data?.datasetSource?.datasetId ?? null;
}

/**
 * Every dataset id a canvas node is linked to: the palette-creation marker
 * (``datasetSource``) plus every applied/referenced dataset (``datasetRefs`` /
 * ``appliedDatasets``). This is the single source of truth for palette↔canvas
 * highlighting, so a node created by dragging a *group* (whose ``datasetSource``
 * is the synthetic group id but whose ``datasetRefs`` are the real per-layer
 * ids) is matched when interacting with either the group or one of its layers.
 */
export function nodeLinkedDatasetIds(data: any): string[] {
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

export function canApplyDatasetToNode(data: any): boolean {
  const nodeType = data?.nodeType;
  if (!nodeType) return false;
  if (nodeType === NodeType.DATA_LOADING) return true;
  if (typeof nodeType === "string" && nodeType.includes("data-loading")) return true;
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
