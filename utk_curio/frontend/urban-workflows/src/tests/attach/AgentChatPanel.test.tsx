import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";
import type { AgentAttachment, AgentSessionTurn } from "../../api/agentsApi";

const attachment: AgentAttachment = {
  attachmentId: "a1",
  coord: "agent.node-explainer@1.0.0",
  target: { kind: "canvas" as const },
  sessionId: "s1234567890",
  revision: 1,
  name: "Node Explainer",
  category: "node",
  hooks: ["node"],
  intent: "Explain the selected node's code and outputs.",
  intentEdited: false,
};

const noTurns: AgentSessionTurn[] = [];

function renderPanel(overrides: Partial<React.ComponentProps<typeof AgentChatPanel>> = {}) {
  const props: React.ComponentProps<typeof AgentChatPanel> = {
    attachment,
    turns: noTurns,
    onSend: jest.fn().mockResolvedValue(undefined),
    onClose: jest.fn(),
    ...overrides,
  };
  return { ...render(<AgentChatPanel {...props} />), props };
}

describe("AgentChatPanel", () => {
  it("renders the concept header: name, target, session chip", () => {
    renderPanel();
    expect(screen.getByText("Node Explainer")).toBeInTheDocument();
    expect(screen.getByText(/attached to canvas/i)).toBeInTheDocument();
    expect(screen.getByText(/session s1234567/)).toBeInTheDocument();
  });

  it("sends the trimmed message through onSend", async () => {
    const onSend = jest.fn().mockResolvedValue(undefined);
    renderPanel({ onSend });
    fireEvent.change(screen.getByPlaceholderText(/message this agent/i), {
      target: { value: "  explain this  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSend).toHaveBeenCalledWith("explain this");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Send" })).toBeDisabled(),
    );
  });

  it("renders provided turns: user bubble, agent row, error tone", () => {
    renderPanel({
      turns: [
        { role: "user", text: "q1" },
        { role: "agent", text: "a1" },
        { role: "agent", text: "(error) boom", error: true },
      ],
    });
    expect(screen.getByText("q1")).toBeInTheDocument();
    expect(screen.getByText("a1")).toBeInTheDocument();
    const err = screen.getByText("(error) boom");
    expect(err.className).toMatch(/msgError/);
  });

  it("Send is disabled on empty input", () => {
    renderPanel();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("the close button closes without detaching", () => {
    const onClose = jest.fn();
    renderPanel({ onClose });
    fireEvent.click(screen.getByRole("button", { name: "Close chat" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Escape closes the panel", () => {
    const onClose = jest.fn();
    renderPanel({ onClose });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows the prompt-sourced initial intent, with a placeholder when absent", () => {
    renderPanel();
    expect(screen.getByText(attachment.intent as string)).toBeInTheDocument();
    renderPanel({ attachment: { ...attachment, intent: null } });
    expect(screen.getByText(/no instruction prompt available/i)).toBeInTheDocument();
  });

  it("renders the intent as the first message, clamped with a show more/less toggle", () => {
    const long = "x".repeat(400);
    renderPanel({ attachment: { ...attachment, intent: long, intentEdited: true } });
    const bubble = screen.getByText(long);
    expect(bubble.className).toMatch(/msgUser/); // plain first-message styling
    const toggle = screen.getByRole("button", { name: /show more/i });
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: /show less/i })).toBeInTheDocument();
  });

  it("edits the intent: save sends the draft; an emptied draft sends null", async () => {
    const onSaveIntent = jest.fn().mockResolvedValue(undefined);
    renderPanel({ onSaveIntent });
    fireEvent.click(screen.getByRole("button", { name: "Edit initial intent" }));
    const textarea = screen.getByRole("textbox", { name: /initial intent/i });
    fireEvent.change(textarea, { target: { value: "focus on cost" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveIntent).toHaveBeenCalledWith("focus on cost");
    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: /initial intent/i })).not.toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Edit initial intent" }));
    fireEvent.change(screen.getByRole("textbox", { name: /initial intent/i }), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveIntent).toHaveBeenLastCalledWith(null);
  });

  it("shows history loading and a retryable history error", () => {
    renderPanel({ loadingHistory: true });
    expect(screen.getByText(/loading conversation/i)).toBeInTheDocument();

    const onRetryHistory = jest.fn();
    renderPanel({ historyError: "boom", onRetryHistory });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetryHistory).toHaveBeenCalled();
  });

  it("clear conversation confirms first", async () => {
    const onClearConversation = jest.fn().mockResolvedValue(undefined);
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    renderPanel({ onClearConversation });
    fireEvent.click(screen.getByRole("button", { name: "Clear conversation" }));
    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => expect(onClearConversation).toHaveBeenCalledTimes(1));
    confirmSpy.mockRestore();
  });
});
