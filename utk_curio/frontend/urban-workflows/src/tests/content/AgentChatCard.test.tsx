import React from "react";
import { render, screen } from "@testing-library/react";

import { AgentChatCard } from "../../components/agents/content/AgentChatCard";

describe("AgentChatCard — kinds", () => {
  it("labels the Dataset Finder's hand-off card (dev/114) and keeps unknown kinds raw", () => {
    render(
      <AgentChatCard
        card={{ type: "card", kind: "handoff", title: "Handing off to Node Builder",
                lines: ["NOAA Climate Data API — https://api.noaa.gov — verified ✓"] }}
      />,
    );
    expect(screen.getByRole("group", { name: "handoff card: Handing off to Node Builder" })).toBeInTheDocument();
    expect(screen.getByText("hand-off")).toBeInTheDocument();
    expect(screen.getByText(/verified ✓/)).toBeInTheDocument();
    render(<AgentChatCard card={{ type: "card", kind: "future-kind", title: "x", lines: [] }} />);
    expect(screen.getByText("future-kind")).toBeInTheDocument();
  });

  it("carries no action buttons (docs/08)", () => {
    render(<AgentChatCard card={{ type: "card", kind: "result", title: "Installed", lines: ["ok"] }} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
