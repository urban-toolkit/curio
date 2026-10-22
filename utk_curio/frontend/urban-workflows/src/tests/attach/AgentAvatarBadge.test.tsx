import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgentAvatarBadge } from "../../components/agents/attach/AgentAvatarBadge";
import { TooltipLayer } from "../../components/tooltip/TooltipLayer";
import { setTooltipTimings } from "../../components/tooltip/tooltipStore";
import { getByTooltip } from "../_support/tooltips";

function attachment(over: Partial<any> = {}): any {
  return {
    attachmentId: "att-1",
    coord: "agent.researcher@1.0.0",
    target: { kind: "canvas" },
    sessionId: "s1",
    revision: 1,
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
    name: "Researcher",
    category: "node",
    hooks: ["node", "canvas"],
    ...over,
  };
}

describe("AgentAvatarBadge", () => {
  it("shows the agent name in the Curio tooltip on hover", async () => {
    const restore = setTooltipTimings({ show: 0 });
    try {
      render(
        <>
          <TooltipLayer />
          <AgentAvatarBadge attachment={attachment()} active={false} onOpen={jest.fn()} onDetach={jest.fn()} />
        </>,
      );
      // The name is shown only in the tooltip (the chip itself is an icon).
      expect(screen.queryByText("Researcher")).toBeNull();
      await userEvent.hover(screen.getByRole("button", { name: /Open chat with Researcher/ }));
      expect(await screen.findByRole("tooltip")).toHaveTextContent(/^Researcher$/);
    } finally {
      restore();
    }
  });

  it("applies the blue focus-border (active) class only when selected", () => {
    const { rerender } = render(
      <AgentAvatarBadge attachment={attachment()} active={false} onOpen={jest.fn()} onDetach={jest.fn()} />,
    );
    const chip = screen.getByRole("button", { name: /Open chat with Researcher/ });
    const badge = chip.parentElement as HTMLElement;
    expect(badge.className).not.toMatch(/badgeActive/);
    rerender(
      <AgentAvatarBadge attachment={attachment()} active={true} onOpen={jest.fn()} onDetach={jest.fn()} />,
    );
    expect(badge.className).toMatch(/badgeActive/);
  });

  it("composes '<name>: <title>' into the tooltip and both aria-labels (memo dev/25)", () => {
    render(
      <AgentAvatarBadge
        attachment={attachment({ title: "Dataset Import Help" })}
        active={false}
        onOpen={jest.fn()}
        onDetach={jest.fn()}
      />,
    );
    expect(getByTooltip(document.body, "Researcher: Dataset Import Help")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open chat with Researcher: Dataset Import Help" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Detach Researcher: Dataset Import Help" }),
    ).toBeInTheDocument();
  });

  it("opens chat on click and detaches on the ✕", () => {
    const onOpen = jest.fn();
    const onDetach = jest.fn();
    render(
      <AgentAvatarBadge attachment={attachment()} active={false} onOpen={onOpen} onDetach={onDetach} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Open chat with Researcher/ }));
    expect(onOpen).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Detach Researcher/ }));
    expect(onDetach).toHaveBeenCalled();
  });
});

describe("AgentAvatarBadge — dev/115 the running dot", () => {
  it("shows a labeled running dot only while a background job is live", () => {
    const { rerender } = render(
      <AgentAvatarBadge
        attachment={attachment({ liveJob: { executionId: "e1", kind: "solve-batch", status: "running", startedAt: 1 } })}
        active={false} onOpen={jest.fn()} onDetach={jest.fn()}
      />,
    );
    expect(screen.getByRole("img", { name: "Researcher is solving in the background" })).toBeInTheDocument();
    rerender(
      <AgentAvatarBadge
        attachment={attachment({ liveJob: { executionId: "e1", kind: "solve-batch", status: "done", startedAt: 1 } })}
        active={false} onOpen={jest.fn()} onDetach={jest.fn()}
      />,
    );
    expect(screen.queryByRole("img")).toBeNull();
  });
});
