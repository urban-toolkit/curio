/**
 * A landed plan's card says when the plan set the dataflow's goal: the plan's
 * first write gives a dataflow whose goal is empty the plan's own, and the
 * card's part carries it (`goalSet`, from `changes.card`). The card then reads
 * "Goal set to: <goal>", one line, in place of the plan's goal on its own. A
 * plan that found a goal written says nothing of it.
 */
import React from "react";
import { render, screen } from "@testing-library/react";

import { AgentChangeCard } from "../../components/agents/content/AgentChangeCard";
import type { AgentChangePart } from "../../services/agents";

const GOAL = "Find the parks a short walk from home";

/** A plan the agent landed, as its turn's card carries it. */
const landedPlan = (overrides: Partial<AgentChangePart> = {}): AgentChangePart => ({
  type: "change",
  changeId: "c-plan",
  tool: "dataflow.plan.write",
  kind: "plan",
  summary: "Plan · 1 node, 0 edges",
  preview: "",
  status: "applied",
  lines: ["+1 node · +0 connections", "1 pending for Build & validate or Solve", "Topology: acyclic."],
  planId: "plan-1",
  plan: {
    goal: GOAL,
    nodes: [{ ref: "a", nodeType: "curio.builtin/python-computation", title: "Load parks", intent: "load the parks" }],
    edgeCount: 0,
    edges: [],
  },
  ...overrides,
});

describe("a landed plan's card and the dataflow's goal", () => {
  it("says, in one line, the goal the plan set", () => {
    render(<AgentChangeCard part={landedPlan({ goalSet: GOAL })} onUndo={jest.fn()} />);
    expect(screen.getByText(`Goal set to: ${GOAL}`)).toBeInTheDocument();
    // That line is the plan's goal on the card: it is not shown twice.
    expect(screen.queryByText(GOAL)).toBeNull();
  });

  it("says nothing of the dataflow's goal when the plan set none", () => {
    render(<AgentChangeCard part={landedPlan()} onUndo={jest.fn()} />);
    expect(screen.queryByText(/Goal set to/)).toBeNull();
    expect(screen.getByText(GOAL)).toBeInTheDocument();
  });
});
