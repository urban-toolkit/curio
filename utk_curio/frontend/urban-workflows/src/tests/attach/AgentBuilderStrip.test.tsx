import React from "react";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

const mockPlayAllNodes = jest.fn();
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: mockPlayAllNodes }),
}));

import { AgentBuilderStrip, HIDE_PLAN_MORE, SHOW_PLAN_MORE } from "../../components/agents/attach/AgentBuilderStrip";
import type { AgentAttachment } from "../../services/agents";

const attachment = (session: AgentAttachment["builderSession"]): AgentAttachment =>
  ({
    attachmentId: "a1",
    coord: "agent.curio.dataflow-builder@1",
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

/** Opens the plan line's more part: the plan's nodes, its other actions and
 *  its hints, which stay closed until asked for. */
const openMore = () => fireEvent.click(screen.getByRole("button", { name: SHOW_PLAN_MORE }));

beforeEach(() => jest.clearAllMocks());

describe("AgentBuilderStrip (dev/52 DR-5)", () => {
  it("before any plan there is no line: nothing to solve, run or build, and no templates", () => {
    // The planning templates are in the empty conversation now
    // (AgentChatPanel's "the Dataflow Builder's empty conversation" cases).
    const { container } = render(
      <AgentBuilderStrip attachment={attachment({ phase: "idle" })} onSolve={jest.fn()} onSimulate={jest.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("group", { name: "Dataflow Builder" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Solve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Run workflow" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Load and Clean" })).toBeNull();
  });

  it("says the phase in words with the plan's counts, and no review sits between a plan and its Solve", () => {
    const { rerender } = render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", appliedPlanId: "p1", nodeRuns: { a: "pending", b: "solved" } })}
        onSolve={jest.fn()}
      />,
    );
    const line = screen.getByRole("group", { name: "Dataflow Builder" });
    expect(line).toHaveTextContent("Planned · 2 nodes, 1 to solve");
    expect(screen.queryByText("Review")).not.toBeInTheDocument();
    rerender(
      <AgentBuilderStrip
        attachment={attachment({ phase: "ready", appliedPlanId: "p1", nodeRuns: { a: "solved" } })}
        onSolve={jest.fn()}
      />,
    );
    expect(line).toHaveTextContent("Ready · 1 node");
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
      />,
    );
    openMore();
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
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Solve" }));
    await waitFor(() =>
      expect(screen.getByText("a solve is already running")).toBeInTheDocument(),
    );
  });
});

describe("AgentBuilderStrip's more part", () => {
  it("opens and closes only when asked, and says which it does", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", appliedPlanId: "p1", nodeRuns: { a: "pending" } })}
        onSolve={jest.fn()}
      />,
    );
    const toggle = screen.getByRole("button", { name: SHOW_PLAN_MORE });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("data-tooltip", SHOW_PLAN_MORE);
    expect(screen.queryByRole("list", { name: "Plan node progress" })).toBeNull();
    fireEvent.click(toggle);
    const hide = screen.getByRole("button", { name: HIDE_PLAN_MORE });
    expect(hide).toHaveAttribute("aria-expanded", "true");
    const list = screen.getByRole("list", { name: "Plan node progress" });
    expect(hide).toHaveAttribute("aria-controls", list.parentElement!.id);
    fireEvent.click(hide);
    expect(screen.queryByRole("list", { name: "Plan node progress" })).toBeNull();
  });

  it("holds the actions the line does not: each control is drawn once", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", appliedPlanId: "p1", nodeRuns: { a: "pending" } })}
        onSolve={jest.fn()}
      />,
    );
    openMore();
    expect(screen.getAllByRole("button", { name: "Solve" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Run workflow" })).toHaveLength(1);
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
      />,
    );
    openMore();
    expect(screen.getByText("solving")).toBeInTheDocument();
    expect(screen.getByText("solved")).toBeInTheDocument();
    expect(screen.queryByText("pending")).toBeNull();
    // No live solve → no Cancel control.
    expect(screen.queryByRole("button", { name: "Stop" })).toBeNull();
  });

  it("Stop appears during a session and disables after the click", async () => {
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
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(onCancelSolve).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled();
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
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Solve" }));
    await waitFor(() =>
      expect(screen.getByText("Cancelled: 2 nodes not attempted")).toBeInTheDocument(),
    );
  });
});

/** A plan the agent landed: its refs a and b placed as nodes na and nb. */
const LANDED_PLAN = {
  proposalId: "pp1",
  tool: "dataflow.plan.write",
  nodeId: "",
  summary: "Plan · 2 nodes, 1 edges",
  status: "applied" as const,
  appliedRefs: ["a", "b"],
  nodeIds: { a: "na", b: "nb" },
};

const withLandedPlan = (nodeStates: Record<string, string>, extra: Record<string, unknown> = {}): AgentAttachment =>
  ({
    ...attachment({
      phase: "applied",
      appliedPlanId: "pp1",
      planProposalId: "pp1",
      nodeRuns: { na: "pending", nb: "pending" },
      nodeStates,
      nodeIds: { a: "na", b: "nb" },
      ...extra,
    } as never),
    planProposal: LANDED_PLAN,
  }) as AgentAttachment;

describe("AgentBuilderStrip over a landed plan (dev/67-9, DEC-054)", () => {
  it("Build & validate and Step drive the plan that landed; nothing applies or dismisses it", async () => {
    const onSimulate = jest.fn().mockResolvedValue({ status: "completed" });
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan({ a: "created", b: "created" })}
        onSolve={jest.fn()}
        onApplyProposal={jest.fn()}
        onDismissProposal={jest.fn()}
        onSimulate={onSimulate}
      />,
    );
    openMore();
    expect(screen.getByText("Plan · 2 nodes, 1 edges")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Build & validate plan" }));
    await waitFor(() => expect(onSimulate).toHaveBeenCalledWith("auto"));
    fireEvent.click(screen.getByRole("button", { name: "Step" }));
    await waitFor(() => expect(onSimulate).toHaveBeenCalledWith("step"));
    // The plan landed whole: no review controls are left for it.
    expect(screen.queryByRole("button", { name: "Apply all without validation" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Apply plan" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
  });

  it("a paused build narrates the reason and relabels Resume", async () => {
    const onSimulate = jest.fn().mockResolvedValue({ status: "completed" });
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan(
          { a: "failed", b: "created" },
          { pauseReason: { kind: "validation-failed", ref: "a", message: "validation failed and nothing was written" } },
        )}
        onSolve={jest.fn()}
        onSimulate={onSimulate}
      />,
    );
    // The paused build's Resume is the line's main action, its reason on it.
    const line = screen.getByRole("group", { name: "Dataflow Builder" });
    expect(line).toHaveTextContent(/^Paused/);
    const resume = screen.getByRole("button", { name: "Resume" });
    expect(resume).toHaveAttribute("data-tooltip", "Paused: validation failed and nothing was written");
    openMore();
    expect(screen.getByText(/Paused: validation failed and nothing was written/)).toBeInTheDocument();
    // One Resume, the line's: the more part keeps Step.
    expect(screen.getAllByRole("button", { name: "Resume" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Step" })).toBeInTheDocument();
    fireEvent.click(resume);
    await waitFor(() => expect(onSimulate).toHaveBeenCalledWith("auto"));
  });

  it("a validated node still waits for its approve step, so the controls stay", () => {
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan({ a: "approved", b: "validated" })}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
      />,
    );
    openMore();
    expect(screen.getByRole("button", { name: "Build & validate plan" })).toBeInTheDocument();
  });

  it("once every node is approved, nothing is left to build", () => {
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan({ a: "approved", b: "approved" })}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
      />,
    );
    openMore();
    expect(screen.queryByRole("button", { name: "Build & validate plan" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Step" })).toBeNull();
  });

  it("no plan landed (or its Undo took it back): no build controls", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", appliedPlanId: "p1", nodeRuns: { a: "pending" } })}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
      />,
    );
    openMore();
    expect(screen.queryByRole("button", { name: "Build & validate plan" })).toBeNull();
  });

  it("a failed build surfaces the error", async () => {
    const onSimulate = jest.fn().mockRejectedValue(new Error("no plan to build: ask the agent for one"));
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan({ a: "created", b: "created" })}
        onSolve={jest.fn()}
        onSimulate={onSimulate}
      />,
    );
    openMore();
    fireEvent.click(screen.getByRole("button", { name: "Build & validate plan" }));
    await waitFor(() => expect(screen.getByText(/no plan to build/)).toBeInTheDocument());
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
      />,
    );
    expect(screen.queryByText(/Solving…/)).toBeNull();
    expect(screen.queryByText("Solve batch running")).toBeNull();
  });

  it("the auto-simulation drive shows Building without a fraction when no nodes ran yet", () => {
    // A landed plan whose nodes no Solve has run yet: the session lists none.
    const landed = { ...withLandedPlan({ a: "created", b: "created" }) };
    landed.builderSession = { ...landed.builderSession!, nodeRuns: {} };
    render(
      <AgentBuilderStrip
        attachment={landed}
        onSolve={jest.fn()}
        onSimulate={() => new Promise(() => {})} // held in flight
      />,
    );
    openMore();
    fireEvent.click(screen.getByRole("button", { name: "Build & validate plan" }));
    const line = screen.getByText(/Building… · \d+:\d\d/);
    expect(line).toBeInTheDocument();
    expect(line.textContent).not.toContain("nodes"); // no fraction without entries
  });

  it("the step drive shows Stepping", () => {
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan({ a: "created", b: "created" })}
        onSolve={jest.fn()}
        onSimulate={() => new Promise(() => {})}
      />,
    );
    openMore();
    fireEvent.click(screen.getByRole("button", { name: "Step" }));
    expect(screen.getByText(/Stepping… · \d+:\d\d/)).toBeInTheDocument();
  });
});

describe("AgentBuilderStrip missing specialist (dev/106)", () => {
  const installProposal = {
    proposalId: "ip1",
    tool: "project.install",
    summary: "Install Node Builder in this project",
    status: "pending",
  } as unknown as NonNullable<AgentAttachment["activeProposal"]>;
  const runs = { "node-aaaa-1": "failed", "node-bbbb-2": "failed" } as const;

  it("surfaces Add to project / Dismiss from the mirror alone, in view under the line", async () => {
    const onApplyProposal = jest.fn().mockResolvedValue(undefined);
    const onDismissProposal = jest.fn().mockResolvedValue(undefined);
    render(
      <AgentBuilderStrip
        attachment={{ ...attachment({ phase: "applied", nodeRuns: runs }), activeProposal: installProposal }}
        onSolve={jest.fn()}
        onApplyProposal={onApplyProposal}
        onDismissProposal={onDismissProposal}
      />,
    );
    const group = screen.getByRole("group", { name: "Missing specialist" });
    expect(group).toHaveTextContent("Install Node Builder in this project");
    fireEvent.click(within(group).getByRole("button", { name: "Add to project" }));
    await waitFor(() => expect(onApplyProposal).toHaveBeenCalledWith("ip1"));
    // Retry stays available alongside.
    expect(screen.getByRole("button", { name: "Retry 2 failed" })).toBeEnabled();
    fireEvent.click(within(group).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(onDismissProposal).toHaveBeenCalledWith("ip1"));
    // The plan's build controls are NOT conjured by an install proposal.
    openMore();
    expect(screen.queryByRole("button", { name: "Build & validate plan" })).toBeNull();
  });

  it("renders one reason line for six identical node failures", () => {
    const reason = "specialist not installed: Node Builder is not installed in this project";
    const errors = Object.fromEntries(
      ["n1", "n2", "n3", "n4", "n5", "n6"].map((n) => [n, reason]),
    );
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: runs })}
        onSolve={jest.fn()}
        solveErrors={errors}
      />,
    );
    openMore();
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
        onApplyProposal={jest.fn()}
      />,
    );
    expect(screen.queryByRole("group", { name: "Missing specialist" })).toBeNull();
  });
});

describe("AgentBuilderStrip — dev/115 verified Solve as a background job", () => {
  it("an interrupted session says so and offers a linked Retry", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "interrupted",
          appliedPlanId: "p1",
          interruptedExecutionId: "dead0000",
          nodeRuns: { "node-aaaa-1": "pending", "node-bbbb-2": "solved" },
        })}
        onSolve={jest.fn()}
      />,
    );
    expect(screen.getByRole("group", { name: "Dataflow Builder" })).toHaveTextContent(/^Interrupted/);
    openMore();
    expect(screen.getByRole("status")).toHaveTextContent(/Solve was interrupted/);
    expect(screen.getByRole("status")).toHaveTextContent(/nothing was replayed/);
    const retry = screen.getByRole("button", { name: "Retry 1 interrupted" });
    expect(retry).not.toBeDisabled();
    expect(retry).toHaveAttribute("data-tooltip", expect.stringContaining("linked to the interrupted one"));
  });

  it("the live pills speak the verified loop's states in words", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "solving", appliedPlanId: "p1",
          nodeRuns: { "node-aaaa-1": "pending", "node-bbbb-2": "pending", "node-cccc-3": "pending" } })}
        onSolve={jest.fn()}
        solveProgress={{ "node-aaaa-1": "verifying", "node-bbbb-2": "fixing", "node-cccc-3": "verified" }}
      />,
    );
    openMore();
    expect(screen.getByText("verifying: running in the sandbox…")).toBeInTheDocument();
    expect(screen.getByText("fixing: the run failed, correcting…")).toBeInTheDocument();
    expect(screen.getByText("solved ✓ verified")).toBeInTheDocument();
    // The background-job copy and the honest cancel title.
    expect(screen.getByText("Solve keeps running if you close this panel.")).toBeInTheDocument();
  });

  it("a running background job (reattached) shows Solving even before the strip's own click", () => {
    render(
      <AgentBuilderStrip
        attachment={{
          ...attachment({ phase: "solving", appliedPlanId: "p1", nodeRuns: { "node-aaaa-1": "pending" } }),
          liveJob: { executionId: "e1", kind: "solve-batch", status: "running", startedAt: 1 },
        }}
        onSolve={jest.fn()}
        onCancelSolve={jest.fn()}
      />,
    );
    // Stop is the line's action while the batch runs; Solve waits in the more part.
    expect(screen.getByRole("button", { name: "Stop" })).toHaveAttribute(
      "data-tooltip", expect.stringContaining("a running fetch cannot be aborted"),
    );
    openMore();
    expect(screen.getByRole("button", { name: "Solving…" })).toBeDisabled();
  });
});


describe("AgentBuilderStrip — dev/116 missing connection keys", () => {
  it("renders one Add key action per host, whatever the number of failed nodes, in view under the line", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "failed", b: "failed", c: "failed" } })}
        onSolve={jest.fn()}
        solveErrors={{ a: "not fixed — source-missing", b: "not fixed — source-missing" }}
        solveRemedies={{
          a: { kind: "connection-key", host: "api.census.gov", suggestedName: "census" },
          b: { kind: "connection-key", host: "api.census.gov", suggestedName: "census" },
          c: { kind: "use-connection-key", host: "api.noaa.gov", name: "noaa" },
        }}
      />,
    );
    const group = screen.getByRole("group", { name: "Missing connection keys" });
    expect(within(group).getAllByRole("button", { name: /Add key for/ })).toHaveLength(1);
    expect(group).toHaveTextContent("Add key for api.census.gov");
    expect(group).toHaveTextContent(/A connection key "noaa" is saved for api.noaa.gov. Solve again/);
  });

  it("no group without remedies", () => {
    render(
      <AgentBuilderStrip attachment={attachment({ phase: "applied", nodeRuns: { a: "failed" } })}
        onSolve={jest.fn()} solveErrors={{ a: "boom" }} />,
    );
    openMore();
    expect(screen.queryByRole("group", { name: "Missing connection keys" })).toBeNull();
  });
});


describe("AgentBuilderStrip — dev/126 nodes awaiting a dataset selection", () => {
  const remedy = (attachmentId: string) => ({
    kind: "dataset-selection",
    attachmentId,
    nodeId: "n",
  });
  // The live list's name for each node's own finder.
  const finderNameOf = (id: string) => (["att-a", "att-b"].includes(id) ? "Dataset Finder" : null);

  it("offers one button per node, each opening that node's Dataset Finder", () => {
    const onOpenChat = jest.fn();
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending", b: "pending" } })}
        onSolve={jest.fn()}
        solveErrors={{
          a: "awaiting your dataset selection: 3 candidates awaiting your selection",
        }}
        solveRemedies={{ a: remedy("att-a"), b: remedy("att-b") }}
        onOpenChat={onOpenChat}
        agentNameOf={finderNameOf}
      />,
    );
    // The buttons stay in view under the line: they are the way to the candidates.
    const group = screen.getByRole("group", { name: "Nodes awaiting a dataset selection" });
    const buttons = within(group).getAllByRole("button", { name: /Open Dataset Finder/ });
    expect(buttons).toHaveLength(2);
    // Two awaiting nodes are disambiguated by the short id the pills show.
    expect(buttons[0]).toHaveAccessibleName(/Open Dataset Finder for a/);
    fireEvent.click(buttons[0]);
    expect(onOpenChat).toHaveBeenCalledWith("att-a");
    // The reason is announced once, with the plan's nodes, as every reason is.
    openMore();
    expect(screen.getByText(/awaiting your dataset selection/)).toBeInTheDocument();
  });

  it("a single awaiting node needs no disambiguation", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending" } })}
        onSolve={jest.fn()}
        solveRemedies={{ a: remedy("att-a") }}
        onOpenChat={jest.fn()}
        agentNameOf={finderNameOf}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Open Dataset Finder for this node" }),
    ).toBeInTheDocument();
    // A dataset-selection remedy is never rendered as a connection key.
    expect(screen.queryByRole("group", { name: "Missing connection keys" })).toBeNull();
  });

  it("without a way to open a chat the reason stands alone", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending" } })}
        onSolve={jest.fn()}
        solveErrors={{ a: "awaiting your dataset selection: 1 candidate awaiting your selection" }}
        solveRemedies={{ a: remedy("att-a") }}
      />,
    );
    openMore();
    expect(screen.queryByRole("group", { name: "Nodes awaiting a dataset selection" })).toBeNull();
    expect(screen.getByText(/awaiting your dataset selection/)).toBeInTheDocument();
  });
});


describe("AgentBuilderStrip — dev/118 waves, written kinds and notices", () => {
  it("names the wave on the status line while solving", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "solving", nodeRuns: { a: "solved", b: "pending", c: "pending" } })}
        onSolve={jest.fn()}
        solveProgress={{ b: "verifying" }}
        solveWave={{ wave: 2, of: 3, nodeIds: ["b", "c"] }}
      />,
    );
    expect(screen.getByText(/wave 2 of 3: 2 nodes/)).toBeInTheDocument();
    expect(screen.getByText(/1\/3 nodes/)).toBeInTheDocument();
  });

  it("a written-not-executed pill says so in words, and notices render once per text, not as errors", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { v: "solved", p: "pending", q: "pending" } })}
        onSolve={jest.fn()}
        solveProgress={{ v: "written" }}
        solveNotices={{
          p: "pending: the batch's time budget (45 min) was spent; Retry continues from here",
          q: "pending: the batch's time budget (45 min) was spent; Retry continues from here",
        }}
      />,
    );
    openMore();
    expect(screen.getByRole("list", { name: "Plan node progress" })).toHaveTextContent("written: no code to run; renders in the browser or its own service");
    const notes = screen.getByRole("note", { name: "Solve notices" });
    expect(notes.textContent!.match(/time budget/g)).toHaveLength(1);
    expect(screen.queryByText(/^Solve failed/)).toBeNull();
  });
});


describe("AgentBuilderStrip — dev/131 the session, and nodes that depend on you", () => {
  const waiting = (over: Partial<{ nodeId: string; kind: string; reason: string; attachmentId: string }> = {}) => ({
    nodeId: "a",
    kind: "dataset-selection",
    reason: "awaiting your dataset selection: 3 candidates awaiting your selection",
    attachmentId: "att-df",
    ...over,
  });

  it("deactivates Solve while every unresolved node depends on the user", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending" } })}
        onSolve={jest.fn()}
        solveWaiting={[waiting()]}
      />,
    );
    const solve = screen.getByRole("button", { name: /Solve/ });
    expect(solve).toBeDisabled();
    expect(solve).toHaveAttribute("data-tooltip", expect.stringContaining("Waiting for you"));
    // The line says whose turn it is.
    expect(screen.getByRole("group", { name: "Dataflow Builder" })).toHaveTextContent("1 needs you");
  });

  it("keeps Solve active when something else can still be attempted", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending", b: "failed" } })}
        onSolve={jest.fn()}
        solveWaiting={[waiting()]}
      />,
    );
    expect(screen.getByRole("button", { name: /^Solve$/ })).toBeEnabled();
  });

  it("marks the nodes that depend on the user, and only those", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending", b: "pending" } })}
        onSolve={jest.fn()}
        solveWaiting={[waiting(), waiting({ nodeId: "b", kind: "upstream", reason: "upstream node 'a' has no content yet" })]}
      />,
    );
    openMore();
    // One label each: the node that waits for its source reads Needs a
    // source, as the plan card's row does, and the one that waits upstream
    // says only that. Neither says its status beside it.
    expect(screen.getAllByText("Needs a source")).toHaveLength(1);
    expect(screen.getAllByText("waiting upstream")).toHaveLength(1);
    expect(screen.queryByText("needs you")).toBeNull();
    expect(screen.queryByText("pending")).toBeNull();
  });

  it("offers Solve on each unresolved pill, and disables it for a node that needs the user", async () => {
    const onSolveNode = jest.fn().mockResolvedValue({});
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending", b: "failed", c: "solved" } })}
        onSolve={jest.fn()}
        solveWaiting={[waiting()]}
        onSolveNode={onSolveNode}
      />,
    );
    openMore();
    // The solved node carries no action; the two unresolved ones do.
    expect(screen.getByRole("button", { name: "Solve node a on its own" })).toBeDisabled();
    const b = screen.getByRole("button", { name: "Solve node b on its own" });
    expect(b).toBeEnabled();
    fireEvent.click(b);
    await waitFor(() => expect(onSolveNode).toHaveBeenCalledWith("b"));
  });

  it("narrates the running session and then how it ended", () => {
    const { rerender } = render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "solving", nodeRuns: { a: "pending", b: "solved" } })}
        onSolve={jest.fn()}
        solvePass={3}
        solveWaiting={[waiting()]}
      />,
    );
    openMore();
    expect(screen.getByText(/Managing the dataflow: pass 3/)).toHaveTextContent(
      /waiting for you on 1 node/,
    );
    rerender(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending", b: "solved" } })}
        onSolve={jest.fn()}
        solveEndedBy="budget"
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      /Out of time for this session: 1 node still pending/,
    );
    rerender(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "solved" } })}
        onSolve={jest.fn()}
        solveEndedBy="complete"
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Finished: nothing left to do.");
  });
});

// A build runs as a stream over the plan, not as an agent job: a Solve started
// meanwhile would run over the same nodes.
describe("AgentBuilderStrip while a build runs", () => {
  it("the line's action is the build's Stop, drawn once, and Solve is not offered", async () => {
    const onCancelSimulate = jest.fn().mockResolvedValue(undefined);
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan({ a: "created", b: "created" })}
        onSolve={jest.fn()}
        onCancelSolve={jest.fn()}
        onSolveNode={jest.fn()}
        onSimulate={() => new Promise(() => {})} // held in flight
        onCancelSimulate={onCancelSimulate}
      />,
    );
    openMore();
    fireEvent.click(screen.getByRole("button", { name: "Build & validate plan" }));
    fireEvent.click(screen.getByRole("button", { name: HIDE_PLAN_MORE }));

    // The line, its more part closed.
    expect(screen.queryByRole("button", { name: /^(Solve|Retry)\b/ })).toBeNull();
    const stop = screen.getByRole("button", { name: "Stop" });

    // The more part offers no Solve either, the plan's or a node's, and does
    // not draw the build's stop again.
    openMore();
    const solves = screen.queryAllByRole("button", { name: /^(Solve|Retry)\b/ });
    expect(solves.length).toBeGreaterThan(0);
    for (const solve of solves) expect(solve).toBeDisabled();
    expect(screen.getAllByRole("button", { name: /^(Stop|Stopping…|Cancel)$/ })).toEqual([stop]);

    fireEvent.click(stop);
    await waitFor(() => expect(onCancelSimulate).toHaveBeenCalledTimes(1));
  });

  it("Resume's build holds the line the same way", () => {
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan(
          { a: "failed", b: "created" },
          { pauseReason: { kind: "validation-failed", ref: "a", message: "validation failed and nothing was written" } },
        )}
        onSolve={jest.fn()}
        onSimulate={() => new Promise(() => {})}
        onCancelSimulate={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(Solve|Retry)\b/ })).toBeNull();
  });

  it("a build the chat runs for this agent holds the line it draws again, as after a switch on the rail", () => {
    // The line is drawn anew (the panel reopened, or the rail went to another
    // agent and back) while the build the chat started for it still runs.
    const props = {
      attachment: withLandedPlan({ a: "created", b: "created" }),
      onSolve: jest.fn(),
      onSimulate: jest.fn(),
      onCancelSimulate: jest.fn(),
      simulating: "auto" as const,
    } as React.ComponentProps<typeof AgentBuilderStrip>;
    render(<AgentBuilderStrip {...props} />);
    expect(screen.getByText(/Building… · \d+:\d\d/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(Solve|Retry)\b/ })).toBeNull();
  });

  it("a build another tab runs, which the listing names, holds the line the same way", () => {
    render(
      <AgentBuilderStrip
        attachment={{
          ...withLandedPlan({ a: "created", b: "created" }, { simulateMode: "auto", simulatingSince: Date.now() / 1000 }),
          buildRunning: "auto",
        }}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
        onCancelSimulate={jest.fn()}
      />,
    );
    expect(screen.getByText(/Building… · \d+:\d\d/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(Solve|Retry)\b/ })).toBeNull();
  });

  it("a build the record names that the server does not say runs holds nothing", () => {
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan(
          { a: "created", b: "created" },
          { simulateMode: "auto", simulatingSince: Date.now() / 1000 - 16 * 60 },
        )}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
        onCancelSimulate={jest.fn()}
      />,
    );
    expect(screen.queryByText(/Building…/)).toBeNull();
    expect(screen.getByRole("button", { name: /^Solve$/ })).toBeEnabled();
  });
});

// The listing says which nodes the plan's agent waits on for the user: those
// whose candidates its chat holds, as Build & validate paused on them.
describe("AgentBuilderStrip counts who waits for you from the listing", () => {
  it("the line says how many need you, and the more part marks them", () => {
    render(
      <AgentBuilderStrip
        attachment={{
          ...withLandedPlan(
            { a: "awaiting-source", b: "created" },
            { pauseReason: { kind: "awaiting-source", message: "a needs a source", nodes: [{ ref: "a", nodeId: "na", attachmentId: "att-a" }] } },
          ),
          waitsForYou: ["na"],
        }}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
      />,
    );
    expect(screen.getByRole("group", { name: "Dataflow Builder" })).toHaveTextContent("1 needs you");
    openMore();
    // Its row reads Needs a source, once, and no "needs you" beside it.
    expect(screen.getAllByText("Needs a source")).toHaveLength(1);
    expect(screen.queryByText("needs you")).toBeNull();
  });
});

describe("AgentBuilderStrip's batch Stop", () => {
  it("reads Stop again for the next batch, however the last one ended", async () => {
    const onCancelSolve = jest.fn().mockResolvedValue(undefined);
    const running = (executionId: string): AgentAttachment => ({
      ...attachment({ phase: "solving", appliedPlanId: "p1", nodeRuns: { a: "pending" } }),
      liveJob: { executionId, kind: "solve-batch", status: "running", startedAt: 1 },
    });
    const { rerender } = render(<AgentBuilderStrip attachment={running("e1")} onSolve={jest.fn()} onCancelSolve={onCancelSolve} />);
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(onCancelSolve).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled();

    // The batch ends as another tab, or a panel opened again, sees it: no
    // Solve of this line's own was waiting on it.
    rerender(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", appliedPlanId: "p1", nodeRuns: { a: "pending" } })}
        onSolve={jest.fn()}
        onCancelSolve={onCancelSolve}
      />,
    );
    // The next batch.
    rerender(<AgentBuilderStrip attachment={running("e2")} onSolve={jest.fn()} onCancelSolve={onCancelSolve} />);
    expect(screen.queryByRole("button", { name: "Stopping…" })).toBeNull();
    expect(screen.getByRole("button", { name: "Stop" })).toBeEnabled();
  });
});

describe("AgentBuilderStrip's line says what its closed more part holds", () => {
  /** The line's live region: it says what the closed more part holds. */
  const sign = () => document.querySelector<HTMLElement>("[data-curio-plan-sign]");

  it("the plan's failures, how many, their reasons on its tooltip", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "failed", b: "failed", c: "pending" } })}
        onSolve={jest.fn()}
        solveErrors={{ a: "the sandbox refused the run", b: "the sandbox refused the run" }}
      />,
    );
    const line = screen.getByRole("group", { name: "Dataflow Builder" });
    expect(line).toHaveTextContent("2 failed: see more");
    expect(sign()).not.toBeNull();
    expect(line.contains(sign())).toBe(true);
    expect(sign()).toHaveTextContent("2 failed: see more");
    expect(sign()).toHaveAttribute("data-tooltip", "the sandbox refused the run");
  });

  it("how the last session ended, when it left work undone", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending", b: "solved" } })}
        onSolve={jest.fn()}
        solveEndedBy="stopped"
      />,
    );
    expect(screen.getByRole("group", { name: "Dataflow Builder" })).toHaveTextContent(
      "Stopped by you: 1 node still pending.",
    );
  });

  it("in a live region that stays mounted as the failures come and the more part opens", () => {
    const { rerender } = render(
      <AgentBuilderStrip attachment={attachment({ phase: "applied", nodeRuns: { a: "pending", b: "pending" } })} onSolve={jest.fn()} />,
    );
    const region = sign();
    expect(region).not.toBeNull();
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toBeEmptyDOMElement();

    rerender(
      <AgentBuilderStrip attachment={attachment({ phase: "applied", nodeRuns: { a: "failed", b: "pending" } })} onSolve={jest.fn()} />,
    );
    expect(sign()).toBe(region);
    expect(region).toHaveTextContent("1 failed: see more");

    // Open, the more part shows them itself.
    openMore();
    expect(sign()).toBe(region);
    expect(region).toBeEmptyDOMElement();
    fireEvent.click(screen.getByRole("button", { name: HIDE_PLAN_MORE }));
    expect(sign()).toBe(region);
    expect(region).toHaveTextContent("1 failed: see more");
  });
});


// The strip's buttons and pills for a node awaiting a source name the agent
// that holds its candidates as its manifest does: here a user's own copy of the
// Dataset Finder, "My Finder", run by their own copy of the Dataflow Builder.
describe("AgentBuilderStrip names each node's own finder", () => {
  const myOrchestrator = (session: AgentAttachment["builderSession"]): AgentAttachment => ({
    ...attachment(session),
    coord: "agent.test.my-orchestrator@1",
    name: "My Orchestrator",
    capabilities: ["dataflow.orchestrate"],
  });
  const agentNameOf = (id: string) => (id === "att-my-finder" ? "My Finder" : null);

  it("the awaiting node's button and its pill name My Finder", () => {
    render(
      <AgentBuilderStrip
        attachment={myOrchestrator({ phase: "applied", nodeRuns: { a: "pending" } })}
        onSolve={jest.fn()}
        solveRemedies={{ a: { kind: "dataset-selection", attachmentId: "att-my-finder", nodeId: "a" } }}
        solveWaiting={[{
          nodeId: "a",
          kind: "dataset-selection",
          reason: "awaiting your dataset selection: 2 candidates awaiting your selection",
          attachmentId: "att-my-finder",
        }]}
        onSolveNode={jest.fn()}
        onOpenChat={jest.fn()}
        agentNameOf={agentNameOf}
      />,
    );
    const group = screen.getByRole("group", { name: "Nodes awaiting a dataset selection" });
    const open = within(group).getByRole("button", { name: "Open My Finder for this node" });
    expect(open).toHaveTextContent(/^Open My Finder$/);
    expect(open).toHaveAttribute(
      "data-tooltip",
      "Opens this node's My Finder chat, where its candidates wait for you: pick one with Use this source.",
    );
    openMore();
    expect(screen.getByRole("button", { name: "Solve node a on its own" })).toHaveAttribute(
      "data-tooltip",
      "This node waits for you to pick its source on its card, with Use this source",
    );
    expect(screen.getByRole("group", { name: "My Orchestrator" })).not.toHaveTextContent(/Dataset Finder/);
  });
});

// A plan row's Solve that runs on the server (the listing's `validating`), the
// one a pick goes on with among them, is work on the plan's node: no build
// starts over it.
describe("AgentBuilderStrip while a row's Solve runs on the plan", () => {
  it("Build & validate and Step wait for it, saying why", () => {
    render(
      <AgentBuilderStrip
        attachment={{ ...withLandedPlan({ a: "created", b: "created" }), validating: { ref: "a", nodeId: "na" } }}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
      />,
    );
    openMore();
    const build = screen.getByRole("button", { name: "Build & validate plan" });
    expect(build).toBeDisabled();
    expect(build).toHaveAttribute("data-tooltip", "A node of this plan is being solved: wait for its Solve to end");
    expect(screen.getByRole("button", { name: "Step" })).toBeDisabled();
  });
});

// A pause this line's build ended on says so until the plan goes on: a pick's
// own continuation builds the plan from the provider, not from this line, and
// the line no longer says the plan is paused once it does.
describe("AgentBuilderStrip: a pause's line goes once the plan goes on", () => {
  it("the Paused line goes once a build of the plan runs again, started elsewhere", async () => {
    const onSimulate = jest.fn().mockResolvedValue({
      status: "paused",
      reason: { message: "a needs a source: pick one on its card in this chat" },
    });
    const props = {
      attachment: withLandedPlan({ a: "created", b: "created" }),
      onSolve: jest.fn(),
      onSimulate,
      onCancelSimulate: jest.fn(),
    } as React.ComponentProps<typeof AgentBuilderStrip>;
    const { rerender } = render(<AgentBuilderStrip {...props} />);
    openMore();
    fireEvent.click(screen.getByRole("button", { name: "Build & validate plan" }));
    expect(await screen.findByText("Paused: a needs a source: pick one on its card in this chat")).toBeInTheDocument();
    // The pick's continuation: a build of the plan from the provider.
    rerender(<AgentBuilderStrip {...props} simulating="auto" />);
    // It ends with every node built.
    rerender(<AgentBuilderStrip {...props} attachment={withLandedPlan({ a: "approved", b: "approved" })} simulating={null} />);
    expect(screen.queryByText(/^Paused:/)).toBeNull();
  });
});
