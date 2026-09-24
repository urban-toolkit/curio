/**
 * Survive a failed DuckDB spatial-extension download (#318).
 *
 * autk-db's `init()` runs `INSTALL spatial; LOAD spatial;`, so every fresh
 * in-browser DuckDB fetches the extension from extensions.duckdb.org over the
 * network. Nothing in Curio asks for that and nothing can redirect it, but a
 * node pays for it: one flaky fetch failed `Interaction_AutkMap`'s map-only
 * node in CI with
 *
 *     Failed to execute 'send' on 'XMLHttpRequest': Failed to load
 *     'https://extensions.duckdb.org/v1.5.1/wasm_eh/spatial.duckdb_extension.wasm'
 *
 * and a map that reads its input from an upstream node has no reason to fail
 * because a CDN blinked.
 *
 * The retry rebuilds the thing rather than calling it again: the DuckDB worker
 * that failed to load the extension keeps that state, so only a fresh instance
 * can succeed. Narrow by design — anything that is not an extension-load
 * failure is rethrown on the first attempt, because retrying a Binder Error
 * just makes a broken spec slower to report.
 */

/** Default backoff. Three attempts total: the fetch is usually fine by the second. */
const DEFAULT_DELAYS_MS = [400, 1500];

export function isExtensionLoadError(err: unknown): boolean {
  const text = typeof err === "string"
    ? err
    : ((err as any)?.message ?? String(err ?? ""));
  return /extensions\.duckdb\.org|duckdb_extension/i.test(text);
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Run *make* until it succeeds, retrying only an extension-load failure.
 *
 * *make* must build whatever it needs from scratch — a new `AutkGrammar`, a new
 * `AutkDb` — because the instance that failed cannot recover.
 */
export async function withExtensionRetry<T>(
  make: () => Promise<T>,
  { delaysMs = DEFAULT_DELAYS_MS }: { delaysMs?: number[] } = {},
): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 0; attempt <= delaysMs.length; attempt++) {
    try {
      return await make();
    } catch (err) {
      lastErr = err;
      if (!isExtensionLoadError(err) || attempt === delaysMs.length) throw err;
      console.warn(
        `[autk-grammar] duckdb spatial extension failed to load `
        + `(attempt ${attempt + 1}/${delaysMs.length + 1}); retrying:`,
        (err as any)?.message ?? err,
      );
      await sleep(delaysMs[attempt]);
    }
  }
  throw lastErr;
}
