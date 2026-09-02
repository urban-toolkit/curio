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
