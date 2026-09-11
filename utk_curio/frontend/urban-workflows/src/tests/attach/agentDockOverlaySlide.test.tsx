/**
 * What the dock overlay does with the chat panel's presentation (#295).
 *
 * The panel now stays mounted through its own exit, which creates two states
 * that did not exist while it appeared and vanished instantly:
 *
 * - **The exit renders a selection that is already gone.** Detaching the open
 *   agent empties the roster, so anything read live during the slide - the
 *   attachment itself, its "n of m", the name of what it is attached to -
 *   would blank or repaint as "0 / 0" for the length of the animation.
 * - **Switching agents is a content swap, not a new panel.** The ‹ › arrows
 *   change who is in the panel; they must not slide it out and back in.
 */
import React from "react";
import { render, screen, act } from "@testing-library/react";
import "@testing-library/jest-dom";

// ── the panel, as a probe that records the props it is handed ───────────────
const panelProps: any[] = [];
jest.mock("../../components/agents/attach/AgentChatPanel", () => ({
  AgentChatPanel: (props: any) => {
    panelProps.push(props);
    return (
      <div data-testid="chat-probe">
        <span data-testid="who">{props.attachment.name}</span>
        <span data-testid="pos">{`${props.index} / ${props.total}`}</span>
        <span data-testid="presented">{String(props.presented)}</span>
        <span data-testid="target">{String(props.targetName)}</span>
      </div>
    );
  },
}));

jest.mock("../../components/agents/attach/AgentDock", () => ({
  AgentDock: () => <div data-testid="dock" />,
}));
jest.mock("../../components/agents/attach/useAgentCanvasMutations", () => ({
  useAgentCanvasMutations: () => undefined,
}));
jest.mock("reactflow", () => ({
  useReactFlow: () => ({ getNodes: () => [], getEdges: () => [] }),
  useStore: () => "Node A",
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: "p1",
    workflowGoal: "",
    setWorkflowGoal: jest.fn(),
    workflowNameRef: { current: "wf" },
  }),
}));

const mockCtx = jest.fn();
jest.mock("../../components/agents/attach/AgentAttachmentsProvider", () => ({
  useAgentAttachmentsContext: () => mockCtx(),
}));

import { AgentDockOverlay } from "../../components/agents/attach/AgentDockOverlay";

function attachment(id: string, name: string): any {
  return {
    attachmentId: id,
    coord: "agent.chat-agent@1.0.0",
    target: { kind: "canvas" },
    sessionId: `s-${id}`,
    revision: 1,
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
    name,
    category: "canvas",
    hooks: ["canvas"],
  };
}

function ctx(attachments: any[], selectedId: string | null) {
  return {
    attachments,
    selectedId,
    busy: false,
    error: null,
    reload: jest.fn(),
    attach: jest.fn(),
    detach: jest.fn(),
    run: jest.fn(),
    openChat: jest.fn(),
    closeChat: jest.fn(),
    transcripts: {},
    toolActivity: {},
    runStatus: {},
    hydrateErrors: {},
    solveProgress: {},
    solveErrors: {},
    simulationActivity: {},
    hydratingId: null,
    hydrateSession: jest.fn(),
    sendMessage: jest.fn(),
    saveIntent: jest.fn(),
    saveTitle: jest.fn(),
    clearConversation: jest.fn(),
    applyProposal: jest.fn(),
    dismissProposal: jest.fn(),
    applyPlanNode: jest.fn(),
    savePlanGoal: jest.fn(),
    applyPlanEdges: jest.fn(),
    validateNode: jest.fn(),
    runNode: jest.fn(),
    runSimulation: jest.fn(),
    cancelSimulation: jest.fn(),
    solveAttachment: jest.fn(),
  };
}

async function settleFrames() {
  await act(async () => {
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    await new Promise((r) => setTimeout(r, 0));
  });
}

const A = attachment("a", "Alpha");
const B = attachment("b", "Beta");

beforeEach(() => {
  panelProps.length = 0;
  jest.clearAllMocks();
});

describe("AgentDockOverlay chat presentation", () => {
  it("renders no panel with nothing selected", () => {
    mockCtx.mockReturnValue(ctx([A, B], null));
    render(<AgentDockOverlay />);
    expect(screen.queryByTestId("chat-probe")).toBeNull();
  });

  it("mounts the panel closed, then presents it", async () => {
    mockCtx.mockReturnValue(ctx([A, B], "a"));
    render(<AgentDockOverlay />);
    expect(screen.getByTestId("presented")).toHaveTextContent("false");
    await settleFrames();
    expect(screen.getByTestId("presented")).toHaveTextContent("true");
    expect(screen.getByTestId("who")).toHaveTextContent("Alpha");
    expect(screen.getByTestId("pos")).toHaveTextContent("1 / 2");
  });

  it("keeps the panel mounted, and showing the same agent, through the exit", async () => {
    mockCtx.mockReturnValue(ctx([A, B], "a"));
    const { rerender } = render(<AgentDockOverlay />);
    await settleFrames();

    // The chat closes: selection clears, but the slide has not finished.
    mockCtx.mockReturnValue(ctx([A, B], null));
    await act(async () => { rerender(<AgentDockOverlay />); });

    expect(screen.getByTestId("chat-probe")).toBeInTheDocument();
    expect(screen.getByTestId("presented")).toHaveTextContent("false");
    expect(screen.getByTestId("who")).toHaveTextContent("Alpha");
  });

  it("pins n-of-m so detaching the open agent cannot repaint it as 0 / 0", async () => {
    mockCtx.mockReturnValue(ctx([A], "a"));
    const { rerender } = render(<AgentDockOverlay />);
    await settleFrames();
    expect(screen.getByTestId("pos")).toHaveTextContent("1 / 1");

    // Detach: the roster empties AND the selection clears, in one update.
    mockCtx.mockReturnValue(ctx([], null));
    await act(async () => { rerender(<AgentDockOverlay />); });

    expect(screen.getByTestId("who")).toHaveTextContent("Alpha");
    expect(screen.getByTestId("pos")).toHaveTextContent("1 / 1");
  });

  it("pins the attachment target name through the exit too", async () => {
    mockCtx.mockReturnValue(ctx([A], "a"));
    const { rerender } = render(<AgentDockOverlay />);
    await settleFrames();
    const named = screen.getByTestId("target").textContent;

    mockCtx.mockReturnValue(ctx([], null));
    await act(async () => { rerender(<AgentDockOverlay />); });
    expect(screen.getByTestId("target")).toHaveTextContent(String(named));
  });

  it("swaps content without re-sliding when cycling to another agent", async () => {
    mockCtx.mockReturnValue(ctx([A, B], "a"));
    const { rerender } = render(<AgentDockOverlay />);
    await settleFrames();

    const before = panelProps.length;
    mockCtx.mockReturnValue(ctx([A, B], "b"));
    await act(async () => { rerender(<AgentDockOverlay />); });
    await settleFrames();

    expect(screen.getByTestId("who")).toHaveTextContent("Beta");
    expect(screen.getByTestId("pos")).toHaveTextContent("2 / 2");
    // The claim: the panel never left its resting transform. A single
    // `presented: false` across the swap would be a visible slide out and back
    // in for what is only a change of contents.
    const during = panelProps.slice(before);
    expect(during.length).toBeGreaterThan(0);
    expect(during.every((p) => p.presented === true)).toBe(true);
  });

  it("unmounts once the panel reports its exit finished", async () => {
    mockCtx.mockReturnValue(ctx([A], "a"));
    const { rerender } = render(<AgentDockOverlay />);
    await settleFrames();

    mockCtx.mockReturnValue(ctx([A], null));
    await act(async () => { rerender(<AgentDockOverlay />); });
    expect(screen.getByTestId("chat-probe")).toBeInTheDocument();

    const latest = panelProps[panelProps.length - 1];
    await act(async () => { latest.onExitComplete(); });
    expect(screen.queryByTestId("chat-probe")).toBeNull();
  });
});
