/**
 * The backend's base URL, resolved at RUNTIME in the browser.
 *
 * Every other module must read the backend address through this function and
 * never through `process.env.BACKEND_URL` directly. dotenv-webpack inlines that
 * variable into bundle.js at BUILD time, so a bundle only ever knows the one
 * backend it was compiled against -- which is why changing `--backend-port`
 * used to force a frontend rebuild, and why a bundle built for the wrong port
 * fails silently (the canvas loads, no node ever renders).
 *
 * This is the same reasoning as `SANDBOX_BACKEND_URL_TOKEN` in
 * adapters/node/autkGrammarBehavior.tsx (#248): resolve the address in the
 * process that performs the fetch. Resolution order:
 *
 *   1. `window.__CURIO_BACKEND_URL__` -- set by whoever serves or drives the
 *      page. The e2e harness injects it per browser context so one frontend
 *      build can talk to any of several backends at once.
 *   2. `process.env.BACKEND_URL` -- the build-time value, kept as the fallback
 *      so an ordinary `curio.py start` and every existing deployment behave
 *      exactly as before.
 *   3. `''` -- same-origin. Callers that want `http://localhost:5002` instead
 *      write `backendUrl() || 'http://localhost:5002'`, so each call site keeps
 *      the fallback it had before this helper existed.
 *
 * A trailing slash is stripped so `${backendUrl()}/path` never doubles it.
 */
export function backendUrl(): string {
  const w = typeof window !== 'undefined' ? (window as any) : undefined;
  const injected = w?.__CURIO_BACKEND_URL__;
  const raw =
    typeof injected === 'string' && injected !== ''
      ? injected
      : (process.env.BACKEND_URL ?? '');
  return raw.replace(/\/+$/, '');
}
