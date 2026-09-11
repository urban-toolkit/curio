import React from "react";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

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

describe("AgentBuilderStrip streamed solve (dev/63)", () => {
  it("the live overlay wins per node while the batch streams", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "applied",
          appliedPlanId: "p1",
          nodeRuns: { "node-aaaa-1": "pending", "node-bbbb-2": "pending" },
        })}
        onSolve={jest.fn()}
        solveProgress={{ "node-aaaa-1": "solving", "node-bbbb-2": "solved" }}
        onCancelSolve={jest.fn()}
        onComposePrompt={jest.fn()}
      />,
    );
    expect(screen.getByText("solving")).toBeInTheDocument();
    expect(screen.getByText("solved")).toBeInTheDocument();
    expect(screen.queryByText("pending")).toBeNull();
    // No live solve → no Cancel control.
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  });

  it("Cancel appears during a solve and disables after the click", async () => {
    const onCancelSolve = jest.fn().mockResolvedValue(undefined);
    render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "solving",
          appliedPlanId: "p1",
          nodeRuns: { "node-aaaa-1": "pending" },
        })}
        onSolve={jest.fn()}
        onCancelSolve={onCancelSolve}
        onComposePrompt={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(onCancelSolve).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Cancelling…" })).toBeDisabled();
  });

  it("a cancelled result surfaces the not-attempted notice", async () => {
    const onSolve = jest.fn().mockResolvedValue({ cancelled: true, notAttempted: ["a", "b"] });
    render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "applied",
          appliedPlanId: "p1",
          nodeRuns: { "node-aaaa-1": "pending" },
        })}
        onSolve={onSolve}
        onCancelSolve={jest.fn()}
        onComposePrompt={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Solve" }));
    await waitFor(() =>
      expect(screen.getByText("Cancelled — 2 nodes not attempted")).toBeInTheDocument(),
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

describe("AgentBuilderStrip simulation controls (dev/67-9, DEC-054)", () => {
  const planReview = {
    proposalId: "pp1",
    tool: "dataflow.plan.write",
    nodeId: "",
    summary: "Apply plan · 2 nodes, 1 edges",
    status: "pending" as const,
  };

  it("the validated sequence is the default; bulk apply is the labeled secondary", async () => {
    const onSimulate = jest.fn().mockResolvedValue({ status: "completed" });
    render(
      <AgentBuilderStrip
        attachment={{ ...attachment({ phase: "plan_review" }), activeProposal: planReview }}
        onSolve={jest.fn()}
        onComposePrompt={jest.fn()}
        onApplyProposal={jest.fn()}
        onSimulate={onSimulate}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Build & validate plan" }));
    await waitFor(() => expect(onSimulate).toHaveBeenCalledWith("auto"));
    fireEvent.click(screen.getByRole("button", { name: "Step" }));
    await waitFor(() => expect(onSimulate).toHaveBeenCalledWith("step"));
    expect(
      screen.getByRole("button", { name: "Apply all without validation" }),
    ).toBeInTheDocument();
  });

  it("a paused run narrates the reason and relabels Resume — parked plans included", () => {
    render(
      <AgentBuilderStrip
        attachment={{
          ...attachment({
            phase: "simulating",
            nodeStates: { a: "failed" },
            pauseReason: { kind: "validation-failed", ref: "a", message: "validation failed — review the proposed content" },
          } as never),
          // The plan is PARKED behind the content review (dev/67-9).
          activeProposal: { ...planReview, proposalId: "cp1", tool: "node.content.write" },
          planProposal: planReview,
        }}
        onSolve={jest.fn()}
        onComposePrompt={jest.fn()}
        onSimulate={jest.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.getByText(/Paused — validation failed/)).toBeInTheDocument();
  });
});

describe("AgentBuilderStrip running-status line (dev/83)", () => {
  it("a solving batch renders the shared status line — fixed label, elapsed, terminal-state fraction — and the old note is gone", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "solving",
          appliedPlanId: "p1",
          nodeRuns: {
            a: "solved",
            b: "failed",
            c: "skipped",
            d: "solving",
            e: "pending",
          },
        })}
        onSolve={jest.fn()}
        onComposePrompt={jest.fn()}
      />,
    );
    // solved/failed/skipped count as done; solving/pending do not.
    expect(screen.getByText(/Solving… · \d+:\d\d · 3\/5 nodes/)).toBeInTheDocument();
    expect(screen.getByText("Solve batch running")).toBeInTheDocument();
    expect(screen.queryByText("solving…")).toBeNull(); // the dev/52 note is gone
  });

  it("renders no status line while no batch is active", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "applied",
          appliedPlanId: "p1",
          nodeRuns: { a: "pending" },
        })}
        onSolve={jest.fn()}
        onComposePrompt={jest.fn()}
      />,
    );
    expect(screen.queryByText(/Solving…/)).toBeNull();
    expect(screen.queryByText("Solve batch running")).toBeNull();
  });

  it("the auto-simulation drive shows Building without a fraction when no nodes ran yet", () => {
    const withReview: AgentAttachment = {
      ...attachment({ phase: "plan_review", planProposalId: "pp1" }),
      activeProposal: {
        proposalId: "pp1",
        tool: "dataflow.plan.write",
        nodeId: "",
        summary: "Apply plan · 2 nodes",
        status: "pending",
      },
    } as AgentAttachment;
    render(
      <AgentBuilderStrip
        attachment={withReview}
        onSolve={jest.fn()}
        onComposePrompt={jest.fn()}
        onSimulate={() => new Promise(() => {})} // held in flight
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Build & validate plan" }));
    const line = screen.getByText(/Building… · \d+:\d\d/);
    expect(line).toBeInTheDocument();
    expect(line.textContent).not.toContain("nodes"); // no fraction without entries
  });

  it("the step drive shows Stepping", () => {
    const withReview: AgentAttachment = {
      ...attachment({ phase: "plan_review", planProposalId: "pp1" }),
      activeProposal: {
        proposalId: "pp1",
        tool: "dataflow.plan.write",
        nodeId: "",
        summary: "Apply plan · 2 nodes",
        status: "pending",
      },
    } as AgentAttachment;
    render(
      <AgentBuilderStrip
        attachment={withReview}
        onSolve={jest.fn()}
        onComposePrompt={jest.fn()}
        onSimulate={() => new Promise(() => {})}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Step" }));
    expect(screen.getByText(/Stepping… · \d+:\d\d/)).toBeInTheDocument();
  });
});

describe("AgentBuilderStrip missing specialist (dev/106)", () => {
  const installProposal = {
    proposalId: "ip1",
    tool: "project.install",
    summary: "Install Node Content Builder in this project",
    status: "pending",
  } as unknown as NonNullable<AgentAttachment["activeProposal"]>;
  const runs = { "node-aaaa-1": "failed", "node-bbbb-2": "failed" } as const;

  it("surfaces Add to project / Dismiss from the mirror alone", async () => {
    const onApplyProposal = jest.fn().mockResolvedValue(undefined);
    const onDismissProposal = jest.fn().mockResolvedValue(undefined);
    render(
      <AgentBuilderStrip
        attachment={{ ...attachment({ phase: "applied", nodeRuns: runs }), activeProposal: installProposal }}
        onSolve={jest.fn()}
        onComposePrompt={jest.fn()}
        onApplyProposal={onApplyProposal}
        onDismissProposal={onDismissProposal}
      />,
    );
    const group = screen.getByRole("group", { name: "Missing specialist" });
    expect(group).toHaveTextContent("Install Node Content Builder in this project");
    fireEvent.click(within(group).getByRole("button", { name: "Add to project" }));
    await waitFor(() => expect(onApplyProposal).toHaveBeenCalledWith("ip1"));
    // Retry stays available alongside.
    expect(screen.getByRole("button", { name: "Retry 2 failed" })).toBeEnabled();
    fireEvent.click(within(group).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(onDismissProposal).toHaveBeenCalledWith("ip1"));
    // The plan-review controls are NOT conjured by an install proposal.
    expect(screen.queryByRole("button", { name: "Apply plan" })).toBeNull();
  });

  it("renders one reason line for six identical node failures", () => {
    const reason = "specialist not installed — Node Content Builder is not installed in this project";
    const errors = Object.fromEntries(
      ["n1", "n2", "n3", "n4", "n5", "n6"].map((n) => [n, reason]),
    );
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: runs })}
        onSolve={jest.fn()}
        onComposePrompt={jest.fn()}
        solveErrors={errors}
      />,
    );
    expect(screen.getAllByText(reason)).toHaveLength(1);
  });

  it("shows no install row when the proposal is applied", () => {
    render(
      <AgentBuilderStrip
        attachment={{
          ...attachment({ phase: "applied", nodeRuns: runs }),
          activeProposal: { ...installProposal, status: "applied" } as typeof installProposal,
        }}
        onSolve={jest.fn()}
        onComposePrompt={jest.fn()}
        onApplyProposal={jest.fn()}
      />,
    );
    expect(screen.queryByRole("group", { name: "Missing specialist" })).toBeNull();
  });
});
