/**
 * Why a node body is empty, so it can say which kind of empty (#224).
 *
 * The reported symptom is that the states are indistinguishable: an unconnected
 * node, one whose upstream has not run, and a broken one all rendered the same
 * blank rectangle. Four states need four different things from the user, so the
 * classifier is where the fix actually lives — the component only renders it.
 */
import {
  NODE_EMPTY_COPY,
  hasIncomingEdge,
  resolveGrammarEmptyReason,
  resolveNodeEmptyReason,
  type NodeEmptyReason,
} from "../../utils/nodeEmptyState";

const READY = { connected: true, hasInput: true, tabular: true, rowCount: 3 };

describe("resolveNodeEmptyReason", () => {
  test("null when there is data to show", () => {
    expect(resolveNodeEmptyReason(READY)).toBeNull();
  });

  test("names each state", () => {
    expect(resolveNodeEmptyReason({ ...READY, connected: false })).toBe("disconnected");
    expect(resolveNodeEmptyReason({ ...READY, hasInput: false })).toBe("upstream-not-run");
    expect(resolveNodeEmptyReason({ ...READY, tabular: false })).toBe("not-tabular");
    expect(resolveNodeEmptyReason({ ...READY, rowCount: 0 })).toBe("no-rows");
  });

  test("connectivity outranks everything after it", () => {
    // An unconnected node is unconnected whether or not it also has stale rows
    // lying around; telling the user to run an upstream node that is not there
    // would send them nowhere.
    expect(
      resolveNodeEmptyReason({ connected: false, hasInput: false, tabular: false, rowCount: 0 }),
    ).toBe("disconnected");
  });

  test("having run outranks the shape of what came back", () => {
    expect(
      resolveNodeEmptyReason({ connected: true, hasInput: false, tabular: false, rowCount: 0 }),
    ).toBe("upstream-not-run");
  });
});

describe("the copy", () => {
  const REASONS: NodeEmptyReason[] = [
    "disconnected",
    "upstream-not-run",
    "no-rows",
    "not-tabular",
  ];

  test("every state has something to say", () => {
    for (const reason of REASONS) {
      expect(NODE_EMPTY_COPY[reason].title.trim()).not.toBe("");
    }
  });

  test("the four states do not all read the same", () => {
    // The whole complaint was that they were indistinguishable, so identical
    // copy for two of them would reintroduce it. Titles may repeat ("No data
    // yet" fits two states); the hint is what has to differ.
    const hints = REASONS.map((r) => NODE_EMPTY_COPY[r].hint);
    expect(new Set(hints).size).toBe(REASONS.length);
  });
});

describe("hasIncomingEdge", () => {
  test("true when an edge terminates on the node", () => {
    expect(hasIncomingEdge([{ target: "n2" }], "n2")).toBe(true);
  });

  test("false for an edge that only leaves it", () => {
    expect(hasIncomingEdge([{ target: "n3" }], "n2")).toBe(false);
  });

  test("survives an empty or absent graph", () => {
    expect(hasIncomingEdge([], "n2")).toBe(false);
    expect(hasIncomingEdge(undefined, "n2")).toBe(false);
    expect(hasIncomingEdge([{ target: "n2" }], "")).toBe(false);
  });
});

describe("the grammar states", () => {
  // Added for the Vega-Lite node, which rendered no empty state at all: when
  // nothing compiled, its output div was simply blank, the exact #224
  // complaint, still true of the most-used visualisation node.
  const GRAMMAR_REASONS: NodeEmptyReason[] = [
    "input-type-rejected",
    "geometry-unresolved",
    "geometry-ambiguous",
  ];

  test("each has something to say", () => {
    for (const reason of GRAMMAR_REASONS) {
      expect(NODE_EMPTY_COPY[reason].title.trim()).not.toBe("");
      expect(NODE_EMPTY_COPY[reason].hint.trim()).not.toBe("");
    }
  });

  test("they do not read the same as each other", () => {
    const hints = GRAMMAR_REASONS.map((r) => NODE_EMPTY_COPY[r].hint);
    expect(new Set(hints).size).toBe(GRAMMAR_REASONS.length);
  });

  test("the geometry hints name the thing the user has to type", () => {
    // A message that says only "something is wrong with your geometry" is the
    // failure this replaces. Each one has to be actionable on its own.
    expect(NODE_EMPTY_COPY["geometry-ambiguous"].hint).toContain('"geojson"');
    expect(NODE_EMPTY_COPY["geometry-unresolved"].hint).toContain("geoshape");
  });

  test("adding them left the tabular states untouched", () => {
    // Data Pool, Simple View and autk-grammar read these; the change was meant
    // to be purely additive.
    expect(NODE_EMPTY_COPY.disconnected.hint).toBe("Connect a node to this one's input.");
    expect(NODE_EMPTY_COPY["upstream-not-run"].hint).toBe("Run the node feeding this one.");
    expect(
      resolveNodeEmptyReason({ connected: true, hasInput: true, tabular: true, rowCount: 3 }),
    ).toBeNull();
  });
});

describe("resolveGrammarEmptyReason", () => {
  // A sibling of resolveNodeEmptyReason rather than an extension: a chart has
  // no notion of rows or of being "tabular", and a table has none of a spec.
  const inputs = (over: Partial<Parameters<typeof resolveGrammarEmptyReason>[0]> = {}) => ({
    connected: true,
    hasInput: true,
    hasSpec: true,
    hasRun: true,
    ...over,
  });

  test("connectivity is asked first", () => {
    expect(
      resolveGrammarEmptyReason(inputs({ connected: false, hasInput: false, hasSpec: false })),
    ).toBe("disconnected");
  });

  test("an edge with no output yet is upstream-not-run", () => {
    // The state that makes the default-spec feature honest: an edge alone
    // carries no schema, so there is nothing to fill from and saying so beats
    // sitting blank.
    expect(resolveGrammarEmptyReason(inputs({ hasInput: false }))).toBe("upstream-not-run");
  });

  test("an unreadable input outranks a missing spec", () => {
    // No spec will fix a payload this node cannot read, so say the true thing.
    expect(
      resolveGrammarEmptyReason(
        inputs({ hasSpec: false, inputProblem: "input-type-rejected" }),
      ),
    ).toBe("input-type-rejected");
  });

  test("an empty editor is no-spec", () => {
    expect(resolveGrammarEmptyReason(inputs({ hasSpec: false }))).toBe("no-spec");
  });

  test("a spec that has not been compiled is not-run", () => {
    expect(resolveGrammarEmptyReason(inputs({ hasRun: false }))).toBe("not-run");
  });

  test("a compile that drew nothing is rendered-empty", () => {
    expect(resolveGrammarEmptyReason(inputs({ renderedEmpty: true }))).toBe("rendered-empty");
  });

  test("a node with a chart to show reports nothing", () => {
    expect(resolveGrammarEmptyReason(inputs())).toBeNull();
  });

  test("the geometry reasons pass straight through as input problems", () => {
    for (const problem of ["geometry-unresolved", "geometry-ambiguous"] as const) {
      expect(resolveGrammarEmptyReason(inputs({ inputProblem: problem }))).toBe(problem);
    }
  });
});
