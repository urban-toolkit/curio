import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";

const mockPlayAllNodes = jest.fn();
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: mockPlayAllNodes }),
}));

import { AgentBuilderStrip, PLAN_ACTIONS } from "../../components/agents/attach/AgentBuilderStrip";
import { planNodeStateFor } from "../../components/agents/attach/chat/chatPanelDerived";
import { AgentChangeCard } from "../../components/agents/content/AgentChangeCard";
import { ROW_WAIT_WORDS } from "../../components/agents/content/reviewCard/reviewCardText";
import type { AgentAttachment, AgentChangePart } from "../../services/agents";

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
    // Said once: no line under the line, in these words or in others. The
    // plan line is its words, its one action and its menu's chevron, and
    // nothing else is said in it.
    expect(screen.getAllByText(/needs a source/)).toHaveLength(1);
    expect(screen.queryByText(PAUSE)).toBeNull();
    const group = screen.getByRole("group", { name: "Dataflow Builder" });
    expect(group.children).toHaveLength(1);
    expect(group).toHaveTextContent(/^Paused · na needs a sourceShow its sources$/);
    expect(within(group).getAllByRole("button").map((b) => b.getAttribute("aria-label") ?? b.textContent)).toEqual([
      "Show its sources",
      PLAN_ACTIONS,
    ]);
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

  it("the row of the loader says the plan card's word, once; the row after it says only that it waits on it", () => {
    // The same agent, its plan of two nodes: the loader a (node na), and b
    // (node nb), which reads from it.
    const agent = pausedOnTheLoader();
    const twoNodes = {
      ...agent,
      builderSession: {
        ...agent.builderSession!,
        nodeRuns: { na: "pending", nb: "pending" },
        nodeStates: { a: "awaiting-source", b: "created" },
        nodeIds: { a: "na", b: "nb" },
      },
      planProposal: { ...agent.planProposal!, appliedRefs: ["a", "b"], nodeIds: { a: "na", b: "nb" } },
    } as AgentAttachment;
    const card = {
      type: "change", changeId: "c-plan", tool: "dataflow.plan.write", kind: "plan", planId: "pp1",
      summary: "Plan · 2 nodes, 1 edges", status: "applied", lines: [],
      plan: {
        goal: "g",
        nodes: [
          { ref: "a", nodeType: "t", title: "Load a", intent: "load it" },
          { ref: "b", nodeType: "t", title: "Count b", intent: "count it" },
        ],
        edgeCount: 1,
        edges: [{ from: "a", to: "b", fromLabel: "Load a", toLabel: "Count b" }],
      },
    } as unknown as AgentChangePart;
    const waiting = [...WAITS_FOR_THE_PICK, { nodeId: "nb", kind: "upstream", reason: "upstream node 'a' has no content yet" }];
    render(
      <>
        <AgentBuilderStrip attachment={twoNodes} onSolve={jest.fn()} onSimulate={jest.fn()} solveWaiting={waiting} onShowSources={jest.fn()} />
        <AgentChangeCard
          part={card}
          planNodeState={planNodeStateFor(twoNodes, card, false, { solveWaiting: waiting })}
          onSolvePlanNode={jest.fn()}
        />
      </>,
    );
    const row = (ref: string) => document.querySelector<HTMLElement>(`[data-curio-plan-row="${ref}"]`)!;
    // The loader's row: the card's one word, no status beside it, no Solve.
    expect(row("a")).toHaveAttribute("data-curio-row-view", "pick");
    expect(within(row("a")).getByText(NEEDS_A_SOURCE)).toBeInTheDocument();
    expect(within(row("a")).queryByText(/pending/)).toBeNull();
    expect(within(row("a")).queryByRole("button", { name: /^Solve node/ })).toBeNull();
    // The node that reads from it says only that it comes after it.
    expect(within(row("b")).getByText("after Load a")).toBeInTheDocument();
    expect(within(row("b")).queryByText(NEEDS_A_SOURCE)).toBeNull();
    expect(within(row("b")).queryByText(/pending|upstream/)).toBeNull();
    // The line says the wait once, in the card's words for the loader.
    expect(words()).toHaveTextContent(/^Paused · na needs a source$/);
    expect(screen.getAllByText(NEEDS_A_SOURCE)).toHaveLength(1);
  });
});
