/**
 * Where the collaboration socket connects. socket.io takes the path of the URL
 * it is given as the namespace and sends its handshake to `path` at that URL's
 * origin, so a backend under a path (`https://<host>/curio/api`, `/api`) puts
 * its prefix in `path`, not in the URL. `backend` is `backendUrl()`'s value:
 * absolute, a path, or `''` for same-origin, each resolved against the page.
 */
export function collabSocketTarget(
  backend: string,
  namespace: string,
  page: string = window.location.href,
): { url: string; path: string } {
  const base = new URL(backend || "/", page);
  const prefix = base.pathname.replace(/\/+$/, "");
  return { url: `${base.origin}${namespace}`, path: `${prefix}/socket.io` };
}
