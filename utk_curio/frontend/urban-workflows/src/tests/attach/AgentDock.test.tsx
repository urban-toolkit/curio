import React from "react";
import { act, render, screen, fireEvent } from "@testing-library/react";
import { AgentDock, DOCK_LEFT_PROPERTY } from "../../components/agents/attach/AgentDock";

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
 * The canvas title shares the dock's row, from the left, and is cut short
 * where the dock starts (UpMenu.module.css reads the edge); a long dataflow
 * name was drawn over the dock. jsdom lays nothing out, so the dock's box is
 * given here; test_canvas_title_beside_the_dock_e2e.py measures both in a
 * browser.
 */
describe("the dock's left edge, for the canvas title beside it", () => {
  const edge = () => document.documentElement.style.getPropertyValue(DOCK_LEFT_PROPERTY);
  const at = (left: number) =>
    ({ left, right: left + 404, top: 76, bottom: 108, width: 404, height: 32, x: left, y: 76, toJSON: () => ({}) }) as DOMRect;
  const AGENTS = [att("a1", "explainer")];
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
    const { rerender, unmount } = render(<AgentDock attachments={AGENTS} />);
    expect(edge()).toBe("437px");
    // Nothing left to show: the dock draws nothing, and its edge goes.
    rerender(<AgentDock attachments={[]} />);
    expect(edge()).toBe("");
    rerender(<AgentDock attachments={AGENTS} />);
    expect(edge()).toBe("437px");
    unmount();
    expect(edge()).toBe("");
  });

  it("follows the dock when the window changes", () => {
    render(<AgentDock attachments={AGENTS} />);
    expect(edge()).toBe("437px");
    box.mockReturnValue(at(300.2));
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    expect(edge()).toBe("300px");
  });

  it("is not on the page while the dock sits under a read-only canvas's banner, below the title", () => {
    expect(DOCK_LEFT_PROPERTY).toBe("--curio-canvas-dock-left");
    render(<AgentDock attachments={AGENTS} belowBanner />);
    expect(screen.getByRole("toolbar", { name: "Canvas agents" })).toBeInTheDocument();
    expect(edge()).toBe("");
  });
});
