import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";

const attachment = {
  attachmentId: "a1",
  coord: "agent.node-explainer@1.0.0",
  target: { kind: "canvas" as const },
  sessionId: "s",
  revision: 1,
  name: "Node Explainer",
  category: "node",
  hooks: ["node"],
};

describe("AgentChatPanel", () => {
  it("sends a message and shows the reply", async () => {
    const onSend = jest.fn().mockResolvedValue("here is the explanation");
    render(<AgentChatPanel attachment={attachment} onSend={onSend} onClose={jest.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/message this agent/i), {
      target: { value: "explain this" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSend).toHaveBeenCalledWith("explain this");
    expect(screen.getByText("explain this")).toBeInTheDocument(); // user turn
    await waitFor(() => expect(screen.getByText("here is the explanation")).toBeInTheDocument());
  });

  it("shows an error turn when the run fails", async () => {
    const onSend = jest.fn().mockRejectedValue(new Error("provider 401"));
    render(<AgentChatPanel attachment={attachment} onSend={onSend} onClose={jest.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/message this agent/i), { target: { value: "hi" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByText(/\(error\) provider 401/)).toBeInTheDocument());
  });

  it("Send is disabled on empty input", () => {
    render(<AgentChatPanel attachment={attachment} onSend={jest.fn()} onClose={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("close calls onClose", () => {
    const onClose = jest.fn();
    render(<AgentChatPanel attachment={attachment} onSend={jest.fn()} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });
});
