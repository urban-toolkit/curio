import { runAndAlwaysSettle } from "../../../adapters/node/autkRunSettlement";

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
