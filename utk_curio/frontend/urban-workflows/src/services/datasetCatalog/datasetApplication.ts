import { NodeType } from "../../constants";
import {
  DatasetCatalogItem,
  DatasetDragPayload,
} from "./datasetCatalogTypes";
import { buildDatasetLoaderCode, mergeDatasetLoaderCode } from "./datasetLoaderSnippets";

export type DatasetLoaderNodeOptions = {
  position: { x: number; y: number };
  code: string;
  datasetRefs: string[];
  appliedDatasets: Record<string, { id: string; title: string; uri: string; path?: string | null; format: string }>;
};

/** Options for ``createCodeNode(NodeType.DATA_LOADING, …)`` after a dataset drop. */
export function buildDatasetLoaderNodeOptions(
  dataset: DatasetLike,
  position: { x: number; y: number },
): DatasetLoaderNodeOptions {
  const datasetId = "datasetId" in dataset ? dataset.datasetId : dataset.id;
  return {
    position,
    code: buildDatasetLoaderCode(dataset),
    datasetRefs: [datasetId],
    appliedDatasets: {
      [datasetId]: {
        id: datasetId,
        title: dataset.title,
        uri: dataset.uri,
        path: dataset.path,
        format: dataset.format,
      },
    },
  };
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
  const datasetId = "datasetId" in dataset ? dataset.datasetId : dataset.id;
  const datasetRefs = Array.from(new Set([...(data?.datasetRefs || []), datasetId]));
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
        [datasetId]: {
          id: datasetId,
          title: dataset.title,
          uri: dataset.uri,
          path: dataset.path,
          format: dataset.format,
        },
      },
    },
  };
}
