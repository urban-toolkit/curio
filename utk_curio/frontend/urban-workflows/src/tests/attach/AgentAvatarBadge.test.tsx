import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { AgentAvatarBadge } from "../../components/agents/attach/AgentAvatarBadge";

function attachment(over: Partial<any> = {}): any {
  return {
    attachmentId: "att-1",
    coord: "agent.chat-agent@1.0.0",
    target: { kind: "canvas" },
    sessionId: "s1",
    revision: 1,
    name: "Chat",
    category: "node",
    hooks: ["node", "canvas"],
    ...over,
  };
}

describe("AgentAvatarBadge", () => {
  it("renders a hover tooltip with the agent name (macOS Dock style)", () => {
    render(
      <AgentAvatarBadge attachment={attachment()} active={false} onOpen={jest.fn()} onDetach={jest.fn()} />,
    );
    // The name is shown only in the tooltip label (the chip itself is an icon).
    const tooltip = screen.getByText("Chat");
    expect(tooltip).toBeInTheDocument();
    expect(tooltip).toHaveAttribute("aria-hidden", "true");
  });

  it("opens chat on click and detaches on the ✕", () => {
    const onOpen = jest.fn();
    const onDetach = jest.fn();
    render(
      <AgentAvatarBadge attachment={attachment()} active={false} onOpen={onOpen} onDetach={onDetach} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Open chat with Chat/ }));
    expect(onOpen).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Detach Chat/ }));
    expect(onDetach).toHaveBeenCalled();
  });
});
