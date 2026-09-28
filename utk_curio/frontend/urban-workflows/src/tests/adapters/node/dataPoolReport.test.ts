import { NODE_EMPTY_COPY, resolveNodeEmptyReason } from "../../../utils/nodeEmptyState";

/**
 * dev/138 (closes dev/137 F1): the Data Pool is the node that DETECTS a bad
 * input — "Nothing to display / This input is not tabular data" is its own
 * sentence — and it reported nothing to the journal, because its outcome lives
 * in its behavior's local state rather than in `nodeState.output`, so dev/135's
 * reporter never fired for it. In the owner's `edd71e67` the pool was the only
 * node that knew the upstream had produced something unusable.
 *
 * The behavior's decision is `resolveNodeEmptyReason`'s (tested in full beside
 * it); these pin WHICH of its four answers are worth reporting and what the
 * message says, which is the part a harness reads.
 */

/** The rule the pool now applies, extracted so it is testable as data. */
function reportFor(inputs: Parameters<typeof resolveNodeEmptyReason>[0]) {
  const reason = resolveNodeEmptyReason(inputs);
  if (reason === "disconnected" || reason === "upstream-not-run") return null;
  if (reason === null) return { status: "ok" as const };
  const copy = NODE_EMPTY_COPY[reason];
  return {
    status: "error" as const,
    message: `${copy.title} — ${copy.hint}`,
    kind: `bad-input:${reason}`,
  };
}

describe("what the pool reports", () => {
  it("reports a non-tabular input as a failure the harness can read", () => {
    const report = reportFor({ connected: true, hasInput: true, tabular: false, rowCount: 0 });
    expect(report).toEqual({
      status: "error",
      message: "Nothing to display — This input is not tabular data.",
      kind: "bad-input:not-tabular",
    });
  });

  it("reports an input that ran and came back empty", () => {
    const report = reportFor({ connected: true, hasInput: true, tabular: true, rowCount: 0 });
    expect(report?.kind).toBe("bad-input:no-rows");
    expect(report?.message).toContain("came back empty");
  });

  it("owes nothing when it is not wired yet", () => {
    expect(reportFor({ connected: false, hasInput: false, tabular: false, rowCount: 0 }))
      .toBeNull();
  });

  it("says nothing while its upstream has not run — that node reports itself", () => {
    expect(reportFor({ connected: true, hasInput: false, tabular: false, rowCount: 0 }))
      .toBeNull();
  });

  it("reports ok once it has rows to show", () => {
    expect(reportFor({ connected: true, hasInput: true, tabular: true, rowCount: 12 }))
      .toEqual({ status: "ok" });
  });
});
