/**
 * A landed plan's card reads its rows' state from the plan's agent
 * (`planNodeStateFor`): the attachment's ledger of the plan, and what runs on
 * it now, which the chat streams. Each row of the card says its node's run,
 * why it failed, a notice, and whether it waits for the person's pick, from
 * here; the card's own cases (AgentChangeCard.test.tsx) hand it a state
 * ready-made.
 */
import { planNodeStateFor } from "../../components/agents/attach/chat/chatPanelDerived";
import type { AgentAttachment, AgentChangePart } from "../../services/agents";

/** The plan's agent, its plan pp1 landed: ref a placed as node na, b as nb. */
const agent = (over: Partial<AgentAttachment> = {}): AgentAttachment =>
  ({
    attachmentId: "dfb",
    coord: "agent.curio.dataflow-builder@1",
    target: { kind: "canvas" },
    sessionId: "s1",
    revision: 1,
    name: "Dataflow Builder",
    category: "canvas",
    planProposal: {
      proposalId: "pp1", tool: "dataflow.plan.write", nodeId: "", summary: "Plan · 2 nodes", status: "applied",
      appliedRefs: ["a", "b"], nodeIds: { a: "na", b: "nb" },
    },
    builderSession: {
      phase: "applied", planProposalId: "pp1",
      nodeStates: { a: "created", b: "created" }, nodeIds: { a: "na", b: "nb" },
      nodeRuns: { na: "pending", nb: "solved" },
      nodeChecks: { b: "valid" },
    },
    ...over,
  }) as unknown as AgentAttachment;

/** The plan's card, as its turn carries it. */
const card = (planId = "pp1"): AgentChangePart =>
  ({
    type: "change", changeId: "c-plan", tool: "dataflow.plan.write", kind: "plan", planId,
    summary: "Plan · 2 nodes", status: "applied", lines: [],
    plan: { goal: "g", nodes: [], edgeCount: 0, edges: [] },
  }) as unknown as AgentChangePart;

describe("a landed plan's rows read their state from the plan's agent", () => {
  it("only for the plan the agent holds now", () => {
    expect(planNodeStateFor(agent(), card("an-older-plan"))).toBeUndefined();
    expect(planNodeStateFor(agent(), card())?.appliedRefs).toEqual(["a", "b"]);
  });

  it("each node's run, the live batch's winning over the record's", () => {
    const state = planNodeStateFor(agent(), card(), false, { solveProgress: { na: "verifying" } })!;
    expect(state.runs).toEqual({ na: "verifying", nb: "solved" });
    // How each node's code was checked, from the ledger.
    expect(state.nodeChecks).toEqual({ b: "valid" });
  });

  it("why a node failed, from the batch, and from a build that paused on it", () => {
    const paused = agent({
      builderSession: {
        ...agent().builderSession!,
        pauseReason: { kind: "validation-failed", ref: "a", message: "validation failed and nothing was written" },
      },
    });
    expect(planNodeStateFor(paused, card())!.failures).toEqual({ na: "Validation failed and nothing was written" });
    // The batch's own reason wins.
    expect(planNodeStateFor(paused, card(), false, { solveErrors: { na: "KeyError: 'x'" } })!.failures).toEqual({
      na: "KeyError: 'x'",
    });
    // A build running again says no reason of its pause.
    expect(planNodeStateFor(paused, card(), true)!.failures).toEqual({});
  });

  it("a notice that is no failure", () => {
    expect(planNodeStateFor(agent(), card(), false, { solveNotices: { nb: "written: no code to run" } })!.notices).toEqual({
      nb: "written: no code to run",
    });
  });

  it("the nodes that wait for the person's pick: the agent's, and the batch's, not a wait upstream", () => {
    const state = planNodeStateFor(agent({ waitsForYou: ["na"] }), card(), false, {
      solveWaiting: [
        { nodeId: "nb", kind: "dataset-selection" },
        { nodeId: "nc", kind: "upstream" },
      ],
    })!;
    expect(state.waitsForPick).toEqual(["na", "nb"]);
  });

  it("what runs over the plan: a build at its node, a batch, a row's Solve", () => {
    const building = agent({ builderSession: { ...agent().builderSession!, currentRef: "a" } });
    const idle = planNodeStateFor(building, card(), false, { simulationActivity: "writing its code" })!;
    expect([idle.buildRunning, idle.buildRef, idle.buildActivity]).toEqual([false, null, null]);
    const built = planNodeStateFor(building, card(), true, { simulationActivity: "writing its code" })!;
    expect([built.buildRunning, built.buildRef, built.buildActivity]).toEqual([true, "a", "writing its code"]);
    expect(planNodeStateFor(agent({ builderSession: { ...agent().builderSession!, phase: "solving" } }), card())!.batchRunning).toBe(true);
    expect(planNodeStateFor(agent({ validating: { ref: "b", nodeId: "nb" } }), card())!.solvingRef).toBe("b");
  });
});
