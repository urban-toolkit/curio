import type { DatasetCatalogItem } from "./datasetCatalogTypes";

/**
 * What a dataset's copy control hands over, decided in one place.
 *
 * #206 asks for "a way to copy the path". The path is the wrong thing to give
 * out, and giving it out is why the request exists: an absolute path is
 * specific to one machine, one user and one mount, so pasting it into a node
 * produces code that works until someone else opens the dataflow. The portable
 * reference is ``curio_dataset_path("<id>")`` — the sandbox resolves it to a
 * real location at execution time, and it is exactly what the palette's own
 * generated loaders emit.
 *
 * So the copy control hands over the reference, and the details view shows the
 * path as information. One function decides, so no surface has to reason about
 * ids versus dirNames versus paths again.
 */

/**
 * Ids are interpolated into Python source, so only ids matching this whitelist
 * can appear inside a ``curio_dataset_path("<id>")`` call — one with a quote or
 * a backslash would break out of the string literal. Kept in step with
 * ``SAFE_DATASET_ID_RE`` in ``datasetLoaderSnippets.ts`` and the backend's
 * ``_SAFE_DATASET_ID_RE``.
 */
const SAFE_DATASET_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._@-]{0,199}$/;

export interface DatasetReference {
  /** The Python expression to paste into a node. */
  code: string;
  /** Where the bytes actually are, for display. Empty when unknown. */
  location: string;
}

/**
 * The reference and the location for *dataset*.
 *
 * Falls back to a quoted literal path when the id cannot be embedded safely —
 * the same fallback ``pathExpr`` makes when generating a loader, so what is
 * copied always matches what the palette would have written.
 */
export function datasetReference(
  dataset: Pick<DatasetCatalogItem, "id" | "path" | "uri">,
): DatasetReference {
  const location = String(dataset.path || dataset.uri || "");
  const id = String(dataset.id ?? "");
  const code = SAFE_DATASET_ID_RE.test(id)
    ? `curio_dataset_path(${JSON.stringify(id)})`
    : JSON.stringify(location);
  return { code, location };
}

/** Just the string a copy control puts on the clipboard. */
export function datasetReferenceCode(
  dataset: Pick<DatasetCatalogItem, "id" | "path" | "uri">,
): string {
  return datasetReference(dataset).code;
}
