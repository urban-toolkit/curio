import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: "p1" }),
}));

jest.mock("../../api/agentsApi", () => ({
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
  },
}));

import { agentsApi } from "../../api/agentsApi";
import {
  AgentAttachmentsProvider,
  useAgentAttachmentsContext,
} from "../../components/agents/attach/AgentAttachmentsProvider";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

const attachment = {
  attachmentId: "a1",
  coord: "agent.node-explainer@1.0.0",
  target: { kind: "canvas" as const },
  sessionId: "s1",
  revision: 1,
  name: "Node Explainer",
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

  it("a pre-delta stream failure falls back to the blocking run once", async () => {
    api.runAttachmentStream.mockRejectedValue(new Error("stream broke"));
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    fireEvent.click(screen.getByText("send"));
    await waitFor(() =>
      expect(screen.getByTestId("turns")).toHaveTextContent("user:hi|agent:fresh"),
    );
    expect(api.runAttachment).toHaveBeenCalledTimes(1);
  });

  it("a failed run (stream + fallback) appends an error turn", async () => {
    api.runAttachmentStream.mockRejectedValue(new Error("stream broke"));
    api.runAttachment.mockRejectedValue(new Error("provider down"));
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    fireEvent.click(screen.getByText("send"));
    await waitFor(() =>
      expect(screen.getByTestId("turns")).toHaveTextContent("agent:(error) provider down"),
    );
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
    );
  });

  it("the blocking fallback carries the same context", async () => {
    api.runAttachmentStream.mockRejectedValue(new Error("stream broke"));
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    await act(async () => {
      fireEvent.click(screen.getByText("send-ctx"));
    });
    expect(api.runAttachment).toHaveBeenCalledWith("p1", "a1", "hi", "LIVE-TRILL");
  });
});

describe("AgentAttachmentsProvider apply→canvas bridge (memo dev/48 §3.3)", () => {
  const events: unknown[] = [];
  let unsubscribe: () => void = () => undefined;

  beforeEach(() => {
    events.length = 0;
    const { subscribeAgentCanvasMutations } = jest.requireActual(
      "../../utils/agentCanvasEvents",
    );
    unsubscribe = subscribeAgentCanvasMutations((m: unknown) => events.push(m));
  });

  afterEach(() => unsubscribe());

  it("a createdNode apply response dispatches node-created (with the template dir)", async () => {
    api.applyProposal.mockResolvedValue({
      attachmentId: "a1",
      proposalId: "p1",
      status: "applied",
      mutationApplied: true,
      createdNode: { id: "nid", type: "curio.agent.scorer/scorer", content: "c", x: 1, y: 2 },
      createdTemplate: { id: "curio.agent.scorer/scorer", label: "Scorer", packageDir: "curio.agent.scorer@1" },
    });
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    await act(async () => {
      fireEvent.click(screen.getByText("apply"));
    });
    expect(events).toEqual([
      {
        kind: "node-created",
        node: { id: "nid", type: "curio.agent.scorer/scorer", content: "c", x: 1, y: 2 },
        createdPackageDir: "curio.agent.scorer@1",
      },
    ]);
  });

  it("an appliedContent apply response dispatches node-content-applied (the dev/41 clobber fix)", async () => {
    api.applyProposal.mockResolvedValue({
      attachmentId: "a1",
      proposalId: "p1",
      status: "applied",
      mutationApplied: true,
      appliedContent: { nodeId: "n1", content: "print(2)" },
    });
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    await act(async () => {
      fireEvent.click(screen.getByText("apply"));
    });
    expect(events).toEqual([
      { kind: "node-content-applied", nodeId: "n1", content: "print(2)" },
    ]);
  });

  it("a plain apply response (project.install / legacy) dispatches nothing", async () => {
    api.applyProposal.mockResolvedValue({
      attachmentId: "a1",
      proposalId: "p1",
      status: "applied",
      installedCoord: "agent.node-content-builder@1.0.0",
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
      onEvent?.("delegate_started", { capability: "node.content.generate", coord: "agent.node-content-builder@1.0.0" });
      onEvent?.("delegate_result", { capability: "node.content.generate", coord: "agent.node-content-builder@1.0.0", status: "ok", durationMs: 12 });
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
    expect(flat).toContain("agent.node-content-builder@1.0.0 · ok");
    // Transient: cleared once the turn finalizes.
    expect(seen[seen.length - 1]).toEqual([]);
  });
});
