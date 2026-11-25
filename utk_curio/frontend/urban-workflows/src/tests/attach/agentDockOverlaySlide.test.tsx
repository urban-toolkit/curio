/**
 * What the dock overlay does with the chat panel's presentation (#295).
 *
 * The panel now stays mounted through its own exit, which creates two states
 * that did not exist while it appeared and vanished instantly:
 *
 * - **The exit renders a selection that is already gone.** Detaching the open
 *   agent empties the roster, so anything read live during the slide - the
 *   attachment itself, the rail's agents, the name of what it is attached to -
 *   would blank or empty for the length of the animation.
 * - **Switching agents is a content swap, not a new panel.** The rail changes
 *   who is in the panel; it must not slide it out and back in.
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
        <span data-testid="rail">{(props.attachments ?? []).map((a: any) => a.name).join(", ")}</span>
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
// The canvas as React Flow's store holds it: one node, "Node A".
const mockFlowState = {
  nodeInternals: new Map([["node-a", { id: "node-a", data: { nodeType: "curio.builtin/python", title: "Node A" } }]]),
  edges: [],
};
jest.mock("reactflow", () => ({
  ...jest.requireActual("reactflow"),
  useReactFlow: () => ({ getNodes: () => [], getEdges: () => [] }),
  useStore: (selector: (state: unknown) => unknown) => selector(mockFlowState),
}));
let mockWorkflowGoal = "";
const mockSetWorkflowGoal = jest.fn();
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: "p1",
    workflowGoal: mockWorkflowGoal,
    setWorkflowGoal: mockSetWorkflowGoal,
    workflowNameRef: { current: "wf" },
  }),
}));

const mockCtx = jest.fn();
jest.mock("../../providers/agents/AgentAttachmentsProvider", () => ({
  useAgentAttachmentsContext: () => mockCtx(),
}));

import { AgentDockOverlay } from "../../components/agents/attach/AgentDockOverlay";

function attachment(id: string, name: string): any {
  return {
    attachmentId: id,
    coord: "agent.curio.researcher@1",
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
    waitingAsks: {},
    stopTurn: jest.fn(),
    withdrawAsk: jest.fn(),
    hydrateErrors: {},
    solveProgress: {},
    solveErrors: {},
    simulationActivity: {},
    simulating: {},
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
    // The Solve lane and the Dataset Finder rows the overlay also reads: the
    // real context always supplies them, so the double must too.
    solveRemedies: {},
    solveWaiting: {},
    solveEndedBy: {},
    solvePass: {},
    solveWave: {},
    solveNotices: {},
    solveNodeActivity: {},
    solveNode: jest.fn(),
    cancelSolve: jest.fn(),
    recordDatasetSelection: jest.fn(),
    importDataset: jest.fn(),
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
// An agent on the store's node, whose chat names it.
const N = { ...attachment("n", "Node Builder"), target: { kind: "node", targetId: "node-a" } };

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
    expect(screen.getByTestId("rail")).toHaveTextContent("Alpha, Beta");
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

  it("pins the rail so detaching the open agent cannot empty it mid-slide", async () => {
    mockCtx.mockReturnValue(ctx([A], "a"));
    const { rerender } = render(<AgentDockOverlay />);
    await settleFrames();
    expect(screen.getByTestId("rail")).toHaveTextContent("Alpha");

    // Detach: the roster empties AND the selection clears, in one update.
    mockCtx.mockReturnValue(ctx([], null));
    await act(async () => { rerender(<AgentDockOverlay />); });

    expect(screen.getByTestId("who")).toHaveTextContent("Alpha");
    expect(screen.getByTestId("rail")).toHaveTextContent("Alpha");
    const latest = panelProps[panelProps.length - 1];
    expect(latest.attachments.map((a: any) => a.attachmentId)).toEqual(["a"]);
  });

  it("pins the attachment target name through the exit too", async () => {
    mockCtx.mockReturnValue(ctx([N], "n"));
    const { rerender } = render(<AgentDockOverlay />);
    await settleFrames();
    expect(screen.getByTestId("target")).toHaveTextContent("Node A");

    mockCtx.mockReturnValue(ctx([], null));
    await act(async () => { rerender(<AgentDockOverlay />); });
    expect(screen.getByTestId("target")).toHaveTextContent("Node A");
    const latest = panelProps[panelProps.length - 1];
    expect(latest.targetNameOf(N)).toBe("Node A");
  });

  it("swaps content without re-sliding when the rail opens another agent", async () => {
    const context = ctx([A, B], "a");
    mockCtx.mockReturnValue(context);
    const { rerender } = render(<AgentDockOverlay />);
    await settleFrames();
    // The rail opens a chat through the provider's own openChat.
    expect(panelProps[panelProps.length - 1].onOpenAgentChat).toBe(context.openChat);

    const before = panelProps.length;
    mockCtx.mockReturnValue(ctx([A, B], "b"));
    await act(async () => { rerender(<AgentDockOverlay />); });
    await settleFrames();

    expect(screen.getByTestId("who")).toHaveTextContent("Beta");
    expect(screen.getByTestId("rail")).toHaveTextContent("Alpha, Beta");
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

// The chat's labels that open another agent's chat name it from the live list,
// so a user's own copies of the shipped cards read under their own names.
describe("AgentDockOverlay names the dataflow's agents for the chat", () => {
  it("hands the panel each attachment's name as the live list has it", () => {
    const myBuilder = attachment("att-my-builder", "My Builder");
    const myFinder = attachment("att-my-finder", "My Finder");
    mockCtx.mockReturnValue(ctx([myBuilder, myFinder], "att-my-builder"));
    render(<AgentDockOverlay />);
    const latest = panelProps[panelProps.length - 1];
    expect(latest.agentNameOf("att-my-finder")).toBe("My Finder");
    expect(latest.agentNameOf("att-my-builder")).toBe("My Builder");
    // An attachment the dataflow no longer holds has no name to show.
    expect(latest.agentNameOf("att-detached")).toBeNull();
  });
});

// The dataflow's goal is the Goal line of every agent's chat (#227: in the
// dock, among the agents' chips, it read as a chat box).
describe("AgentDockOverlay hands the chat the dataflow's goal", () => {
  afterEach(() => {
    mockWorkflowGoal = "";
  });

  it("gives every agent's chat the flow's goal, and keeps an edit as the flow's goal", () => {
    mockWorkflowGoal = "Find heat islands in Chicago";
    const nodeAgent = { ...attachment("n", "Node Builder"), target: { kind: "node", targetId: "node-1" } };
    mockCtx.mockReturnValue(ctx([A, nodeAgent], "n"));
    render(<AgentDockOverlay />);
    const latest = panelProps[panelProps.length - 1];
    expect(latest.attachment.attachmentId).toBe("n");
    expect(latest.goal).toBe("Find heat islands in Chicago");
    latest.onSaveGoal("Rank the blocks by exposure");
    expect(mockSetWorkflowGoal).toHaveBeenCalledWith("Rank the blocks by exposure");
  });
});

// A plan row's Solve (validate-node) and Run (run-node) wait while what the
// node reads downloads on its first use. Each streams how far that has come
// (`node_download`, an empty message once it is over), and the dock hands the
// row's run a listener that gives the row each line, as a node's Solve
// narrates it on its own line.
describe("AgentDockOverlay: a plan row's Solve and Run say how far a download has come", () => {
  const MESSAGE = "Downloading model.safetensors, a file of the weights of model.curio.sam3: 1.21 of 3.44 GB (35%)";

  it.each([
    ["onSolvePlanNode", "validateNode"],
    ["onRunPlanNode", "runNode"],
  ])("%s hands %s a listener whose download events reach the row's line", async (prop, call) => {
    const context = ctx([A], "a");
    mockCtx.mockReturnValue(context);
    render(<AgentDockOverlay />);
    const latest = panelProps[panelProps.length - 1];
    const lines: string[] = [];

    await act(async () => { await latest[prop]("load", (line: string) => lines.push(line)); });

    const asked = (context as any)[call] as jest.Mock;
    expect(asked).toHaveBeenCalledWith("a", { ref: "load" }, expect.any(Function));
    const onEvent = asked.mock.calls[0][2];
    act(() => {
      onEvent("node_executed", { nodeId: "n1", index: 0, total: 1 });
      onEvent("node_download", { nodeId: "n1", message: MESSAGE, done: 1210000000, total: 3440000000 });
      onEvent("node_download", { nodeId: "n1", message: "" });
    });
    expect(lines).toEqual([MESSAGE, ""]);
  });
});
