import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";

import { AgentDelegationEntry } from "../../components/agents/content/AgentDelegationEntry";
import type { AgentDelegationPart } from "../../services/agents";

const part = (overrides: Partial<AgentDelegationPart> = {}): AgentDelegationPart => ({
  type: "delegation",
  capability: "research.verify",
  coord: "agent.curio.researcher@1",
  name: "Researcher",
  category: "node",
  attachmentId: "att-r",
  status: "ok",
  summary: "verified — 200, socrata",
  ...overrides,
});

describe("AgentDelegationEntry (memo dev/72)", () => {
  it("names the agent it asked, whose name opens its chat, and the task's outcome", () => {
    const onOpenChat = jest.fn();
    render(<AgentDelegationEntry part={part()} onOpenChat={onOpenChat} />);
    const name = screen.getByRole("button", { name: "Open Researcher's chat" });
    expect(name).toHaveTextContent("Researcher");
    expect(name).toHaveAttribute("data-tooltip", "Open Researcher's chat");
    expect(screen.getByText("verified — 200, socrata")).toBeInTheDocument();
    // The capability and its status are Show run details'.
    expect(screen.queryByText(/research\.verify/)).toBeNull();
    expect(screen.queryByText("ok")).toBeNull();
    fireEvent.click(name);
    expect(onOpenChat).toHaveBeenCalledWith("att-r");
  });

  it("with run details, says the capability and how the task ended", () => {
    render(<AgentDelegationEntry part={part()} onOpenChat={jest.fn()} runDetails />);
    expect(screen.getByText("research.verify · ok")).toBeInTheDocument();
  });

  it("failed status says failed, with or without run details", () => {
    const { unmount } = render(<AgentDelegationEntry part={part({ status: "failed", summary: "boom" })} />);
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
    unmount();
    render(<AgentDelegationEntry part={part({ status: "failed", summary: "boom" })} runDetails />);
    expect(screen.getByText("research.verify · failed")).toBeInTheDocument();
  });

  it("no home (attachmentId null) → plain entry, no button", () => {
    render(<AgentDelegationEntry part={part({ attachmentId: null })} onOpenChat={jest.fn()} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("Researcher")).toBeInTheDocument();
  });

  it("a detached home (delegateExists false) → plain entry, never a dead link", () => {
    render(
      <AgentDelegationEntry
        part={part()}
        onOpenChat={jest.fn()}
        delegateExists={() => false}
        runDetails
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("research.verify · ok")).toBeInTheDocument();
  });
});

describe("AgentDelegationEntry: what the delegate ran on", () => {
  it("with run details, shows the delegate's configuration and model, which may not be the parent's", () => {
    const { unmount } = render(<AgentDelegationEntry part={part({ model: "llama3", llmLabel: "Local" })} />);
    expect(screen.queryByText(/Local \(llama3\)/)).toBeNull();
    unmount();
    render(<AgentDelegationEntry part={part({ model: "llama3", llmLabel: "Local" })} runDetails />);
    expect(screen.getByText("research.verify · Local (llama3) · ok")).toBeInTheDocument();
  });

  it("shows nothing extra when the entry names no model", () => {
    const { container } = render(<AgentDelegationEntry part={part()} runDetails />);
    expect(container.textContent).not.toContain("(");
  });
});
