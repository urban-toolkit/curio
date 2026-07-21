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
    updateAttachmentIntent: jest.fn(),
    getSession: jest.fn(),
    clearSession: jest.fn(),
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
      <button onClick={() => void ctx.detach("a1")}>detach</button>
      <button onClick={() => void ctx.clearConversation("a1")}>clear</button>
      <div data-testid="selected">{ctx.selectedId ?? "none"}</div>
      <div data-testid="hydrating">{ctx.hydratingId ?? "none"}</div>
      <div data-testid="turns">{turns.map((t) => `${t.role}:${t.text}`).join("|")}</div>
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
  api.detachAttachment.mockResolvedValue({ attachmentId: "a1", detached: true });
  api.clearSession.mockResolvedValue({ attachmentId: "a1", sessionId: "s1", turns: [] });
  api.updateAttachmentIntent.mockResolvedValue({ ...attachment, intent: "x", intentEdited: true });
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

  it("a failed run appends an error turn", async () => {
    api.runAttachment.mockRejectedValue(new Error("provider down"));
    renderProvider();
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByTestId("turns")).toHaveTextContent("old-q"));
    fireEvent.click(screen.getByText("send"));
    await waitFor(() =>
      expect(screen.getByTestId("turns")).toHaveTextContent("agent:(error) provider down"),
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
