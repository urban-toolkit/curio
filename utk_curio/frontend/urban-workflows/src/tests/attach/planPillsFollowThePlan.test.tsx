/**
 * The Dataflow Builder's plan pills ("Plan node progress") read in the plan's
 * own order, the order its change card lists its nodes in. A session's
 * nodeRuns are keyed by node id, and the server's answer sorts those keys, so
 * the order they come in says nothing of the plan. A node the plan does not
 * list, one an earlier plan placed, follows the plan's nodes in the canvas's
 * order, and a node that is no longer on the canvas comes last. With several
 * nodes awaiting a source, their Open Dataset Finder buttons read in the
 * pills' order too, whatever order the live batch's remedies come in.
 */
import React from "react";
import { render, screen, within } from "@testing-library/react";

const PYTHON = "curio.builtin/python-computation@1";
// The plan's three nodes, in its order. Their ids sort in another order.
const STREETS = "c41d7e20-6a3b-4f1e-9d2c-5b8a7e6f4d3c";
const GRID = "1f7a9b3c-2d4e-4a6b-8c1d-3e5f7a9b1c2d";
const BUILDINGS = "8b2e4f6a-1c3d-4e5f-a7b9-c1d3e5f7a9b2";
// Two nodes an earlier plan placed, and two that are no longer on the canvas.
const TREES = "e5a1b2c3-4d5e-4f6a-8b7c-9d0e1f2a3b4c";
const PARKS = "3c9d8e7f-6a5b-4c4d-9e3f-2a1b0c9d8e7f";
const GONE_FIRST = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const GONE_LAST = "f9e8d7c6-b5a4-4f3e-8d2c-1b0a9f8e7d6c";

/** The canvas's nodes, as the flow context holds them, in the order they
 *  were added: not the plan's order either, so only the plan gives it. */
const mockNodes = [
  [BUILDINGS, "Load existing buildings"],
  [TREES, "Load street trees"],
  [GRID, "Make open-ground grid"],
  [PARKS, "Load parks"],
  [STREETS, "Load streets"],
].map(([id, title]) => ({ id, position: { x: 0, y: 0 }, data: { nodeId: id, nodeType: PYTHON, title } }));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: jest.fn(), nodes: mockNodes }),
}));

import { AgentBuilderStrip } from "../../components/agents/attach/AgentBuilderStrip";
import type { AgentAttachment, AgentRemedy } from "../../services/agents";

/** The Dataflow Builder after its plan landed: the plan's refs in its order
 *  (`appliedRefs`), each with the node it placed, as the server sends them. */
const attachment = (
  refs: Array<[string, string]>,
  nodeRuns: NonNullable<AgentAttachment["builderSession"]>["nodeRuns"],
): AgentAttachment =>
  ({
    attachmentId: "a1",
    coord: "agent.curio.dataflow-builder@1",
    target: { kind: "canvas" },
    sessionId: "s1",
    revision: 1,
    name: "Dataflow Builder",
    category: "canvas",
    hooks: ["canvas"],
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
    builderSession: {
      phase: "applied",
      appliedPlanId: "plan-1",
      planProposalId: "plan-1",
      nodeRuns,
      nodeIds: Object.fromEntries(refs),
    },
    planProposal: {
      proposalId: "plan-1",
      tool: "dataflow.plan.write",
      nodeId: "",
      summary: `Plan · ${refs.length} nodes`,
      status: "applied",
      appliedRefs: refs.map(([ref]) => ref),
      nodeIds: Object.fromEntries(refs),
    },
  }) as AgentAttachment;

/** The pills' names, top to bottom: each pill starts with its node's name. */
function pillNames(): Array<string | null | undefined> {
  const pills = screen.getByRole("list", { name: "Plan node progress" });
  return within(pills)
    .getAllByRole("listitem")
    .map((pill) => pill.firstElementChild?.textContent);
}

function renderStrip(value: AgentAttachment, props: Partial<React.ComponentProps<typeof AgentBuilderStrip>> = {}) {
  render(<AgentBuilderStrip attachment={value} onSolve={jest.fn()} onComposePrompt={jest.fn()} {...props} />);
}

/** A node awaiting a source: its own Dataset Finder holds the candidates. */
const awaitingSource = (nodeId: string): AgentRemedy => ({
  kind: "dataset-selection",
  attachmentId: `finder-${nodeId}`,
  nodeId,
});

test("the pills list the plan's nodes in the plan's order, whatever order nodeRuns come in", () => {
  renderStrip(
    attachment(
      [["streets", STREETS], ["grid", GRID], ["buildings", BUILDINGS]],
      { [BUILDINGS]: "pending", [STREETS]: "pending", [GRID]: "pending" },
    ),
  );
  expect(pillNames()).toEqual(["Load streets", "Make open-ground grid", "Load existing buildings"]);
});

test("a node the plan does not list follows the plan's, in the canvas's order, and one off the canvas comes last", () => {
  renderStrip(
    attachment(
      [["streets", STREETS], ["grid", GRID]],
      {
        [GONE_LAST]: "failed",
        [PARKS]: "solved",
        [GRID]: "pending",
        [TREES]: "solved",
        [GONE_FIRST]: "failed",
        [STREETS]: "pending",
      },
    ),
  );
  expect(pillNames()).toEqual([
    "Load streets",
    "Make open-ground grid",
    "Load street trees",
    "Load parks",
    GONE_FIRST.slice(0, 8),
    GONE_LAST.slice(0, 8),
  ]);
});

test("the Open Dataset Finder buttons of the nodes awaiting a source read in the pills' order", () => {
  renderStrip(
    attachment(
      [["streets", STREETS], ["grid", GRID], ["buildings", BUILDINGS]],
      { [GRID]: "pending", [BUILDINGS]: "pending", [STREETS]: "pending" },
    ),
    {
      // The live batch's remedies, keyed in yet another order.
      solveRemedies: {
        [BUILDINGS]: awaitingSource(BUILDINGS),
        [STREETS]: awaitingSource(STREETS),
        [GRID]: awaitingSource(GRID),
      },
      onOpenChat: jest.fn(),
      agentNameOf: () => "Dataset Finder",
    },
  );
  const plan = ["Load streets", "Make open-ground grid", "Load existing buildings"];
  const group = screen.getByRole("group", { name: "Nodes awaiting a dataset selection" });
  expect(within(group).getAllByRole("button").map((button) => button.getAttribute("aria-label"))).toEqual(
    plan.map((name) => `Open Dataset Finder for ${name}`),
  );
  expect(pillNames()).toEqual(plan);
});
