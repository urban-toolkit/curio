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
  incomingSourceIds,
  isTabularPayload,
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

describe("an errored upstream is not an unrun one (#347)", () => {
  // A node whose execution fails produces no artifact, so it never calls
  // outputCallback and nothing downstream changes at all. hasInput therefore
  // stays false and the ladder said "upstream-not-run" - "Run the node feeding
  // this one", to a user who had just run it and watched it fail.
  test("outranks having no input", () => {
    expect(
      resolveNodeEmptyReason({
        connected: true,
        upstreamErrored: true,
        hasInput: false,
        tabular: false,
        rowCount: 0,
      }),
    ).toBe("upstream-errored");
  });

  test("outranks a stale input left over from an earlier good run", () => {
    // Why it sits above hasInput rather than below: the rows on screen are from
    // the run before the failure, so reporting on their shape would be a lie.
    expect(
      resolveNodeEmptyReason({
        connected: true,
        upstreamErrored: true,
        hasInput: true,
        tabular: false,
        rowCount: 0,
      }),
    ).toBe("upstream-errored");
  });

  test("does not outrank being disconnected", () => {
    // An edge the user deleted leaves the old exec status behind; connectivity
    // is still the more fundamental fact.
    expect(
      resolveNodeEmptyReason({
        connected: false,
        upstreamErrored: true,
        hasInput: false,
        tabular: false,
        rowCount: 0,
      }),
    ).toBe("disconnected");
  });

  test("the grammar ladder agrees", () => {
    expect(
      resolveGrammarEmptyReason({
        connected: true,
        upstreamErrored: true,
        hasInput: false,
        hasSpec: true,
        hasRun: false,
      }),
    ).toBe("upstream-errored");
  });

  test("is absent by default, so nothing changes for callers that do not pass it", () => {
    expect(
      resolveNodeEmptyReason({ connected: true, hasInput: false, tabular: false, rowCount: 0 }),
    ).toBe("upstream-not-run");
  });
});

describe("a dashboard's tile while a viewer's run makes what it shows, or after it stopped", () => {
  // A visitor runs no node and opens none: "Run the node feeding this one" and
  // "Open it to see the error" told a visitor to do what the page does not let
  // them, while the page was computing, or after a step it could not run.
  const EMPTY = { connected: true, hasInput: false, tabular: false, rowCount: 0 };

  test("a table with nothing in yet is computing while the run goes, even after an earlier failure", () => {
    expect(resolveNodeEmptyReason({ ...EMPTY, upstreamRunning: true })).toBe("upstream-running");
    expect(resolveNodeEmptyReason({ ...EMPTY, upstreamRunning: true, upstreamErrored: true })).toBe("upstream-running");
  });

  test("a table with nothing in says why the run stopped, rather than which node to open", () => {
    expect(resolveNodeEmptyReason({ ...EMPTY, upstreamStopped: '"Rays" could not run in this browser.' })).toBe(
      "upstream-stopped",
    );
    expect(
      resolveNodeEmptyReason({ ...EMPTY, upstreamErrored: true, upstreamStopped: '"Rays" could not run in this browser.' }),
    ).toBe("upstream-stopped");
  });

  test("a table that has rows keeps showing them while a run goes", () => {
    expect(resolveNodeEmptyReason({ ...READY, upstreamRunning: true })).toBeNull();
    expect(resolveNodeEmptyReason({ ...READY, upstreamStopped: "stopped" })).toBeNull();
  });

  test("being disconnected still comes first", () => {
    expect(resolveNodeEmptyReason({ ...EMPTY, connected: false, upstreamRunning: true })).toBe("disconnected");
    expect(
      resolveGrammarEmptyReason({ connected: false, hasInput: false, hasSpec: true, hasRun: false, upstreamRunning: true }),
    ).toBe("disconnected");
  });

  test("a map or chart that drew nothing is computing while the run goes, even with some inputs in", () => {
    // A grammar node is asked only while it shows nothing; with some of its
    // inputs in it would otherwise say "Press play to draw this spec".
    const partial = { connected: true, hasInput: true, hasSpec: true, hasRun: false };
    expect(resolveGrammarEmptyReason({ ...partial, upstreamRunning: true })).toBe("upstream-running");
    expect(resolveGrammarEmptyReason({ ...partial, upstreamStopped: "stopped" })).toBe("upstream-stopped");
    expect(resolveGrammarEmptyReason({ ...partial, upstreamErrored: true, upstreamStopped: "stopped" })).toBe(
      "upstream-stopped",
    );
  });

  test("a document that reads no input says nothing about the run", () => {
    expect(
      resolveGrammarEmptyReason({ connected: false, hasInput: false, hasSpec: true, hasRun: false, needsInput: false, upstreamRunning: true }),
    ).toBe("not-run");
  });

  test("the words name no node to run or open", () => {
    for (const reason of ["upstream-running", "upstream-stopped"] as NodeEmptyReason[]) {
      const { title, hint } = NODE_EMPTY_COPY[reason];
      expect(`${title} ${hint}`).not.toMatch(/\b(run|open|press)\b.*\bnode\b/i);
    }
    // The owner's words (10-25).
    expect(NODE_EMPTY_COPY["upstream-running"]).toEqual({
      title: "Computing...",
      hint: "Results will be shown here once they are ready.",
    });
  });
});

describe("a table reading the rows of an input that just arrived", () => {
  // The input names its artifact a moment before its rows are read. Until
  // then the node has an input and no table: on a dashboard that read
  // "Nothing to display" for about a second between "Computing..." and the
  // rows (10-25).
  const ARRIVED = { connected: true, hasInput: true, tabular: false, rowCount: 0 };

  test("is still computing, not a payload it cannot show nor an empty table", () => {
    expect(resolveNodeEmptyReason({ ...ARRIVED, reading: true })).toBe("upstream-running");
    expect(resolveNodeEmptyReason({ ...ARRIVED, tabular: true, reading: true })).toBe("upstream-running");
  });

  test("a failed upstream still comes first, as it does over any input (#347)", () => {
    expect(resolveNodeEmptyReason({ ...ARRIVED, reading: true, upstreamErrored: true })).toBe("upstream-errored");
  });

  test("says what it read once the read is done", () => {
    expect(resolveNodeEmptyReason({ ...ARRIVED, reading: false })).toBe("not-tabular");
    expect(resolveNodeEmptyReason({ ...ARRIVED, tabular: true, reading: false })).toBe("no-rows");
  });

  test("reading means nothing before an input arrives, or once the rows are shown", () => {
    expect(resolveNodeEmptyReason({ ...ARRIVED, hasInput: false, reading: true })).toBe("upstream-not-run");
    expect(resolveNodeEmptyReason({ ...READY, reading: true })).toBeNull();
    expect(resolveNodeEmptyReason({ ...ARRIVED, connected: false, reading: true })).toBe("disconnected");
  });
});

describe("a dashboard's tile, which has no node to run and no play to press", () => {
  // On dev (10-25) a visitor saw "No data yet. Run the node feeding this one."
  // for 170 ms as the page opened, and "Not drawn yet. Press play to draw
  // this spec." on the map between the run's end and its draw: the tile was
  // still being made, by the page.
  const NOTHING = { connected: true, hasInput: false, tabular: false, rowCount: 0 };
  const CHART = { connected: true, hasInput: true, hasSpec: true, hasRun: false };

  test("a table with nothing in yet is computing, with no run going too", () => {
    expect(resolveNodeEmptyReason({ ...NOTHING, onDashboard: true })).toBe("upstream-running");
    expect(resolveNodeEmptyReason({ ...NOTHING })).toBe("upstream-not-run");
  });

  test("a map or chart is computing until its first draw, with no play to press", () => {
    expect(resolveGrammarEmptyReason({ ...CHART, onDashboard: true })).toBe("upstream-running");
    expect(resolveGrammarEmptyReason({ ...CHART, hasInput: false, onDashboard: true })).toBe("upstream-running");
    expect(resolveGrammarEmptyReason({ ...CHART })).toBe("not-run");
    expect(resolveGrammarEmptyReason({ ...CHART, hasInput: false })).toBe("upstream-not-run");
    // A document that loads its own data draws by itself on a dashboard too.
    expect(resolveGrammarEmptyReason({ ...CHART, needsInput: false, onDashboard: true })).toBe("upstream-running");
  });

  test("why a run stopped, or that a step failed, still comes first", () => {
    expect(resolveNodeEmptyReason({ ...NOTHING, onDashboard: true, upstreamStopped: "Too many runs." })).toBe(
      "upstream-stopped",
    );
    expect(resolveGrammarEmptyReason({ ...CHART, onDashboard: true, upstreamStopped: "Too many runs." })).toBe(
      "upstream-stopped",
    );
  });

  test("a step that failed stops the tile there, with no node for the visitor to open (owner, 10-25)", () => {
    // On the canvas it says to open the failed node; a visitor cannot.
    expect(resolveNodeEmptyReason({ ...NOTHING, onDashboard: true, upstreamErrored: true })).toBe("upstream-stopped");
    expect(resolveGrammarEmptyReason({ ...CHART, onDashboard: true, upstreamErrored: true })).toBe("upstream-stopped");
    expect(NODE_EMPTY_COPY["upstream-stopped"]).toEqual({ title: "No results", hint: "A step before this one failed." });
    expect(resolveNodeEmptyReason({ ...NOTHING, upstreamErrored: true })).toBe("upstream-errored");
    expect(resolveGrammarEmptyReason({ ...CHART, upstreamErrored: true })).toBe("upstream-errored");
  });

  test("what it has, it shows, and what it read says what it is", () => {
    expect(resolveNodeEmptyReason({ ...READY, onDashboard: true })).toBeNull();
    expect(resolveNodeEmptyReason({ ...READY, tabular: false, onDashboard: true })).toBe("not-tabular");
    expect(resolveGrammarEmptyReason({ ...CHART, hasRun: true, onDashboard: true })).toBeNull();
    expect(resolveGrammarEmptyReason({ ...CHART, hasRun: true, renderedEmpty: true, onDashboard: true })).toBe(
      "rendered-empty",
    );
  });
});

describe("incomingSourceIds", () => {
  test("names the nodes feeding this one", () => {
    const edges = [
      { source: "a", target: "pool" },
      { source: "b", target: "pool" },
      { source: "pool", target: "chart" },
    ];
    expect(incomingSourceIds(edges, "pool").sort()).toEqual(["a", "b"]);
  });

  test("de-duplicates a node wired into two ports", () => {
    const edges = [
      { source: "a", target: "merge", targetHandle: "in1" },
      { source: "a", target: "merge", targetHandle: "in2" },
    ];
    expect(incomingSourceIds(edges, "merge")).toEqual(["a"]);
  });

  test("is empty for no edges, no id, or nothing incoming", () => {
    expect(incomingSourceIds([], "pool")).toEqual([]);
    expect(incomingSourceIds(null, "pool")).toEqual([]);
    expect(incomingSourceIds([{ source: "a", target: "other" }], "pool")).toEqual([]);
  });
});

describe("isTabularPayload", () => {
  // The #347 correction: ask the payload what it is, not the row count. A
  // zero-row dataframe is still tabular, and saying otherwise is what sent it
  // to "This input is not tabular data".
  test("an empty dataframe is still tabular", () => {
    expect(isTabularPayload({ dataType: "dataframe", data: {} })).toBe(true);
    expect(isTabularPayload({ dataType: "geodataframe", data: { features: [] } })).toBe(true);
  });

  test("a scalar or dict payload is not", () => {
    expect(isTabularPayload({ dataType: "value", data: 42 })).toBe(false);
    expect(isTabularPayload({ dataType: "dict", data: {} })).toBe(false);
  });

  test("an outputs envelope is tabular when any layer in it is", () => {
    expect(
      isTabularPayload({
        dataType: "outputs",
        data: [{ dataType: "value", data: 1 }, { dataType: "dataframe", data: {} }],
      }),
    ).toBe(true);
    expect(
      isTabularPayload({ dataType: "outputs", data: [{ dataType: "value", data: 1 }] }),
    ).toBe(false);
  });

  test("a bare filename ref or a missing input is not", () => {
    // What the pool receives before the preview fetch resolves.
    expect(isTabularPayload({ filename: "artifact_id" })).toBe(false);
    expect(isTabularPayload("")).toBe(false);
    expect(isTabularPayload(null)).toBe(false);
  });
});

describe("the copy", () => {
  const REASONS: NodeEmptyReason[] = [
    "disconnected",
    "upstream-not-run",
    "upstream-errored",
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

describe("the Map Editor states", () => {
  // The node edits on a map it feeds and is linked to, and reads the code it
  // writes: each state is a reason of the shared table, not a title of its own.
  const MAP_EDITS_REASONS: NodeEmptyReason[] = ["unlinked", "code-unreadable"];

  test("each has something to say", () => {
    for (const reason of MAP_EDITS_REASONS) {
      expect(NODE_EMPTY_COPY[reason].title.trim()).not.toBe("");
      expect(NODE_EMPTY_COPY[reason].hint.trim()).not.toBe("");
    }
  });

  test("unlinked says how to link the map", () => {
    expect(NODE_EMPTY_COPY.unlinked.title).toBe("Not linked to a map");
    expect(NODE_EMPTY_COPY.unlinked.hint).toContain("link the two with an interaction edge");
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

  test("a document that reads no input says nothing about one", () => {
    // An Autark document that loads everything it draws: nothing connected is
    // not a problem, so the first thing worth saying is about the spec.
    const selfContained = inputs({ connected: false, hasInput: false, needsInput: false, hasRun: false });
    expect(resolveGrammarEmptyReason(selfContained)).toBe("not-run");
    expect(resolveGrammarEmptyReason({ ...selfContained, upstreamErrored: true })).toBe("not-run");
    expect(resolveGrammarEmptyReason({ ...selfContained, hasSpec: false })).toBe("no-spec");
  });

  test("the no-spec copy names no grammar", () => {
    expect(NODE_EMPTY_COPY["no-spec"].hint).toBe("Write a spec, or connect an input to generate one.");
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
