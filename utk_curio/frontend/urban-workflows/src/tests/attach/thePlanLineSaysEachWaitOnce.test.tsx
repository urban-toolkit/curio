import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";

const mockPlayAllNodes = jest.fn();
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: mockPlayAllNodes }),
}));

import { AgentBuilderStrip, SHOW_PLAN_MORE } from "../../components/agents/attach/AgentBuilderStrip";
import { ROW_STATE_CHIP } from "../../components/agents/content/reviewCard/reviewCardText";
import type { AgentAttachment } from "../../services/agents";

// The owner's PlanOpen board says a paused build's pause once, and gives each
// row of the plan one label: a row that waits for its source reads Needs a
// source, as the plan card's row does, and a row that waits upstream says only
// that.

/** Why the build paused: its loader, node na, waits for the user's pick. */
const PAUSE = "Load a needs a source: pick one on its card in this chat";
const PAUSE_SAID = /Load a needs a source: pick one on its card in this chat/;

/** The plan card's words for a row whose loader waits for its source. */
const NEEDS_A_SOURCE = ROW_STATE_CHIP["awaiting-source"];

/** The Dataflow Builder's attachment, its plan landed (ref a placed as node
 *  na) and its build paused on the loader. */
const pausedOnTheLoader = (): AgentAttachment =>
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
      appliedPlanId: "pp1",
      planProposalId: "pp1",
      nodeRuns: { na: "pending" },
      nodeStates: { a: "awaiting-source" },
      nodeIds: { a: "na" },
      pauseReason: {
        kind: "awaiting-source",
        message: PAUSE,
        nodes: [{ ref: "a", nodeId: "na", attachmentId: "att-df" }],
      },
    },
    planProposal: {
      proposalId: "pp1",
      tool: "dataflow.plan.write",
      nodeId: "",
      summary: "Plan · 1 node, 0 edges",
      status: "applied",
      appliedRefs: ["a"],
      nodeIds: { a: "na" },
    },
  }) as unknown as AgentAttachment;

/** The loader's wait for the user's pick, as the session says it. */
const WAITS_FOR_THE_PICK = [
  {
    nodeId: "na",
    kind: "dataset-selection",
    reason: "awaiting your dataset selection: 1 candidate awaiting your selection",
    attachmentId: "att-df",
  },
];

/** A Dataflow Builder's attachment whose session holds these node runs. */
const withRuns = (nodeRuns: Record<string, string>): AgentAttachment =>
  ({
    ...pausedOnTheLoader(),
    builderSession: { phase: "applied", appliedPlanId: "p1", nodeRuns },
    planProposal: undefined,
  }) as unknown as AgentAttachment;

const openMore = () => fireEvent.click(screen.getByRole("button", { name: SHOW_PLAN_MORE }));

beforeEach(() => jest.clearAllMocks());

describe("The plan line says a paused build's pause once", () => {
  it("under the line, whether its more part is open or not", () => {
    render(
      <AgentBuilderStrip
        attachment={pausedOnTheLoader()}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
        solveWaiting={WAITS_FOR_THE_PICK}
      />,
    );
    // Folded, the line under the plan line says it, as a tab opened after
    // the build paused reads it from the session.
    expect(screen.getAllByText(PAUSE_SAID)).toHaveLength(1);
    // Open, the more part says it no more, in these words or in others.
    openMore();
    expect(screen.getAllByText(PAUSE_SAID)).toHaveLength(1);
    expect(screen.queryByText(/^Waiting for you/)).toBeNull();
    expect(screen.queryByText(/Resume continues from here/)).toBeNull();
  });

  it("once too after this line's own build ended on it", async () => {
    const onSimulate = jest.fn().mockResolvedValue({ status: "paused", reason: { message: PAUSE } });
    render(
      <AgentBuilderStrip
        attachment={pausedOnTheLoader()}
        onSolve={jest.fn()}
        onSimulate={onSimulate}
        solveWaiting={WAITS_FOR_THE_PICK}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(onSimulate).toHaveBeenCalledWith("auto");
    // The build ended on the same pause: the line says it once.
    expect(await screen.findAllByText(PAUSE_SAID)).toHaveLength(1);
    openMore();
    expect(screen.getAllByText(PAUSE_SAID)).toHaveLength(1);
    expect(screen.queryByText(/^Waiting for you/)).toBeNull();
    expect(screen.queryByText(/Resume continues from here/)).toBeNull();
  });
});

describe("Each row of the plan line has one label", () => {
  it("a row that waits for its source reads Needs a source; one that waits upstream says only that", () => {
    expect(NEEDS_A_SOURCE).toBe("Needs a source");
    render(
      <AgentBuilderStrip
        attachment={withRuns({ a: "pending", b: "pending", c: "pending" })}
        onSolve={jest.fn()}
        solveWaiting={[
          { ...WAITS_FOR_THE_PICK[0], nodeId: "a" },
          { nodeId: "b", kind: "upstream", reason: "upstream node 'a' has no content yet" },
        ]}
      />,
    );
    openMore();
    const [a, b, c] = within(screen.getByRole("list", { name: "Plan node progress" })).getAllByRole("listitem");
    // The loader that waits for your pick: the plan card's words, with the
    // wait's reason on them, and no status beside them.
    expect(within(a).getByText(NEEDS_A_SOURCE)).toHaveAttribute(
      "data-tooltip",
      "awaiting your dataset selection: 1 candidate awaiting your selection",
    );
    expect(within(a).queryByText("pending")).toBeNull();
    expect(within(a).queryByText(/needs you/i)).toBeNull();
    // The node that waits upstream says only that.
    expect(within(b).getByText("waiting upstream")).toBeInTheDocument();
    expect(within(b).queryByText("pending")).toBeNull();
    // A node that waits for nothing says its status.
    expect(within(c).getByText("pending")).toBeInTheDocument();
  });
});
