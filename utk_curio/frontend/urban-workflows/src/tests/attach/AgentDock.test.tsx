import React from "react";
import { act, render, screen, fireEvent } from "@testing-library/react";
import { AgentDock, DOCK_LEFT_PROPERTY, GOAL_PLACEHOLDER } from "../../components/agents/attach/AgentDock";

function att(id: string, name: string) {
  return {
    attachmentId: id,
    coord: `agent.test.${name}@1`,
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
      "data-tooltip",
      expect.stringContaining("shared with every agent"),
    );
  });
});

/**
 * #355: every existing goal test renders with ``attachments={[]}``, so nothing
 * covered the case the issue is actually about - the goal field sharing the
 * dock with several avatars. These are behavioural; the CSS that keeps it from
 * being cropped is pinned in ``src/tests/styles/agentDockGoalGeometry.test.ts``,
 * because jsdom has no layout engine and cannot measure a crop.
 */
describe("the goal field beside attached agents", () => {
  const MANY = [att("a1", "explainer"), att("a2", "debug"), att("a3", "planner"),
                att("a4", "critic"), att("a5", "researcher")];

  function renderCrowded(goal = "") {
    const onGoalChange = jest.fn();
    render(
      <AgentDock
        attachments={MANY}
        selectedId={null}
        onSelect={jest.fn()}
        onDetach={jest.fn()}
        showGoal
        goal={goal}
        onGoalChange={onGoalChange}
      />,
    );
    return { onGoalChange };
  }

  it("still renders the goal with five agents attached", () => {
    renderCrowded();
    expect(screen.getByLabelText("Dataflow goal")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Open chat with/ })).toHaveLength(5);
  });

  it("comes before the avatars, so the agents squeeze rather than displace it", () => {
    // Order is the reason this is a DOM test and not only a CSS one: the goal
    // has to be the first item in the row for `flex: 1 1 auto` to give it the
    // leftover space rather than the avatars.
    renderCrowded();
    const dock = screen.getByRole("toolbar", { name: "Canvas agents" });
    const goal = screen.getByLabelText("Dataflow goal");
    const firstAvatar = screen.getAllByRole("button", { name: /Open chat with/ })[0];
    const position = goal.compareDocumentPosition(firstAvatar);
    // eslint-disable-next-line no-bitwise
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(dock).toContainElement(goal);
  });

  it("keeps its standing label, so a typed value does not leave it unnamed", () => {
    // The placeholder is gone the moment anything is typed; the label is what
    // still names the field, and it is only useful if it is wired to the input.
    renderCrowded("Find heat islands in Chicago");
    const input = screen.getByLabelText("Dataflow goal") as HTMLInputElement;
    expect(input.value).toBe("Find heat islands in Chicago");
    const label = screen.getByText("Goal") as HTMLLabelElement;
    expect(label.htmlFor).toBe(input.id);
    expect(input.id).not.toBe("");
  });

  it("reports what the user types", () => {
    const { onGoalChange } = renderCrowded();
    fireEvent.change(screen.getByLabelText("Dataflow goal"), {
      target: { value: "Map tree canopy" },
    });
    expect(onGoalChange).toHaveBeenCalledWith("Map tree canopy");
  });

  it("shows the goal with no agents attached at all", () => {
    // The `attachments.length === 0 && !showGoal` early return: showGoal alone
    // has to be enough, or the field cannot be used before attaching anyone.
    render(
      <AgentDock
        attachments={[]}
        selectedId={null}
        onSelect={jest.fn()}
        onDetach={jest.fn()}
        showGoal
        goal=""
        onGoalChange={jest.fn()}
      />,
    );
    expect(screen.getByLabelText("Dataflow goal")).toBeInTheDocument();
  });
});

/**
 * The canvas title shares the dock's row, from the left, and is cut short
 * where the dock starts (UpMenu.module.css reads the edge); a long dataflow
 * name was drawn over the dock and its goal field. jsdom lays nothing out, so
 * the dock's box is given here; test_canvas_title_beside_the_dock_e2e.py
 * measures both in a browser.
 */
describe("the dock's left edge, for the canvas title beside it", () => {
  const edge = () => document.documentElement.style.getPropertyValue(DOCK_LEFT_PROPERTY);
  const at = (left: number) =>
    ({ left, right: left + 404, top: 76, bottom: 108, width: 404, height: 32, x: left, y: 76, toJSON: () => ({}) }) as DOMRect;
  let box: jest.SpyInstance;

  beforeEach(() => {
    box = jest.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(at(437.6));
  });

  afterEach(() => {
    box.mockRestore();
    document.documentElement.style.removeProperty(DOCK_LEFT_PROPERTY);
  });

  it("is on the page while the dock shares the title's row, and goes with the dock", () => {
    expect(DOCK_LEFT_PROPERTY).toBe("--curio-canvas-dock-left");
    const { rerender, unmount } = render(<AgentDock showGoal goal="" onGoalChange={jest.fn()} />);
    expect(edge()).toBe("437px");
    // Nothing left to show: the dock draws nothing, and its edge goes.
    rerender(<AgentDock showGoal={false} />);
    expect(edge()).toBe("");
    rerender(<AgentDock showGoal goal="" onGoalChange={jest.fn()} />);
    expect(edge()).toBe("437px");
    unmount();
    expect(edge()).toBe("");
  });

  it("follows the dock when the window changes", () => {
    render(<AgentDock showGoal goal="" onGoalChange={jest.fn()} />);
    expect(edge()).toBe("437px");
    box.mockReturnValue(at(300.2));
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    expect(edge()).toBe("300px");
  });

  it("is not on the page while the dock sits under a read-only canvas's banner, below the title", () => {
    expect(DOCK_LEFT_PROPERTY).toBe("--curio-canvas-dock-left");
    render(<AgentDock showGoal goal="" belowBanner />);
    expect(screen.getByRole("toolbar", { name: "Canvas agents" })).toBeInTheDocument();
    expect(edge()).toBe("");
  });
});
