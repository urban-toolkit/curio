import {
  MODEL_ORIGIN_LABEL,
  MODEL_RUNTIME_LABEL,
  type ModelOrigin,
  type ModelRuntime,
} from "../../services/modelCatalog";

/**
 * The filter chips on `/catalog/models`, mirroring
 * `pages/discovery/discoveryBrowseConstants.ts`.
 *
 * Declared rather than derived from the rows so the chip ORDER is stable; the
 * counts still come from the rows, and a runtime with no model reads zero.
 */
export const RUNTIME_FILTERS: { value: ModelRuntime; label: string }[] = (
  ["onnx", "transformers"] as ModelRuntime[]
).map((value) => ({ value, label: MODEL_RUNTIME_LABEL[value] }));

export const ORIGIN_FILTERS: { value: ModelOrigin; label: string }[] = (
  ["shipped", "downloaded"] as ModelOrigin[]
).map((value) => ({ value, label: MODEL_ORIGIN_LABEL[value] }));
