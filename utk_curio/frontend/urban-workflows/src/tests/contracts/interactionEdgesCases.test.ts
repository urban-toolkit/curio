/**
 * The one rule for interaction edges, run on the cases in
 * contracts/interactionEdges.cases.json through the canvas's reader
 * (contracts/interactionEdges.ts). backend/tests/test_interaction_edges.py runs
 * the same file through the backend's (execution/run_plan.py, and the plan
 * topology that delegates to it), so the canvas, a run on the server and an
 * agent's plan tell an interaction edge from a data edge alike: a node's own
 * handle `in/out`, a view's `in/out@<id>`.
 */
import fs from "fs";
import path from "path";

const CONTRACTS = path.join(__dirname, "../../contracts");

type HandleCase = { name: string; handle: string | null; interaction: boolean; view: string | null };
type EdgeCase = { name: string; edge: Record<string, unknown> | null; interaction: boolean };
type ViewHandleCase = { name: string; view: string | null; handle: string };

const CASES: { handles: HandleCase[]; edges: EdgeCase[]; viewHandles: ViewHandleCase[] } = JSON.parse(
  fs.readFileSync(path.join(CONTRACTS, "interactionEdges.cases.json"), "utf8"),
);

/** Read when a test runs, so a checkout without it fails each test on its own. */
const contract = () => JSON.parse(fs.readFileSync(path.join(CONTRACTS, "interactionEdges.json"), "utf8"));

/** Loaded when a test runs, for the same reason. */
const rule = () =>
  require("../../contracts/interactionEdges") as {
    INTERACTION_HANDLE: string;
    isInteractionHandle: (handle: unknown) => boolean;
    interactionHandleView: (handle: unknown) => string | null;
    interactionHandleOr: (handle: unknown) => string;
    isInteractionEdge: (edge: unknown) => boolean;
    interactionViewHandle: (view: string | null | undefined) => string;
  };

describe("the contract", () => {
  test("names a node's own handle, the mark before a view's id, and how a saved dataflow and a plan mark an interaction edge", () => {
    expect(contract()).toMatchObject({ handle: "in/out", viewMark: "@", edgeType: "Interaction", planKind: "interaction" });
    expect(rule().INTERACTION_HANDLE).toBe(contract().handle);
  });

  test("the cases hold handles and edges of both kinds", () => {
    for (const list of [CASES.handles, CASES.edges]) {
      expect(list.some((c) => c.interaction)).toBe(true);
      expect(list.some((c) => !c.interaction)).toBe(true);
    }
    expect(CASES.handles.some((c) => c.view !== null)).toBe(true);
  });
});

describe("a handle", () => {
  test.each(CASES.handles.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(rule().isInteractionHandle(c.handle)).toBe(c.interaction);
    expect(rule().interactionHandleView(c.handle)).toBe(c.view);
    // An interaction edge keeps an interaction handle, and puts a node's own in place of any other.
    expect(rule().interactionHandleOr(c.handle)).toBe(c.interaction ? c.handle : contract().handle);
  });
});

describe("an edge", () => {
  test.each(CASES.edges.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(rule().isInteractionEdge(c.edge)).toBe(c.interaction);
  });
});

// A view's dot, an agent's plan and a load write a view's handle through the
// rule, from the view's id: the node's own handle for none.
describe("a view's handle", () => {
  test("the cases name views and a node's own handle", () => {
    expect(CASES.viewHandles.some((c) => c.view)).toBe(true);
    expect(CASES.viewHandles.some((c) => !c.view)).toBe(true);
  });

  test.each(CASES.viewHandles.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(rule().interactionViewHandle(c.view)).toBe(c.handle);
    // It is an interaction handle, and names the view it was made for.
    expect(rule().isInteractionHandle(c.handle)).toBe(true);
    expect(rule().interactionHandleView(c.handle)).toBe(c.view ? c.view : null);
  });
});
