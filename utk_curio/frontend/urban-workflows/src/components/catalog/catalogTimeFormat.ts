/**
 * Relative-time helpers shared by both catalog browse surfaces.
 *
 * The Data Catalog stores timestamps as ISO strings (``dataset.updatedAt``) while
 * the Node Catalog stores epoch milliseconds (``pkg.createdAtMs``), so each page
 * had grown its own near-identical formatter — ``relativeTime`` in
 * ``datasetDetailHelpers`` and a hand-copied ``relativeFromMs`` in *both*
 * ``PackageBrowseCard`` and ``PackageBrowseDrawer``. These accept either shape so
 * the two catalogs render the same string for the same age.
 */

export type CatalogTimestamp = string | number | null | undefined;

/** Freshness cutoff for the meta-row dot: updated within the last day. */
const FRESH_WINDOW_MS = 24 * 60 * 60 * 1000;

/** ISO string or epoch ms -> epoch ms. ``NaN`` when the value is unusable. */
function toMillis(value: CatalogTimestamp): number {
  if (value == null) return NaN;
  if (typeof value === "number") return value > 0 ? value : NaN;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : NaN;
}

/**
 * ``"5m ago"`` / ``"3h ago"`` / ``"2d ago"``. Returns ``fallback`` (an em dash by
 * default) when the timestamp is missing or unparseable, rather than inventing a
 * vague "recently" for data we do not have.
 */
export function catalogRelativeTime(value: CatalogTimestamp, fallback = "—"): string {
  const ms = toMillis(value);
  if (!Number.isFinite(ms)) return fallback;
  const delta = Date.now() - ms;
  if (!Number.isFinite(delta)) return fallback;
  const minutes = Math.max(1, Math.round(delta / 60_000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/** True when the item changed within the last 24h — drives the meta-row live dot. */
export function catalogIsFresh(value: CatalogTimestamp): boolean {
  const ms = toMillis(value);
  if (!Number.isFinite(ms)) return false;
  const delta = Date.now() - ms;
  return Number.isFinite(delta) && delta >= 0 && delta < FRESH_WINDOW_MS;
}
