import React from "react";
import { render, screen } from "@testing-library/react";

import { AgentChatCard } from "../../components/agents/content/AgentChatCard";

describe("AgentChatCard — kinds", () => {
  it("names the Dataset Finder's hand-off card (dev/114) by its kind, and keeps unknown kinds raw, with no kind chip", () => {
    render(
      <AgentChatCard
        card={{ type: "card", kind: "handoff", title: "Handing off to Node Builder",
                lines: ["NOAA Climate Data API — https://api.noaa.gov — verified ✓"] }}
      />,
    );
    const card = screen.getByRole("group", { name: "handoff card: Handing off to Node Builder" });
    expect(card).toBeInTheDocument();
    // Its title says what it is: no chip names its kind.
    expect(screen.queryByText("hand-off")).toBeNull();
    expect(screen.getByText(/verified ✓/)).toBeInTheDocument();
    render(<AgentChatCard card={{ type: "card", kind: "future-kind", title: "x", lines: [] }} />);
    expect(screen.getByRole("group", { name: "future-kind card: x" })).toBeInTheDocument();
    expect(screen.queryByText("future-kind")).toBeNull();
  });

  it("an error card's title is in the error colour, not the agent's tint", () => {
    render(
      <AgentChatCard card={{ type: "card", kind: "error", title: "Solve failed", lines: [] }} tintClassName="tint_data" />,
    );
    const header = screen.getByText("Solve failed").parentElement as HTMLElement;
    expect(header).toHaveClass("headerError");
    expect(header).not.toHaveClass("tint_data");
  });

  it("carries no action buttons (docs/08)", () => {
    render(<AgentChatCard card={{ type: "card", kind: "result", title: "Installed", lines: ["ok"] }} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
