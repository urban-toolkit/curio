import React from "react";
import { render, screen, within } from "@testing-library/react";

import { AgentReviewCard } from "../../components/agents/content/AgentReviewCard";
import type { AgentProposalPart } from "../../services/agents";

/**
 * A plan that removes nodes pinned to the dataflow's dashboard says so: its
 * effect line counts the removed nodes that are dashboard tiles, which leave
 * the dashboard, and the list of what it removes marks each of them. The
 * backend flags such a removal with `pinned: true`.
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

const revision = (removals: Removal[]): AgentProposalPart => ({
  type: "proposal",
  proposalId: "p-tiles",
  tool: "dataflow.plan.write",
  summary: "Apply plan · 1 nodes, 1 edges, removes nodes",
  preview: "Parks · curio.builtin/autk-grammar: map the parks",
  pins: { baseGraphDigest: "abc" },
  status: "pending",
  plan: {
    goal: "map the parks from a node upstream",
    nodes: [{ ref: "a", nodeType: "curio.builtin/autk-grammar", title: "Parks", intent: "map the parks" }],
    edgeCount: 1,
    removals,
  },
});

describe("AgentReviewCard: a plan that removes dashboard tiles", () => {
  it("says in its effect line how many removed nodes are tiles, which leave the dashboard", () => {
    const one = render(<AgentReviewCard part={revision([parksMap, loader])} onApply={jest.fn()} />);
    expect(
      screen.getByText(
        "Applying adds 1 node and removes 2. Removal deletes their content and cannot be undone. " +
          "1 of them is a dashboard tile, which leaves the dashboard.",
      ),
    ).toBeInTheDocument();
    one.unmount();
    const two = render(<AgentReviewCard part={revision([parksMap, treesMap, loader])} onApply={jest.fn()} />);
    expect(
      screen.getByText(
        "Applying adds 1 node and removes 3. Removal deletes their content and cannot be undone. " +
          "2 of them are dashboard tiles, which leave the dashboard.",
      ),
    ).toBeInTheDocument();
    two.unmount();
    // A plan that removes no tile says nothing of the dashboard.
    render(<AgentReviewCard part={revision([loader])} onApply={jest.fn()} />);
    expect(
      screen.getByText("Applying adds 1 node and removes 1. Removal deletes their content and cannot be undone."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/dashboard/)).toBeNull();
  });

  it("marks each removed tile where the card lists what the plan removes", () => {
    render(<AgentReviewCard part={revision([parksMap, loader])} onApply={jest.fn()} />);
    const section = screen.getByRole("group", { name: "Nodes and connections this plan removes" });
    const [tile, other] = within(section).getAllByRole("listitem");
    expect(tile).toHaveTextContent(
      "Parks map · curio.builtin/autk-grammar · dashboard tile (contains 40 chars of content)",
    );
    expect(other).toHaveTextContent("Load CSV · curio.builtin/computation-analysis (contains 10 chars of content)");
    expect(other).not.toHaveTextContent("dashboard");
  });
});
