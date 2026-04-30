/**
 * Resolve the backend base URL at runtime from the page's own location.
 *
 * Baking BACKEND_URL into the bundle (via webpack DefinePlugin / dotenv-webpack)
 * is brittle: every IP/network change requires a rebuild, Docker images go stale,
 * and dev vs LAN vs collab needs different bakes. Using window.location means
 * "talk to the backend on the same host that served this page" — which is true
 * for localhost dev, Docker, and LAN collab uniformly.
 *
 * Override at runtime by setting `window.__CURIO_BACKEND_URL__` before the app
 * loads (e.g. in a deployed environment that needs a different backend host).
 */
export const BACKEND_URL: string =
  ((globalThis as any).window?.__CURIO_BACKEND_URL__ as string | undefined) ||
  (typeof window !== "undefined"
    ? `${window.location.protocol}//${window.location.hostname}:5002`
    : "http://localhost:5002");
