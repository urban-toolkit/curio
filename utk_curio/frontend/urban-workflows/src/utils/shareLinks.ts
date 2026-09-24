/**
 * The two shareable dataflow URLs, in one place.
 *
 * A dataflow and its dashboard are the same project under two routes, so the
 * paths are built from one id and the "is this a share link" test covers both.
 * That test used to be an inline regex in ``UserProvider`` naming ``/dataflow``
 * alone, which is why a visitor landing on a dashboard link would have been
 * shown a sign-in form instead of the dashboard.
 */

/** A project id as the routes carry it (uuid4, ``Project.id``). */
export const SHARE_UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Unanchored on the left on purpose: this runs against
// ``window.location.pathname``, which carries the router's basename
// (``PUBLIC_PATH``, see index.tsx), so a prefixed deployment must still match.
// Anchored on the right by a delimiter so ``/dashboards/<uuid>`` does not.
const SHARE_PATH_RE =
  /\/(?:dataflow|dashboard)\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:[/?#]|$)/i;

/** Is this pathname a link to one specific dataflow or its dashboard? */
export function isShareLinkPath(pathname: string | null | undefined): boolean {
  if (!pathname) return false;
  return SHARE_PATH_RE.test(pathname);
}

/** Router path for a dataflow's canvas. */
export function dataflowPath(id: string): string {
  return `/dataflow/${id}`;
}

/** Router path for a dataflow's dashboard. */
export function dashboardPath(id: string): string {
  return `/dashboard/${id}`;
}

/**
 * Absolute URL for a router path, for copying and for a link that opens in a
 * new tab.
 *
 * *href* is what ``useHref`` returns, i.e. the path with the router's basename
 * already applied; this only adds the origin. Kept out of the components so the
 * basename half cannot be forgotten in one of them.
 */
export function absoluteUrl(href: string, origin?: string): string {
  const base =
    origin ?? (typeof window === "undefined" ? "" : window.location.origin);
  if (!href.startsWith("/")) return `${base}/${href}`;
  return `${base}${href}`;
}
