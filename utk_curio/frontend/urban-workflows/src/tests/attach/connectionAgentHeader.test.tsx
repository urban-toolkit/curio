/**
 * A connection agent's chat names the two nodes its connection joins, as a
 * node agent's names its node (#228). The overlay looked a name up for node
 * agents only, so a connection agent's header read "connection" and the edge's
 * id, which tells nobody which connection it is.
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

const EDGE_ID = "reactflow__edge-7f3a2b1c-load-join";

// The canvas as React Flow's store holds it: the two nodes and their connection.
const mockFlowState = {
  nodeInternals: new Map<string, unknown>([
    ["n-load", { id: "n-load", data: { nodeType: "curio.builtin/data-loading", title: "Load buildings" } }],
    ["n-join", { id: "n-join", data: { nodeType: "curio.builtin/python", title: "Join blocks" } }],
  ]),
  edges: [{ id: EDGE_ID, source: "n-load", target: "n-join" }],
};
jest.mock("reactflow", () => ({
  ...jest.requireActual("reactflow"),
  useReactFlow: () => ({ getNodes: () => [], getEdges: () => [] }),
  useStore: (selector: (state: unknown) => unknown) => selector(mockFlowState),
}));
jest.mock("../../components/agents/attach/AgentDock", () => ({ AgentDock: () => null }));
jest.mock("../../components/agents/attach/useAgentCanvasMutations", () => ({
  useAgentCanvasMutations: () => undefined,
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: "p1",
    workflowGoal: "",
    setWorkflowGoal: jest.fn(),
    workflowNameRef: { current: "wf" },
    outputs: {},
    scenarios: [],
    projectDirty: false,
    playAllNodes: jest.fn(),
    nodes: [],
  }),
}));
jest.mock("../../services/packages/packagesApi", () => ({ packagesApi: {} }));
const mockCtx = jest.fn();
jest.mock("../../providers/agents/AgentAttachmentsProvider", () => ({
  useAgentAttachmentsContext: () => mockCtx(),
}));

import { AgentDockOverlay } from "../../components/agents/attach/AgentDockOverlay";

const connectionAgent = {
  attachmentId: "att-conn",
  coord: "agent.curio.researcher@1",
  target: { kind: "connection", targetId: EDGE_ID },
  sessionId: "s-conn-1234",
  revision: 1,
  intent: null,
  intentEdited: false,
  title: null,
  titleEdited: false,
  name: "Researcher",
  category: "canvas",
  hooks: ["connection"],
};

function ctx(attachments: unknown[], selectedId: string | null) {
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

describe("a connection agent's chat header", () => {
  it("names the two nodes the connection joins, and keeps the ids on the tooltip", async () => {
    mockCtx.mockReturnValue(ctx([connectionAgent], "att-conn"));
    render(<AgentDockOverlay />, { wrapper: MemoryRouter });
    // The chat slides in; it is named once it is presented.
    const panel = await waitFor(() => screen.getByRole("dialog", { name: /^Chat with Researcher/ }));
    const header = panel.querySelector<HTMLElement>('[data-curio-chat-header="true"]');
    expect(header).not.toBeNull();
    expect(header).toHaveTextContent("from Load buildings to Join blocks");
    // The ids are for support, on the tooltip, not in the header's words.
    expect(header).not.toHaveTextContent(EDGE_ID);
    const named = Array.from(header!.querySelectorAll<HTMLElement>("[data-tooltip]")).find((el) =>
      (el.textContent ?? "").includes("from Load buildings to Join blocks"),
    );
    expect(named?.getAttribute("data-tooltip") ?? "").toContain(EDGE_ID);
    expect(named?.getAttribute("data-tooltip") ?? "").toContain("session s-conn-1234");
  });
});
