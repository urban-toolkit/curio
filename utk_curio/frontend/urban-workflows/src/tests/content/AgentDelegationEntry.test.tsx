import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";

import { AgentDelegationEntry } from "../../components/agents/content/AgentDelegationEntry";
import type { AgentDelegationPart } from "../../services/agents";

const part = (overrides: Partial<AgentDelegationPart> = {}): AgentDelegationPart => ({
  type: "delegation",
  capability: "research.verify",
  coord: "agent.node-researcher@1.0.0",
  name: "Node Researcher",
  category: "evaluate",
  attachmentId: "att-r",
  status: "ok",
  summary: "verified — 200, socrata",
  ...overrides,
});

describe("AgentDelegationEntry (memo dev/72)", () => {
  it("renders the task, delegate name, status, and summary — icon opens the chat", () => {
    const onOpenChat = jest.fn();
    render(<AgentDelegationEntry part={part()} onOpenChat={onOpenChat} />);
    expect(screen.getByText("research.verify")).toBeInTheDocument();
    expect(screen.getByText("Node Researcher")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.getByText("verified — 200, socrata")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Node Researcher's chat" }));
    expect(onOpenChat).toHaveBeenCalledWith("att-r");
  });

  it("failed status renders the failed chip", () => {
    render(<AgentDelegationEntry part={part({ status: "failed", summary: "boom" })} />);
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });

  it("no home (attachmentId null) → plain entry, no button", () => {
    render(<AgentDelegationEntry part={part({ attachmentId: null })} onOpenChat={jest.fn()} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("a detached home (delegateExists false) → plain entry, never a dead link", () => {
    render(
      <AgentDelegationEntry
        part={part()}
        onOpenChat={jest.fn()}
        delegateExists={() => false}
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("research.verify")).toBeInTheDocument();
  });
});

describe("AgentDelegationEntry: what the delegate ran on", () => {
  it("shows the delegate's configuration and model, which may not be the parent's", () => {
    render(<AgentDelegationEntry part={part({ model: "llama3", llmLabel: "Local" })} />);
    expect(screen.getByText("Local (llama3)")).toBeInTheDocument();
  });

  it("shows nothing extra when the entry names no model", () => {
    const { container } = render(<AgentDelegationEntry part={part()} />);
    expect(container.textContent).not.toContain("(");
  });
});

