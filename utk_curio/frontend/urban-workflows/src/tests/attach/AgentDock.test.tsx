import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { AgentDock, GOAL_PLACEHOLDER } from "../../components/agents/attach/AgentDock";

function att(id: string, name: string) {
  return {
    attachmentId: id,
    coord: `agent.${name}@1.0.0`,
    target: { kind: "canvas" as const },
    sessionId: "s",
    revision: 1,
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
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

/**
 * The dataflow goal field (#227).
 *
 * Reported as a cropped placeholder plus "which of several attached agents
 * answers a question typed here". The second rests on a misreading: nothing is
 * sent from this field and no agent answers it. It is a persisted property of
 * the dataflow, handed to every agent whose manifest declares ``workflowGoal``.
 * It read as a chat box because it sat among the agent chips carrying no label
 * except a placeholder too long to read.
 *
 * So it is made legible and permanently named, rather than given routing it
 * does not have. The width half is CSS and belongs to the baseline walkthrough.
 */
describe("AgentDock — the dataflow goal", () => {
  const renderGoal = (goal = "") =>
    render(
      <AgentDock
        attachments={[]}
        selectedId={null}
        onSelect={jest.fn()}
        onDetach={jest.fn()}
        showGoal
        goal={goal}
        onGoalChange={jest.fn()}
      />,
    );

  it("is named by a standing label, not only by its placeholder", () => {
    // The placeholder was the only thing naming the field, so the name vanished
    // the moment anything was typed.
    renderGoal("Find heat islands");
    expect(screen.getByText("Goal")).toBeInTheDocument();
    expect(screen.getByLabelText("Dataflow goal")).toHaveValue("Find heat islands");
  });

  it("has a placeholder short enough to read in full", () => {
    // It was "What is this dataflow for? (shared with your agents)" in a field
    // that could be 260px wide.
    renderGoal();
    expect(GOAL_PLACEHOLDER).toBe("What is this dataflow for?");
    expect(GOAL_PLACEHOLDER.length).toBeLessThanOrEqual(30);
    expect(screen.getByPlaceholderText(GOAL_PLACEHOLDER)).toBeInTheDocument();
  });

  it("keeps the audience it dropped, on hover", () => {
    // "shared with your agents" answers "who sees this?" and is worth keeping
    // somewhere, just not in the visible-width budget.
    renderGoal();
    expect(screen.getByLabelText("Dataflow goal")).toHaveAttribute(
      "title",
      expect.stringContaining("shared with every agent"),
    );
  });
});
