/**
 * A loader's two views, preview and code (plans/data-loading-expressive-preview-memo.md).
 *
 * `data.loaderView` is saved with the dataflow and shared with collaborators.
 * When it is absent (an example, an older dataflow, a node an agent made), the
 * view follows the code: preview when there is code to describe, the editor
 * when there is none. An empty loader always shows its editor, whatever is
 * stored, since there is nothing to preview; the stored choice comes back with
 * the code.
 */
import { hasLoaderCode } from "../services/datasetCatalog/loaderProfile";

export type LoaderView = "preview" | "code";

/** The preview box's default height, header included. */
export const LOADER_PREVIEW_HEIGHT = 168;

/** Room the preview adds under itself for a failed run's missing-library notice. */
export const LOADER_NOTICE_HEIGHT = 150;

/** The folded chip: one size for every type, the label inside it. */
export const LOADER_CHIP_WIDTH = 84;
export const LOADER_CHIP_HEIGHT = 62;

export function isLoaderView(value: unknown): value is LoaderView {
  return value === "preview" || value === "code";
}

export function resolveLoaderView(stored: unknown, code: unknown): LoaderView {
  if (!hasLoaderCode(code)) return "code";
  return isLoaderView(stored) ? stored : "preview";
}
