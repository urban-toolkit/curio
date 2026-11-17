/**
 * What a `node_download` event of an agent's run says, for the line that
 * narrates the node's run: how far a download on first use of what the node
 * reads has come, as the canvas says a run's step_progress; null once its
 * downloads are over and the node runs.
 */
export function downloadLine(payload: Record<string, unknown>): string | null {
  return typeof payload.message === "string" && payload.message ? payload.message : null;
}

/**
 * A listener of an agent run's events that hands *onLine* the line each of
 * its `node_download` events says, an empty one once the downloads are over:
 * what a plan row says under itself while its Solve or its Run waits on one.
 */
export function downloadLines(onLine?: (line: string) => void) {
  return (name: string, payload: Record<string, unknown>) => {
    if (name === "node_download") onLine?.(downloadLine(payload) ?? "");
  };
}
