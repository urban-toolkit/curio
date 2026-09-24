import {
  CHECK_CONSOLE,
  NO_DETAIL_MESSAGE,
  UNREPORTED_MESSAGE,
  describeRunError,
  runAndAlwaysSettle,
} from "../../../adapters/node/autkRunSettlement";

/**
 * The guarantee behind #271: an Autark run reports exactly one terminal output,
 * however it ends. FlowProvider's Run All has no promise to await — it watches
 * for the node's output to flip to success or error — so a run that returns
 * saying nothing holds that run, and every later Run / Run All click with it.
 *
 * These test the net directly because through `useAutkGrammarBehavior` it is
 * unreachable: `runGrammar` catches its own failures and emits the error
 * itself. Deleting the entire try/catch/finally from `applyGrammar` left all 14
 * tests in `autkGrammarWebgpuFallback.test.tsx` passing, including the three
 * named for this very guarantee.
 */
function harness() {
  const calls: string[] = [];
  let settled = false;
  return {
    calls,
    settle: () => { settled = true; },
    handlers: {
      settled: () => settled,
      onError: (message: string) => { settled = true; calls.push(`error:${message}`); },
      onUnreported: () => { settled = true; calls.push("unreported"); },
    },
  };
}

describe("runAndAlwaysSettle (#271)", () => {
  it("reports a run that ends without saying anything", async () => {
    // The wedging case: no throw, no output, and the runner waits for ever.
    const h = harness();
    await runAndAlwaysSettle(async () => { /* returns, reports nothing */ }, h.handlers);
    expect(h.calls).toEqual(["unreported"]);
  });

  it("turns a rejection into one error and does not rethrow", async () => {
    // A rejection escaping here would leave the node in "exec" for ever, which
    // is the same wedge by another route.
    const h = harness();
    await expect(
      runAndAlwaysSettle(async () => { throw new Error("createShaderModule of undefined"); }, h.handlers),
    ).resolves.toBeUndefined();
    expect(h.calls).toEqual(["error:createShaderModule of undefined"]);
  });

  it("adds nothing when the run already reported", async () => {
    // The common path. A second terminal output would flip the node's state
    // after the runner had already moved on.
    const h = harness();
    await runAndAlwaysSettle(async () => { h.settle(); }, h.handlers);
    expect(h.calls).toEqual([]);
  });

  it("reports a throw that happens after a success, without a second unreported", async () => {
    const h = harness();
    await runAndAlwaysSettle(async () => {
      h.settle();
      throw new Error("teardown blew up");
    }, h.handlers);
    expect(h.calls).toEqual(["error:teardown blew up"]);
  });

  it("carries a non-Error rejection through as text", async () => {
    const h = harness();
    // eslint-disable-next-line prefer-promise-reject-errors
    await runAndAlwaysSettle(async () => { throw "just a string"; }, h.handlers);
    expect(h.calls).toEqual(["error:just a string"]);
  });
});

describe("an error message is never empty (#318)", () => {
  // A node in Error with no text tells the user nothing, and the e2e harness
  // reports "execution failed with Error" with no detail. d3 (bundled in
  // autk-map) throws bare `Error()`, and duckdb-wasm rebuilds worker errors
  // with whatever message came across, which can be "".
  it("names the error type when the message is empty", async () => {
    const h = harness();
    await runAndAlwaysSettle(async () => { throw new TypeError(""); }, h.handlers);
    expect(h.calls).toEqual([`error:TypeError (no message)${CHECK_CONSOLE}`]);
  });

  it("falls back to a sentence when there is nothing at all", async () => {
    const h = harness();
    // eslint-disable-next-line prefer-promise-reject-errors
    await runAndAlwaysSettle(async () => { throw ""; }, h.handlers);
    expect(h.calls).toEqual([`error:${NO_DETAIL_MESSAGE}`]);
  });
});

/**
 * #318 made the fallbacks honest; #344 is the other half. "The run failed
 * without saying why." is true and leaves the user with nowhere to go, which is
 * what Renzo-Filho's 2026-09-11 comment on #201 ("it continues to throw an
 * error, but it doesn't inform the user why") was hitting.
 *
 * The rule: a rung that can name a cause says only the cause; a rung that
 * cannot says what to do instead. Asserted through `reasonCode`, so the copy
 * stays editable without a test rewrite.
 */
describe("a failure with no cause still says what to do (#344)", () => {
  it("leaves a real message alone", () => {
    const d = describeRunError(new Error("createShaderModule of undefined"));
    expect(d.reasonCode).toBe("message");
    expect(d.message).toBe("createShaderModule of undefined");
    // Advice appended here would push the real cause out of a toast.
    expect(d.message).not.toContain(CHECK_CONSOLE.trim());
  });

  it("points a message-less DOMException at the console", () => {
    // The real source named in #344. A DOMException always has a name and can
    // have no message, so it lands on the name rung - which on its own is a
    // symptom, not a cause.
    const err = new DOMException("", "NotSupportedError");
    const d = describeRunError(err);
    expect(d.reasonCode).toBe("name-only");
    expect(d.message).toContain("NotSupportedError");
    expect(d.message).toContain(CHECK_CONSOLE.trim());
  });

  it("points a worker-boundary error with nothing left on it at the console", () => {
    // duckdb-wasm/d3 rebuild an error across postMessage and can lose both the
    // message and the name.
    const d = describeRunError({});
    expect(d.reasonCode).toBe("no-detail");
    expect(d.message).toBe(NO_DETAIL_MESSAGE);
  });

  it("never shows the user [object Object]", () => {
    // String({}) is non-empty, so the old ladder returned it verbatim: strictly
    // worse than the fallback, because it looks like a cause.
    expect(describeRunError({ code: 42 }).message).not.toContain("[object Object]");
    expect(describeRunError(Object.create(null)).message).toBe(NO_DETAIL_MESSAGE);
  });

  it("still prefers anything real over the fallback", () => {
    expect(describeRunError("just a string").reasonCode).toBe("stringified");
    expect(describeRunError("just a string").message).toBe("just a string");
  });

  it("gives the unreported-run copy the same next step", () => {
    // The sibling case: the node emitted nothing at all (#271). Same dead end
    // for the user, so the same treatment.
    expect(UNREPORTED_MESSAGE).toContain(CHECK_CONSOLE.trim());
  });
});
