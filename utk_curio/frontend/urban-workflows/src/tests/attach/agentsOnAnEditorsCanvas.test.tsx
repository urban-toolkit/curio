/**
 * An invited editor drives the dataflow's agents (`agentsOnCanvas`), so their
 * canvas lists the dataflow's attachments, as the owner's does. An editor's
 * tab saves no dataflow: on another account's dataflow, opened from its link,
 * the flow state's `projectId` is null (`loadSharedProject`). The agents work
 * on the dataflow the route opened (`projectPackagesStore`), which the room
 * joins too. A watcher's canvas, and an editor's before the room names them,
 * list none.
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

let mockFlow: { projectId: string | null; viewerMode: "owner" | "shared" };
let mockCollab: { role: string | null };
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => mockFlow,
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => mockCollab,
}));
jest.mock("../../services/packages/packagesApi", () => ({ packagesApi: {} }));
jest.mock("../../services/agents/agentsApi", () => ({
  agentsApi: {
    listAttachments: jest.fn(),
    attach: jest.fn(),
    detachAttachment: jest.fn(),
    runAttachment: jest.fn(),
    runAttachmentStream: jest.fn(),
    updateAttachmentIntent: jest.fn(),
    updateAttachmentTitle: jest.fn(),
    getSession: jest.fn(),
    clearSession: jest.fn(),
    applyProposal: jest.fn(),
    dismissProposal: jest.fn(),
    solveAttachmentStream: jest.fn(),
    solveNodeStream: jest.fn(),
    attachJobStream: jest.fn(),
    cancelSolve: jest.fn(),
    applyPlanNode: jest.fn(),
    savePlanGoal: jest.fn(),
    applyPlanEdges: jest.fn(),
    runNode: jest.fn(),
    simulate: jest.fn(),
    cancelSimulate: jest.fn(),
  },
}));

import { agentsApi } from "../../services/agents";
import { AgentAttachmentsProvider, useAgentAttachmentsContext } from "../../providers/agents";
import { clearCurrentProject, setCurrentProject } from "../../registry/projectPackagesStore";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

const builder = {
  attachmentId: "a1",
  coord: "agent.curio.dataflow-builder@1",
  target: { kind: "canvas" as const },
  sessionId: "s1",
  revision: 1,
  name: "Dataflow Builder",
  category: "dataflow",
  hooks: ["canvas"],
  intent: null,
  intentEdited: false,
  title: null,
  titleEdited: false,
};

/** The canvas's agents, as the dock reads them. */
const Agents: React.FC = () => {
  const ctx = useAgentAttachmentsContext();
  return <div data-testid="agents">{ctx?.attachments.map((a) => a.name).join(",") || "none"}</div>;
};

function canvas() {
  return render(
    <AgentAttachmentsProvider>
      <Agents />
    </AgentAttachmentsProvider>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  api.listAttachments.mockResolvedValue({ attachments: [builder] } as never);
});

afterEach(() => {
  clearCurrentProject();
});

describe("the dataflow whose agents a canvas drives", () => {
  it("an invited editor's canvas lists the agents of the dataflow its link opened", async () => {
    setCurrentProject("p-shared", []);
    mockFlow = { projectId: null, viewerMode: "shared" };
    mockCollab = { role: "editor" };
    canvas();

    await waitFor(() => expect(api.listAttachments).toHaveBeenCalledWith("p-shared"));
    expect(await screen.findByText("Dataflow Builder")).toBeInTheDocument();
  });

  it("the owner's canvas lists those of the dataflow it saves", async () => {
    setCurrentProject("p-own", []);
    mockFlow = { projectId: "p-own", viewerMode: "owner" };
    mockCollab = { role: "owner" };
    canvas();

    await waitFor(() => expect(api.listAttachments).toHaveBeenCalledWith("p-own"));
    expect(await screen.findByText("Dataflow Builder")).toBeInTheDocument();
  });

  it("a watcher's canvas, and an editor's before the room names them, list none", async () => {
    setCurrentProject("p-shared", []);
    mockFlow = { projectId: null, viewerMode: "shared" };
    for (const role of ["watcher", null]) {
      mockCollab = { role };
      const { unmount } = canvas();
      await screen.findByText("none");
      unmount();
    }
    expect(api.listAttachments).not.toHaveBeenCalled();
  });
});
