/**
 * The Dataflow Builder's plan line reads the plan's nodes in the plan's own
 * order, the order its change card lists them in. A session's nodeRuns are
 * keyed by node id, and the server's answer sorts those keys, so the order
 * they come in says nothing of the plan. A node the plan does not list, one
 * an earlier plan placed, follows the plan's nodes in the canvas's order, and
 * a node that is no longer on the canvas comes last. With several nodes
 * awaiting a source, Show its sources goes to the first of them in that
 * order, whatever order the live batch's remedies come in.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

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

/** A node awaiting a source: its own Dataset Finder holds the candidates. */
const awaitingSource = (nodeId: string): AgentRemedy => ({
  kind: "dataset-selection",
  attachmentId: `finder-${nodeId}`,
  nodeId,
});

/** Renders the line with *waits*, the nodes the live batch says wait for a
 *  pick, keyed in the order given; returns what Show its sources went to. */
function showSourcesOf(value: AgentAttachment, waits: string[]): string {
  const onShowSources = jest.fn();
  render(
    <AgentBuilderStrip
      attachment={value}
      onSolve={jest.fn()}
      solveRemedies={Object.fromEntries(waits.map((id) => [id, awaitingSource(id)]))}
      onShowSources={onShowSources}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Show its sources" }));
  return onShowSources.mock.calls[0][0];
}

test("Show its sources goes to the plan's first waiting node, whatever order nodeRuns and the remedies come in", () => {
  expect(
    showSourcesOf(
      attachment(
        [["streets", STREETS], ["grid", GRID], ["buildings", BUILDINGS]],
        { [BUILDINGS]: "pending", [STREETS]: "pending", [GRID]: "pending" },
      ),
      [BUILDINGS, STREETS, GRID],
    ),
  ).toBe(STREETS);
});

test("a node the plan does not list follows the plan's, in the canvas's order, and one off the canvas comes last", () => {
  expect(
    showSourcesOf(
      attachment(
        [["streets", STREETS], ["grid", GRID]],
        {
          [GONE_LAST]: "pending",
          [PARKS]: "pending",
          [GRID]: "solved",
          [TREES]: "pending",
          [GONE_FIRST]: "pending",
          [STREETS]: "solved",
        },
      ),
      [GONE_LAST, PARKS, GONE_FIRST, TREES],
    ),
  ).toBe(TREES);
});

test("a node off the canvas comes after every node on it", () => {
  expect(
    showSourcesOf(
      attachment([["streets", STREETS]], { [GONE_LAST]: "pending", [GONE_FIRST]: "pending", [STREETS]: "solved" }),
      [GONE_LAST, GONE_FIRST],
    ),
  ).toBe(GONE_FIRST);
});

test("the line names a waiting node as its header does, and counts several", () => {
  const { unmount } = render(
    <AgentBuilderStrip
      attachment={attachment([["streets", STREETS], ["grid", GRID]], { [STREETS]: "pending", [GRID]: "solved" })}
      onSolve={jest.fn()}
      solveRemedies={{ [STREETS]: awaitingSource(STREETS) }}
      onShowSources={jest.fn()}
    />,
  );
  expect(document.querySelector("[data-curio-plan-words]")).toHaveTextContent(/^Paused · Load streets needs a source$/);
  unmount();
  render(
    <AgentBuilderStrip
      attachment={attachment([["streets", STREETS], ["grid", GRID]], { [STREETS]: "pending", [GRID]: "pending" })}
      onSolve={jest.fn()}
      solveRemedies={{ [STREETS]: awaitingSource(STREETS), [GRID]: awaitingSource(GRID) }}
      onShowSources={jest.fn()}
    />,
  );
  expect(document.querySelector("[data-curio-plan-words]")).toHaveTextContent(/^Paused · 2 nodes need a source$/);
});
