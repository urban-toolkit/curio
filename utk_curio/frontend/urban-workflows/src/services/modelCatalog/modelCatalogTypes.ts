/**
 * The Model Catalog's wire types.
 *
 * Mirrors `model_row` in `backend/app/model_catalog/service.py`, which builds
 * every row by explicit allowlist and never includes a path on the server.
 * Keep the two in step.
 */

/** Matches `RUNTIMES` in `model_catalog/domain/manifest.py`. */
export type ModelRuntime = "onnx" | "transformers";

/** Matches `TASKS`. */
export type ModelTask = "semantic-segmentation" | "image-to-image";

/** `shipped` models come with Curio and stay where they are; `downloaded`
 *  ones arrived from the Discovery Catalog and belong to this account. */
export type ModelOrigin = "shipped" | "downloaded";

/** An ONNX model's input, as the manifest declares it. */
export interface ModelInput {
  width: number;
  height: number;
  dtype: "uint8" | "float32";
}

/** Where a downloaded model came from, as a downloaded dataset records it. */
export interface ModelDiscoverySource {
  sourceId: string;
  sourceName?: string;
  resourceId: string;
  fetchedAt?: string;
  [key: string]: unknown;
}

export interface ModelRow {
  id: string;
  /** `<id>@<major>`, the folder the model lives in. */
  dirName: string;
  name: string;
  version: string;
  description: string;
  publisher: string;
  homepage: string | null;
  license: string;
  /** True when `GET /api/models/<id>/license` has a text to serve. */
  hasLicenseText: boolean;
  runtime: ModelRuntime;
  task: ModelTask;
  labels: string[];
  labelCount: number;
  input?: ModelInput;
  sizeBytes: number;
  tags: string[];
  origin: ModelOrigin;
  createdAt: string | null;
  discoverySource?: ModelDiscoverySource;
  /** The libraries its runtime needs, by name, installed when it was added. */
  dependencies?: string[];
}

export interface ModelCatalogResponse {
  /** Shipped models first, then by name. */
  items: ModelRow[];
}

export interface ModelCatalogQuery {
  q?: string;
}

export const MODEL_RUNTIME_LABEL: Record<ModelRuntime, string> = {
  onnx: "ONNX",
  transformers: "Transformers",
};

export const MODEL_ORIGIN_LABEL: Record<ModelOrigin, string> = {
  shipped: "Shipped with Curio",
  downloaded: "Downloaded",
};

export const MODEL_TASK_LABEL: Record<ModelTask, string> = {
  "semantic-segmentation": "Semantic segmentation",
  "image-to-image": "Image to image",
};

/** Only a model this account downloaded can be deleted; the server answers
 *  403 for a shipped one, so nothing offers it. */
export function isDeletableModel(model: Pick<ModelRow, "origin">): boolean {
  return model.origin === "downloaded";
}

/** `shipped` is the server's own order (shipped models first, then by name). */
export type ModelSortMode = "shipped" | "name";

export const MODEL_SORT_OPTIONS: { value: ModelSortMode; label: string }[] = [
  { value: "shipped", label: "Sort: Shipped first" },
  { value: "name", label: "Sort: Name" },
];

export function sortModels(items: ModelRow[], mode: ModelSortMode): ModelRow[] {
  if (mode === "shipped") return items;
  return [...items].sort((a, b) => a.name.localeCompare(b.name));
}
