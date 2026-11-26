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
 * A read is the chat whole, but what only this tab holds stays: a message it
 * sent that the server does not hold yet, and an ask of its own the server
 * refused before it kept anything. A card this tab acts on (Undo, Apply,
 * Dismiss) stays at work until the chat is read after the action, the read
 * the room's word started meanwhile included, and a refusal stays on its
 * card until the user acts on it again.
 *
 * The room is the real `CollaborationProvider` on a fake socket, so the word
 * reaches the chat only if the provider hands it on.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

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
import type { AgentAskView, AgentContentPart, AgentSessionTurn } from "../../services/agents/types";
import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";
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
const NODE_BUILDER = attachment("a3", "agent.curio.node-builder@1", "Node Builder", { kind: "node", targetId: "sum" });

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
/** The reads of each chat that wait, answered with the chat as the server
 * held it when it was asked, once let go (`holdNextRead`). */
let held: Record<string, Array<Promise<void>>> = {};

const said = (role: "user" | "agent", text: string): AgentSessionTurn => ({ role, text });
const shown = (turns: AgentSessionTurn[]) => turns.map((t) => `${t.role}:${t.text}`).join("|");

/** The next read of *attachmentId*'s chat waits until it is let go, as an
 * answer slow to come does: it answers with the chat as the server held it
 * when the tab asked. */
function holdNextRead(attachmentId: string): { letGo: () => Promise<void> } {
  let letGo: () => void = () => undefined;
  (held[attachmentId] ??= []).push(new Promise<void>((resolve) => (letGo = resolve)));
  return {
    letGo: async () => {
      await act(async () => {
        letGo();
      });
      await settle();
    },
  };
}

/** How many times this tab read *attachmentId*'s chat. */
const readsOf = (attachmentId: string) =>
  api.getSession.mock.calls.filter(([, attachment]) => attachment === attachmentId).length;

/** What the server answers a request it refuses, as `agentsApi` throws it. */
const refused = (status: number, message: string) => Object.assign(new Error(message), { status });

/** The Node Builder's change to the sum, whose card offers its Undo. */
const CHANGE: AgentContentPart = {
  type: "change",
  changeId: "c1",
  tool: "node.content.write",
  kind: "content",
  summary: "Replaced the content of the Python node · sum",
  preview: "return input_0.sum()",
  status: "applied",
  lines: ["Python · sum"],
  nodeId: "sum",
};
/** An install the Node Builder asked for, whose card waits for Ana's review. */
const PROPOSAL: AgentContentPart = {
  type: "proposal",
  proposalId: "p1",
  tool: "dataset.install",
  summary: "Install dataset · Cities",
  preview: "Cities · csv · imported",
  pins: { datasetId: "imported.cities@1" },
  status: "pending",
};
const REWRITE = "Rewrite the sum.";
const REWRITTEN = "I rewrote the sum, and it needs the Cities dataset.";

/** The status the server holds of the card *id* in *attachmentId*'s chat
 * becomes *status*. */
function setStatus(attachmentId: string, id: string, status: string) {
  server[attachmentId].turns = server[attachmentId].turns.map((turn) =>
    turn.content
      ? {
          ...turn,
          content: turn.content.map((part) =>
            (part.type === "change" && part.changeId === id) || (part.type === "proposal" && part.proposalId === id)
              ? ({ ...part, status } as AgentContentPart)
              : part,
          ),
        }
      : turn,
  );
}

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
      <button onClick={() => ctx.openChat("a3")}>Node Builder</button>
      <button onClick={() => ctx.closeChat()}>Close</button>
      <button onClick={() => void ctx.sendMessage("a1", "Build it.")}>Send</button>
      <button onClick={() => void ctx.clearConversation("a1")}>Clear the Dataflow Builder's chat</button>
      <div data-testid="open">{open ?? "none"}</div>
      <div data-testid="turns">{shownTurns}</div>
      <div data-testid="run-status">{ctx.runStatus["a1"]?.phase ?? "none"}</div>
    </div>
  );
};

/** The chat this tab shows, drawn as the dock draws it (`AgentDockOverlay`):
 * its cards with their Undo, Apply and Dismiss, and why the server refused
 * one. */
const Panel: React.FC = () => {
  const ctx = useAgentAttachmentsContext();
  const open = ctx?.selectedId ?? null;
  const openAttachment = ctx?.attachments.find((a) => a.attachmentId === open) ?? null;
  if (!ctx || !open || !openAttachment) return null;
  return (
    <MemoryRouter>
      <AgentChatPanel
        attachment={openAttachment}
        turns={ctx.transcripts[open] ?? []}
        loadingHistory={ctx.hydratingId === open}
        onSend={(message) => ctx.sendMessage(open, message)}
        onClose={ctx.closeChat}
        onUndoChange={(changeId) => ctx.undoChange(open, changeId)}
        onApplyProposal={(proposalId) => ctx.applyProposal(open, proposalId)}
        onDismissProposal={(proposalId) => ctx.dismissProposal(open, proposalId)}
        refusals={ctx.refusals?.[open]}
      />
    </MemoryRouter>
  );
};

const turns = () => screen.getByTestId("turns").textContent;
/** The open chat's card of the Node Builder's change, and of its install. */
const changeCard = () => screen.getByRole("group", { name: `Change: ${(CHANGE as { summary: string }).summary}` });
const reviewCard = () =>
  screen.getByRole("group", { name: `Review proposal: ${(PROPOSAL as { summary: string }).summary}` });

/** Ana's tab on dataflow p1, in its room, its agents listed once, showing
 * the open chat as the harness above does, and as *panel* draws it. */
async function anasTabInTheRoom(panel: React.ReactNode = null): Promise<FakeSocket> {
  render(
    <CollaborationProvider>
      <AgentAttachmentsProvider>
        <Chat />
        {panel}
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
  fireEvent.click(screen.getByRole("button", { name }));
  await waitFor(() => expect(screen.getByTestId("open").textContent).toBe(attachmentId));
  await waitFor(() => expect(turns()).toBe(expected));
}

beforeEach(() => {
  jest.clearAllMocks();
  sockets = [];
  held = {};
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
    a3: {
      turns: [
        said("user", REWRITE),
        { role: "agent", text: REWRITTEN, content: [CHANGE, PROPOSAL] },
      ],
      asks: [],
    },
  };
  api.listAttachments.mockResolvedValue({ attachments: [BUILDER, FINDER] } as never);
  api.getSession.mockImplementation(async (_projectId: string, attachmentId: string) => {
    const answer = {
      attachmentId,
      sessionId: `s-${attachmentId}`,
      turns: [...(server[attachmentId]?.turns ?? [])],
      asks: [...(server[attachmentId]?.asks ?? [])],
    };
    const waits = held[attachmentId]?.shift();
    if (waits) await waits;
    return answer as never;
  });
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

test("a word that names several chats reads the open one at once, and each other one this tab read when it opens", async () => {
  const socket = await anasTabInTheRoom();
  const finder = `user:${TASK}|agent:${FOUND}`;
  await opens("Dataset Finder", "a2", finder);
  const before = `user:${ASKED}|agent:${PAUSED}`;
  await opens("Dataflow Builder", "a1", before);

  // Ben's pick writes its Source recorded turn into the Builder's chat and
  // the Finder's in one wait of the room's: one word names both.
  server.a1.turns.push(said("agent", RECORDED));
  server.a2.turns.push(said("agent", RECORDED));
  fire(socket, CHAT_CHANGED, { projectId: "p1", attachmentIds: ["a1", "a2"] });
  await waitFor(() => expect(turns()).toBe(`${before}|agent:${RECORDED}`));
  await opens("Dataset Finder", "a2", `${finder}|agent:${RECORDED}`);
});

test("a chat whose read is in flight when the room names it, though not open, is read once more after that read", async () => {
  const socket = await anasTabInTheRoom();
  const finder = `user:${TASK}|agent:${FOUND}`;
  // Ana opens the Finder's chat, whose first read is slow, and moves on to
  // the Builder's before it lands.
  const first = holdNextRead("a2");
  fireEvent.click(screen.getByRole("button", { name: "Dataset Finder" }));
  await waitFor(() => expect(screen.getByTestId("open").textContent).toBe("a2"));
  expect(turns()).toBe(LOADING);
  await opens("Dataflow Builder", "a1", `user:${ASKED}|agent:${PAUSED}`);

  // The server writes into the Finder's chat after it answered that read.
  server.a2.turns.push(said("agent", RECORDED));
  chatChanged(socket, "a2");
  await first.letGo();
  await waitFor(() => expect(readsOf("a2")).toBe(2));
  await settle();

  // Opened again, the Finder's chat shows the turn at once, with no read.
  fireEvent.click(screen.getByRole("button", { name: "Dataset Finder" }));
  expect(turns()).toBe(`${finder}|agent:${RECORDED}`);
  await settle();
  expect(readsOf("a2")).toBe(2);
});

test("this tab's ask that the server refused before it kept anything stays in the chat across a read, until the chat is cleared", async () => {
  const socket = await anasTabInTheRoom();
  const before = `user:${ASKED}|agent:${PAUSED}`;
  await opens("Dataflow Builder", "a1", before);

  // Ana's ask is refused before its turn is built: the server keeps nothing
  // of it, and her tab says why under her message.
  api.askTurn.mockRejectedValueOnce(refused(429, "Too many asks of this agent at once."));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
  });
  const failed = `${before}|user:Build it.|agent:(error) Too many asks of this agent at once.`;
  await waitFor(() => expect(turns()).toBe(failed));

  // A Solve's turn lands in the chat, which is read again: her message and
  // its error stay where they were, with the new turn after them.
  server.a1.turns.push(said("agent", SOLVED));
  chatChanged(socket, "a1");
  await waitFor(() => expect(turns()).toBe(`${failed}|agent:${SOLVED}`));
  await settle();
  expect(turns()).toBe(`${failed}|agent:${SOLVED}`);

  // Cleared, the chat holds none of it, on the server or in her tab.
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Clear the Dataflow Builder's chat" }));
  });
  server.a1 = { turns: [], asks: [] };
  chatChanged(socket, "a1");
  await settle();
  expect(turns()).toBe("");
});

test("a message this tab sends while the server writes into its chat stays, and says why when its ask is refused", async () => {
  const socket = await anasTabInTheRoom();
  const before = `user:${ASKED}|agent:${PAUSED}`;
  await opens("Dataflow Builder", "a1", before);

  // Ana sends a message; the server has not answered her ask yet.
  let refuse: (e: unknown) => void = () => undefined;
  api.askTurn.mockImplementationOnce(() => new Promise((_resolve, reject) => (refuse = reject)) as never);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
  });
  expect(turns()).toBe(`${before}|user:Build it.`);

  // Meanwhile a Solve's turn lands in the chat, which is read again: the
  // server holds no ask of hers yet, and her message stays, after the turn.
  server.a1.turns.push(said("agent", SOLVED));
  chatChanged(socket, "a1");
  await waitFor(() => expect(readsOf("a1")).toBe(2));
  await settle();
  expect(turns()).toBe(`${before}|agent:${SOLVED}|user:Build it.`);
  expect(screen.getByTestId("run-status").textContent).toBe("running");

  // The server refuses her ask: the chat says why, under her message.
  await act(async () => {
    refuse(refused(409, "This agent is busy with another ask."));
  });
  await settle();
  expect(turns()).toBe(`${before}|agent:${SOLVED}|user:Build it.|agent:(error) This agent is busy with another ask.`);
  expect(screen.getByTestId("run-status").textContent).toBe("error");
});

/** Each card action, as the Node Builder's chat offers it: the button that
 * starts it, the label it shows while at work, the server's request, its
 * answer, and the status and outcome the card holds after it. */
const CARD_ACTIONS = [
  {
    action: "Undo",
    card: changeCard,
    id: "c1",
    request: () => api.undoChange,
    answer: { attachmentId: "a3", changeId: "c1", status: "undone", canvas: [] },
    status: "undone",
    outcome: "Undone",
  },
  {
    action: "Apply",
    card: reviewCard,
    id: "p1",
    request: () => api.applyProposal,
    answer: {},
    status: "applied",
    outcome: "Applied",
  },
  {
    action: "Dismiss",
    card: reviewCard,
    id: "p1",
    request: () => api.dismissProposal,
    answer: undefined,
    status: "dismissed",
    outcome: "Dismissed",
  },
];

/** The card's buttons that act on it: Undo, Apply, Dismiss, as they read idle or at work. */
const actionButtons = (card: HTMLElement) =>
  within(card).queryAllByRole("button", { name: /^(Undo|Undoing…|Apply|Applying…|Dismiss)$/ });

test.each(CARD_ACTIONS)(
  "a card's $action keeps it at work until the chat is read after it, the read the room's word started meanwhile included",
  async ({ action, card, id, request, answer, status, outcome }) => {
    api.listAttachments.mockResolvedValue({ attachments: [BUILDER, FINDER, NODE_BUILDER] } as never);
    const socket = await anasTabInTheRoom(<Panel />);
    await opens("Node Builder", "a3", `user:${REWRITE}|agent:${REWRITTEN}`);

    let answered: (value: unknown) => void = () => undefined;
    (request() as jest.Mock).mockImplementationOnce(() => new Promise((resolve) => (answered = resolve)));
    await act(async () => {
      fireEvent.click(within(card()).getByRole("button", { name: action }));
    });

    // The server sets the card's status and tells the room before it
    // answers: the word starts a read of the chat, slow to land.
    const read = holdNextRead("a3");
    setStatus("a3", id, status);
    chatChanged(socket, "a3");
    await act(async () => {
      answered(answer);
    });
    await settle();

    // The action answered, but the chat is not read after it yet: the card
    // offers no action on the status it held before.
    const buttons = actionButtons(card());
    expect(buttons.length).toBeGreaterThan(0);
    for (const button of buttons) expect(button).toBeDisabled();

    // The read lands: the card says the action's outcome, with no action left
    // and nothing refused.
    await read.letGo();
    await waitFor(() => expect(within(card()).getByText(outcome)).toBeInTheDocument());
    expect(actionButtons(card())).toHaveLength(0);
    expect(screen.queryByRole("alert")).toBeNull();
  },
);

test("a refused Undo says why on its card, across reads of the chat and a look at another chat, until Ana acts on the card again", async () => {
  api.listAttachments.mockResolvedValue({ attachments: [BUILDER, FINDER, NODE_BUILDER] } as never);
  const socket = await anasTabInTheRoom(<Panel />);
  const nodeBuilder = `user:${REWRITE}|agent:${REWRITTEN}`;
  await opens("Node Builder", "a3", nodeBuilder);

  // The dev check's refusal: nothing was undone, so the change stands.
  const why = "Someone changed this dataflow after; nothing was undone.";
  api.undoChange.mockRejectedValueOnce(refused(409, why));
  await act(async () => {
    fireEvent.click(within(changeCard()).getByRole("button", { name: "Undo" }));
  });
  await waitFor(() => expect(within(changeCard()).getByRole("alert")).toHaveTextContent(why));
  expect(within(changeCard()).getByRole("button", { name: "Undo" })).toBeEnabled();

  // Another tab writes into the chat, which is read again: the card still
  // says why.
  const drawn = "The sum's chart is drawn.";
  server.a3.turns.push(said("agent", drawn));
  chatChanged(socket, "a3");
  await waitFor(() => expect(turns()).toBe(`${nodeBuilder}|agent:${drawn}`));
  expect(within(changeCard()).getByRole("alert")).toHaveTextContent(why);

  // Ana looks at the Builder's chat, then comes back: the card still says why.
  await opens("Dataflow Builder", "a1", `user:${ASKED}|agent:${PAUSED}`);
  await opens("Node Builder", "a3", `${nodeBuilder}|agent:${drawn}`);
  expect(within(changeCard()).getByRole("alert")).toHaveTextContent(why);

  // She acts on the card again: the reason goes, and the Undo's own outcome
  // shows.
  let answered: (value: unknown) => void = () => undefined;
  api.undoChange.mockImplementationOnce(() => new Promise((resolve) => (answered = resolve)) as never);
  await act(async () => {
    fireEvent.click(within(changeCard()).getByRole("button", { name: "Undo" }));
  });
  expect(within(changeCard()).queryByRole("alert")).toBeNull();
  setStatus("a3", "c1", "undone");
  await act(async () => {
    answered({ attachmentId: "a3", changeId: "c1", status: "undone", canvas: [] });
  });
  await waitFor(() => expect(within(changeCard()).getByText("Undone")).toBeInTheDocument());
  expect(within(changeCard()).queryByRole("alert")).toBeNull();
});

test.each([
  {
    action: "Apply",
    request: () => api.applyProposal,
    why: "The dataset is not in the Data Catalog any more.",
    status: "stale",
  },
  { action: "Dismiss", request: () => api.dismissProposal, why: "This install was reviewed already.", status: null },
])("a refused $action says why on its card, as an alert, across a look at another chat", async ({ action, request, why, status }) => {
  api.listAttachments.mockResolvedValue({ attachments: [BUILDER, FINDER, NODE_BUILDER] } as never);
  await anasTabInTheRoom(<Panel />);
  const nodeBuilder = `user:${REWRITE}|agent:${REWRITTEN}`;
  await opens("Node Builder", "a3", nodeBuilder);

  (request() as jest.Mock).mockImplementationOnce(async () => {
    if (status) setStatus("a3", "p1", status);
    throw refused(409, why);
  });
  await act(async () => {
    fireEvent.click(within(reviewCard()).getByRole("button", { name: action }));
  });
  await waitFor(() => expect(within(reviewCard()).getByRole("alert")).toHaveTextContent(why));

  await opens("Dataflow Builder", "a1", `user:${ASKED}|agent:${PAUSED}`);
  await opens("Node Builder", "a3", nodeBuilder);
  expect(within(reviewCard()).getByRole("alert")).toHaveTextContent(why);
});
