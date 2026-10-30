/**
 * A chat turn runs on the server, and every tab of the dataflow's owner and
 * editors follows it through the room (`agent_turn`, `turn_jobs.py`): the
 * message of whoever asked, named when it is someone else's, the reply as the
 * model writes it, the tool lines, and the reply with its record at the end.
 * A chat opened mid-turn shows the turn as it stands, then the events after
 * it, each once. This tab's own ask is asked at once, shows at once and is
 * followed like anyone's; a second ask while a turn runs waits its turn, and
 * its asker can withdraw it; Stop asks the server to stop the turn that runs.
 * An event that skips one, or a join of the room again, reads the chat again.
 * An ask this tab made before the room held it follows its own stream alone,
 * and a read of the chat keeps it as that stream brings it.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: "p1", viewerMode: "owner" }),
}));

// The room this tab joined, and each handler of its events.
const mockRoom = new Map<string, Set<(payload: unknown) => void>>();
const mockCollab = {
  connected: true,
  participantId: "tab-1" as string | null,
  role: "owner" as string | null,
  users: [],
  lockedNodes: {},
  activity: [],
  lockNode: () => undefined,
  unlockNode: () => undefined,
  onRemote: (event: string, handler: (payload: unknown) => void) => {
    if (!mockRoom.has(event)) mockRoom.set(event, new Set());
    mockRoom.get(event)?.add(handler);
    return () => {
      mockRoom.get(event)?.delete(handler);
    };
  },
};
jest.mock("../../providers/CollaborationProvider", () => ({ useCollab: () => mockCollab }));

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

const api = agentsApi as jest.Mocked<typeof agentsApi>;

const BOB = { kind: "person" as const, account: "7", name: "Bob" };
const ANA = { kind: "person" as const, account: "9", name: "Ana" };

const attachment = {
  attachmentId: "a1",
  coord: "agent.curio.node-builder@1",
  target: { kind: "canvas" as const },
  sessionId: "s1",
  revision: 1,
  name: "Node Builder",
  category: "node",
  hooks: ["node"],
  intent: "prompt text",
  intentEdited: false,
  title: "Titled",
  titleEdited: true,
};

/** The ask this tab withdraws, once a test knows its id. */
let mockWithdrawId = "";

const Harness: React.FC = () => {
  const ctx = useAgentAttachmentsContext();
  if (!ctx) return null;
  const turns = ctx.transcripts["a1"] ?? [];
  const waiting = ctx.waitingAsks?.["a1"] ?? [];
  return (
    <div>
      <button onClick={() => ctx.openChat("a1")}>open</button>
      <button onClick={() => void ctx.sendMessage("a1", "Mine now.")}>send</button>
      <button onClick={() => void ctx.stopTurn?.("a1")}>stop</button>
      <button onClick={() => void ctx.withdrawAsk?.("a1", mockWithdrawId)}>withdraw</button>
      <div data-testid="turns">
        {turns.map((t) => `${t.role}:${t.by?.name ? `${t.by.name}:` : ""}${t.text}`).join("|")}
      </div>
      <div data-testid="waiting">{waiting.map((w) => `${w.message}:${w.status}`).join("|")}</div>
      <div data-testid="run-status">{ctx.runStatus["a1"]?.phase ?? "∅"}</div>
      <div data-testid="lines">{(ctx.toolActivity["a1"] ?? []).join("|")}</div>
      <div data-testid="executions">{turns.map((t) => t.execution?.executionId ?? "∅").join("|")}</div>
    </div>
  );
};

function renderHarness() {
  return render(
    <AgentAttachmentsProvider>
      <Harness />
    </AgentAttachmentsProvider>,
  );
}

/** The room tells this tab one event of an ask on the dataflow's attachment. */
function tell(envelope: { askId: string; seq: number; event: string; data: Record<string, unknown> }) {
  act(() => {
    for (const handler of Array.from(mockRoom.get("agent_turn") ?? [])) {
      handler({ projectId: "p1", attachmentId: "a1", ...envelope });
    }
  });
}

/** Bob's ask, asked and started: his turn runs. */
function bobsTurnRuns() {
  tell({ askId: "k1", seq: 0, event: "asked", data: { by: BOB, message: "What about the map?", askedAt: 1, waiting: false } });
  tell({ askId: "k1", seq: 1, event: "started", data: { startedAt: 2 } });
}

async function openChat() {
  fireEvent.click(screen.getByText("open"));
  await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("user:earlier"));
}

/** The answer of an ask this tab follows by its own stream, held open: the
 * test sends its events and ends it. */
function heldStream() {
  const held = {
    delta: (_text: string) => undefined as void,
    event: (_name: string, _payload: Record<string, unknown>) => undefined as void,
    finish: (_result: Record<string, unknown>) => undefined as void,
  };
  api.runAttachmentStream.mockImplementation((_p, _a, _m, onDelta, onEvent) => {
    held.delta = (text) => onDelta(text);
    held.event = (name, payload) => onEvent?.(name, payload);
    return new Promise((resolve) => {
      held.finish = (result) => resolve(result as never);
    });
  });
  return held;
}

/** The tab is away from the dataflow's room, or not yet in it. */
function outOfTheRoom() {
  mockCollab.role = null;
  mockCollab.participantId = null;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockRoom.clear();
  mockCollab.role = "owner";
  mockCollab.participantId = "tab-1";
  mockWithdrawId = "";
  api.listAttachments.mockResolvedValue({ attachments: [attachment] } as never);
  api.getSession.mockResolvedValue({
    attachmentId: "a1", sessionId: "s1", turns: [{ role: "user", text: "earlier" }], asks: [],
  });
  api.askTurn.mockImplementation(async (_p, attachmentId, askId) => ({ askId, attachmentId, state: "running" }));
  api.stopTurn.mockImplementation(async (_p, attachmentId, askId) => ({ askId, attachmentId, stopping: true }));
  api.withdrawTurn.mockImplementation(async (_p, attachmentId, askId) => ({ askId, attachmentId, withdrawn: true }));
});

describe("a turn followed through the room", () => {
  it("another person's ask reaches this tab: their message, the reply as it streams, then the reply with its record", async () => {
    renderHarness();
    await openChat();
    bobsTurnRuns();
    tell({ askId: "k1", seq: 2, event: "execution", data: { executionId: "e1" } });
    tell({ askId: "k1", seq: 3, event: "delta", data: { text: "It shows" } });
    expect(screen.getByTestId("turns")).toHaveTextContent("user:earlier|user:Bob:What about the map?|agent:It shows");
    expect(screen.getByTestId("run-status")).toHaveTextContent("running");
    tell({ askId: "k1", seq: 4, event: "tool_requested", data: { tool: "dataflow.read" } });
    expect(screen.getByTestId("lines")).toHaveTextContent("dataflow.read …");
    tell({ askId: "k1", seq: 5, event: "delta", data: { text: " the parks." } });
    tell({ askId: "k1", seq: 6, event: "done", data: { reply: "It shows the parks.", executionId: "e1", usage: null } });
    expect(screen.getByTestId("turns")).toHaveTextContent(
      "user:earlier|user:Bob:What about the map?|agent:It shows the parks.",
    );
    expect(screen.getByTestId("executions")).toHaveTextContent("∅|∅|e1");
    expect(screen.getByTestId("run-status")).toHaveTextContent("done");
    expect(screen.getByTestId("lines").textContent).toBe("");
    expect(api.runAttachmentStream).not.toHaveBeenCalled();
  });

  it("a chat opened mid-turn shows the turn as it stands, then each event after it once", async () => {
    api.getSession.mockResolvedValue({
      attachmentId: "a1",
      sessionId: "s1",
      turns: [{ role: "user", text: "earlier" }, { role: "agent", text: "older" }],
      asks: [
        {
          askId: "k1", by: BOB, message: "Rewrite it.", state: "running", askedAt: 1, startedAt: 2, seq: 4,
          text: "I will",
          events: [
            { seq: 2, event: "execution", data: { executionId: "e1" } },
            { seq: 3, event: "tool_requested", data: { tool: "node.content.write" } },
          ],
        },
        {
          askId: "k2", by: ANA, message: "Then the chart.", state: "waiting", askedAt: 3, startedAt: null, seq: 0,
          text: "", events: [],
        },
      ],
    });
    renderHarness();
    await openChat();
    expect(screen.getByTestId("turns")).toHaveTextContent("user:earlier|agent:older|user:Bob:Rewrite it.|agent:I will");
    expect(screen.getByTestId("waiting")).toHaveTextContent("Then the chart.:waiting");
    expect(screen.getByTestId("run-status")).toHaveTextContent("running");
    expect(screen.getByTestId("lines")).toHaveTextContent("node.content.write …");
    tell({ askId: "k1", seq: 4, event: "delta", data: { text: " TWICE" } });
    tell({ askId: "k1", seq: 5, event: "delta", data: { text: " rewrite it." } });
    tell({ askId: "k1", seq: 6, event: "done", data: { reply: "I will rewrite it.", executionId: "e1", usage: null } });
    tell({ askId: "k2", seq: 1, event: "started", data: { startedAt: 9 } });
    expect(screen.getByTestId("turns")).toHaveTextContent(
      "user:earlier|agent:older|user:Bob:Rewrite it.|agent:I will rewrite it.|user:Ana:Then the chart.",
    );
    expect(screen.getByTestId("turns")).not.toHaveTextContent("TWICE");
    expect(screen.getByTestId("waiting").textContent).toBe("");
    expect(screen.getByTestId("run-status")).toHaveTextContent("running");
  });

  it("this tab's own ask is asked at once, shows at once, and is followed through the room", async () => {
    renderHarness();
    await openChat();
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    expect(api.askTurn).toHaveBeenCalledWith("p1", "a1", expect.stringMatching(/^[0-9a-f]{32}$/), "Mine now.", undefined);
    expect(api.runAttachmentStream).not.toHaveBeenCalled();
    expect(screen.getByTestId("turns")).toHaveTextContent("user:earlier|user:Mine now.");
    expect(screen.getByTestId("run-status")).toHaveTextContent("running");
    const askId = api.askTurn.mock.calls[0][2];
    tell({ askId, seq: 0, event: "asked", data: { by: ANA, message: "Mine now.", askedAt: 1, waiting: false } });
    tell({ askId, seq: 1, event: "started", data: { startedAt: 2 } });
    tell({ askId, seq: 2, event: "execution", data: { executionId: "e5" } });
    tell({ askId, seq: 3, event: "delta", data: { text: "Here." } });
    tell({ askId, seq: 4, event: "done", data: { reply: "Here.", executionId: "e5", usage: null } });
    expect(screen.getByTestId("turns")).toHaveTextContent("user:earlier|user:Mine now.|agent:Here.");
    expect(screen.getByTestId("executions")).toHaveTextContent("∅|∅|e5");
  });

  it("a second ask while a turn runs waits its turn, and its asker can withdraw it", async () => {
    renderHarness();
    await openChat();
    bobsTurnRuns();
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    expect(screen.getByTestId("waiting")).toHaveTextContent("Mine now.:sending");
    expect(screen.getByTestId("turns")).not.toHaveTextContent("Mine now.");
    const askId = api.askTurn.mock.calls[0][2];
    tell({ askId, seq: 0, event: "asked", data: { by: ANA, message: "Mine now.", askedAt: 3, waiting: true } });
    expect(screen.getByTestId("waiting")).toHaveTextContent("Mine now.:waiting");
    mockWithdrawId = askId;
    await act(async () => {
      fireEvent.click(screen.getByText("withdraw"));
    });
    expect(api.withdrawTurn).toHaveBeenCalledWith("p1", "a1", askId);
    expect(screen.getByTestId("waiting").textContent).toBe("");
    tell({ askId, seq: 1, event: "withdrawn", data: { by: ANA } });
    tell({ askId: "k1", seq: 2, event: "done", data: { reply: "The map.", executionId: "e1", usage: null } });
    expect(screen.getByTestId("turns")).toHaveTextContent("user:earlier|user:Bob:What about the map?|agent:The map.");
    expect(screen.getByTestId("turns")).not.toHaveTextContent("Mine now.");
  });

  it("Stop asks the server to stop the turn that runs", async () => {
    renderHarness();
    await openChat();
    bobsTurnRuns();
    await act(async () => {
      fireEvent.click(screen.getByText("stop"));
    });
    expect(api.stopTurn).toHaveBeenCalledWith("p1", "a1", "k1");
    tell({
      askId: "k1", seq: 2, event: "done",
      data: { reply: "", executionId: "e1", usage: null, stopped: { by: ANA } },
    });
    expect(screen.getByTestId("executions")).toHaveTextContent("∅|∅|e1");
    expect(screen.getByTestId("run-status")).toHaveTextContent("done");
  });

  it("an event that skips one reads the chat again", async () => {
    renderHarness();
    await openChat();
    expect(api.getSession).toHaveBeenCalledTimes(1);
    tell({ askId: "k1", seq: 0, event: "asked", data: { by: BOB, message: "What about the map?", askedAt: 1, waiting: false } });
    tell({ askId: "k1", seq: 2, event: "delta", data: { text: "skipped one" } });
    await waitFor(() => expect(api.getSession).toHaveBeenCalledTimes(2));
  });

  it("a tab that joins the room again reads its open chats again", async () => {
    const { rerender } = renderHarness();
    const again = () =>
      rerender(
        <AgentAttachmentsProvider>
          <Harness />
        </AgentAttachmentsProvider>,
      );
    await openChat();
    expect(api.getSession).toHaveBeenCalledTimes(1);
    // Away from the room, the tab has no id there; back, it has a new one.
    mockCollab.participantId = null;
    again();
    expect(api.getSession).toHaveBeenCalledTimes(1);
    mockCollab.participantId = "tab-2";
    again();
    await waitFor(() => expect(api.getSession).toHaveBeenCalledTimes(2));
  });

  it("this tab's own ask that an earlier turn holds back waits its turn after it", async () => {
    renderHarness();
    await openChat();
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    expect(api.askTurn).toHaveBeenCalledTimes(1);
    const askId = api.askTurn.mock.calls[0][2];
    expect(screen.getByTestId("turns").textContent).toBe("user:earlier|user:Mine now.");
    api.getSession.mockResolvedValue({
      attachmentId: "a1",
      sessionId: "s1",
      turns: [{ role: "user", text: "earlier" }],
      asks: [
        {
          askId: "k1", by: BOB, message: "What about the map?", state: "running", askedAt: 1, startedAt: 2, seq: 1,
          text: "", events: [],
        },
        { askId, by: ANA, message: "Mine now.", state: "waiting", askedAt: 3, startedAt: null, seq: 0, text: "", events: [] },
      ],
    });
    tell({ askId, seq: 0, event: "asked", data: { by: ANA, message: "Mine now.", askedAt: 3, waiting: true } });
    await waitFor(() => expect(screen.getByTestId("waiting").textContent).toBe("Mine now.:waiting"));
    expect(screen.getByTestId("turns").textContent).toBe("user:earlier|user:Bob:What about the map?");
  });
});

describe("an ask this tab made before the room held it", () => {
  it("follows its own stream, and the room's events of it show nothing twice", async () => {
    outOfTheRoom();
    const stream = heldStream();
    const { rerender } = renderHarness();
    await openChat();
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    expect(api.runAttachmentStream).toHaveBeenCalledWith(
      "p1", "a1", "Mine now.", expect.any(Function), expect.any(Function), undefined,
      expect.stringMatching(/^[0-9a-f]{32}$/),
    );
    const askId = api.runAttachmentStream.mock.calls[0][6] as string;
    expect(api.askTurn).not.toHaveBeenCalled();
    // The room holds the tab now, and tells it the same ask's events.
    mockCollab.role = "owner";
    mockCollab.participantId = "tab-1";
    rerender(
      <AgentAttachmentsProvider>
        <Harness />
      </AgentAttachmentsProvider>,
    );
    act(() => {
      stream.event("execution", { executionId: "e7" });
      stream.delta("Here.");
    });
    tell({ askId, seq: 0, event: "asked", data: { by: ANA, message: "Mine now.", askedAt: 1, waiting: false } });
    tell({ askId, seq: 1, event: "started", data: { startedAt: 2 } });
    tell({ askId, seq: 2, event: "execution", data: { executionId: "e7" } });
    tell({ askId, seq: 3, event: "delta", data: { text: "Here." } });
    tell({ askId, seq: 4, event: "done", data: { reply: "Here.", executionId: "e7", usage: null } });
    await act(async () => {
      stream.finish({ reply: "Here.", executionId: "e7", usage: null });
    });
    expect(screen.getByTestId("turns").textContent).toBe("user:earlier|user:Mine now.|agent:Here.");
    expect(screen.getByTestId("executions").textContent).toBe("∅|∅|e7");
    expect(api.getSession).toHaveBeenCalledTimes(1);
  });

  it("waits its turn behind a turn that runs, and runs once its stream starts", async () => {
    outOfTheRoom();
    const stream = heldStream();
    api.getSession.mockResolvedValue({
      attachmentId: "a1",
      sessionId: "s1",
      turns: [{ role: "user", text: "earlier" }],
      asks: [
        {
          askId: "k1", by: BOB, message: "What about the map?", state: "running", askedAt: 1, startedAt: 2, seq: 1,
          text: "", events: [],
        },
      ],
    });
    renderHarness();
    await openChat();
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    expect(api.runAttachmentStream).toHaveBeenCalledWith(
      "p1", "a1", "Mine now.", expect.any(Function), expect.any(Function), undefined,
      expect.stringMatching(/^[0-9a-f]{32}$/),
    );
    expect(screen.getByTestId("waiting").textContent).toBe("Mine now.:waiting");
    expect(screen.getByTestId("turns")).not.toHaveTextContent("Mine now.");
    act(() => {
      stream.event("execution", { executionId: "e8" });
      stream.delta("Now.");
    });
    expect(screen.getByTestId("waiting").textContent).toBe("");
    expect(screen.getByTestId("turns").textContent?.endsWith("|user:Mine now.|agent:Now.")).toBe(true);
  });

  it("keeps the ask as its stream brings it when the chat is read again", async () => {
    outOfTheRoom();
    const stream = heldStream();
    renderHarness();
    await openChat();
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    expect(api.runAttachmentStream).toHaveBeenCalledWith(
      "p1", "a1", "Mine now.", expect.any(Function), expect.any(Function), undefined,
      expect.stringMatching(/^[0-9a-f]{32}$/),
    );
    const askId = api.runAttachmentStream.mock.calls[0][6] as string;
    act(() => {
      stream.event("execution", { executionId: "e7" });
      stream.delta("Her");
    });
    api.getSession.mockResolvedValue({
      attachmentId: "a1",
      sessionId: "s1",
      turns: [{ role: "user", text: "earlier" }, { role: "agent", text: "older" }],
      asks: [
        { askId, by: ANA, message: "Mine now.", state: "running", askedAt: 1, startedAt: 2, seq: 3, text: "Her", events: [] },
      ],
    });
    // An event that skips one reads the chat again while the stream runs.
    tell({ askId: "k1", seq: 2, event: "delta", data: { text: "skipped one" } });
    await waitFor(() =>
      expect(screen.getByTestId("turns").textContent).toBe("user:earlier|agent:older|user:Mine now.|agent:Her"),
    );
    act(() => stream.delta("e."));
    await act(async () => {
      stream.finish({ reply: "Here.", executionId: "e7", usage: null });
    });
    expect(screen.getByTestId("turns").textContent).toBe("user:earlier|agent:older|user:Mine now.|agent:Here.");
    expect(screen.getByTestId("executions").textContent).toBe("∅|∅|∅|e7");
  });
});
