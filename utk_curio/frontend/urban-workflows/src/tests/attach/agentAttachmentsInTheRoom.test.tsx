/**
 * The agents attached to a dataflow are kept beside its doc, so no change of
 * the doc tells a tab of them. The room does: when someone attaches an agent
 * to the dataflow, takes one off or changes one, such as its chat's title,
 * the server tells the tabs of its owner and editors
 * (`agent_attachments_changed`), and each lists the agents again at once,
 * with no click on its canvas. What the room tells of another dataflow lists
 * nothing here. A tab back in the room after a time away lists them again,
 * as it may have missed what the room told meanwhile.
 *
 * The room is the real `CollaborationProvider` on a fake socket, so the event
 * reaches the dock only if the provider hands it on.
 */
import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";

const mockIo = jest.fn();
jest.mock("socket.io-client", () => ({
  io: (...args: unknown[]) => mockIo(...args),
}));
jest.mock("../../utils/backendUrl", () => ({
  backendUrl: () => "http://localhost:5002",
}));
jest.mock("../../utils/authApi", () => ({
  getToken: () => "tok",
  authApi: {
    getPublicConfig: () => Promise.resolve({ collab_namespace: "/collab" }),
    getMe: () => Promise.resolve({ id: 7, username: "ana" }),
  },
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: "p1", viewerMode: "owner" }),
}));
jest.mock("../../services/packages/packagesApi", () => ({ packagesApi: {} }));
jest.mock("../../services/agents/agentsApi", () => ({
  agentsApi: {
    listAttachments: jest.fn(),
    getSession: jest.fn(),
    askTurn: jest.fn(),
    followTurn: jest.fn(),
    stopTurn: jest.fn(),
    withdrawTurn: jest.fn(),
    runAttachmentStream: jest.fn(),
    runAttachment: jest.fn(),
    attach: jest.fn(),
    detachAttachment: jest.fn(),
    updateAttachmentIntent: jest.fn(),
    updateAttachmentTitle: jest.fn(),
    clearSession: jest.fn(),
    applyProposal: jest.fn(),
    dismissProposal: jest.fn(),
    solveAttachmentStream: jest.fn(),
    solveNodeStream: jest.fn(),
    attachJobStream: jest.fn(),
    cancelSolve: jest.fn(),
    undoChange: jest.fn(),
    runNode: jest.fn(),
    validateNode: jest.fn(),
    simulate: jest.fn(),
    cancelSimulate: jest.fn(),
  },
}));

import { agentsApi } from "../../services/agents";
import { AgentAttachmentsProvider, useAgentAttachmentsContext } from "../../providers/agents";
import { CollaborationProvider } from "../../providers/CollaborationProvider";
import { clearCurrentProject, setCurrentProject } from "../../registry/projectPackagesStore";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

/** What the server tells the room when an agent is attached or taken off. */
const ATTACHMENTS_CHANGED = "agent_attachments_changed";

function attachment(attachmentId: string, name: string) {
  return {
    attachmentId,
    coord: "agent.curio.node-builder@1",
    target: { kind: "canvas" as const },
    sessionId: `s-${attachmentId}`,
    revision: 1,
    name,
    category: "node",
    hooks: ["node"],
    intent: "prompt text",
    intentEdited: false,
    title: null,
    titleEdited: false,
  };
}

const ANAS = attachment("a1", "Node Builder");
const BENS = attachment("a2", "Dataset Finder");

type Handler = (payload?: any) => void;
interface FakeSocket {
  handlers: Record<string, Handler[]>;
  emits: Array<{ event: string; payload: any; ack?: (answer: any) => void }>;
}
let sockets: FakeSocket[] = [];

function fakeSocket(): FakeSocket & Record<string, unknown> {
  const fake: any = {
    handlers: {},
    emits: [],
    connected: true,
    on(event: string, handler: Handler) {
      fake.handlers[event] = fake.handlers[event] || [];
      fake.handlers[event].push(handler);
    },
    off(event: string, handler: Handler) {
      fake.handlers[event] = (fake.handlers[event] || []).filter((h: Handler) => h !== handler);
    },
    emit(event: string, payload: any, ack?: (answer: any) => void) {
      fake.emits.push({ event, payload, ack });
    },
    removeAllListeners: jest.fn(),
    disconnect: jest.fn(),
  };
  return fake;
}

/** The server sends *event* to this tab's socket. */
function fire(socket: FakeSocket, event: string, payload?: any) {
  act(() => {
    for (const handler of socket.handlers[event] ?? []) handler(payload);
  });
}

/** The room answers the tab's last join, naming it *participantId*. */
function joined(socket: FakeSocket, participantId: string) {
  const joins = socket.emits.filter((e) => e.event === "join_session");
  expect(joins.length).toBeGreaterThan(0);
  const users = [{ user_id: 7, username: "ana", participant_id: participantId, role: "owner" }];
  act(() => joins[joins.length - 1].ack!({
    ok: true, participant_id: participantId, role: "owner", snapshot: { users, locks: {}, activity: [] },
  }));
}

async function settle() {
  for (let i = 0; i < 5; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

/** The agents this tab's dock shows, by name, with their chat's title. */
const Dock: React.FC = () => {
  const ctx = useAgentAttachmentsContext();
  const shown = (ctx?.attachments ?? []).map((a) => (a.title ? `${a.name}: ${a.title}` : a.name));
  return <div data-testid="dock">{shown.join("|")}</div>;
};

/** Ana's tab on dataflow p1, in its room, its dock listed once. */
async function anasTabInTheRoom(): Promise<FakeSocket> {
  render(
    <CollaborationProvider>
      <AgentAttachmentsProvider>
        <Dock />
      </AgentAttachmentsProvider>
    </CollaborationProvider>,
  );
  await waitFor(() => expect(sockets).toHaveLength(1));
  const socket = sockets[0];
  fire(socket, "connect");
  joined(socket, "p-1");
  await waitFor(() => expect(screen.getByTestId("dock")).toHaveTextContent("Node Builder"));
  await settle();
  return socket;
}

beforeEach(() => {
  jest.clearAllMocks();
  sockets = [];
  mockIo.mockReset();
  mockIo.mockImplementation(() => {
    const socket = fakeSocket();
    sockets.push(socket);
    return socket;
  });
  setCurrentProject("p1", []);
  api.listAttachments.mockResolvedValue({ attachments: [ANAS] } as never);
});

afterEach(() => {
  clearCurrentProject();
});

test("an agent someone else attaches or takes off shows in this tab's dock at once, with no click", async () => {
  const socket = await anasTabInTheRoom();
  const listed = api.listAttachments.mock.calls.length;

  // Ben attaches the Dataset Finder on his tab, and the server tells the room.
  api.listAttachments.mockResolvedValue({ attachments: [ANAS, BENS] } as never);
  fire(socket, ATTACHMENTS_CHANGED, { projectId: "p1" });
  await waitFor(() => expect(screen.getByTestId("dock")).toHaveTextContent("Node Builder|Dataset Finder"));
  expect(api.listAttachments).toHaveBeenCalledTimes(listed + 1);
  expect(api.listAttachments).toHaveBeenLastCalledWith("p1");

  // What the room tells of another dataflow lists nothing here.
  fire(socket, ATTACHMENTS_CHANGED, { projectId: "p2" });
  await settle();
  expect(api.listAttachments).toHaveBeenCalledTimes(listed + 1);

  // Ben takes his agent off again.
  api.listAttachments.mockResolvedValue({ attachments: [ANAS] } as never);
  fire(socket, ATTACHMENTS_CHANGED, { projectId: "p1" });
  await waitFor(() => expect(screen.getByTestId("dock").textContent).toBe("Node Builder"));
  expect(api.listAttachments).toHaveBeenCalledTimes(listed + 2);
});

test("a new title Ben gives his agent's chat shows in this tab's dock at once, with no click", async () => {
  api.listAttachments.mockResolvedValue({ attachments: [ANAS, BENS] } as never);
  const socket = await anasTabInTheRoom();
  expect(screen.getByTestId("dock").textContent).toBe("Node Builder|Dataset Finder");
  const listed = api.listAttachments.mock.calls.length;

  // Ben renames his agent's chat on his tab, and the server tells the room.
  const renamed = { ...BENS, title: "Parks by the river", titleEdited: true };
  api.listAttachments.mockResolvedValue({ attachments: [ANAS, renamed] } as never);
  fire(socket, ATTACHMENTS_CHANGED, { projectId: "p1" });
  await waitFor(() => expect(screen.getByTestId("dock")).toHaveTextContent("Dataset Finder: Parks by the river"));
  expect(api.listAttachments).toHaveBeenCalledTimes(listed + 1);
});

test("a tab back in the room after a time away lists the agents again", async () => {
  const socket = await anasTabInTheRoom();
  const listed = api.listAttachments.mock.calls.length;

  // Away from the room, the tab hears nothing of Ben's agent.
  fire(socket, "disconnect");
  api.listAttachments.mockResolvedValue({ attachments: [ANAS, BENS] } as never);
  await settle();
  expect(api.listAttachments).toHaveBeenCalledTimes(listed);

  fire(socket, "connect");
  joined(socket, "p-2");
  await waitFor(() => expect(screen.getByTestId("dock")).toHaveTextContent("Node Builder|Dataset Finder"));
  expect(api.listAttachments).toHaveBeenCalledTimes(listed + 1);
});
