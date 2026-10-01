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

/** Shape the drawer's placeholder matching reads off a catalog row. */
export interface DrawerListedRef extends InstalledMatchRef {
  origin?: string;
  installed?: boolean;
  dirName?: string | null;
}

/**
 * The drawer's "Installing…" cards: pending installs no listed row stands for.
 *
 * A row counts once it is what the install produces: an installed item, a
 * non-catalog row, or a run's saved output (a computed row with a store
 * folder). An un-installed hub row sharing the id does not, so its
 * placeholder stays while the install runs. A run's output is never added to
 * the project, so the "In project" tab shows no run placeholders (#217).
 */
export function drawerPendingInstalls(
  pending: PendingInstall[],
  items: DrawerListedRef[],
  tab: string,
): PendingInstall[] {
  const landed = items.filter(
    (item) =>
      item.installed === true ||
      (item.origin !== "hub" && item.origin !== "computed") ||
      (item.origin === "computed" && Boolean(item.dirName)),
  );
  const shown = tab === "installed" ? pending.filter((entry) => !entry.producerNodeId) : pending;
  return pendingInstallsNotYetListed(shown, landed);
}
