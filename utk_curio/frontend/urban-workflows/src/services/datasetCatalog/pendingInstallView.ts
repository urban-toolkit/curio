import type { PendingInstall } from "./datasetCatalogTypes";

/** Minimal shape needed to match a pending install against an already-listed row. */
export interface InstalledMatchRef {
  id?: string;
  producerNodeId?: string | null;
}

/**
 * Return the pending installs that are NOT yet represented by a real installed
 * row, so a placeholder is shown only until the genuine row lands (matched by
 * catalog id or producer node id). Pass the list of rows the surface already
 * renders as installed; once the real row appears its placeholder is suppressed
 * even if the explicit clear hasn't fired yet (no duplicate, no flicker).
 */
export function pendingInstallsNotYetListed(
  pending: PendingInstall[],
  installedItems: InstalledMatchRef[],
): PendingInstall[] {
  if (!pending.length) return [];
  const ids = new Set<string>();
  const producers = new Set<string>();
  for (const item of installedItems) {
    if (item.id) ids.add(item.id);
    if (item.producerNodeId) producers.add(item.producerNodeId);
  }
  return pending.filter(
    (p) =>
      !(p.datasetId && ids.has(p.datasetId)) &&
      !(p.producerNodeId && producers.has(p.producerNodeId)),
  );
}
