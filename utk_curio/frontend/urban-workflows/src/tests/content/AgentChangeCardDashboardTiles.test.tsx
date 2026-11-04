import React from "react";
import { render, screen, within } from "@testing-library/react";

import { AgentChangeCard } from "../../components/agents/content/AgentChangeCard";
import type { AgentChangePart } from "../../services/agents";

/**
 * A plan that removed nodes pinned to the dataflow's dashboard says so: its
 * card counts the removed nodes that were dashboard tiles, which left the
 * dashboard, and the list of what it removed marks each of them. The backend
 * flags such a removal with `pinned: true`.
 */
type Removal = { id: string; label: string; nodeType: string; contentChars: number };

const loader: Removal = {
  id: "old-loader",
  label: "Load CSV",
  nodeType: "curio.builtin/computation-analysis",
  contentChars: 10,
};
const parksMap = {
  id: "parks-map",
  label: "Parks map",
  nodeType: "curio.builtin/autk-grammar",
  contentChars: 40,
  pinned: true,
};
const treesMap = { ...parksMap, id: "trees-map", label: "Trees map" };

const revision = (removals: Removal[]): AgentChangePart => ({
  type: "change",
  changeId: "c-tiles",
  tool: "dataflow.plan.write",
  kind: "plan",
  planId: "p-tiles",
  summary: "Plan · 1 nodes, 1 edges, removes nodes",
  preview: "Parks · curio.builtin/autk-grammar: map the parks",
  status: "applied",
  lines: [],
  plan: {
    goal: "map the parks from a node upstream",
    nodes: [{ ref: "a", nodeType: "curio.builtin/autk-grammar", title: "Parks", intent: "map the parks" }],
    edgeCount: 1,
    removals,
  },
});

describe("AgentChangeCard: a plan that removed dashboard tiles", () => {
  it("says how many removed nodes were tiles, which left the dashboard", () => {
    const one = render(<AgentChangeCard part={revision([parksMap, loader])} onUndo={jest.fn()} />);
    expect(screen.getByText("1 of them was a dashboard tile, which left the dashboard.")).toBeInTheDocument();
    one.unmount();
    const two = render(<AgentChangeCard part={revision([parksMap, treesMap, loader])} onUndo={jest.fn()} />);
    expect(screen.getByText("2 of them were dashboard tiles, which left the dashboard.")).toBeInTheDocument();
    two.unmount();
    // A plan that removed no tile says nothing of the dashboard.
    render(<AgentChangeCard part={revision([loader])} onUndo={jest.fn()} />);
    expect(screen.getByText("Removed 1 node")).toBeInTheDocument();
    expect(screen.queryByText(/dashboard/)).toBeNull();
  });

  it("marks each removed tile where the card lists what the plan removed", () => {
    render(<AgentChangeCard part={revision([parksMap, loader])} onUndo={jest.fn()} />);
    const section = screen.getByRole("group", { name: "Nodes and connections this plan removed" });
    const [tile, other] = within(section).getAllByRole("listitem");
    expect(tile).toHaveTextContent(
      "Parks map · curio.builtin/autk-grammar · dashboard tile (contained 40 chars of content)",
    );
    expect(other).toHaveTextContent("Load CSV · curio.builtin/computation-analysis (contained 10 chars of content)");
    expect(other).not.toHaveTextContent("dashboard");
  });
});
