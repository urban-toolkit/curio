import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";

const mockPlayAllNodes = jest.fn();
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: mockPlayAllNodes }),
}));

import { AgentBuilderStrip } from "../../components/agents/attach/AgentBuilderStrip";
import { ROW_WAIT_WORDS } from "../../components/agents/content/reviewCard/reviewCardText";
import type { AgentAttachment } from "../../services/agents";

// The owner's boards say a paused build's pause once, on the plan line, which
// names its node; each row of the plan card has one label (AgentChangeCard's
// "a landed plan's rows" cases).
// While the pause waits for the person's pick, the line goes to the card: the
// pick goes on by itself, so Resume adds nothing there.

/** Why the build paused: its loader, node na, waits for the user's pick. */
const PAUSE = "Load a needs a source: pick one on its card in this chat";

/** The plan card's words for a row whose loader waits for its source. */
const NEEDS_A_SOURCE = ROW_WAIT_WORDS["awaiting-source"];

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

/** The line's words, while nothing runs. */
const words = () => document.querySelector<HTMLElement>("[data-curio-plan-words]");

beforeEach(() => jest.clearAllMocks());

describe("The plan line says a paused build's pause once", () => {
  it("on the line, which names its node, with the server's words on its tooltip", () => {
    render(
      <AgentBuilderStrip
        attachment={pausedOnTheLoader()}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
        solveWaiting={WAITS_FOR_THE_PICK}
        onShowSources={jest.fn()}
      />,
    );
    expect(words()).toHaveTextContent(/^Paused · na needs a source$/);
    expect(words()).toHaveAttribute("data-tooltip", PAUSE);
    // Said once: no line under the line, in these words or in others.
    expect(screen.getAllByText(/needs a source/)).toHaveLength(1);
    expect(screen.queryByText(PAUSE)).toBeNull();
    expect(screen.queryByText(/^Waiting for you/)).toBeNull();
    expect(screen.queryByText(/needs you/)).toBeNull();
    expect(screen.queryByText(/Resume continues from here/)).toBeNull();
  });

  it("goes to the card, not Resume, while the pause waits for the pick, which goes on by itself", () => {
    const onShowSources = jest.fn();
    const onSimulate = jest.fn();
    render(
      <AgentBuilderStrip
        attachment={pausedOnTheLoader()}
        onSolve={jest.fn()}
        onSimulate={onSimulate}
        solveWaiting={WAITS_FOR_THE_PICK}
        onShowSources={onShowSources}
      />,
    );
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show its sources" }));
    expect(onShowSources).toHaveBeenCalledWith("na");
    expect(onSimulate).not.toHaveBeenCalled();
    // The line says the pause once still.
    expect(screen.getAllByText(/needs a source/)).toHaveLength(1);
  });

  it("the row's word and the line's are the plan card's", () => {
    expect(NEEDS_A_SOURCE).toBe("Needs a source");
  });
});
