import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockPlayAllNodes = jest.fn();
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: mockPlayAllNodes }),
}));

import { AgentBuilderStrip } from "../../components/agents/attach/AgentBuilderStrip";
import { BUILDER_TEMPLATES } from "../../components/agents/attach/builderTemplates";
import type { AgentAttachment } from "../../api/agentsApi";

const attachment = (session: AgentAttachment["builderSession"]): AgentAttachment =>
  ({
    attachmentId: "a1",
    coord: "agent.dataflow-builder@1.0.0",
    target: { kind: "canvas" },
    sessionId: "s1",
    revision: 1,
    name: "Dataflow Builder",
    category: "canvas",
    hooks: ["canvas"],
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
    builderSession: session,
  }) as AgentAttachment;

beforeEach(() => jest.clearAllMocks());

describe("AgentBuilderStrip (dev/52 DR-5)", () => {
  it("idle phase offers the six planning templates seeding the prompt", () => {
    const onComposePrompt = jest.fn();
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "idle" })}
        onSolve={jest.fn()}
        onComposePrompt={onComposePrompt}
      />,
    );
    expect(screen.getAllByRole("button").length).toBeGreaterThanOrEqual(BUILDER_TEMPLATES.length);
    fireEvent.click(screen.getByRole("button", { name: "Load and Clean" }));
    expect(onComposePrompt).toHaveBeenCalledWith(BUILDER_TEMPLATES[0].seed);
    // Solve/Run disabled pre-plan with reasons.
    expect(screen.getByRole("button", { name: "Solve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run workflow" })).toBeDisabled();
  });

  it("plan_review disables Solve naming the pending review", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "plan_review" })}
        onSolve={jest.fn()}
        onComposePrompt={jest.fn()}
      />,
    );
    const solve = screen.getByRole("button", { name: "Solve" });
    expect(solve).toBeDisabled();
    expect(solve).toHaveAttribute("title", "Apply or dismiss the plan review first");
  });

  it("applied phase shows per-node progress and solves the batch", async () => {
    const onSolve = jest.fn().mockResolvedValue({});
    render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "applied",
          appliedPlanId: "p1",
          nodeRuns: { "node-aaaa-1": "pending", "node-bbbb-2": "pending" },
        })}
        onSolve={onSolve}
        onComposePrompt={jest.fn()}
      />,
    );
    expect(screen.getAllByText("pending")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Solve" }));
    await waitFor(() => expect(onSolve).toHaveBeenCalledWith(undefined));
    expect(screen.getByRole("button", { name: "Run workflow" })).toBeDisabled();
  });

  it("failed-only nodes retry the subset", async () => {
    const onSolve = jest.fn().mockResolvedValue({});
    render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "applied",
          appliedPlanId: "p1",
          nodeRuns: { good: "solved", bad: "failed" },
        })}
        onSolve={onSolve}
        onComposePrompt={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry 1 failed" }));
    await waitFor(() => expect(onSolve).toHaveBeenCalledWith(["bad"]));
  });

  it("ready phase enables Run workflow via the existing playAllNodes", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "ready",
          appliedPlanId: "p1",
          nodeRuns: { done: "solved" },
        })}
        onSolve={jest.fn()}
        onComposePrompt={jest.fn()}
      />,
    );
    const run = screen.getByRole("button", { name: "Run workflow" });
    expect(run).not.toBeDisabled();
    fireEvent.click(run);
    expect(mockPlayAllNodes).toHaveBeenCalledTimes(1);
  });

  it("a solve failure surfaces the error", async () => {
    const onSolve = jest.fn().mockRejectedValue(new Error("a solve is already running"));
    render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "applied",
          appliedPlanId: "p1",
          nodeRuns: { n: "pending" },
        })}
        onSolve={onSolve}
        onComposePrompt={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Solve" }));
    await waitFor(() =>
      expect(screen.getByText("a solve is already running")).toBeInTheDocument(),
    );
  });
});

describe("AgentBuilderStrip plan-review controls (dev/53)", () => {
  const withReview = (): AgentAttachment => ({
    ...attachment({ phase: "plan_review", planProposalId: "pp1" }),
    activeProposal: {
      proposalId: "pp1",
      tool: "dataflow.plan.write",
      nodeId: "",
      summary: "Apply plan · 3 nodes, 2 edges",
      status: "pending",
    },
  }) as AgentAttachment;

  it("surfaces Apply plan / Dismiss targeting the activeProposal mirror", async () => {
    const onApplyProposal = jest.fn().mockResolvedValue(undefined);
    const onDismissProposal = jest.fn().mockResolvedValue(undefined);
    render(
      <AgentBuilderStrip
        attachment={withReview()}
        onSolve={jest.fn()}
        onComposePrompt={jest.fn()}
        onApplyProposal={onApplyProposal}
        onDismissProposal={onDismissProposal}
      />,
    );
    expect(screen.getByText("Apply plan · 3 nodes, 2 edges")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Apply plan" }));
    await waitFor(() => expect(onApplyProposal).toHaveBeenCalledWith("pp1"));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(onDismissProposal).toHaveBeenCalledWith("pp1"));
  });

  it("shows no review controls without a pending plan proposal", () => {
    const other: AgentAttachment = {
      ...attachment({ phase: "applied", appliedPlanId: "pp0", nodeRuns: { n: "pending" } }),
      activeProposal: {
        proposalId: "x1",
        tool: "node.content.write",
        nodeId: "n1",
        summary: "Replace content",
        status: "pending",
      },
    } as AgentAttachment;
    render(
      <AgentBuilderStrip
        attachment={other}
        onSolve={jest.fn()}
        onComposePrompt={jest.fn()}
        onApplyProposal={jest.fn()}
        onDismissProposal={jest.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Apply plan" })).toBeNull();
  });

  it("a failed apply surfaces the error", async () => {
    const onApplyProposal = jest.fn().mockRejectedValue(new Error("the canvas changed since this plan was proposed"));
    render(
      <AgentBuilderStrip
        attachment={withReview()}
        onSolve={jest.fn()}
        onComposePrompt={jest.fn()}
        onApplyProposal={onApplyProposal}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Apply plan" }));
    await waitFor(() =>
      expect(screen.getByText(/canvas changed since/)).toBeInTheDocument(),
    );
  });
});
