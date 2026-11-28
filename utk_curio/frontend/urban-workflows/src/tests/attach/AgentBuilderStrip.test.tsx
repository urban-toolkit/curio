import React from "react";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

const mockPlayAllNodes = jest.fn();
let mockRunActive = false;
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: mockPlayAllNodes, isRunActive: mockRunActive }),
}));

import {
  AgentBuilderStrip,
  PLAN_ACTIONS,
  RESUME_HINT,
  RETRY_INTERRUPTED_HINT,
  RUN_HINT,
  SHOW_SOURCES_HINT,
  SOLVE_HINT,
  STOP_BUILD_HINT,
  STOP_SOLVE_HINT,
} from "../../components/agents/attach/AgentBuilderStrip";
import { modalStackDepth } from "../../components/ModalShell";
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

/** The plan line: where the plan stands, its one action and its menu. */
const line = () => screen.getByRole("group", { name: "Dataflow Builder" });
/** The line's words, while nothing runs. */
const words = () => document.querySelector<HTMLElement>("[data-curio-plan-words]");
/** Opens the line's menu of the plan's other actions. */
const openActions = () => {
  fireEvent.click(screen.getByRole("button", { name: PLAN_ACTIONS }));
  return screen.getByRole("menu", { name: PLAN_ACTIONS });
};

beforeEach(() => {
  jest.clearAllMocks();
  mockRunActive = false;
});

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

  it("says where the plan stands in one count, and no review sits between a plan and its Solve", () => {
    const { rerender } = render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", appliedPlanId: "p1", nodeRuns: { a: "pending", b: "solved" } })}
        onSolve={jest.fn()}
      />,
    );
    // One count: how many of the plan's nodes are built.
    expect(words()).toHaveTextContent(/^Planned · 1 of 2 built$/);
    expect(screen.queryByText("Review")).not.toBeInTheDocument();
    rerender(
      <AgentBuilderStrip
        attachment={attachment({ phase: "ready", appliedPlanId: "p1", nodeRuns: { a: "solved" } })}
        onSolve={jest.fn()}
      />,
    );
    expect(words()).toHaveTextContent(/^Ready · 1 node built$/);
  });

  it("Solve solves the batch; the line lists no node, and offers no Run until the plan is ready", async () => {
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
    // Each node's state is on its row of the plan's card.
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.queryByText("pending")).toBeNull();
    const solve = screen.getByRole("button", { name: "Solve" });
    expect(solve).toHaveAttribute("data-tooltip", SOLVE_HINT);
    expect(screen.queryByRole("button", { name: "Run workflow" })).toBeNull();
    fireEvent.click(solve);
    await waitFor(() => expect(onSolve).toHaveBeenCalledWith(undefined));
  });

  it("failed-only nodes retry the subset, and the line names the node that failed", async () => {
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
    expect(words()).toHaveTextContent(/^Failed · bad$/);
    fireEvent.click(screen.getByRole("button", { name: "Retry 1 failed" }));
    await waitFor(() => expect(onSolve).toHaveBeenCalledWith(["bad"]));
  });

  it("ready phase offers Run workflow, the line's action, via the existing playAllNodes", () => {
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
    expect(run).toHaveAttribute("data-tooltip", RUN_HINT);
    expect(screen.queryByRole("button", { name: "Solve" })).toBeNull();
    fireEvent.click(run);
    expect(mockPlayAllNodes).toHaveBeenCalledTimes(1);
  });

  it("Run workflow waits while a run is in progress", () => {
    mockRunActive = true;
    render(
      <AgentBuilderStrip attachment={attachment({ phase: "ready", nodeRuns: { done: "solved" } })} onSolve={jest.fn()} />,
    );
    const run = screen.getByRole("button", { name: "Run workflow" });
    expect(run).toBeDisabled();
    expect(run).toHaveAttribute("data-tooltip", "A run is already in progress");
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

describe("AgentBuilderStrip's menu of the plan's other actions", () => {
  it("is a menu named More plan actions, closed until asked for, holding Build & validate plan and Step", () => {
    render(
      <AgentBuilderStrip attachment={withLandedPlan({ a: "created", b: "created" })} onSolve={jest.fn()} onSimulate={jest.fn()} />,
    );
    const chevron = screen.getByRole("button", { name: PLAN_ACTIONS });
    expect(chevron).toHaveAttribute("data-tooltip", PLAN_ACTIONS);
    expect(chevron).toHaveAttribute("aria-haspopup", "menu");
    expect(chevron).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).toBeNull();
    const menu = openActions();
    expect(chevron).toHaveAttribute("aria-expanded", "true");
    expect(within(menu).getAllByRole("menuitem").map((item) => item.textContent)).toEqual([
      "Build & validate planIn plan order, each node's code lands as it passes; the first failure pauses.",
      "StepBuilds the next node only.",
    ]);
    // Escape closes it, and the focus goes back to its chevron.
    fireEvent.keyDown(document.activeElement ?? menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(chevron).toHaveFocus();
  });

  it("each action is drawn once: Solve on the line, the builds in the menu", () => {
    render(
      <AgentBuilderStrip attachment={withLandedPlan({ a: "created", b: "created" })} onSolve={jest.fn()} onSimulate={jest.fn()} />,
    );
    openActions();
    expect(screen.getAllByRole("button", { name: "Solve" })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Run workflow" })).toBeNull();
    expect(screen.getAllByRole("menuitem", { name: /^Build & validate plan/ })).toHaveLength(1);
  });
});

describe("AgentBuilderStrip streamed solve (dev/63)", () => {
  it("the live overlay wins per node while the batch streams: the node at work, and the count built", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "solving",
          appliedPlanId: "p1",
          nodeRuns: { "node-aaaa-1": "pending", "node-bbbb-2": "pending", "node-cccc-3": "pending" },
        })}
        onSolve={jest.fn()}
        solveProgress={{ "node-aaaa-1": "generating", "node-bbbb-2": "solved", "node-cccc-3": "verified" }}
        onCancelSolve={jest.fn()}
      />,
    );
    // A node the batch solved, or whose run passed in the sandbox, is built,
    // though the record says pending still.
    expect(line()).toHaveTextContent(/Solving node-aaa · \d+:\d\d · 2 of 3 built/);
    expect(screen.getByRole("status")).toHaveAttribute("data-tooltip", "node-aaa: writing its code");
  });

  it("an overlay a batch left on a plan no batch runs on draws no Stop and no running line", () => {
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
    expect(screen.queryByRole("button", { name: "Stop" })).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByText("Solve batch running")).toBeNull();
    // The line says where the plan stands, the overlay's solved node built.
    expect(words()).toHaveTextContent(/^Planned · 1 of 2 built$/);
  });

  it("Stop appears during a session, says the session goes on if the chat closes, and disables after the click", async () => {
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
    const stop = screen.getByRole("button", { name: "Stop" });
    expect(stop).toHaveAttribute("data-tooltip", STOP_SOLVE_HINT);
    expect(STOP_SOLVE_HINT).toContain("Solve keeps running if you close this chat");
    fireEvent.click(stop);
    await waitFor(() => expect(onCancelSolve).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled();
  });

  it("a session the person stopped says how many nodes it left, on the line", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "applied",
          appliedPlanId: "p1",
          nodeRuns: { "node-aaaa-1": "pending", "node-bbbb-2": "pending" },
        })}
        onSolve={jest.fn()}
        onCancelSolve={jest.fn()}
        solveEndedBy="stopped"
      />,
    );
    expect(words()).toHaveTextContent(/^Stopped · 2 left$/);
    expect(screen.queryByText(/^Cancelled:/)).toBeNull();
  });
});

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
    fireEvent.click(within(openActions()).getByRole("menuitem", { name: /^Build & validate plan/ }));
    await waitFor(() => expect(onSimulate).toHaveBeenCalledWith("auto"));
    // The menu comes back once the build ended.
    fireEvent.click(await screen.findByRole("button", { name: PLAN_ACTIONS }));
    fireEvent.click(
      within(screen.getByRole("menu", { name: PLAN_ACTIONS })).getByRole("menuitem", { name: /^Step/ }),
    );
    await waitFor(() => expect(onSimulate).toHaveBeenCalledWith("step"));
    // The plan landed whole: no review controls are left for it.
    expect(screen.queryByRole("button", { name: "Apply all without validation" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Apply plan" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
  });

  it("a paused build names the node it paused on, says why on its tooltip, and offers Resume", async () => {
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
    expect(words()).toHaveTextContent(/^Paused · na failed$/);
    expect(words()).toHaveAttribute("data-tooltip", "validation failed and nothing was written");
    const resume = screen.getByRole("button", { name: "Resume" });
    expect(resume).toHaveAttribute("data-tooltip", RESUME_HINT);
    // One Resume, the line's: the menu keeps Step.
    expect(screen.getAllByRole("button", { name: "Resume" })).toHaveLength(1);
    const menu = openActions();
    expect(within(menu).queryByRole("menuitem", { name: /^Build & validate plan/ })).toBeNull();
    expect(within(menu).getByRole("menuitem", { name: /^Step/ })).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? menu, { key: "Escape" });
    fireEvent.click(resume);
    await waitFor(() => expect(onSimulate).toHaveBeenCalledWith("auto"));
  });

  // The line and its menu count a node built the same way: a plan the line
  // calls Ready has nothing left for Build & validate or Step.
  it.each([
    ["validated by its row's Solve", { a: "approved", b: "validated" }, {}, {}],
    ["solved by a batch, its record still created", { a: "approved", b: "created" }, { nodeRuns: { na: "pending", nb: "solved" } }, {}],
    ["run in the sandbox, as the batch's stream says", { a: "approved", b: "created" }, {}, { nb: "verified" }],
  ])("a plan whose last node was %s reads Ready, offers Run workflow, and holds no menu", (_how, nodeStates, extra, overlay) => {
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan(nodeStates, extra)}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
        solveProgress={overlay}
      />,
    );
    expect(words()).toHaveTextContent(/^Ready · 2 nodes built$/);
    expect(screen.getByRole("button", { name: "Run workflow" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: PLAN_ACTIONS })).toBeNull();
  });

  it("a node not built yet keeps the menu, beside the line that says so", () => {
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan({ a: "approved", b: "created" })}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
      />,
    );
    expect(words()).toHaveTextContent(/^Planned · 1 of 2 built$/);
    expect(within(openActions()).getByRole("menuitem", { name: /^Build & validate plan/ })).toBeInTheDocument();
  });

  it("once every node is approved, nothing is left to build: no menu", () => {
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan({ a: "approved", b: "approved" })}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: PLAN_ACTIONS })).toBeNull();
  });

  it("no plan landed (or its Undo took it back): no builds", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", appliedPlanId: "p1", nodeRuns: { a: "pending" } })}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: PLAN_ACTIONS })).toBeNull();
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
    fireEvent.click(within(openActions()).getByRole("menuitem", { name: /^Build & validate plan/ }));
    await waitFor(() => expect(screen.getByText(/no plan to build/)).toBeInTheDocument());
  });
});

describe("AgentBuilderStrip running line (dev/83)", () => {
  it("a solving batch names what runs, its time and how many nodes are built, and the old note is gone", () => {
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
    // Built is solved, verified or written: a failure or a skip is not.
    expect(line()).toHaveTextContent(/Solving d · \d+:\d\d · 1 of 5 built/);
    expect(screen.getByText("Solve batch running")).toBeInTheDocument();
    expect(screen.queryByText("solving…")).toBeNull(); // the dev/52 note is gone
    // With no way to stop it here, the line's Solve says it runs, and waits.
    expect(screen.getByRole("button", { name: "Solving…" })).toBeDisabled();
  });

  it("renders no running line while no batch is active", () => {
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
    expect(screen.queryByText(/Solving/)).toBeNull();
    expect(screen.queryByText("Solve batch running")).toBeNull();
  });

  it("the auto build shows Building and its plan's count, before any node ran", () => {
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
    fireEvent.click(within(openActions()).getByRole("menuitem", { name: /^Build & validate plan/ }));
    expect(line()).toHaveTextContent(/Building · \d+:\d\d · 0 of 2 built/);
    expect(screen.getByText("Build running")).toBeInTheDocument();
  });

  it("the build names the node it works on, what it does there on its tooltip", () => {
    render(
      <AgentBuilderStrip
        attachment={{
          ...withLandedPlan({ a: "approved", b: "created" }, { currentRef: "b" }),
          buildRunning: "auto",
        }}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
        onCancelSimulate={jest.fn()}
        simulationActivity="generating content (round 1)"
      />,
    );
    expect(line()).toHaveTextContent(/Building nb · \d+:\d\d · 1 of 2 built/);
    expect(screen.getByRole("status")).toHaveAttribute("data-tooltip", "nb: generating content (round 1)");
  });

  it("the step drive shows Stepping", () => {
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan({ a: "created", b: "created" })}
        onSolve={jest.fn()}
        onSimulate={() => new Promise(() => {})}
      />,
    );
    fireEvent.click(within(openActions()).getByRole("menuitem", { name: /^Step/ }));
    expect(line()).toHaveTextContent(/Stepping · \d+:\d\d/);
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
    // The plan's builds are NOT conjured by an install proposal.
    expect(screen.queryByRole("button", { name: PLAN_ACTIONS })).toBeNull();
  });

  it("says one reason once, on the line's tooltip, for six identical node failures", () => {
    const reason = "specialist not installed: Node Builder is not installed in this project";
    const nodes = ["n1", "n2", "n3", "n4", "n5", "n6"];
    const errors = Object.fromEntries(nodes.map((n) => [n, reason]));
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: Object.fromEntries(nodes.map((n) => [n, "failed"])) })}
        onSolve={jest.fn()}
        solveErrors={errors}
      />,
    );
    expect(words()).toHaveTextContent(/^Failed · 6 nodes$/);
    expect(words()).toHaveAttribute("data-tooltip", reason);
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
  it("an interrupted session says so and offers a linked Retry, whose tooltip says what happened", () => {
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
    expect(words()).toHaveTextContent(/^Interrupted · 1 left$/);
    const retry = screen.getByRole("button", { name: "Retry 1 interrupted" });
    expect(retry).not.toBeDisabled();
    expect(retry).toHaveAttribute("data-tooltip", RETRY_INTERRUPTED_HINT);
    expect(RETRY_INTERRUPTED_HINT).toMatch(/Solve was interrupted/);
    expect(RETRY_INTERRUPTED_HINT).toMatch(/nothing was replayed/);
    expect(RETRY_INTERRUPTED_HINT).toMatch(/linked to the interrupted one/);
  });

  it.each([
    ["solving", "solving it"],
    ["generating", "writing its code"],
    ["verifying", "running it in the sandbox"],
    ["fixing", "the run failed: fixing it"],
  ])("the node at work says its verified loop's state %s in words, on the line's tooltip", (run, said) => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "solving", appliedPlanId: "p1",
          nodeRuns: { "node-aaaa-1": "pending", "node-cccc-3": "pending" } })}
        onSolve={jest.fn()}
        solveProgress={{ "node-aaaa-1": run, "node-cccc-3": "verified" }}
      />,
    );
    expect(line()).toHaveTextContent(/Solving node-aaa · \d+:\d\d · 1 of 2 built/);
    expect(screen.getByRole("status")).toHaveAttribute("data-tooltip", `node-aaa: ${said}`);
  });

  it("a running background job (reattached) shows Solving even before the strip's own click, and offers no Solve", () => {
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
    // Stop is the line's action while the batch runs.
    expect(screen.getByRole("button", { name: "Stop" })).toHaveAttribute(
      "data-tooltip", expect.stringContaining("a running fetch cannot be aborted"),
    );
    expect(line()).toHaveTextContent(/Solving · \d+:\d\d · 0 of 1 built/);
    expect(screen.queryByRole("button", { name: /^(Solve|Solving…|Retry)/ })).toBeNull();
  });
});


describe("AgentBuilderStrip — dev/116 missing connection keys", () => {
  it("renders one Add key action per host, whatever the number of failed nodes, in view under the line", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "failed", b: "failed", c: "failed" } })}
        onSolve={jest.fn()}
        solveErrors={{ a: "not fixed: source-missing", b: "not fixed: source-missing" }}
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
    expect(screen.queryByRole("group", { name: "Missing connection keys" })).toBeNull();
  });
});


describe("AgentBuilderStrip — dev/126 nodes awaiting a dataset selection", () => {
  const remedy = (attachmentId: string) => ({
    kind: "dataset-selection",
    attachmentId,
    nodeId: "n",
  });

  it("says the plan waits on their pick, once, and goes to the first node's sources", () => {
    const onShowSources = jest.fn();
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending", b: "pending" } })}
        onSolve={jest.fn()}
        solveErrors={{
          a: "awaiting your dataset selection: 3 candidates awaiting your selection",
        }}
        solveRemedies={{ a: remedy("att-a"), b: remedy("att-b") }}
        onShowSources={onShowSources}
      />,
    );
    // Said once, on the line, which counts them: no button per node.
    expect(words()).toHaveTextContent(/^Paused · 2 nodes need a source$/);
    expect(screen.queryByRole("group", { name: "Nodes awaiting a dataset selection" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Open Dataset Finder/ })).toBeNull();
    const show = screen.getByRole("button", { name: "Show its sources" });
    // With two waiting, its tooltip names the first, which it goes to.
    expect(show).toHaveAttribute("data-tooltip", "a: Goes to its sources in this chat. Your pick builds it, and the plan goes on.");
    fireEvent.click(show);
    expect(onShowSources).toHaveBeenCalledWith("a");
    // A dataset-selection remedy is never rendered as a connection key.
    expect(screen.queryByRole("group", { name: "Missing connection keys" })).toBeNull();
  });

  it("a single awaiting node is named on the line", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending" } })}
        onSolve={jest.fn()}
        solveRemedies={{ a: remedy("att-a") }}
        onShowSources={jest.fn()}
      />,
    );
    expect(words()).toHaveTextContent(/^Paused · a needs a source$/);
  });

  it("without a way to show the sources, Show its sources is there but does nothing", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending" } })}
        onSolve={jest.fn()}
        solveRemedies={{ a: remedy("att-a") }}
      />,
    );
    expect(screen.getByRole("button", { name: "Show its sources" })).toBeDisabled();
  });
});


describe("AgentBuilderStrip: dev/118 waves", () => {
  it("names the wave with Show run details while solving, and counts what is built on the line", () => {
    const props = {
      attachment: attachment({ phase: "solving", nodeRuns: { a: "solved", b: "pending", c: "pending" } }),
      onSolve: jest.fn(),
      solveProgress: { b: "verifying" },
      solveWave: { wave: 2, of: 3, nodeIds: ["b", "c"] },
    };
    const { rerender } = render(<AgentBuilderStrip {...props} />);
    expect(line()).toHaveTextContent(/1 of 3 built/);
    expect(screen.queryByText(/wave 2 of 3/)).toBeNull();
    rerender(<AgentBuilderStrip {...props} runDetails />);
    expect(screen.getByText(/wave 2 of 3: 2 nodes/)).toBeInTheDocument();
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

  it("offers no Solve while every unresolved node depends on the user: the line goes to the sources instead", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending" } })}
        onSolve={jest.fn()}
        solveWaiting={[waiting()]}
        onShowSources={jest.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /^(Solve|Retry)/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Show its sources" })).toBeEnabled();
    // The line says whose turn it is, and for which node.
    expect(words()).toHaveTextContent(/^Paused · a needs a source$/);
  });

  it("keeps Solve active when something else can still be attempted, and still says the wait", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending", b: "failed" } })}
        onSolve={jest.fn()}
        solveWaiting={[waiting()]}
      />,
    );
    expect(screen.getByRole("button", { name: /^Solve$/ })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Show its sources" })).toBeNull();
    expect(words()).toHaveTextContent(/^Failed · b · a needs a source$/);
  });

  it("says the session's pass with Show run details, and then how it ended, on the line", () => {
    const { rerender } = render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "solving", nodeRuns: { a: "pending", b: "solved" } })}
        onSolve={jest.fn()}
        solvePass={3}
        solveWaiting={[waiting()]}
        runDetails
      />,
    );
    expect(screen.getByText(/Managing the dataflow: pass 3/)).toHaveTextContent(
      /waiting for you on 1 node/,
    );
    // While it runs, the line says the node that waits for you.
    expect(line()).toHaveTextContent(/1 of 2 built · a needs a source/);
    rerender(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending", b: "solved" } })}
        onSolve={jest.fn()}
        solveEndedBy="budget"
      />,
    );
    expect(words()).toHaveTextContent(/^Out of time · 1 left$/);
    rerender(
      <AgentBuilderStrip
        attachment={attachment({ phase: "ready", nodeRuns: { a: "solved" } })}
        onSolve={jest.fn()}
        solveEndedBy="complete"
      />,
    );
    expect(words()).toHaveTextContent(/^Ready · 1 node built$/);
    // A session that left nothing to do reads the same while the plan's
    // record still says applied: its every node is built.
    rerender(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "solved" } })}
        onSolve={jest.fn()}
        solveEndedBy="complete"
      />,
    );
    expect(words()).toHaveTextContent(/^Ready · 1 node built$/);
    expect(screen.getByRole("button", { name: "Run workflow" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Solve" })).toBeNull();
  });

  it("a node that waits on another that waits for a pick waits too: the plan goes to the sources", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending", b: "pending" } })}
        onSolve={jest.fn()}
        solveWaiting={[waiting(), waiting({ nodeId: "b", kind: "upstream", reason: "waits for a" })]}
        onShowSources={jest.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /^(Solve|Retry)/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Show its sources" })).toBeEnabled();
    // Only a is named as needing a source: b waits on it.
    expect(words()).toHaveTextContent(/^Paused · a needs a source$/);
  });
});

// A build runs as a stream over the plan, not as an agent job: a Solve started
// meanwhile would run over the same nodes.
describe("AgentBuilderStrip while a build runs", () => {
  it("the line's action is the build's Stop, drawn once, and no Solve or build is offered", async () => {
    const onCancelSimulate = jest.fn().mockResolvedValue(undefined);
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan({ a: "created", b: "created" })}
        onSolve={jest.fn()}
        onCancelSolve={jest.fn()}
        onSimulate={() => new Promise(() => {})} // held in flight
        onCancelSimulate={onCancelSimulate}
      />,
    );
    fireEvent.click(within(openActions()).getByRole("menuitem", { name: /^Build & validate plan/ }));

    expect(screen.queryByRole("button", { name: /^(Solve|Retry)\b/ })).toBeNull();
    // Nothing in the menu can run while the build does.
    expect(screen.queryByRole("button", { name: PLAN_ACTIONS })).toBeNull();
    const stop = screen.getByRole("button", { name: "Stop" });
    expect(stop).toHaveAttribute("data-tooltip", STOP_BUILD_HINT);
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
    expect(line()).toHaveTextContent(/Building · \d+:\d\d · 0 of 2 built/);
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
    expect(line()).toHaveTextContent(/Building · \d+:\d\d/);
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
    expect(screen.queryByText(/Building/)).toBeNull();
    expect(screen.getByRole("button", { name: /^Solve$/ })).toBeEnabled();
  });

  it("a build that was stopped says how many nodes it left, until a build runs again", async () => {
    const onSimulate = jest.fn().mockResolvedValue({ status: "cancelled" });
    render(
      <AgentBuilderStrip attachment={withLandedPlan({ a: "approved", b: "created" })} onSolve={jest.fn()} onSimulate={onSimulate} />,
    );
    fireEvent.click(within(openActions()).getByRole("menuitem", { name: /^Build & validate plan/ }));
    await waitFor(() => expect(words()).toHaveTextContent(/^Stopped · 1 left$/));
  });
});

// The listing says which nodes the plan's agent waits on for the user: those
// whose candidates its chat holds, as Build & validate paused on them.
describe("AgentBuilderStrip says who waits for you from the listing", () => {
  it("the line names the node that waits for your pick, and goes to its sources, with no Resume", () => {
    const onShowSources = jest.fn();
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
        onShowSources={onShowSources}
      />,
    );
    expect(words()).toHaveTextContent(/^Paused · na needs a source$/);
    expect(screen.queryByText("needs you")).toBeNull();
    // The pick goes on by itself: Resume adds nothing while it waits.
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show its sources" }));
    expect(onShowSources).toHaveBeenCalledWith("na");
  });

  it("a build that paused on a downloading pick keeps Resume, and says what it waits for", () => {
    render(
      <AgentBuilderStrip
        attachment={withLandedPlan(
          { a: "awaiting-download", b: "created" },
          { pauseReason: { kind: "awaiting-source", message: "a waits for its download", nodes: [{ ref: "a", nodeId: "na", attachmentId: "att-a" }] } },
        )}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
        onShowSources={jest.fn()}
      />,
    );
    expect(words()).toHaveTextContent(/^Paused · na waits for its download$/);
    expect(screen.getByRole("button", { name: "Resume" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Show its sources" })).toBeNull();
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

describe("AgentBuilderStrip's line says how the plan ended", () => {
  it("the plan's failures, how many, their reasons on its tooltip", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "failed", b: "failed", c: "pending" } })}
        onSolve={jest.fn()}
        solveErrors={{ a: "the sandbox refused the run", b: "the sandbox refused the run" }}
      />,
    );
    expect(line().contains(words())).toBe(true);
    expect(words()).toHaveTextContent(/^Failed · 2 nodes$/);
    expect(words()).toHaveAttribute("data-tooltip", "the sandbox refused the run");
    // A node is still pending: the line's Solve goes on with it.
    expect(screen.getByRole("button", { name: "Solve" })).toBeEnabled();
  });

  it("how the last session ended, when it left work undone", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({ phase: "applied", nodeRuns: { a: "pending", b: "solved" } })}
        onSolve={jest.fn()}
        solveEndedBy="stopped"
      />,
    );
    expect(words()).toHaveTextContent(/^Stopped · 1 left$/);
  });

  it("in a live region that stays mounted as the failures come", () => {
    const { rerender } = render(
      <AgentBuilderStrip attachment={attachment({ phase: "applied", nodeRuns: { a: "pending", b: "pending" } })} onSolve={jest.fn()} />,
    );
    const region = words();
    expect(region).not.toBeNull();
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toHaveTextContent(/^Planned · 2 nodes$/);

    rerender(
      <AgentBuilderStrip attachment={attachment({ phase: "applied", nodeRuns: { a: "failed", b: "pending" } })} onSolve={jest.fn()} />,
    );
    expect(words()).toBe(region);
    expect(region).toHaveTextContent(/^Failed · a$/);
  });
});


// The line names no agent: a node that waits for its source goes to its
// sources, the card in this chat, whichever agent finds them (here a user's
// own copy of the Dataset Finder, "My Finder", run by their own copy of the
// Dataflow Builder).
describe("AgentBuilderStrip names no node's finder", () => {
  const myOrchestrator = (session: AgentAttachment["builderSession"]): AgentAttachment => ({
    ...attachment(session),
    coord: "agent.test.my-orchestrator@1",
    name: "My Orchestrator",
    capabilities: ["dataflow.orchestrate"],
  });

  it("the awaiting node's action is Show its sources, whoever finds them", () => {
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
        onShowSources={jest.fn()}
      />,
    );
    const myLine = screen.getByRole("group", { name: "My Orchestrator" });
    expect(within(myLine).getByRole("button", { name: "Show its sources" })).toBeInTheDocument();
    expect(myLine).not.toHaveTextContent(/Dataset Finder|My Finder/);
  });
});

// A plan row's Solve that runs on the server (the listing's `validating`), the
// one a pick goes on with among them, is work on the plan's node: no build
// starts over it.
describe("AgentBuilderStrip while a row's Solve runs on the plan", () => {
  it("offers no build or Step: nothing in its menu can run", () => {
    render(
      <AgentBuilderStrip
        attachment={{ ...withLandedPlan({ a: "created", b: "created" }), validating: { ref: "a", nodeId: "na" } }}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: PLAN_ACTIONS })).toBeNull();
  });

  it("Resume waits for it too, saying why", () => {
    render(
      <AgentBuilderStrip
        attachment={{
          ...withLandedPlan(
            { a: "failed", b: "created" },
            { pauseReason: { kind: "validation-failed", ref: "a", message: "validation failed" } },
          ),
          validating: { ref: "a", nodeId: "na" },
        }}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
      />,
    );
    const resume = screen.getByRole("button", { name: "Resume" });
    expect(resume).toBeDisabled();
    expect(resume).toHaveAttribute("data-tooltip", "A node of this plan is being solved: wait for its Solve to end");
  });
});

// A pause says so until the plan goes on: a pick's own continuation builds the
// plan from the provider, not from this line, and the line no longer says the
// plan is paused once it does.
describe("AgentBuilderStrip: a pause's line goes once the plan goes on", () => {
  it("the Paused line goes once a build of the plan runs again, started elsewhere", () => {
    const paused = {
      ...withLandedPlan(
        { a: "awaiting-source", b: "created" },
        { pauseReason: { kind: "awaiting-source", message: "a needs a source", nodes: [{ ref: "a", nodeId: "na", attachmentId: "att-a" }] } },
      ),
      waitsForYou: ["na"],
    };
    const props = {
      attachment: paused,
      onSolve: jest.fn(),
      onSimulate: jest.fn(),
      onCancelSimulate: jest.fn(),
      onShowSources: jest.fn(),
    } as React.ComponentProps<typeof AgentBuilderStrip>;
    const { rerender } = render(<AgentBuilderStrip {...props} />);
    expect(words()).toHaveTextContent(/^Paused · na needs a source$/);
    // The pick's continuation: a build of the plan from the provider, before
    // the plan's record says anything new. The pause is no longer said, and
    // the line's action is the build's Stop.
    rerender(<AgentBuilderStrip {...props} simulating="auto" />);
    expect(screen.queryByText(/Paused/)).toBeNull();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    // Then the record: the pick placed the loader again.
    rerender(
      <AgentBuilderStrip {...props} attachment={withLandedPlan({ a: "created", b: "created" })} simulating="auto" />,
    );
    expect(screen.queryByText(/^Paused/)).toBeNull();
    // It ends with every node built.
    rerender(<AgentBuilderStrip {...props} attachment={withLandedPlan({ a: "approved", b: "approved" })} simulating={null} />);
    expect(screen.queryByText(/Paused/)).toBeNull();
  });

  // A record saved before the server ended such a pause keeps it: the line
  // reads it as the server now does.
  it("a pause on a failed node something built since says nothing, and a plan built out offers Run workflow", () => {
    const failedThenBuilt = (b: string) =>
      withLandedPlan(
        { a: "validated", b },
        { pauseReason: { kind: "validation-failed", ref: "a", message: "validation failed and nothing was written" } },
      );
    const { rerender } = render(
      <AgentBuilderStrip attachment={failedThenBuilt("created")} onSolve={jest.fn()} onSimulate={jest.fn()} />,
    );
    expect(screen.queryByText(/Paused/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
    expect(words()).toHaveTextContent(/^Planned · 1 of 2 built$/);
    expect(words()).not.toHaveAttribute("data-tooltip");
    rerender(<AgentBuilderStrip attachment={failedThenBuilt("validated")} onSolve={jest.fn()} onSimulate={jest.fn()} />);
    expect(words()).toHaveTextContent(/^Ready · 2 nodes built$/);
    expect(screen.getByRole("button", { name: "Run workflow" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
  });
});

// The batch's card of lines is a run detail: what the last Solve said of the
// plan's nodes is kept on the plan's ledger, which a reload and every tab
// read, and the line's tooltip says it there as the stream says it live.
describe("AgentBuilderStrip says the last Solve's reasons after a reload", () => {
  it("why its nodes failed: no agent that builds nodes", () => {
    const reason = "no installed agent declares node.content.generate";
    render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "applied",
          appliedPlanId: "p1",
          nodeRuns: { n1: "failed", n2: "failed" },
          nodeReasons: { n1: reason, n2: reason },
          batchReason: reason,
        })}
        onSolve={jest.fn()}
      />,
    );
    expect(words()).toHaveTextContent(/^Failed · 2 nodes$/);
    expect(words()).toHaveAttribute("data-tooltip", reason);
  });

  it("the Solve's own reason while nodes are left: it ran out of time", () => {
    const reason = "the batch's time budget (45 min) was spent; Retry continues from here";
    const { rerender } = render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "applied",
          appliedPlanId: "p1",
          nodeRuns: { n1: "solved", n2: "pending" },
          nodeReasons: { n2: reason },
          batchReason: reason,
        })}
        onSolve={jest.fn()}
      />,
    );
    expect(words()).toHaveTextContent(/^Planned · 1 of 2 built$/);
    expect(words()).toHaveAttribute("data-tooltip", reason);
    // Once nothing is left, it says nothing of it.
    rerender(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "ready",
          appliedPlanId: "p1",
          nodeRuns: { n1: "solved", n2: "solved" },
          batchReason: reason,
        })}
        onSolve={jest.fn()}
      />,
    );
    expect(words()).toHaveTextContent(/^Ready · 2 nodes built$/);
    expect(words()).not.toHaveAttribute("data-tooltip");
  });

  it("the live batch's words win", () => {
    render(
      <AgentBuilderStrip
        attachment={attachment({
          phase: "applied",
          appliedPlanId: "p1",
          nodeRuns: { n1: "failed" },
          nodeReasons: { n1: "an older reason" },
        })}
        onSolve={jest.fn()}
        solveErrors={{ n1: "KeyError: 'x'" }}
      />,
    );
    expect(words()).toHaveAttribute("data-tooltip", "KeyError: 'x'");
  });
});

// A menu the line stops drawing closes, and its layer of the modal stack goes
// with it: the chat's Escape is its own again, and the menu never opens again
// by itself when the line draws it again.
describe("AgentBuilderStrip's menu, when a build starts elsewhere", () => {
  it("closes with its layer, and is closed when it comes back", () => {
    const props = {
      attachment: withLandedPlan({ a: "created", b: "created" }),
      onSolve: jest.fn(),
      onSimulate: jest.fn(),
      onCancelSimulate: jest.fn(),
    } as React.ComponentProps<typeof AgentBuilderStrip>;
    const { rerender } = render(<AgentBuilderStrip {...props} />);
    openActions();
    expect(modalStackDepth()).toBe(1);
    // Another tab's build: the line holds its Stop, and no menu.
    rerender(<AgentBuilderStrip {...props} attachment={{ ...props.attachment, buildRunning: "auto" }} />);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.queryByRole("button", { name: PLAN_ACTIONS })).toBeNull();
    expect(modalStackDepth()).toBe(0);
    // The build ended: the menu's button is back, its menu closed.
    rerender(<AgentBuilderStrip {...props} />);
    expect(screen.getByRole("button", { name: PLAN_ACTIONS })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(modalStackDepth()).toBe(0);
  });
});

// Show its sources goes to this chat's card of the node's sources, else to
// its Dataset Finder's chat: its tooltip says which, and with several nodes
// waiting, which node it goes to.
describe("AgentBuilderStrip's Show its sources says where it goes", () => {
  const waiting = (ids: string[]) =>
    ({ ...attachment({ phase: "applied", appliedPlanId: "p1", nodeRuns: Object.fromEntries(ids.map((id) => [id, "pending"])) }), waitsForYou: ids }) as AgentAttachment;

  it("to its Finder's chat, when this chat holds no card of it", () => {
    const hint = "Opens the chat of its Dataset Finder, which holds its sources. Your pick builds it, and the plan goes on.";
    render(<AgentBuilderStrip attachment={waiting(["n1"])} onSolve={jest.fn()} onShowSources={jest.fn()} sourcesHintOf={() => hint} />);
    expect(screen.getByRole("button", { name: "Show its sources" })).toHaveAttribute("data-tooltip", hint);
  });

  it("to this chat, by default", () => {
    render(<AgentBuilderStrip attachment={waiting(["n1"])} onSolve={jest.fn()} onShowSources={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Show its sources" })).toHaveAttribute("data-tooltip", SHOW_SOURCES_HINT);
  });

  it("to the first node's, which it names, when several wait", () => {
    const onShowSources = jest.fn();
    render(<AgentBuilderStrip attachment={waiting(["n1", "n2"])} onSolve={jest.fn()} onShowSources={onShowSources} />);
    const show = screen.getByRole("button", { name: "Show its sources" });
    expect(show).toHaveAttribute("data-tooltip", `n1: ${SHOW_SOURCES_HINT}`);
    fireEvent.click(show);
    expect(onShowSources).toHaveBeenCalledWith("n1");
  });
});
