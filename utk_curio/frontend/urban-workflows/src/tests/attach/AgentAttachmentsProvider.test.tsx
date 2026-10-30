import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: "p1" }),
}));

const mockPaletteRefresh = jest.fn();
jest.mock("../../services/agents/agentEvents", () => ({
  ...jest.requireActual("../../services/agents/agentEvents"),
  notifyAgentCatalogRefresh: () => mockPaletteRefresh(),
}));

// The chat panel the line tests render loads the package review on demand
// only; mocked so this suite stays network-free, as the panel's own suite is.
jest.mock("../../services/packages/packagesApi", () => ({ packagesApi: {} }));

jest.mock("../../services/agents/agentsApi", () => ({
  agentsApi: {
    listAttachments: jest.fn(),
    attach: jest.fn(),
    detachAttachment: jest.fn(),
    runAttachment: jest.fn(),
    runAttachmentStream: jest.fn(),
    askTurn: jest.fn(),
    followTurn: jest.fn(),
    stopTurn: jest.fn(),
    withdrawTurn: jest.fn(),
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
    undoChange: jest.fn(),
    runNode: jest.fn(),
    validateNode: jest.fn(),
    simulate: jest.fn(),
    cancelSimulate: jest.fn(),
  },
}));

/** A follow of an ask (`followTurn`) that says *envelopes*, the ask's id
 * and attachment filled in from the call. */
function followed(...envelopes: Array<{ seq: number; event: string; data: Record<string, unknown> }>) {
  return async (
    pid: string,
    attachmentId: string,
    askId: string,
    onEnvelope: (envelope: { projectId: string; attachmentId: string; askId: string; seq: number; event: string; data: Record<string, unknown> }) => void,
  ) => {
    for (const envelope of envelopes) onEnvelope({ projectId: pid, attachmentId, askId, ...envelope });
  };
}

/** The ask as a follow's first envelope says it: running, with its turn's
 * execution so far. */
function runningView(executionId: string) {
  return {
    seq: 2,
    event: "snapshot",
    data: {
      askId: "x", by: null, message: "hi", state: "running", askedAt: 1, startedAt: 1, seq: 2, text: "",
      events: [{ seq: 2, event: "execution", data: { executionId } }],
    },
  };
}

import { MemoryRouter } from "react-router-dom";

import { agentsApi } from "../../services/agents";
import {
  AgentAttachmentsProvider,
  useAgentAttachmentsContext,
} from "../../providers/agents";
import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

const attachment = {
  attachmentId: "a1",
  coord: "agent.test.my-explainer@1",
  target: { kind: "canvas" as const },
  sessionId: "s1",
  revision: 1,
  name: "My Explainer",
  category: "node",
  hooks: ["node"],
  intent: "prompt text",
  intentEdited: false,
  title: null,
  titleEdited: false,
};

/** Minimal consumer: exposes open/close/send/detach/clear and prints the state. */
const Harness: React.FC = () => {
  const ctx = useAgentAttachmentsContext();
  if (!ctx) return null;
  const turns = ctx.transcripts["a1"] ?? [];
  return (
    <div>
      <button onClick={() => ctx.openChat("a1")}>open</button>
      <button onClick={() => ctx.closeChat()}>close</button>
      <button onClick={() => void ctx.sendMessage("a1", "hi")}>send</button>
      <button onClick={() => void ctx.sendMessage("a1", "hi", "LIVE-TRILL")}>send-ctx</button>
      <button onClick={() => void ctx.detach("a1")}>detach</button>
      <button onClick={() => void ctx.clearConversation("a1")}>clear</button>
      <button onClick={() => void ctx.saveTitle("a1", "New Name")}>rename</button>
      <button onClick={() => void ctx.applyProposal("a1", "p1").catch(() => undefined)}>
        apply
      </button>
      <button onClick={() => void ctx.solveAttachment("a1").catch(() => undefined)}>solve</button>
      <button onClick={() => void ctx.undoChange("a1", "c1").catch(() => undefined)}>undo-change</button>
      <button onClick={() => void ctx.validateNode("a1", { ref: "ra" }).catch(() => undefined)}>
        validate-node
      </button>
      <button onClick={() => void ctx.runSimulation("a1", "auto").catch(() => undefined)}>
        run-simulation
      </button>
      <button onClick={() => void ctx.cancelSolve("a1")}>cancel-solve</button>
      <button onClick={() => void ctx.solveNode("a1", "n1").catch(() => undefined)}>solve-node</button>
      <div data-testid="solve-node-activity">{ctx.solveNodeActivity["a1"] ?? "∅"}</div>
      <div data-testid="solve-progress">
        {Object.entries(ctx.solveProgress["a1"] ?? {})
          .map(([n, st]) => `${n}:${st}`)
          .join("|") || "∅"}
      </div>
      <div data-testid="solve-errors">
        {Object.entries(ctx.solveErrors["a1"] ?? {})
          .map(([n, e]) => `${n}:${e}`)
          .join("|") || "∅"}
      </div>
      <div data-testid="solve-wave">
        {ctx.solveWave["a1"] ? `${ctx.solveWave["a1"].wave}/${ctx.solveWave["a1"].of}:${ctx.solveWave["a1"].nodeIds.join(",")}` : "∅"}
      </div>
      <div data-testid="solve-notices">
        {Object.entries(ctx.solveNotices["a1"] ?? {})
          .map(([n, e]) => `${n}:${e}`)
          .join("|") || "∅"}
      </div>
      <div data-testid="solve-waiting">
        {(ctx.solveWaiting["a1"] ?? [])
          .map((w) => `${w.nodeId}:${w.kind}`)
          .join("|") || "∅"}
      </div>
      <div data-testid="selected">{ctx.selectedId ?? "none"}</div>
      <div data-testid="hydrating">{ctx.hydratingId ?? "none"}</div>
      <div data-testid="turns">{turns.map((t) => `${t.role}:${t.text}`).join("|")}</div>
      <div data-testid="executions">
        {turns
          .map((t) =>
            t.execution
              ? `${t.execution.executionId}:${t.execution.usage?.inputTokens ?? "∅"}/${t.execution.usage?.outputTokens ?? "∅"}`
              : "∅",
          )
          .join("|")}
      </div>
      <div data-testid="contents">
        {turns
          .map((t) => (t.content?.length ? t.content.map((p) => p.type).join(",") : "∅"))
          .join("|")}
      </div>
      <div data-testid="titles">{ctx.attachments.map((a) => a.title ?? "∅").join(",")}</div>
      <div data-testid="run-status">
        {(() => {
          // dev/80: phase : durationMs? : final usage : interim liveUsage
          const rs = ctx.runStatus["a1"];
          if (!rs) return "∅";
          const usage = rs.usage
            ? `${rs.usage.inputTokens}/${rs.usage.outputTokens}`
            : "∅";
          const live = rs.liveUsage
            ? `${rs.liveUsage.inputTokens}/${rs.liveUsage.outputTokens}`
            : "∅";
          return `${rs.phase}:${typeof rs.durationMs === "number" ? "ms" : "∅"}:${usage}:${live}`;
        })()}
      </div>
    </div>
  );
};

function renderProvider() {
  return render(
    <AgentAttachmentsProvider>
      <Harness />
    </AgentAttachmentsProvider>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  api.listAttachments.mockResolvedValue({ attachments: [attachment] });
  api.getSession.mockResolvedValue({
    attachmentId: "a1",
    sessionId: "s1",
    turns: [
      { role: "user", text: "old-q" },
      { role: "agent", text: "old-a" },
    ],
  });
  api.runAttachment.mockResolvedValue({ attachmentId: "a1", coord: "c", reply: "fresh" });
  api.runAttachmentStream.mockImplementation(async (_p, _a, _m, onDelta) => {
    onDelta("fre");
    onDelta("sh");
    return { reply: "fresh", executionId: "e1", usage: { inputTokens: 7, outputTokens: 9 } };
  });
  // No room holds this tab (no CollaborationProvider): it follows its own
  // asks over HTTP, and a follow finds no ask unless a test scripts one.
  api.followTurn.mockRejectedValue(Object.assign(new Error("no such ask for this attachment"), { status: 404 }));
  api.askTurn.mockResolvedValue({ askId: "x", attachmentId: "a1", state: "running" });
  api.detachAttachment.mockResolvedValue({ attachmentId: "a1", detached: true });
  api.clearSession.mockResolvedValue({ attachmentId: "a1", sessionId: "s1", turns: [] });
  api.updateAttachmentIntent.mockResolvedValue({ ...attachment, intent: "x", intentEdited: true });
  api.updateAttachmentTitle.mockResolvedValue({
    ...attachment,
    title: "New Name",
    titleEdited: true,
  });
});

describe("AgentAttachmentsProvider chat state", () => {
  it("openChat hydrates the transcript from the server session", async () => {
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() =>
      expect(screen.getByTestId("turns")).toHaveTextContent("user:old-q|agent:old-a"),
    );
    expect(api.getSession).toHaveBeenCalledWith("p1", "a1");
  });

  it("close + reopen restores the transcript without refetching", async () => {
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    fireEvent.click(screen.getByText("close"));
    expect(screen.getByTestId("selected")).toHaveTextContent("none");
    fireEvent.click(screen.getByText("open"));
    expect(screen.getByTestId("selected")).toHaveTextContent("a1");
    // Cached transcript still there, no second session fetch.
    expect(screen.getByTestId("turns")).toHaveTextContent("user:old-q|agent:old-a");
    expect(api.getSession).toHaveBeenCalledTimes(1);
  });

  it("sendMessage appends the user turn and the reply", async () => {
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    fireEvent.click(screen.getByText("send"));
    await waitFor(() =>
      expect(screen.getByTestId("turns")).toHaveTextContent(
        "user:old-q|agent:old-a|user:hi|agent:fresh",
      ),
    );
  });

  it("the finalized turn keeps the run's executionId and Actual usage", async () => {
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    fireEvent.click(screen.getByText("send"));
    await waitFor(() =>
      expect(screen.getByTestId("turns")).toHaveTextContent("agent:fresh"),
    );
    // Hydrated turns have no record (old session); the new run's does.
    expect(screen.getByTestId("executions")).toHaveTextContent("∅|∅|∅|e1:7/9");
  });

  it("the finalized turn keeps the run's typed content parts", async () => {
    const parts = [
      { type: "suggestedPrompts" as const, primary: "Next", alternatives: ["Alt"] },
    ];
    api.runAttachmentStream.mockImplementation(async (_p, _a, _m, onDelta) => {
      onDelta("fresh");
      return { reply: "fresh", executionId: "e1", usage: null, content: parts };
    });
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    fireEvent.click(screen.getByText("send"));
    await waitFor(() =>
      expect(screen.getByTestId("turns")).toHaveTextContent("agent:fresh"),
    );
    expect(screen.getByTestId("contents")).toHaveTextContent("∅|∅|∅|suggestedPrompts");
  });

  it("a done frame without execution fields finalizes a plain turn", async () => {
    api.runAttachmentStream.mockImplementation(async (_p, _a, _m, onDelta) => {
      onDelta("fresh");
      return { reply: "fresh" }; // old server: no executionId/usage
    });
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    fireEvent.click(screen.getByText("send"));
    await waitFor(() =>
      expect(screen.getByTestId("turns")).toHaveTextContent("agent:fresh"),
    );
    expect(screen.getByTestId("executions")).toHaveTextContent("∅|∅|∅|∅");
  });

  it("a pre-delta stream failure follows the ask by its id, never asking again", async () => {
    // The turn runs on the server: a broken answer leaves it running there,
    // so the tab follows that ask instead of asking a second time.
    api.runAttachmentStream.mockRejectedValue(new Error("stream broke"));
    api.followTurn.mockImplementation(
      followed(runningView("e3"), { seq: 3, event: "delta", data: { text: "fresh" } },
               { seq: 4, event: "done", data: { reply: "fresh", executionId: "e3", usage: null } }),
    );
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    fireEvent.click(screen.getByText("send"));
    await waitFor(() =>
      expect(screen.getByTestId("turns")).toHaveTextContent("user:hi|agent:fresh"),
    );
    expect(api.followTurn).toHaveBeenCalledTimes(1);
    const askId = api.runAttachmentStream.mock.calls[0][6];
    expect(askId).toMatch(/^[0-9a-f]{32}$/);
    expect(api.followTurn.mock.calls[0].slice(0, 3)).toEqual(["p1", "a1", askId]);
    expect(api.runAttachment).not.toHaveBeenCalled();
    expect(api.runAttachmentStream).toHaveBeenCalledTimes(1);
  });

  it("a broken stream whose ask cannot be followed appends the stream's error turn", async () => {
    api.runAttachmentStream.mockRejectedValue(new Error("stream broke"));
    api.followTurn.mockRejectedValue(Object.assign(new Error("no such ask for this attachment"), { status: 404 }));
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    fireEvent.click(screen.getByText("send"));
    await waitFor(() =>
      expect(screen.getByTestId("turns")).toHaveTextContent("user:hi|agent:(error) stream broke"),
    );
    expect(api.followTurn).toHaveBeenCalledTimes(1);
    expect(api.runAttachment).not.toHaveBeenCalled();
  });

  it("an HTTP error (quota 429) renders directly without a fallback", async () => {
    const denial = Object.assign(new Error("daily agent-run limit reached (200/day)"), {
      status: 429,
      body: { quota: true, resetAt: "2026-07-23T00:00:00+00:00" },
    });
    api.runAttachmentStream.mockRejectedValue(denial);
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    fireEvent.click(screen.getByText("send"));
    await waitFor(() =>
      expect(screen.getByTestId("turns")).toHaveTextContent(/daily agent-run limit reached.*resets/),
    );
    expect(api.runAttachment).not.toHaveBeenCalled();
  });

  it("deltas grow the live agent turn before done finalizes it", async () => {
    let release: () => void = () => undefined;
    api.runAttachmentStream.mockImplementation(async (_p, _a, _m, onDelta) => {
      onDelta("fre");
      await new Promise<void>((r) => {
        release = r;
      });
      onDelta("sh");
      return { reply: "fresh" };
    });
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    fireEvent.click(screen.getByText("send"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("user:hi|agent:fre"));
    release();
    await waitFor(() =>
      expect(screen.getByTestId("turns")).toHaveTextContent("user:hi|agent:fresh"),
    );
  });

  it("detach drops the cached transcript", async () => {
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    await act(async () => {
      fireEvent.click(screen.getByText("detach"));
    });
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent(""));
    expect(api.detachAttachment).toHaveBeenCalledWith("p1", "a1");
  });

  it("clearConversation empties the transcript via the server", async () => {
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    await act(async () => {
      fireEvent.click(screen.getByText("clear"));
    });
    expect(api.clearSession).toHaveBeenCalledWith("p1", "a1");
    expect(screen.getByTestId("turns")).toHaveTextContent("");
  });
});

describe("AgentAttachmentsProvider conversation titles (memo dev/25)", () => {
  it("saveTitle PATCHes the title then reloads the listing", async () => {
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("titles")).toHaveTextContent("∅"));
    api.listAttachments.mockResolvedValue({
      attachments: [{ ...attachment, title: "New Name", titleEdited: true }],
    });
    await act(async () => {
      fireEvent.click(screen.getByText("rename"));
    });
    expect(api.updateAttachmentTitle).toHaveBeenCalledWith("p1", "a1", "New Name");
    await waitFor(() => expect(screen.getByTestId("titles")).toHaveTextContent("New Name"));
  });

  it("a send on an untitled attachment reloads the listing afterwards", async () => {
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    const before = api.listAttachments.mock.calls.length;
    // The server minted a title during the first exchange.
    api.listAttachments.mockResolvedValue({
      attachments: [{ ...attachment, title: "Fresh Title" }],
    });
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    await waitFor(() =>
      expect(api.listAttachments.mock.calls.length).toBe(before + 1),
    );
    await waitFor(() => expect(screen.getByTestId("titles")).toHaveTextContent("Fresh Title"));
  });

  it("a send on an already-titled attachment does not reload", async () => {
    api.listAttachments.mockResolvedValue({
      attachments: [{ ...attachment, title: "Already Titled" }],
    });
    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("titles")).toHaveTextContent("Already Titled"),
    );
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    const before = api.listAttachments.mock.calls.length;
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("agent:fresh"));
    expect(api.listAttachments.mock.calls.length).toBe(before);
  });

  it("a failed send does not reload even when untitled", async () => {
    api.runAttachmentStream.mockRejectedValue(
      Object.assign(new Error("denied"), { status: 429 }),
    );
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    const before = api.listAttachments.mock.calls.length;
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("denied"));
    expect(api.listAttachments.mock.calls.length).toBe(before);
  });
});

describe("AgentAttachmentsProvider review proposals (memo dev/41)", () => {
  it("applyProposal calls the endpoint then refreshes transcript and listing", async () => {
    api.applyProposal.mockResolvedValue({ attachmentId: "a1", proposalId: "p1", status: "applied" });
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    api.getSession.mockClear();
    api.listAttachments.mockClear();
    await act(async () => {
      fireEvent.click(screen.getByText("apply"));
    });
    expect(api.applyProposal).toHaveBeenCalledWith("p1", "a1", "p1");
    // The transcript (statuses + result turn) and the listing (activeProposal
    // mirror) are both refreshed so the outcome arrives together.
    expect(api.getSession).toHaveBeenCalledWith("p1", "a1");
    expect(api.listAttachments).toHaveBeenCalled();
  });

  it("a 409 conflict still refreshes (the proposal was marked stale server-side)", async () => {
    api.applyProposal.mockRejectedValue(
      Object.assign(new Error("the node changed since this was proposed"), { status: 409 }),
    );
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    api.getSession.mockClear();
    await act(async () => {
      fireEvent.click(screen.getByText("apply"));
    });
    expect(api.getSession).toHaveBeenCalledWith("p1", "a1");
  });
});

describe("AgentAttachmentsProvider grounded context (memo dev/44)", () => {
  it("sendMessage forwards the composed context to the stream call", async () => {
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    await act(async () => {
      fireEvent.click(screen.getByText("send-ctx"));
    });
    expect(api.runAttachmentStream).toHaveBeenCalledWith(
      "p1",
      "a1",
      "hi",
      expect.any(Function),
      expect.any(Function),
      "LIVE-TRILL",
      expect.stringMatching(/^[0-9a-f]{32}$/),
    );
  });

  it("a broken stream sends the message and its context once: the ask is followed, never asked again", async () => {
    api.runAttachmentStream.mockRejectedValue(new Error("stream broke"));
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    await act(async () => {
      fireEvent.click(screen.getByText("send-ctx"));
    });
    expect(api.runAttachmentStream).toHaveBeenCalledTimes(1);
    expect(api.runAttachmentStream.mock.calls[0][5]).toBe("LIVE-TRILL");
    const askId = api.runAttachmentStream.mock.calls[0][6];
    expect(api.followTurn.mock.calls.map((call) => call.slice(0, 3))).toEqual([["p1", "a1", askId]]);
    expect(api.runAttachment).not.toHaveBeenCalled();
    expect(api.askTurn).not.toHaveBeenCalled();
  });
});

describe("AgentAttachmentsProvider apply→canvas bridge (memo dev/48 §3.3)", () => {
  const events: unknown[] = [];
  let unsubscribe: () => void = () => undefined;

  beforeEach(() => {
    events.length = 0;
    const { subscribeAgentCanvasMutations } = jest.requireActual(
      "../../services/agents/agentEvents",
    );
    unsubscribe = subscribeAgentCanvasMutations((m: unknown) => events.push(m));
  });

  afterEach(() => unsubscribe());

  it("a change that landed during a reply reaches the canvas from its stream event, marked landed", async () => {
    const canvas = { kind: "node-created", node: { id: "nid", type: "curio.builtin/computation-analysis", content: "c", x: 1, y: 2 } };
    api.runAttachmentStream.mockImplementation(async (_p, _a, _m, onDelta, onEvent) => {
      onEvent?.("change", { changeId: "c1", attachmentId: "a1", tool: "node.create", canvas });
      onDelta("added");
      return { reply: "added", executionId: "e1", content: [{ type: "change", changeId: "c1" } as never] };
    });
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    api.listAttachments.mockClear();
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    expect(events).toEqual([{ ...canvas, landed: true }]);
    // The change moved the attachment's changes and plan: the listing reloads.
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalled());
  });

  it("a change a followed ask lands after the tab follows it reaches the canvas, marked landed", async () => {
    const canvas = { kind: "node-content-applied" as const, nodeId: "n1", content: "print(2)", agent: "Node Builder" };
    api.runAttachmentStream.mockRejectedValue(new Error("stream broke"));
    api.followTurn.mockImplementation(
      followed(
        runningView("e1"),
        { seq: 3, event: "change", data: { changeId: "c1", attachmentId: "a1", tool: "node.content.write", canvas } },
        { seq: 4, event: "done", data: { reply: "written", executionId: "e1", usage: null } },
      ),
    );
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    expect(events).toEqual([{ ...canvas, landed: true }]);
    expect(api.runAttachment).not.toHaveBeenCalled();
  });

  it("an Undo posts the change, hands its answer's canvas mutations on marked landed, and refreshes", async () => {
    const restored = { kind: "node-content-applied" as const, nodeId: "n1", content: "print(1)", agent: "Undid Node Builder's change" };
    api.undoChange.mockResolvedValue({ attachmentId: "a1", changeId: "c1", status: "undone", canvas: [restored] });
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    api.getSession.mockClear();
    api.listAttachments.mockClear();
    await act(async () => {
      fireEvent.click(screen.getByText("undo-change"));
    });
    expect(api.undoChange).toHaveBeenCalledWith("p1", "a1", "c1");
    expect(events).toEqual([{ ...restored, landed: true }]);
    // The card says undone, from the transcript and the listing.
    expect(api.getSession).toHaveBeenCalledWith("p1", "a1");
    expect(api.listAttachments).toHaveBeenCalled();
  });

  it("an Undo someone refused (they changed it after) changes nothing on the canvas and still refreshes", async () => {
    api.undoChange.mockRejectedValue(
      Object.assign(new Error("Ana changed this node after; nothing was undone."), { status: 409 }),
    );
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    api.getSession.mockClear();
    await act(async () => {
      fireEvent.click(screen.getByText("undo-change"));
    });
    expect(events).toEqual([]);
    expect(api.getSession).toHaveBeenCalledWith("p1", "a1");
  });

  it("a validated node's code that landed reaches the canvas from the validate stream", async () => {
    const canvas = { kind: "node-content-applied", nodeId: "n1", content: "x = 2", agent: "Node Builder" };
    api.validateNode.mockImplementation(async (_p, _a, _t, onEvent) => {
      onEvent("round_verdict", { round: 1, verdict: "pass" });
      onEvent("change", { changeId: "c9", attachmentId: "a2", tool: "node.content.write", canvas });
      return { verdict: "pass", changeId: "c9" };
    });
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    await act(async () => {
      fireEvent.click(screen.getByText("validate-node"));
    });
    expect(api.validateNode).toHaveBeenCalledWith("p1", "a1", { ref: "ra" }, expect.any(Function));
    expect(events).toEqual([{ ...canvas, landed: true }]);
  });

  // dev/105 A4 — the third live test: a package.install apply re-enlisted the
  // notes package, but the result carried no requiresRegistryRefresh, so the
  // registry stayed stale and the notes painted "Loading node…". The install
  // apply now declares the lockfile change; the SAME bridge branch pulses the
  // registry, here with no notes to place.
  it("a package-install apply dispatches package-nodes-created with no nodes (dev/105 A4)", async () => {
    api.applyProposal.mockResolvedValue({
      attachmentId: "a1",
      proposalId: "p1",
      status: "applied",
      mutationApplied: true,
      requiresRegistryRefresh: true,
      installedPackage: { dirName: "curio.notes@1", name: "Simple Notes" },
    });
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    await act(async () => {
      fireEvent.click(screen.getByText("apply"));
    });
    expect(events).toEqual([
      {
        kind: "package-nodes-created",
        artifactDigest: "p1",
        packageDir: "curio.notes@1",
        nodes: [],
      },
    ]);
  });

  it("a package-draft apply dispatches package-nodes-created (dev/89 registry-before-canvas)", async () => {
    api.applyProposal.mockResolvedValue({
      attachmentId: "a1",
      proposalId: "p1",
      status: "applied",
      mutationApplied: true,
      requiresRegistryRefresh: true,
      installedPackage: { dirName: "ai.agent.notes@1", name: "Agent Notes" },
      createdNodes: [
        {
          id: "note-1",
          type: "ai.agent.notes/note-kind@1",
          content: "# Findings",
          x: 3,
          y: 4,
          title: "Research note",
          metadata: { appearance: { backgroundColor: "#fbd3e0" } },
        },
      ],
    });
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    await act(async () => {
      fireEvent.click(screen.getByText("apply"));
    });
    expect(events).toEqual([
      {
        kind: "package-nodes-created",
        artifactDigest: "p1",
        packageDir: "ai.agent.notes@1",
        nodes: [
          {
            id: "note-1",
            type: "ai.agent.notes/note-kind@1",
            content: "# Findings",
            x: 3,
            y: 4,
            title: "Research note",
            metadata: { appearance: { backgroundColor: "#fbd3e0" } },
          },
        ],
      },
    ]);
  });

  it("a project.install apply repaints the AGENTS palette (dev/106)", async () => {
    api.applyProposal.mockResolvedValue({
      attachmentId: "a1",
      proposalId: "p1",
      status: "applied",
      installedCoord: "agent.curio.node-builder@1",
    });
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    await act(async () => {
      fireEvent.click(screen.getByText("apply"));
    });
    await waitFor(() => expect(mockPaletteRefresh).toHaveBeenCalledTimes(1));
  });

  it("a plain apply response (project.install / legacy) dispatches nothing", async () => {
    api.applyProposal.mockResolvedValue({
      attachmentId: "a1",
      proposalId: "p1",
      status: "applied",
      installedCoord: "agent.curio.node-builder@1",
    });
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    await act(async () => {
      fireEvent.click(screen.getByText("apply"));
    });
    expect(events).toEqual([]);
  });
});

describe("AgentAttachmentsProvider delegate activity lines (memo dev/48)", () => {
  it("delegate events render transient lines and clear on finalize", async () => {
    const seen: string[][] = [];
    api.runAttachmentStream.mockImplementation(async (_p, _a, _m, onDelta, onEvent) => {
      onEvent?.("delegate_requested", { capability: "node.content.generate" });
      onEvent?.("delegate_started", { capability: "node.content.generate", coord: "agent.curio.node-builder@1" });
      onEvent?.("delegate_result", { capability: "node.content.generate", coord: "agent.curio.node-builder@1", status: "ok", durationMs: 12 });
      onDelta("done");
      return { reply: "done", executionId: "e9", usage: null };
    });
    const Probe: React.FC = () => {
      const ctx = useAgentAttachmentsContext();
      if (!ctx) return null;
      seen.push(ctx.toolActivity["a1"] ?? []);
      return (
        <button onClick={() => void ctx.sendMessage("a1", "go")}>send-delegate</button>
      );
    };
    render(
      <AgentAttachmentsProvider>
        <Probe />
      </AgentAttachmentsProvider>,
    );
    await act(async () => {
      fireEvent.click(screen.getByText("send-delegate"));
    });
    const flat = seen.flat();
    expect(flat).toContain("delegating node.content.generate …");
    expect(flat).toContain("agent.curio.node-builder@1 · ok");
    // Transient: cleared once the turn finalizes.
    expect(seen[seen.length - 1]).toEqual([]);
  });
});

describe("AgentAttachmentsProvider lines that stay under a reply (#447, #243)", () => {
  const REFUSAL =
    "refused by the egress policy: host '127.0.0.1' resolves to a non-public address (127.0.0.1) - refused";
  const NO_CHANGE = "No changes were made to the canvas";
  // What the Node Builder's manifest declares: the panel says a reply changed
  // nothing for an agent that declares node.build.
  const nodeBuilder = {
    ...attachment,
    coord: "agent.curio.node-builder@1",
    name: "Node Builder",
    capabilities: ["node.build", "dataset.fetch.author", "node.content.generate"],
  };

  /** The live chat: the provider's transcript and tool lines in the real panel. */
  function renderChat(chat: typeof attachment, seen: string[][] = []) {
    const ChatProbe: React.FC = () => {
      const ctx = useAgentAttachmentsContext();
      if (!ctx) return null;
      seen.push(ctx.toolActivity["a1"] ?? []);
      return (
        <>
          <button onClick={() => void ctx.sendMessage("a1", "go")}>send-go</button>
          <AgentChatPanel
            attachment={chat}
            turns={ctx.transcripts["a1"] ?? []}
            toolActivity={ctx.toolActivity["a1"] ?? []}
            onSend={async () => undefined}
            onClose={() => undefined}
          />
        </>
      );
    };
    return render(
      <MemoryRouter>
        <AgentAttachmentsProvider>
          <ChatProbe />
        </AgentAttachmentsProvider>
      </MemoryRouter>,
    );
  }

  it("a refused web.fetch keeps its reason under the reply once the turn ends (#447)", async () => {
    api.runAttachmentStream.mockImplementation(async (_p, _a, _m, onDelta, onEvent) => {
      onEvent?.("tool_requested", { tool: "web.fetch" });
      onEvent?.("tool_started", { tool: "web.fetch" });
      onEvent?.("tool_result", { tool: "web.fetch", status: "error", reason: REFUSAL, egress: true });
      onDelta("I could not reach that address.");
      return { reply: "I could not reach that address.", executionId: "e5", usage: null };
    });
    const seen: string[][] = [];
    renderChat(attachment, seen);
    await act(async () => {
      fireEvent.click(screen.getByText("send-go"));
    });
    // While the run streams, the tool line already names the refusal...
    expect(seen.flat()).toContain(`web.fetch · ${REFUSAL}`);
    // ...the transient lines are gone once the turn ends...
    expect(seen[seen.length - 1]).toEqual([]);
    // ...and the refusal stays under the reply.
    expect(screen.getByText("I could not reach that address.")).toBeInTheDocument();
    expect(screen.getByText(`web.fetch · ${REFUSAL}`)).toBeInTheDocument();
  });

  it("a Node Builder reply with only a dataflow.read call says nothing changed on the canvas (#243)", async () => {
    api.runAttachmentStream.mockImplementation(async (_p, _a, _m, onDelta, onEvent) => {
      onEvent?.("tool_requested", { tool: "dataflow.read" });
      onEvent?.("tool_started", { tool: "dataflow.read" });
      onEvent?.("tool_result", { tool: "dataflow.read", status: "ok" });
      onDelta("I have now added a new node to your dataflow.");
      return { reply: "I have now added a new node to your dataflow.", executionId: "e6", usage: null };
    });
    renderChat(nodeBuilder);
    await act(async () => {
      fireEvent.click(screen.getByText("send-go"));
    });
    expect(screen.getByText("I have now added a new node to your dataflow.")).toBeInTheDocument();
    expect(screen.getByText(NO_CHANGE)).toBeInTheDocument();
  });

  it("a Node Builder reply that holds a node it added does not (#243)", async () => {
    api.runAttachmentStream.mockImplementation(async (_p, _a, _m, onDelta, onEvent) => {
      onEvent?.("tool_requested", { tool: "node.create" });
      onEvent?.("tool_result", { tool: "node.create", status: "applied" });
      onDelta("I added the node.");
      return {
        reply: "I added the node.",
        executionId: "e7",
        usage: null,
        content: [
          {
            type: "change",
            changeId: "c1",
            tool: "node.create",
            kind: "node",
            summary: "Created a new Python node",
            preview: "print(1)",
            status: "applied",
            lines: ["Python · COMPUTATION_ANALYSIS", "node n1"],
          },
        ],
      } as never;
    });
    renderChat(nodeBuilder);
    await act(async () => {
      fireEvent.click(screen.getByText("send-go"));
    });
    expect(screen.getByText("I added the node.")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Change: Created a new Python node" })).toBeInTheDocument();
    expect(screen.queryByText(NO_CHANGE)).not.toBeInTheDocument();
  });

  it("a request for a tool the agent is not granted leaves no line (#447)", async () => {
    api.runAttachmentStream.mockImplementation(async (_p, _a, _m, onDelta, onEvent) => {
      onEvent?.("tool_requested", { tool: "dataflow.read" });
      // What the server sends for it: refused to the model only, with no reason.
      onEvent?.("tool_result", { tool: "dataflow.read", status: "refused" });
      onDelta("Done without it.");
      return { reply: "Done without it.", executionId: "e8", usage: null };
    });
    renderChat(attachment);
    await act(async () => {
      fireEvent.click(screen.getByText("send-go"));
    });
    expect(screen.getByText("Done without it.")).toBeInTheDocument();
    expect(screen.queryByText(/^dataflow\.read ·/)).not.toBeInTheDocument();
  });

  it("a node.create the turn recovered from leaves no line beside the change that landed (#447)", async () => {
    api.runAttachmentStream.mockImplementation(async (_p, _a, _m, onDelta, onEvent) => {
      onEvent?.("tool_requested", { tool: "node.create" });
      onEvent?.("tool_result", {
        tool: "node.create",
        status: "refused",
        reason: "template.content must be a non-empty string",
      });
      onEvent?.("tool_requested", { tool: "node.create" });
      onEvent?.("tool_result", { tool: "node.create", status: "applied" });
      onDelta("I added the node.");
      return {
        reply: "I added the node.",
        executionId: "e10",
        usage: null,
        content: [
          {
            type: "change",
            changeId: "c2",
            tool: "node.create",
            kind: "node",
            summary: "Created a new Python node",
            preview: "print(1)",
            status: "applied",
            lines: [],
          },
        ],
      } as never;
    });
    renderChat(nodeBuilder);
    await act(async () => {
      fireEvent.click(screen.getByText("send-go"));
    });
    expect(screen.getByRole("group", { name: "Change: Created a new Python node" })).toBeInTheDocument();
    expect(screen.queryByText(/^node\.create ·/)).not.toBeInTheDocument();
    expect(screen.queryByText(NO_CHANGE)).not.toBeInTheDocument();
  });

  it("a change still keeps the reason of a failed call no later call of its tool recovered (#447)", async () => {
    api.runAttachmentStream.mockImplementation(async (_p, _a, _m, onDelta, onEvent) => {
      onEvent?.("tool_requested", { tool: "node.settings.write" });
      onEvent?.("tool_result", { tool: "node.settings.write", status: "refused", reason: "no such setting" });
      onEvent?.("tool_requested", { tool: "node.create" });
      onEvent?.("tool_result", { tool: "node.create", status: "applied" });
      onDelta("Added; the setting is not one it has.");
      return { reply: "Added; the setting is not one it has.", executionId: "e11", usage: null } as never;
    });
    renderChat(nodeBuilder);
    await act(async () => {
      fireEvent.click(screen.getByText("send-go"));
    });
    expect(screen.getByText("node.settings.write · no such setting")).toBeInTheDocument();
  });
});

describe("AgentAttachmentsProvider follow payload parity (dev/53)", () => {
  it("a pre-delta stream failure's followed ask keeps the content parts (the change card renders)", async () => {
    api.runAttachmentStream.mockRejectedValue(new Error("stream transport failed"));
    api.followTurn.mockImplementation(
      followed(runningView("e7"), {
        seq: 3,
        event: "done",
        data: {
          reply: "Here is the plan.",
          executionId: "e7",
          usage: { inputTokens: 5, outputTokens: 6 },
          content: [
            {
              type: "change",
              changeId: "c9",
              tool: "dataflow.plan.write",
              kind: "plan",
              planId: "plan-9",
              summary: "Plan · 2 nodes, 1 edges",
              preview: "Load…",
              status: "applied",
              lines: ["+2 nodes · +1 connection"],
            },
          ],
        },
      }),
    );
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    expect(api.followTurn).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("turns")).toHaveTextContent("Here is the plan.");
    // The followed turn carries the parts AND the execution record.
    expect(screen.getByTestId("contents")).toHaveTextContent("change");
    expect(screen.getByTestId("executions")).toHaveTextContent("e7:5/6");
    // A change that landed still triggers the listing reload (its changes, its plan).
    expect(api.listAttachments.mock.calls.length).toBeGreaterThan(1);
    expect(api.runAttachment).not.toHaveBeenCalled();
  });
});

describe("AgentAttachmentsProvider streamed solve (dev/63)", () => {
  const events: unknown[] = [];
  let unsubscribe: () => void = () => undefined;

  beforeEach(() => {
    events.length = 0;
    const { subscribeAgentCanvasMutations } = jest.requireActual(
      "../../services/agents/agentEvents",
    );
    unsubscribe = subscribeAgentCanvasMutations((m: unknown) => events.push(m));
  });

  afterEach(() => unsubscribe());

  it("records each failed node's reason from node_result and clears it when the next solve starts (dev/106)", async () => {
    let emit: (name: string, payload: Record<string, unknown>) => void = () => undefined;
    // Typed as the stream's own resolution: `res` below is that promise's
    // resolve, so a bare `unknown` parameter is not assignable to it.
    let finish: (r: Awaited<ReturnType<typeof api.solveAttachmentStream>>) => void =
      () => undefined;
    api.solveAttachmentStream.mockImplementation(
      (_p: string, _a: string, onEvent: (n: string, pl: Record<string, unknown>) => void) => {
        emit = onEvent;
        return new Promise((res) => {
          finish = res as (r: unknown) => void;
        }) as ReturnType<typeof api.solveAttachmentStream>;
      },
    );
    renderProvider();
    fireEvent.click(screen.getByText("solve"));
    await waitFor(() => expect(api.solveAttachmentStream).toHaveBeenCalled());
    const reason = "specialist not installed: Node Builder is not installed in this project";
    act(() => {
      emit("node_result", { nodeId: "n1", status: "failed", error: reason });
      emit("node_result", { nodeId: "n2", status: "failed", error: reason });
    });
    expect(screen.getByTestId("solve-errors")).toHaveTextContent(`n1:${reason}|n2:${reason}`);
    await act(async () => {
      finish({
        attachmentId: "a1",
        executionId: "e1",
        results: { n1: { status: "failed", error: reason }, n2: { status: "failed", error: reason } },
        appliedContents: [],
        builderSession: { phase: "applied" },
        reason,
      });
    });
    // Survives done (the pills need their why) …
    expect(screen.getByTestId("solve-errors")).toHaveTextContent("n1:");
    // … and clears the moment the next batch starts.
    fireEvent.click(screen.getByText("solve"));
    await waitFor(() => expect(api.solveAttachmentStream).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("solve-errors")).toHaveTextContent("∅");
    await act(async () => {
      finish({ attachmentId: "a1", executionId: "e2", results: {}, appliedContents: [], builderSession: { phase: "ready" } });
    });
  });

  it("dev/137: a later result clears what an earlier pass said about the node", async () => {
    let emit: (name: string, payload: Record<string, unknown>) => void = () => undefined;
    let finish: (r: Awaited<ReturnType<typeof api.solveAttachmentStream>>) => void = () => undefined;
    api.solveAttachmentStream.mockImplementation(
      (_p: string, _a: string, onEvent: (n: string, pl: Record<string, unknown>) => void) => {
        emit = onEvent;
        return new Promise((res) => {
          finish = res as (r: unknown) => void;
        }) as ReturnType<typeof api.solveAttachmentStream>;
      },
    );
    renderProvider();
    fireEvent.click(screen.getByText("solve"));
    await waitFor(() => expect(api.solveAttachmentStream).toHaveBeenCalled());
    // Pass 1: n1 fails, n2 waits on it. This is the owner's `7a27b702` panel.
    act(() => {
      emit("solve_pass", { pass: 1, targets: ["n1", "n2"], waiting: [] });
      emit("node_result", { nodeId: "n1", status: "failed",
        error: "not fixed after 15 attempts: execution-error: SyntaxError: invalid syntax" });
      emit("node_result", { nodeId: "n2", status: "pending",
        reason: "upstream node 'n1' has no content yet; solve or fill it first" });
    });
    expect(screen.getByTestId("solve-errors")).toHaveTextContent("n1:not fixed after 15 attempts");
    expect(screen.getByTestId("solve-notices")).toHaveTextContent("n2:pending: upstream node 'n1' has no content yet");
    // Pass 2 attempts them again: the previous pass's lines go FIRST.
    act(() => {
      emit("solve_pass", { pass: 2, targets: ["n1", "n2"], waiting: [] });
    });
    expect(screen.getByTestId("solve-errors")).toHaveTextContent("∅");
    expect(screen.getByTestId("solve-notices")).toHaveTextContent("∅");
    // …and when they solve, nothing contradicts the pill.
    act(() => {
      emit("node_result", { nodeId: "n1", status: "solved", verdict: "pass", content: "df" });
      emit("node_result", { nodeId: "n2", status: "solved", verdict: "pass", content: "df" });
    });
    expect(screen.getByTestId("solve-errors")).toHaveTextContent("∅");
    expect(screen.getByTestId("solve-progress")).toHaveTextContent("n1:verified|n2:verified");
    await act(async () => {
      finish({
        attachmentId: "a1", executionId: "e1",
        results: { n1: { status: "solved" }, n2: { status: "solved" } },
        appliedContents: [], builderSession: { phase: "ready" },
        endedBy: "complete",
        waiting: [{ nodeId: "n2", kind: "upstream", reason: "upstream node 'n1' has no content yet" }],
      } as never);
    });
    // A session that finished everything waits for nothing — the other half of
    // the contradiction ("Finished — nothing left to do" over a pending line).
    expect(screen.getByTestId("solve-waiting")).toHaveTextContent("∅");
  });

  it("dev/137: a session that did NOT finish keeps saying what it waits for", async () => {
    let finish: (r: Awaited<ReturnType<typeof api.solveAttachmentStream>>) => void = () => undefined;
    api.solveAttachmentStream.mockImplementation(
      () => new Promise((res) => {
        finish = res as (r: unknown) => void;
      }) as ReturnType<typeof api.solveAttachmentStream>,
    );
    renderProvider();
    fireEvent.click(screen.getByText("solve"));
    await waitFor(() => expect(api.solveAttachmentStream).toHaveBeenCalled());
    await act(async () => {
      finish({
        attachmentId: "a1", executionId: "e1", results: {}, appliedContents: [],
        builderSession: { phase: "applied" },
        endedBy: "budget",
        waiting: [{ nodeId: "n9", kind: "dataset-selection", reason: "awaiting your selection" }],
      } as never);
    });
    expect(screen.getByTestId("solve-waiting")).toHaveTextContent("n9:dataset-selection");
  });

  it("dev/118: waves, written-not-executed pills and pending/skipped notices ride the stream and clear on done", async () => {
    let emit: (name: string, payload: Record<string, unknown>) => void = () => undefined;
    let finish: (r: Awaited<ReturnType<typeof api.solveAttachmentStream>>) => void = () => undefined;
    api.solveAttachmentStream.mockImplementation(
      (_p: string, _a: string, onEvent: (n: string, pl: Record<string, unknown>) => void) => {
        emit = onEvent;
        return new Promise((res) => {
          finish = res;
        }) as ReturnType<typeof api.solveAttachmentStream>;
      },
    );
    renderProvider();
    fireEvent.click(screen.getByText("solve"));
    await waitFor(() => expect(api.solveAttachmentStream).toHaveBeenCalled());
    act(() => {
      emit("solve_wave", { wave: 1, of: 2, nodeIds: ["n1", "v1"] });
      emit("node_started", { nodeId: "n1" });
      emit("node_result", { nodeId: "n1", status: "solved", verdict: "pass", content: "df" });
      emit("node_result", { nodeId: "v1", status: "solved", content: "{}",
        verification: { status: "not-executable", reason: "vis-vega has no code the sandbox could run; written, not executed" } });
      emit("solve_wave", { wave: 2, of: 2, nodeIds: ["n2"] });
      emit("node_result", { nodeId: "n2", status: "pending", reason: "the batch's time budget (45 min) was spent; Retry continues from here" });
    });
    expect(screen.getByTestId("solve-wave")).toHaveTextContent("2/2:n2");
    expect(screen.getByTestId("solve-progress")).toHaveTextContent("n1:verified|v1:written|n2:pending");
    expect(screen.getByTestId("solve-notices")).toHaveTextContent(
      "v1:vis-vega has no code the sandbox could run; written, not executed|n2:pending: the batch's time budget (45 min) was spent; Retry continues from here",
    );
    expect(screen.getByTestId("solve-errors")).toHaveTextContent("∅"); // notices are not errors
    await act(async () => {
      finish({ attachmentId: "a1", executionId: "e1", results: {}, appliedContents: [], builderSession: { phase: "applied" } });
    });
    expect(screen.getByTestId("solve-wave")).toHaveTextContent("∅"); // the wave clears with the overlay
    expect(screen.getByTestId("solve-notices")).not.toHaveTextContent("∅"); // notices stay until the next solve
  });

  it("overlays per-node progress, applies solved content live, and clears on done", async () => {
    let emit: (name: string, payload: Record<string, unknown>) => void = () => undefined;
    // Typed as the stream's own resolution: `res` below is that promise's
    // resolve, so a bare `unknown` parameter is not assignable to it.
    let finish: (r: Awaited<ReturnType<typeof api.solveAttachmentStream>>) => void =
      () => undefined;
    api.solveAttachmentStream.mockImplementation(
      (_p: string, _a: string, onEvent: (n: string, pl: Record<string, unknown>) => void) => {
        emit = onEvent;
        return new Promise((res) => {
          finish = res;
        }) as ReturnType<typeof api.solveAttachmentStream>;
      },
    );
    renderProvider();
    fireEvent.click(screen.getByText("solve"));
    await waitFor(() => expect(api.solveAttachmentStream).toHaveBeenCalled());
    act(() => {
      emit("node_started", { nodeId: "n1" });
      emit("node_result", { nodeId: "n1", status: "solved", content: "print(9)" });
      emit("node_started", { nodeId: "n2" });
    });
    // The live overlay: n1 terminal, n2 in flight.
    expect(screen.getByTestId("solve-progress")).toHaveTextContent("n1:solved|n2:solving");
    // Solved content reached the canvas bridge AS the node finished.
    expect(events).toEqual([
      { kind: "node-content-applied", nodeId: "n1", content: "print(9)" },
    ]);
    await act(async () => {
      finish({
        attachmentId: "a1",
        executionId: "e1",
        results: { n1: { status: "solved" } },
        appliedContents: [{ nodeId: "n1", content: "print(9)" }],
        builderSession: { phase: "ready" },
      });
    });
    // Terminal: the overlay clears — the refetched session is the truth.
    expect(screen.getByTestId("solve-progress")).toHaveTextContent("∅");
    expect(events).toHaveLength(1); // no double-apply from the done payload
  });

  it("solved content reaches the canvas with the name of the agent that wrote it", async () => {
    let emit: (name: string, payload: Record<string, unknown>) => void = () => undefined;
    api.solveAttachmentStream.mockImplementation(
      (_p: string, _a: string, onEvent: (n: string, pl: Record<string, unknown>) => void) => {
        emit = onEvent;
        return new Promise(() => undefined) as ReturnType<typeof api.solveAttachmentStream>;
      },
    );
    renderProvider();
    fireEvent.click(screen.getByText("solve"));
    await waitFor(() => expect(api.solveAttachmentStream).toHaveBeenCalled());
    act(() => {
      emit("node_started", { nodeId: "n1" });
      emit("node_result", { nodeId: "n1", status: "solved", content: "print(9)", agent: "Node Builder" });
    });
    expect(events).toEqual([
      { kind: "node-content-applied", nodeId: "n1", content: "print(9)", agent: "Node Builder" },
    ]);
  });



  it("runSimulation hands each validated node's landed code to the canvas bridge, marked landed (dev/67-9)", async () => {
    const first = { kind: "node-content-applied", nodeId: "n1", content: "print(1)", agent: "Node Builder" };
    const second = { kind: "node-content-applied", nodeId: "n2", content: "print(2)", agent: "Node Builder" };
    api.simulate.mockImplementation(
      async (_p: string, _a: string, _m: string, onEvent: (n: string, pl: Record<string, unknown>) => void) => {
        onEvent("stage", { action: "validate", ref: "a", label: "Load" });
        onEvent("change", { changeId: "c1", attachmentId: "a2", tool: "node.content.write", canvas: first });
        onEvent("action_result", { action: "validate", ref: "a", outcome: "pass", changeId: "c1" });
        onEvent("change", { changeId: "c2", attachmentId: "a3", tool: "node.content.write", canvas: second });
        return { status: "completed", mode: "auto" };
      },
    );
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("run-simulation"));
    });
    expect(events).toEqual([{ ...first, landed: true }, { ...second, landed: true }]);
  });

  it("runSimulation's other events reach no canvas: a failure pauses with nothing written", async () => {
    api.simulate.mockImplementation(
      async (_p: string, _a: string, _m: string, onEvent: (n: string, pl: Record<string, unknown>) => void) => {
        onEvent("stage", { action: "validate", ref: "a", label: "Load" });
        onEvent("action_result", { action: "validate", ref: "a", outcome: "fail" });
        return { status: "paused", mode: "auto", reason: { kind: "validation-failed", ref: "a", message: "m" } };
      },
    );
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("run-simulation"));
    });
    expect(events).toEqual([]);
  });

  it("cancelSolve posts the cancel endpoint for the attachment", async () => {
    api.cancelSolve.mockResolvedValue({ attachmentId: "a1", cancelRequested: true });
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("cancel-solve"));
    });
    expect(api.cancelSolve).toHaveBeenCalledWith("p1", "a1");
  });
});

describe("AgentAttachmentsProvider run status (memo dev/80)", () => {
  it("a send flips running → done with duration and Actual usage", async () => {
    let release: () => void = () => undefined;
    api.runAttachmentStream.mockImplementation(async (_p, _a, _m, onDelta) => {
      onDelta("fre");
      await new Promise<void>((r) => {
        release = r;
      });
      onDelta("sh");
      return {
        reply: "fresh",
        executionId: "e1",
        usage: { inputTokens: 7, outputTokens: 9 },
        durationMs: 1234,
      };
    });
    renderProvider();
    fireEvent.click(screen.getByText("send"));
    await waitFor(() =>
      expect(screen.getByTestId("run-status")).toHaveTextContent(/^running/),
    );
    await act(async () => release());
    await waitFor(() =>
      expect(screen.getByTestId("run-status")).toHaveTextContent("done:ms:7/9:∅"),
    );
  });

  it("interim usage events feed liveUsage while running, dropped on finalize", async () => {
    let release: () => void = () => undefined;
    api.runAttachmentStream.mockImplementation(async (_p, _a, _m, onDelta, onEvent) => {
      onDelta("fre");
      onEvent?.("usage", { usage: { inputTokens: 3, outputTokens: 4 } });
      await new Promise<void>((r) => {
        release = r;
      });
      return {
        reply: "fresh",
        executionId: "e1",
        usage: { inputTokens: 7, outputTokens: 9 },
      };
    });
    renderProvider();
    fireEvent.click(screen.getByText("send"));
    await waitFor(() =>
      expect(screen.getByTestId("run-status")).toHaveTextContent("running:∅:∅:3/4"),
    );
    await act(async () => release());
    // Finalize replaces the entry: the persisted usage is the truth, no
    // interim leftovers to double-count.
    await waitFor(() =>
      expect(screen.getByTestId("run-status")).toHaveTextContent("done:ms:7/9:∅"),
    );
  });

  it("a broken stream whose ask cannot be followed finalizes to error", async () => {
    api.runAttachmentStream.mockRejectedValue(new Error("stream broke"));
    api.followTurn.mockRejectedValue(Object.assign(new Error("no such ask for this attachment"), { status: 404 }));
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    expect(api.followTurn).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("run-status")).toHaveTextContent("error:ms:∅:∅");
  });

  it("a followed ask still finalizes done", async () => {
    api.runAttachmentStream.mockRejectedValue(new Error("stream broke"));
    api.followTurn.mockImplementation(
      followed(runningView("e2"), {
        seq: 3,
        event: "done",
        data: { reply: "fresh", executionId: "e2", usage: { inputTokens: 1, outputTokens: 2 }, durationMs: 55 },
      }),
    );
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    expect(screen.getByTestId("run-status")).toHaveTextContent("done:ms:1/2:∅");
  });

  it("clearConversation drops the run status with the transcript", async () => {
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    expect(screen.getByTestId("run-status")).toHaveTextContent(/^done/);
    await act(async () => {
      fireEvent.click(screen.getByText("clear"));
    });
    expect(screen.getByTestId("run-status")).toHaveTextContent("∅");
  });

  it("never commits the finalized (execution-carrying) turn before the done status", async () => {
    // The dev/80 ordering guarantee: the render commit that first contains
    // the finalized turn (its execution record landed) already reports the
    // finished status — no frame shows the final message beside "running".
    const snapshots: Array<{ hasExecution: boolean; phase: string }> = [];
    const Recorder: React.FC = () => {
      const ctx = useAgentAttachmentsContext();
      if (!ctx) return null;
      const turns = ctx.transcripts["a1"] ?? [];
      const last = turns[turns.length - 1];
      snapshots.push({
        hasExecution: Boolean(last && last.role === "agent" && last.execution),
        phase: ctx.runStatus["a1"]?.phase ?? "none",
      });
      return <button onClick={() => void ctx.sendMessage("a1", "hi")}>send-rec</button>;
    };
    render(
      <AgentAttachmentsProvider>
        <Recorder />
      </AgentAttachmentsProvider>,
    );
    await act(async () => {
      fireEvent.click(screen.getByText("send-rec"));
    });
    expect(snapshots.some((s) => s.hasExecution)).toBe(true);
    expect(snapshots.filter((s) => s.hasExecution && s.phase !== "done")).toEqual([]);
  });
});


describe("AgentAttachmentsProvider — dev/115 verified Solve as a background job", () => {
  it("the verified loop's stream events drive the pills: generating → verifying → verified", async () => {
    let emit: (name: string, payload: Record<string, unknown>) => void = () => undefined;
    let finish: (r: Awaited<ReturnType<typeof api.solveAttachmentStream>>) => void = () => undefined;
    api.solveAttachmentStream.mockImplementation(
      (_p: string, _a: string, onEvent: (n: string, pl: Record<string, unknown>) => void) => {
        emit = onEvent;
        return new Promise((res) => {
          finish = res;
        }) as ReturnType<typeof api.solveAttachmentStream>;
      },
    );
    renderProvider();
    fireEvent.click(screen.getByText("solve"));
    await waitFor(() => expect(api.solveAttachmentStream).toHaveBeenCalled());
    act(() => {
      emit("node_started", { nodeId: "n1" });
      emit("node_round", { nodeId: "n1", round: 1 });
    });
    expect(screen.getByTestId("solve-progress")).toHaveTextContent("n1:generating");
    act(() => emit("node_executed", { nodeId: "n1", index: 0, total: 1 }));
    expect(screen.getByTestId("solve-progress")).toHaveTextContent("n1:verifying");
    act(() => emit("node_verdict", { nodeId: "n1", round: 1, verdict: "fail" }));
    expect(screen.getByTestId("solve-progress")).toHaveTextContent("n1:fixing");
    act(() => {
      emit("node_verdict", { nodeId: "n1", round: 2, verdict: "pass" });
      emit("node_result", { nodeId: "n1", status: "solved", verdict: "pass", content: "df" });
    });
    expect(screen.getByTestId("solve-progress")).toHaveTextContent("n1:verified");
    await act(async () => {
      finish({ attachmentId: "a1", executionId: "e1", results: { n1: { status: "solved", verdict: "pass" } },
               appliedContents: [{ nodeId: "n1", content: "df" }], builderSession: { phase: "ready" } });
    });
    expect(screen.getByTestId("solve-progress")).toHaveTextContent("∅");
  });

  it("opening a chat whose attachment carries a running job re-attaches once and refreshes on done", async () => {
    api.listAttachments.mockResolvedValue({
      attachments: [{ ...attachment, liveJob: { executionId: "e9", kind: "solve-batch", status: "running", startedAt: 1 } }],
    });
    let finish: (r: Record<string, unknown> | null) => void = () => undefined;
    api.attachJobStream.mockImplementation(
      (_p: string, _a: string, onEvent: (n: string, pl: Record<string, unknown>) => void) => {
        onEvent("job", { executionId: "e9", kind: "solve-batch", status: "running" });
        onEvent("solve_started", { executionId: "e9", targets: ["n1"] });
        onEvent("node_executed", { nodeId: "n1", index: 0, total: 1 });
        return new Promise((res) => {
          finish = res;
        });
      },
    );
    renderProvider();
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalled());
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(api.attachJobStream).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("solve-progress")).toHaveTextContent("n1:verifying");
    // Re-opening does not attach twice to the same execution.
    fireEvent.click(screen.getByText("close"));
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("selected")).toHaveTextContent("a1"));
    expect(api.attachJobStream).toHaveBeenCalledTimes(1);
    const sessionCalls = api.getSession.mock.calls.length;
    await act(async () => {
      finish({ attachmentId: "a1", executionId: "e9", results: {}, appliedContents: [], builderSession: { phase: "ready" } });
    });
    // The session and the listing refresh once the job finished.
    await waitFor(() => expect(api.getSession.mock.calls.length).toBeGreaterThan(sessionCalls));
    expect(screen.getByTestId("solve-progress")).toHaveTextContent("∅");
  });

  it("solveNode narrates the rounds and clears on done", async () => {
    let finish: (r: Record<string, unknown>) => void = () => undefined;
    api.solveNodeStream.mockImplementation(
      (_p: string, _a: string, _n: string, onEvent: (n: string, pl: Record<string, unknown>) => void) => {
        onEvent("solve_node_started", { nodeId: "n1", hasContent: true });
        onEvent("generation_round", { round: 1 });
        onEvent("round_verdict", { round: 1, verdict: "fail" });
        onEvent("generation_round", { round: 2 });
        return new Promise((res) => {
          finish = res;
        });
      },
    );
    renderProvider();
    fireEvent.click(screen.getByText("solve-node"));
    await waitFor(() => expect(api.solveNodeStream).toHaveBeenCalledWith("p1", "a1", "n1", expect.any(Function)));
    expect(screen.getByTestId("solve-node-activity")).toHaveTextContent("Round 2: generating a fix…");
    await act(async () => {
      finish({ nodeId: "n1", verdict: "pass", rounds: 2, proposalId: "p2" });
    });
    expect(screen.getByTestId("solve-node-activity")).toHaveTextContent("∅");
    expect(api.getSession).toHaveBeenCalled();
  });
});
