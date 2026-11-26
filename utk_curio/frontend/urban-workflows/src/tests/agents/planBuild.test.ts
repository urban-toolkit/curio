import {
  BUILD_RUNNING_HINT,
  buildRunningOn,
  buildRunningOver,
  NODE_ROW_SOLVE_HINT,
  solveNodeBlockerFor,
  type AgentAttachment,
} from "../../services/agents";

/**
 * Whether a Build & validate runs on a plan: the one this tab runs for the
 * plan's agent, or one the server says runs (the listing's `buildRunning`,
 * another tab's among them). While one runs over a node's plan, or the plan's
 * row Solves the node (`validating`), no Solve of that node starts.
 */

const NOW_S = 1_800_000_000;

const builder = (session: Record<string, unknown> = {}, attachmentId = "dfb"): AgentAttachment => ({
  attachmentId,
  coord: "agent.curio.dataflow-builder@1",
  target: { kind: "canvas" },
  sessionId: "s1",
  revision: 1,
  name: "Dataflow Builder",
  category: "canvas",
  hooks: [],
  intent: null,
  intentEdited: false,
  title: null,
  titleEdited: false,
  capabilities: ["dataflow.orchestrate"],
  builderSession: { phase: "applied", nodeIds: { load: "n1", map: "n2" }, ...session } as AgentAttachment["builderSession"],
});

describe("buildRunningOn", () => {
  it("is the build this tab runs for the plan's agent", () => {
    expect(buildRunningOn(builder(), "step")).toBe("step");
  });

  it("is the build the server says runs, which the listing names", () => {
    expect(
      buildRunningOn({ ...builder({ simulateMode: "auto", simulatingSince: NOW_S - 30 }), buildRunning: "auto" }),
    ).toBe("auto");
  });

  it("is none for a build the record names that the server says no longer runs, or with no build", () => {
    expect(
      buildRunningOn({ ...builder({ simulateMode: "auto", simulatingSince: NOW_S - 16 * 60 }), buildRunning: null }),
    ).toBeNull();
    expect(buildRunningOn(builder())).toBeNull();
  });
});

describe("buildRunningOver", () => {
  it("says a node's plan is being built while a build runs on the plan that holds it", () => {
    const attachments = [{ ...builder({ simulateMode: "auto", simulatingSince: NOW_S - 5 }), buildRunning: "auto" as const }];
    expect(buildRunningOver("n1", attachments, {})).toBe(true);
    expect(buildRunningOver("n9", attachments, {})).toBe(false);
  });

  it("reads this tab's own builds, by the plan's agent", () => {
    const attachments = [builder(), builder({ nodeIds: { other: "n9" } }, "dfb2")];
    expect(buildRunningOver("n1", attachments, { dfb2: "auto" })).toBe(false);
    expect(buildRunningOver("n9", attachments, { dfb2: "auto" })).toBe(true);
  });
});

describe("solveNodeBlockerFor", () => {
  it("is the build's hint while a build runs over the node's plan", () => {
    const attachments = [{ ...builder(), buildRunning: "auto" as const }];
    expect(solveNodeBlockerFor("n1", attachments, {})).toBe(BUILD_RUNNING_HINT);
  });

  it("is the row's hint while the node's plan row Solves it, and none for another node", () => {
    const attachments = [{ ...builder(), validating: { ref: "load", nodeId: "n1" } }];
    expect(solveNodeBlockerFor("n1", attachments, {})).toBe(NODE_ROW_SOLVE_HINT);
    expect(solveNodeBlockerFor("n2", attachments, {})).toBeNull();
  });
});

// The server says whether a build runs (the listing's `buildRunning`): the
// browser's clock is never held against the server's, which a build left by a
// process that is gone would beat for up to the stale bound.
describe("a build runs while the server says so", () => {
  it("one the listing says runs holds the plan, whatever the browser's clock says of its start", () => {
    const running: AgentAttachment = { ...builder({ simulateMode: "auto", simulatingSince: 1 }), buildRunning: "auto" };
    expect(buildRunningOn(running)).toBe("auto");
    expect(buildRunningOver("n1", [running], {})).toBe(true);
  });

  it("one the listing does not say runs holds nothing, however recent its start", () => {
    const left = builder({ simulateMode: "auto", simulatingSince: Date.now() / 1000 });
    expect(buildRunningOn(left)).toBeNull();
    expect(buildRunningOver("n1", [left], {})).toBe(false);
  });
});
