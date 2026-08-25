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
    solveAttachmentStream: jest.fn(),
    cancelSolve: jest.fn(),
    applyPlanNode: jest.fn(),
    savePlanGoal: jest.fn(),
    applyPlanEdges: jest.fn(),
    runNode: jest.fn(),
    simulate: jest.fn(),
    cancelSimulate: jest.fn(),
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
      <button onClick={() => void ctx.solveAttachment("a1").catch(() => undefined)}>solve</button>
      <button onClick={() => void ctx.applyPlanNode("a1", "p1", "ra").catch(() => undefined)}>
        apply-plan-node
      </button>
      <button onClick={() => void ctx.savePlanGoal("a1", "p1", "ra", "new goal")}>
        save-plan-goal
      </button>
      <button onClick={() => void ctx.applyPlanEdges("a1", "p1").catch(() => undefined)}>
        apply-plan-edges
      </button>
      <button onClick={() => void ctx.runSimulation("a1", "auto").catch(() => undefined)}>
        run-simulation
      </button>
      <button onClick={() => void ctx.cancelSolve("a1")}>cancel-solve</button>
      <div data-testid="solve-progress">
        {Object.entries(ctx.solveProgress["a1"] ?? {})
          .map(([n, st]) => `${n}:${st}`)
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

  // dev/105 A4 — the third live test: a package.install apply re-enlisted the
  // notes package and queued the note cards, but the result carried no
  // requiresRegistryRefresh, so the registry stayed stale and the follow-up
  // notes painted "Loading node…". The install apply now declares the
  // lockfile change; the SAME bridge branch pulses the registry (no nodes).
  it("a package-install apply dispatches package-nodes-created with no nodes (dev/105 A4)", async () => {
    api.applyProposal.mockResolvedValue({
      attachmentId: "a1",
      proposalId: "p1",
      status: "applied",
      mutationApplied: true,
      requiresRegistryRefresh: true,
      installedPackage: { dirName: "curio.notes@1", name: "Simple Notes" },
      followUpProposals: ["n1", "n2"],
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

describe("AgentAttachmentsProvider stream fallback payload parity (dev/53)", () => {
  it("a pre-delta stream failure keeps the content parts (the review card renders)", async () => {
    api.runAttachmentStream.mockRejectedValue(new Error("stream transport failed"));
    api.runAttachment.mockResolvedValue({
      attachmentId: "a1",
      coord: "agent.dataflow-builder@1.0.0",
      reply: "Here is the plan.",
      executionId: "e7",
      usage: { inputTokens: 5, outputTokens: 6 },
      content: [
        {
          type: "proposal",
          proposalId: "pp9",
          tool: "dataflow.plan.write",
          summary: "Apply plan · 2 nodes, 1 edges",
          preview: "Load…",
          pins: { baseGraphDigest: "d" },
          status: "pending",
        },
      ],
    } as never);
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    expect(screen.getByTestId("turns")).toHaveTextContent("Here is the plan.");
    // The fallback turn carries the parts AND the execution record.
    expect(screen.getByTestId("contents")).toHaveTextContent("proposal");
    expect(screen.getByTestId("executions")).toHaveTextContent("e7:5/6");
    // A minted proposal still triggers the listing reload (activeProposal).
    expect(api.listAttachments.mock.calls.length).toBeGreaterThan(1);
  });
});

describe("AgentAttachmentsProvider streamed solve (dev/63)", () => {
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

  it("overlays per-node progress, applies solved content live, and clears on done", async () => {
    let emit: (name: string, payload: Record<string, unknown>) => void = () => undefined;
    let finish: (r: unknown) => void = () => undefined;
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



  it("runSimulation maps driver stream events onto the canvas bridge (dev/67-9)", async () => {
    api.simulate.mockImplementation(
      async (_p: string, _a: string, _m: string, onEvent: (n: string, pl: Record<string, unknown>) => void) => {
        onEvent("node_created", { createdNode: { id: "n1", type: "t", content: "", x: 1, y: 2 } });
        onEvent("node_content_applied", { nodeId: "n1", content: "print(1)" });
        onEvent("edges_created", { createdEdges: [{ id: "e1", source: "n1", target: "n2" }] });
        return { status: "completed", mode: "auto" };
      },
    );
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("run-simulation"));
    });
    expect(events.map((e: any) => e.kind)).toEqual([
      "node-created", "node-content-applied", "edges-created",
    ]);
  });

  it("applyPlanEdges dispatches edges-created for the applied edges (dev/67-8)", async () => {
    api.applyPlanEdges.mockResolvedValue({
      attachmentId: "a1", proposalId: "p1", status: "pending",
      results: {}, edgeStates: { "0": "applied" },
      createdEdges: [{ id: "ce1", source: "n1", target: "n2", sourceHandle: "out", targetHandle: "in" }],
    });
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("apply-plan-edges"));
    });
    expect(events).toEqual([
      {
        kind: "edges-created",
        batchId: "p1:ce1",
        edges: [{ id: "ce1", source: "n1", target: "n2", sourceHandle: "out", targetHandle: "in" }],
      },
    ]);
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

describe("AgentAttachmentsProvider per-node plan apply (dev/67-5)", () => {
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


  it("applyPlanNode also dispatches the progressive sweep's edges (dev/71)", async () => {
    api.applyPlanNode.mockResolvedValue({
      attachmentId: "a1", proposalId: "p1", status: "pending", ref: "ra",
      createdNode: { id: "nid-1", type: "t", content: "", goal: "g", x: 1, y: 2 },
      createdEdges: [{ id: "pe1", source: "n0", target: "nid-1", sourceHandle: "out", targetHandle: "in" }],
      appliedRefs: ["ra"],
    });
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("apply-plan-node"));
    });
    expect(events.map((e: any) => e.kind)).toEqual(["node-created", "edges-created"]);
    expect((events[1] as any).edges[0]).toMatchObject({ id: "pe1", targetHandle: "in" });
  });

  it("applyPlanNode dispatches node-created for the created node", async () => {
    api.applyPlanNode.mockResolvedValue({
      attachmentId: "a1",
      proposalId: "p1",
      status: "pending",
      ref: "ra",
      createdNode: { id: "nid-1", type: "curio.builtin/computation-analysis",
                     content: "", goal: "Load — load it", x: 500, y: 60 },
      appliedRefs: ["ra"],
    });
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("apply-plan-node"));
    });
    expect(api.applyPlanNode).toHaveBeenCalledWith("p1", "a1", "p1", "ra");
    expect(events).toEqual([
      {
        kind: "node-created",
        node: { id: "nid-1", type: "curio.builtin/computation-analysis",
                content: "", goal: "Load — load it", x: 500, y: 60 },
      },
    ]);
  });

  it("an already-applied result dispatches nothing (idempotence)", async () => {
    api.applyPlanNode.mockResolvedValue({
      attachmentId: "a1", proposalId: "p1", status: "already-applied",
      ref: "ra", nodeId: "nid-1", appliedRefs: ["ra"],
    });
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("apply-plan-node"));
    });
    expect(events).toEqual([]);
  });

  it("savePlanGoal posts the overlay and refreshes the listing", async () => {
    api.savePlanGoal.mockResolvedValue({
      proposalId: "p1", ref: "ra", goal: "new goal", editedGoals: { ra: "new goal" },
    });
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("save-plan-goal"));
    });
    expect(api.savePlanGoal).toHaveBeenCalledWith("p1", "a1", "p1", "ra", "new goal");
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

  it("a failed run (stream + fallback) finalizes to error", async () => {
    api.runAttachmentStream.mockRejectedValue(new Error("stream broke"));
    api.runAttachment.mockRejectedValue(new Error("run failed too"));
    renderProvider();
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
    });
    expect(screen.getByTestId("run-status")).toHaveTextContent("error:ms:∅:∅");
  });

  it("the blocking fallback still finalizes done", async () => {
    api.runAttachmentStream.mockRejectedValue(new Error("stream broke"));
    api.runAttachment.mockResolvedValue({
      attachmentId: "a1",
      coord: "c",
      reply: "fresh",
      executionId: "e2",
      usage: { inputTokens: 1, outputTokens: 2 },
      durationMs: 55,
    } as never);
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
