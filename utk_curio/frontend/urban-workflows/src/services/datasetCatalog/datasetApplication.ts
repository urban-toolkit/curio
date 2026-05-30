import { NodeType } from "../../constants";
import {
  DatasetCatalogItem,
  DatasetDragPayload,
} from "./datasetCatalogTypes";
import { mergeDatasetLoaderCode } from "./datasetLoaderSnippets";

export const DATASET_DRAG_MIME = "application/x-curio-dataset";

type DatasetLike = DatasetCatalogItem | DatasetDragPayload;

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

export function readDatasetDragPayload(dataTransfer: DataTransfer): DatasetDragPayload | null {
  const raw = dataTransfer.getData(DATASET_DRAG_MIME);
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

export function hasDatasetDrag(dataTransfer: DataTransfer): boolean {
  return Array.from(dataTransfer.types || []).includes(DATASET_DRAG_MIME);
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
