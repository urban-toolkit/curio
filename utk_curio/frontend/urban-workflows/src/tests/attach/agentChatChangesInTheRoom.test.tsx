/**
 * The server writes into an agent's chat outside any ask: a pick's Source
 * recorded turn, a Solve's or a build's turns, the task one agent hands
 * another, an Undo's card, a cleared chat. It tells the tabs of the
 * dataflow's owner and editors which chat changed (`agent_chat_changed`,
 * `turn_jobs.py`), and each tab that read that chat reads it again: the open
 * chat at once, one it read before when it opens again. A read is the chat
 * whole, so no turn shows twice, the turns of this tab's own ask among them.
 * While a chat the tab already shows is read again, its turns stay on screen,
 * with no "Loading conversation" in their place. What the room tells of
 * another dataflow reads nothing here.
 *
 * The room is the real `CollaborationProvider` on a fake socket, so the word
 * reaches the chat only if the provider hands it on.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

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
import type { AgentAskView, AgentSessionTurn } from "../../services/agents/types";
import { AgentAttachmentsProvider, useAgentAttachmentsContext } from "../../providers/agents";
import { CollaborationProvider } from "../../providers/CollaborationProvider";
import { clearCurrentProject, setCurrentProject } from "../../registry/projectPackagesStore";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

/** What the server tells the room when it changed one of the dataflow's chats. */
const CHAT_CHANGED = "agent_chat_changed";

const ANA = { kind: "person" as const, account: "7", name: "Ana" };

function attachment(attachmentId: string, coord: string, name: string, target: Record<string, unknown>) {
  return {
    attachmentId,
    coord,
    target,
    sessionId: `s-${attachmentId}`,
    revision: 1,
    name,
    category: "data",
    hooks: [],
    intent: null,
    intentEdited: false,
    title: `${name}'s chat`,
    titleEdited: true,
  };
}

const BUILDER = attachment("a1", "agent.curio.dataflow-builder@1", "Dataflow Builder", { kind: "canvas" });
const FINDER = attachment("a2", "agent.curio.dataset-finder@1", "Dataset Finder", {
  kind: "node",
  targetId: "loader",
});

const ASKED = "Load the locations of the Chicago Public Library branches and map them.";
const PAUSED = "CPL branches needs a source. Its Dataset Finder found 4 candidates: pick one with Use this source.";
const TASK = "[Delegated by Dataflow Builder] Find sources for CPL branches.";
const FOUND = "I found 4 candidates for CPL branches. Pick one with Use this source.";
const RECORDED =
  "Source recorded for CPL branches: Chicago Neighborhoods. " +
  "The Dataflow Builder goes on with its plan and builds the loader from this source.";
const SOLVED = "Solved 'CPL branches': PASS after 9 rounds: the trace and the change live in the node's Node Builder.";
const SOLVED_TOO = "Solved 'Branch points': PASS after 1 round: the trace and the change live in the node's Node Builder.";

/** Each chat as the server holds it, which a read of the chat answers. */
let server: Record<string, { turns: AgentSessionTurn[]; asks: AgentAskView[] }> = {};

const said = (role: "user" | "agent", text: string): AgentSessionTurn => ({ role, text });
const shown = (turns: AgentSessionTurn[]) => turns.map((t) => `${t.role}:${t.text}`).join("|");

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

/** The server tells the room it changed the chat of *attachmentId*. */
function chatChanged(socket: FakeSocket, attachmentId: string, projectId = "p1") {
  fire(socket, CHAT_CHANGED, { projectId, attachmentId });
}

/** The room tells this tab one event of an ask on the Dataflow Builder's chat. */
function turnEvent(socket: FakeSocket, askId: string, seq: number, event: string, data: Record<string, unknown>) {
  fire(socket, "agent_turn", { projectId: "p1", attachmentId: "a1", askId, seq, event, data });
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

/** What the chat panel shows in place of the turns while it reads its chat. */
const LOADING = "Loading conversation";

/** The chat this tab shows, as its panel shows it (`AgentChatPanel`'s
 * `loadingHistory`), and the rail that opens one. */
const Chat: React.FC = () => {
  const ctx = useAgentAttachmentsContext();
  if (!ctx) return null;
  const open = ctx.selectedId;
  const shownTurns = !open ? "" : ctx.hydratingId === open ? LOADING : shown(ctx.transcripts[open] ?? []);
  return (
    <div>
      <button onClick={() => ctx.openChat("a1")}>Dataflow Builder</button>
      <button onClick={() => ctx.openChat("a2")}>Dataset Finder</button>
      <button onClick={() => ctx.closeChat()}>Close</button>
      <button onClick={() => void ctx.sendMessage("a1", "Build it.")}>Send</button>
      <div data-testid="open">{open ?? "none"}</div>
      <div data-testid="turns">{shownTurns}</div>
      <div data-testid="run-status">{ctx.runStatus["a1"]?.phase ?? "none"}</div>
    </div>
  );
};

const turns = () => screen.getByTestId("turns").textContent;

/** Ana's tab on dataflow p1, in its room, its agents listed once. */
async function anasTabInTheRoom(): Promise<FakeSocket> {
  render(
    <CollaborationProvider>
      <AgentAttachmentsProvider>
        <Chat />
      </AgentAttachmentsProvider>
    </CollaborationProvider>,
  );
  await waitFor(() => expect(sockets).toHaveLength(1));
  const socket = sockets[0];
  fire(socket, "connect");
  joined(socket, "p-1");
  await waitFor(() => expect(api.listAttachments).toHaveBeenCalled());
  await settle();
  return socket;
}

/** Ana opens the chat of *name* from the rail, and it shows *expected*. */
async function opens(name: string, attachmentId: string, expected: string) {
  fireEvent.click(screen.getByText(name));
  await waitFor(() => expect(screen.getByTestId("open").textContent).toBe(attachmentId));
  await waitFor(() => expect(turns()).toBe(expected));
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
  server = {
    a1: { turns: [said("user", ASKED), said("agent", PAUSED)], asks: [] },
    a2: { turns: [said("user", TASK), said("agent", FOUND)], asks: [] },
  };
  api.listAttachments.mockResolvedValue({ attachments: [BUILDER, FINDER] } as never);
  api.getSession.mockImplementation(async (_projectId: string, attachmentId: string) => ({
    attachmentId,
    sessionId: `s-${attachmentId}`,
    turns: [...(server[attachmentId]?.turns ?? [])],
    asks: [...(server[attachmentId]?.asks ?? [])],
  }) as never);
  api.askTurn.mockImplementation(async (_p, attachmentId, askId) => ({ askId, attachmentId, state: "running" }));
});

afterEach(() => {
  clearCurrentProject();
});

test("an open chat shows each turn the server appends to it, once, with no reload", async () => {
  const socket = await anasTabInTheRoom();
  const before = `user:${ASKED}|agent:${PAUSED}`;
  await opens("Dataflow Builder", "a1", before);

  // Ben picks the loader's source in his tab: the server says it in this
  // chat, then the Builder goes on and says it solved the loader, and the
  // room is told each time. The chat's turns stay on screen while it is read.
  server.a1.turns.push(said("agent", RECORDED));
  chatChanged(socket, "a1");
  expect(turns()).toBe(before);
  server.a1.turns.push(said("agent", SOLVED));
  chatChanged(socket, "a1");
  expect(turns()).toBe(before);

  const after = `${before}|agent:${RECORDED}|agent:${SOLVED}`;
  await waitFor(() => expect(turns()).toBe(after));
  await settle();
  expect(turns()).toBe(after);

  // What the room tells of another dataflow reads nothing here.
  const reads = api.getSession.mock.calls.length;
  chatChanged(socket, "a1", "p2");
  await settle();
  expect(api.getSession).toHaveBeenCalledTimes(reads);
});

test("a chat read before shows the turns the server appended while it was not open, when it opens again", async () => {
  const socket = await anasTabInTheRoom();
  const finder = `user:${TASK}|agent:${FOUND}`;
  await opens("Dataset Finder", "a2", finder);
  // The rail moves Ana to the Builder's chat.
  await opens("Dataflow Builder", "a1", `user:${ASKED}|agent:${PAUSED}`);

  // Ben's pick says the source is recorded in the Finder's chat too.
  server.a2.turns.push(said("agent", RECORDED));
  chatChanged(socket, "a2");
  await settle();

  // Ana opens the Finder's chat again from the rail: its turns show while it
  // is read, then the one the server appended.
  fireEvent.click(screen.getByText("Dataset Finder"));
  expect(screen.getByTestId("open").textContent).toBe("a2");
  expect(turns()).toBe(finder);
  await waitFor(() => expect(turns()).toBe(`${finder}|agent:${RECORDED}`));

  // Closed, it misses nothing either.
  fireEvent.click(screen.getByText("Close"));
  await waitFor(() => expect(screen.getByTestId("open").textContent).toBe("none"));
  server.a2.turns.push(said("agent", SOLVED));
  chatChanged(socket, "a2");
  await settle();
  await opens("Dataset Finder", "a2", `${finder}|agent:${RECORDED}|agent:${SOLVED}`);
});

test("this tab's own ask, and the turns the server appends to its chat meanwhile and after it, each show once", async () => {
  const socket = await anasTabInTheRoom();
  const before = `user:${ASKED}|agent:${PAUSED}`;
  await opens("Dataflow Builder", "a1", before);

  // Ana asks the Builder, and the room brings her ask's events.
  await act(async () => {
    fireEvent.click(screen.getByText("Send"));
  });
  const askId = api.askTurn.mock.calls[0][2];
  turnEvent(socket, askId, 0, "asked", { by: ANA, message: "Build it.", askedAt: 1, waiting: false });
  turnEvent(socket, askId, 1, "started", { startedAt: 2 });
  turnEvent(socket, askId, 2, "execution", { executionId: "e9" });
  turnEvent(socket, askId, 3, "delta", { text: "Building" });
  expect(turns()).toBe(`${before}|user:Build it.|agent:Building`);

  // A build's Solve says a node is solved in this chat while her turn runs.
  server.a1 = {
    turns: [...server.a1.turns, said("agent", SOLVED_TOO)],
    asks: [{
      askId, by: ANA, message: "Build it.", state: "running", askedAt: 1, startedAt: 2, seq: 3, text: "Building",
      events: [{ seq: 2, event: "execution", data: { executionId: "e9" } }],
    }],
  };
  chatChanged(socket, "a1");
  expect(turns()).toBe(`${before}|user:Build it.|agent:Building`);
  await waitFor(() => expect(turns()).toBe(`${before}|agent:${SOLVED_TOO}|user:Build it.|agent:Building`));

  // Her turn ends: the server holds its exchange.
  turnEvent(socket, askId, 4, "delta", { text: " the map." });
  server.a1 = {
    turns: [
      ...server.a1.turns,
      { role: "user", text: "Build it.", by: ANA },
      {
        role: "agent",
        text: "Building the map.",
        execution: { executionId: "e9", usage: null, status: "ok", durationMs: 5 },
      },
    ],
    asks: [],
  };
  turnEvent(socket, askId, 5, "done", { reply: "Building the map.", executionId: "e9", usage: null });
  expect(screen.getByTestId("run-status").textContent).toBe("done");

  // Then the pick's Source recorded turn lands in her chat.
  server.a1.turns.push(said("agent", RECORDED));
  chatChanged(socket, "a1");
  expect(turns()).toBe(`${before}|agent:${SOLVED_TOO}|user:Build it.|agent:Building the map.`);

  const after = `${before}|agent:${SOLVED_TOO}|user:Build it.|agent:Building the map.|agent:${RECORDED}`;
  await waitFor(() => expect(turns()).toBe(after));
  await settle();
  expect(turns()).toBe(after);
  expect(screen.getByTestId("run-status").textContent).toBe("done");
});
