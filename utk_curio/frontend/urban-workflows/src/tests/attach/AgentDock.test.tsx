import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { AgentDock } from "../../components/agents/attach/AgentDock";

function att(id: string, name: string) {
  return {
    attachmentId: id,
    coord: `agent.${name}@1.0.0`,
    target: { kind: "canvas" as const },
    sessionId: "s",
    revision: 1,
    intent: null,
    intentEdited: false,
    name,
    category: "node",
    hooks: ["node"],
  };
}

describe("AgentDock", () => {
  it("renders nothing when empty", () => {
    const { container } = render(
      <AgentDock attachments={[]} selectedId={null} onSelect={jest.fn()} onDetach={jest.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders an avatar per attachment and selects on click", () => {
    const onSelect = jest.fn();
    render(
      <AgentDock
        attachments={[att("a1", "explainer"), att("a2", "debug")]}
        selectedId={null}
        onSelect={onSelect}
        onDetach={jest.fn()}
      />,
    );
    // The agent name is the avatar's accessible label (concept shows avatars,
    // no visible name text).
    expect(screen.getByRole("button", { name: /Open chat with explainer/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open chat with debug/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Open chat with explainer/ }));
    expect(onSelect).toHaveBeenCalledWith("a1");
  });

  it("detach button does not also select (stopPropagation)", () => {
    const onSelect = jest.fn();
    const onDetach = jest.fn();
    render(
      <AgentDock
        attachments={[att("a1", "explainer")]}
        selectedId={null}
        onSelect={onSelect}
        onDetach={onDetach}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Detach explainer/ }));
    expect(onDetach).toHaveBeenCalledWith("a1");
    expect(onSelect).not.toHaveBeenCalled();
  });
});
