import { buildRunningOn, buildRunningOver, type AgentAttachment } from "../../services/agents";

/**
 * Whether a Build & validate runs on a plan: the one this tab runs for the
 * plan's agent, or one the listing names (another tab's), until its start is
 * older than the server lets a build run (`SIMULATE_STALE_SECONDS`). While one
 * runs over a node's plan, no Solve of that node starts.
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
    expect(buildRunningOn(builder(), "step", NOW_S)).toBe("step");
  });

  it("is the build the listing names while its start is recent", () => {
    expect(buildRunningOn(builder({ simulateMode: "auto", simulatingSince: NOW_S - 30 }), null, NOW_S)).toBe("auto");
  });

  it("is none for a build whose start is older than a build may run, or with no build", () => {
    expect(buildRunningOn(builder({ simulateMode: "auto", simulatingSince: NOW_S - 16 * 60 }), null, NOW_S)).toBeNull();
    expect(buildRunningOn(builder(), null, NOW_S)).toBeNull();
  });
});

describe("buildRunningOver", () => {
  it("says a node's plan is being built while a build runs on the plan that holds it", () => {
    const attachments = [builder({ simulateMode: "auto", simulatingSince: NOW_S - 5 })];
    expect(buildRunningOver("n1", attachments, {}, NOW_S)).toBe(true);
    expect(buildRunningOver("n9", attachments, {}, NOW_S)).toBe(false);
  });

  it("reads this tab's own builds, by the plan's agent", () => {
    const attachments = [builder(), builder({ nodeIds: { other: "n9" } }, "dfb2")];
    expect(buildRunningOver("n1", attachments, { dfb2: "auto" }, NOW_S)).toBe(false);
    expect(buildRunningOver("n9", attachments, { dfb2: "auto" }, NOW_S)).toBe(true);
  });
});
