import type { DatasetCatalogItem } from "../../services/datasetCatalog";
import {
  datasetCountCompact,
  formatBytes,
  relativeTime,
} from "../../components/datasets/catalog/datasetDetailHelpers";

// Re-export the shared catalog helpers so data-hub callers keep importing them
// from here, but there is a single implementation. ``datasetCount`` uses the
// compact (``"feat."``) variant the browse rows have always rendered.
export { formatBytes, relativeTime };
export const datasetCount = datasetCountCompact;

export function isFresh(iso?: string | null): boolean {
  if (!iso) return false;
  const delta = Date.now() - new Date(iso).getTime();
  return Number.isFinite(delta) && delta < 24 * 60 * 60 * 1000;
}

/**
 * "N nodes consume" segment with correct subject/verb agreement:
 * ``0 nodes consume`` | ``1 node consumes`` | ``2 nodes consume``. Defaults a
 * missing/negative count to 0 so a malformed payload never throws or reads
 * "undefined nodes consume".
 */
export function consumeLabel(count: number | null | undefined): string {
  const n = Number.isFinite(count) && (count as number) > 0 ? Math.floor(count as number) : 0;
  return n === 1 ? "1 node consumes" : `${n} nodes consume`;
}

export function metaLeft(dataset: DatasetCatalogItem): string {
  return [
    datasetCount(dataset),
    formatBytes(dataset.sizeBytes),
    consumeLabel(dataset.consumerNodeCount),
  ]
    .filter(Boolean)
    .join(" | ");
}
