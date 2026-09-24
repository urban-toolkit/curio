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
 * Where the description came from. Split out from the prose so tests assert the
 * rung and users read the sentence — the same split `webgpuSupport.ts` uses,
 * for the same reason: pinning user-facing copy in tests makes it uneditable.
 */
export type RunErrorReasonCode =
  /** The error carried a real message. The common, good case. */
  | "message"
  /** No message, but a class name: `TypeError`, `NotSupportedError`, ... */
  | "name-only"
  /** No message or name, but it stringified to something worth showing. */
  | "stringified"
  /** Nothing usable at all — or `[object Object]`, which is the same thing. */
  | "no-detail";

export interface RunErrorDescription {
  /** What the user sees: in the node body, a toast, and the console. */
  message: string;
  reasonCode: RunErrorReasonCode;
}

/**
 * The one next step available when the thrown value explains nothing (#344).
 *
 * Kept short because this rides in a toast as well as the node body. The
 * console is not a guess: `onError` in `autkGrammarBehavior` logs every failure
 * there, so for these cases it genuinely holds more than the node can show —
 * the stack, and whatever the worker boundary stripped off the message.
 */
export const CHECK_CONSOLE = " Open the browser console for the full error.";

/** Terminal copy for a throw that carries nothing at all. */
export const NO_DETAIL_MESSAGE = "The run failed without saying why." + CHECK_CONSOLE;

/** Terminal copy for a run that ended without emitting anything (#271). */
export const UNREPORTED_MESSAGE =
  "The Autark node stopped without reporting a result." + CHECK_CONSOLE;

/** `String(x)` for a plain object, which tells the user strictly nothing. */
const USELESS_STRINGIFICATION = "[object Object]";

/**
 * Something to show the user for *err*, never an empty string (#318) and never
 * only an admission that there is nothing to say (#344).
 *
 * `err?.message ?? String(err)` looks equivalent and is not: `??` keeps an
 * empty message, and empty messages happen — d3 (bundled in autk-map) throws
 * bare `Error()`, duckdb-wasm rebuilds a worker error with whatever message
 * crossed the boundary, and a DOMException can carry none. The node then shows
 * "Error" with nothing beside it, and the e2e harness reports a failure with no
 * detail, which is how #318 stayed unexplained for a month.
 *
 * #318 made the fallbacks honest. #344 is the other half: honest was not
 * actionable. A user who reads "The run failed without saying why." has learnt
 * nothing and has nowhere to go, so the two rungs that cannot name a cause now
 * name a next step instead. The rungs that DO carry a cause are left alone —
 * appending advice to a real message would bury it.
 */
export function describeRunError(err: unknown): RunErrorDescription {
  const message = (err as any)?.message;
  if (typeof message === "string" && message.trim() !== "") {
    return { message, reasonCode: "message" };
  }
  const name = (err as any)?.name;
  if (typeof name === "string" && name.trim() !== "") {
    // A DOMException lands here: the class name is the only thing it carries,
    // and on its own it is a symptom, not a cause.
    return { message: `${name} (no message)` + CHECK_CONSOLE, reasonCode: "name-only" };
  }
  // `String(x)` is not total: a null-prototype object has no `toString`, and
  // converting one throws "Cannot convert object to primitive value". This runs
  // inside the catch that guarantees the node settles, so a throw here would
  // re-open #271 - the exact wedge this module exists to prevent.
  let text = "";
  try {
    text = String(err ?? "").trim();
  } catch {
    text = "";
  }
  if (text !== "" && text !== USELESS_STRINGIFICATION) {
    return { message: text, reasonCode: "stringified" };
  }
  return { message: NO_DETAIL_MESSAGE, reasonCode: "no-detail" };
}

/** The message alone, for the callers that only render it. */
export function describeError(err: unknown): string {
  return describeRunError(err).message;
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
