/**
 * Guarantee that an Autark run reports exactly one terminal output (#271).
 *
 * The runner has no promise to await: FlowProvider's Run All waits for a node's
 * output to flip to ``success`` or ``error``, and until that happens the run -
 * and every later Run / Run All click - is held. A node that returns without
 * reporting therefore wedges the whole dataflow, which is what #271 reported.
 *
 * Extracted from ``applyGrammar`` so the guarantee is reachable by a test.
 * Through the hook it is not: ``runGrammar`` catches its own failures and emits
 * the error itself, so a rejecting grammar never reaches the wrapper, and every
 * early return inside it already emits first. Deleting the whole try/catch/
 * finally from the caller left all 14 tests in
 * ``autkGrammarWebgpuFallback.test.tsx`` green - the block named "the run always
 * ends (#271)" included. The net is real, and it was untested; a seam is the
 * difference.
 *
 * What it covers, in order of likelihood:
 *   - a future ``return`` added to ``runGrammar`` ahead of its terminal emit;
 *   - a throw from the part of ``runGrammar`` that sits outside its own try -
 *     spec parsing, canvas target lookup, tearing down the previous run's
 *     interaction listeners;
 *   - a throw from the emit path itself.
 */
export interface RunSettlement {
  /** Whether a terminal output (success or error) has already been emitted. */
  settled: () => boolean;
  /** Report a failure. Must itself emit a terminal output. */
  onError: (message: string) => void;
  /** Report a run that ended without saying anything. Must emit terminally. */
  onUnreported: () => void;
}

/**
 * Something to show the user for *err*, never an empty string (#318).
 *
 * `err?.message ?? String(err)` looks equivalent and is not: `??` keeps an
 * empty message, and empty messages happen — d3 (bundled in autk-map) throws
 * bare `Error()`, duckdb-wasm rebuilds a worker error with whatever message
 * crossed the boundary, and a DOMException can carry none. The node then shows
 * "Error" with nothing beside it, and the e2e harness reports a failure with no
 * detail, which is how #318 stayed unexplained for a month.
 */
export function describeError(err: unknown): string {
  const message = (err as any)?.message;
  if (typeof message === "string" && message.trim() !== "") return message;
  const name = (err as any)?.name;
  if (typeof name === "string" && name.trim() !== "") return `${name} (no message)`;
  const text = String(err ?? "").trim();
  return text !== "" ? text : "The run failed without saying why.";
}

export async function runAndAlwaysSettle(
  run: () => Promise<void>,
  handlers: RunSettlement,
): Promise<void> {
  try {
    await run();
  } catch (err: any) {
    // Swallowed on purpose: a rejection that escaped here would leave the node
    // in "exec" for ever, which is the bug. The message goes to the node.
    handlers.onError(describeError(err));
  } finally {
    if (!handlers.settled()) handlers.onUnreported();
  }
}
