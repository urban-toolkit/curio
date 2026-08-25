import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { AgentReviewCard } from "../../components/agents/content/AgentReviewCard";
import type { AgentProposalPart } from "../../api/agentsApi";

const part = (status: AgentProposalPart["status"] = "pending"): AgentProposalPart => ({
  type: "proposal",
  proposalId: "p1",
  tool: "node.content.write",
  summary: "Replace the content of node 'n1'",
  preview: "print(2)",
  pins: { nodeId: "n1", contentSha256: "abc" },
  status,
});

describe("AgentReviewCard (review-before-apply, memo dev/41)", () => {
  it("pending renders the preview and the system review controls", () => {
    render(<AgentReviewCard part={part()} onApply={jest.fn()} onDismiss={jest.fn()} />);
    expect(screen.getByText("print(2)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("the preview renders model output inert (REQ-SEC-002)", () => {
    const hostile = { ...part(), preview: '<script>window.__reviewPwned = true;</script>' };
    const { container } = render(<AgentReviewCard part={hostile} onApply={jest.fn()} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>");
    expect((window as unknown as { __reviewPwned?: boolean }).__reviewPwned).toBeUndefined();
  });

  it("apply routes through the callback and shows the busy state", async () => {
    let release: () => void = () => undefined;
    const onApply = jest.fn().mockImplementation(
      () => new Promise<void>((r) => {
        release = r;
      }),
    );
    render(<AgentReviewCard part={part()} onApply={onApply} />);
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(onApply).toHaveBeenCalledWith("p1");
    expect(screen.getByRole("button", { name: "Applying…" })).toBeDisabled();
    release();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Apply" })).not.toBeDisabled(),
    );
  });

  it("a failed apply surfaces the error (e.g. the 409 stale conflict)", async () => {
    const onApply = jest.fn().mockRejectedValue(new Error("the node changed since this was proposed"));
    render(<AgentReviewCard part={part()} onApply={onApply} />);
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() =>
      expect(screen.getByText(/node changed since/)).toBeInTheDocument(),
    );
  });

  it.each([
    ["applied", "Applied"],
    ["dismissed", "Dismissed"],
    ["superseded", /Superseded/],
    ["stale", /changed since this was proposed/],
  ] as const)("%s renders inert with its outcome label", (status, label) => {
    const { container } = render(
      <AgentReviewCard part={part(status)} onApply={jest.fn()} onDismiss={jest.fn()} />,
    );
    expect(container.querySelector("button")).toBeNull();
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});

describe("AgentReviewCard — dev/48 proposal kinds", () => {
  it("node.create shows the creation effect line", () => {
    const create: AgentProposalPart = {
      type: "proposal",
      proposalId: "p2",
      tool: "node.create",
      summary: "Create a new Computation Analysis node",
      preview: "print('new')",
      pins: { nodeType: "curio.builtin/computation-analysis" },
      status: "pending",
    };
    render(<AgentReviewCard part={create} onApply={jest.fn()} onDismiss={jest.fn()} />);
    expect(screen.getByText("Create a new Computation Analysis node")).toBeInTheDocument();
    expect(screen.getByText("Applying adds this node to the canvas.")).toBeInTheDocument();
  });

  it("project.install states the install-only effect", () => {
    const install: AgentProposalPart = {
      type: "proposal",
      proposalId: "p3",
      tool: "project.install",
      summary: "Install Node Content Builder in this project",
      preview: "Capability node.content.generate requires Node Content Builder…",
      pins: { coord: "agent.node-content-builder@1.0.0" },
      status: "pending",
    };
    render(<AgentReviewCard part={install} onApply={jest.fn()} />);
    expect(
      screen.getByText(/installs only this project template/),
    ).toBeInTheDocument();
  });

  it("node.template.create renders the justification FIRST and the two-effects line", () => {
    const template: AgentProposalPart = {
      type: "proposal",
      proposalId: "p4",
      tool: "node.template.create",
      summary: "Create a new custom node type · Sentiment Scorer",
      preview: "print('score')",
      pins: { templateSlug: "sentiment-scorer" },
      status: "pending",
      justification: "Considered computation-analysis: it cannot hold streaming output.",
      template: { label: "Sentiment Scorer", engine: "python", description: "Scores text." },
    };
    const { container } = render(<AgentReviewCard part={template} onApply={jest.fn()} />);
    const justification = screen.getByLabelText("Why a new node type is needed");
    expect(justification).toHaveTextContent("cannot hold streaming output");
    // The reasoning is what the user judges: it precedes the code preview.
    const text = container.textContent ?? "";
    expect(text.indexOf("cannot hold streaming output")).toBeLessThan(
      text.indexOf("print('score')"),
    );
    expect(screen.getByText(/Sentiment Scorer · python — Scores text\./)).toBeInTheDocument();
    expect(
      screen.getByText("Applying registers the node type in this project and adds its first node."),
    ).toBeInTheDocument();
  });

  it("plain node.content.write cards carry no effect line (unchanged dev/41 shape)", () => {
    render(<AgentReviewCard part={part()} onApply={jest.fn()} />);
    expect(screen.queryByText(/Applying/)).toBeNull();
  });
});

describe("AgentReviewCard — dev/50 dataset.install kind", () => {
  it("states the dataset-only effect", () => {
    const install: AgentProposalPart = {
      type: "proposal",
      proposalId: "p5",
      tool: "dataset.install",
      summary: "Install dataset · Cities",
      preview: "Cities · csv · imported",
      pins: { datasetId: "imported.abc@1" },
      status: "pending",
    };
    render(<AgentReviewCard part={install} onApply={jest.fn()} />);
    expect(
      screen.getByText(/installs only this dataset into the project's Data Catalog/),
    ).toBeInTheDocument();
  });
});

describe("AgentReviewCard — dev/52 dataflow.plan.write kind", () => {
  it("renders summary-first counts, the node list, and the dynamic effect line", () => {
    const plan: AgentProposalPart = {
      type: "proposal",
      proposalId: "p6",
      tool: "dataflow.plan.write",
      summary: "Apply plan · 2 nodes, 1 edges",
      preview: "Load · curio.builtin/data-loading — load it\nAnalyze · curio.builtin/computation-analysis — crunch it",
      pins: { baseGraphDigest: "abc" },
      status: "pending",
      plan: {
        goal: "heat analysis",
        nodes: [
          { ref: "a", nodeType: "curio.builtin/data-loading", title: "Load", intent: "load it" },
          { ref: "b", nodeType: "curio.builtin/computation-analysis", title: "Analyze", intent: "crunch it" },
        ],
        edgeCount: 1,
      },
    };
    render(<AgentReviewCard part={plan} onApply={jest.fn()} onDismiss={jest.fn()} />);
    expect(screen.getByText("2 nodes · 1 connections — heat analysis")).toBeInTheDocument();
    expect(screen.getByText(/Load · curio.builtin\/data-loading/)).toBeInTheDocument();
    expect(
      screen.getByText("Applying adds these 2 connected nodes to the canvas — existing work is untouched."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply" })).toBeInTheDocument();
  });
});

describe("AgentReviewCard — dev/59 destructive revision (DEC-049.2)", () => {
  const revision: AgentProposalPart = {
    type: "proposal",
    proposalId: "p7",
    tool: "dataflow.plan.write",
    summary: "Apply plan · 1 nodes, 1 edges, removes 1 node",
    preview: "API Fetch · curio.builtin/computation-analysis — fetch\n− Remove: Load CSV",
    pins: { baseGraphDigest: "abc" },
    status: "pending",
    plan: {
      goal: "replace the loader",
      nodes: [{ ref: "a", nodeType: "curio.builtin/computation-analysis", title: "API Fetch", intent: "fetch" }],
      edgeCount: 1,
      removals: [
        { id: "old-loader", label: "Load CSV", nodeType: "curio.builtin/computation-analysis", contentChars: 10 },
        { id: "scratch", label: "Scratch", contentChars: 0 },
      ],
      cascadeCount: 1,
    },
  };

  it("names every victim with a content flag and the cascade", () => {
    render(<AgentReviewCard part={revision} onApply={jest.fn()} onDismiss={jest.fn()} />);
    const section = screen.getByRole("group", { name: "Nodes this plan removes" });
    expect(section).toHaveTextContent("Removes 2 nodes (and 1 connected edge)");
    expect(section).toHaveTextContent("Load CSV · curio.builtin/computation-analysis — contains 10 chars of content");
    expect(section).toHaveTextContent("Scratch — empty");
    expect(
      screen.getByText("Applying adds 1 node and removes 2 — removal deletes their content and cannot be undone."),
    ).toBeInTheDocument();
  });

  it("additive plans render no Removes section (regression)", () => {
    const additive = { ...revision, plan: { ...revision.plan!, removals: undefined, cascadeCount: undefined } };
    render(<AgentReviewCard part={additive} onApply={jest.fn()} />);
    expect(screen.queryByRole("group", { name: "Nodes this plan removes" })).toBeNull();
    expect(screen.getByText(/existing work is untouched/)).toBeInTheDocument();
  });
});

describe("AgentReviewCard — dev/67-5 per-node plan review (Simulation Mode: create)", () => {
  const planPart = (): AgentProposalPart => ({
    type: "proposal",
    proposalId: "p7",
    tool: "dataflow.plan.write",
    summary: "Apply plan · 2 nodes, 1 edges",
    preview: "should not render when per-node rows do",
    pins: { baseGraphDigest: "abc" },
    status: "pending",
    plan: {
      goal: "heat analysis",
      nodes: [
        { ref: "a", nodeType: "curio.builtin/data-loading", title: "Load",
          intent: "load it", expects: "in: none · out: dataframe" },
        { ref: "b", nodeType: "curio.builtin/computation-analysis", title: "Analyze",
          intent: "crunch it" },
      ],
      edgeCount: 1,
    },
  });

  it("renders per-node rows with editable goals, expects, and per-node Apply", () => {
    render(
      <AgentReviewCard
        part={planPart()}
        onApplyPlanNode={jest.fn()}
        onSavePlanGoal={jest.fn()}
        planNodeState={{ appliedRefs: [], editedGoals: {} }}
      />,
    );
    // Rows replace the raw preview — no generated code surface on plans.
    expect(screen.queryByText(/should not render/)).toBeNull();
    expect(screen.getByText("in: none · out: dataframe")).toBeInTheDocument();
    expect(screen.getByLabelText("Goal for Load")).toHaveValue("load it");
    expect(screen.getByRole("button", { name: "Create node Load" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Create node Analyze" })).toBeEnabled();
  });

  it("an edited goal saves on blur and an applied ref renders Created ✓", async () => {
    const onSavePlanGoal = jest.fn().mockResolvedValue(undefined);
    render(
      <AgentReviewCard
        part={planPart()}
        onApplyPlanNode={jest.fn()}
        onSavePlanGoal={onSavePlanGoal}
        planNodeState={{ appliedRefs: ["a"], editedGoals: { b: "crunch 2024 only" } }}
      />,
    );
    // Applied ref: no Apply button, Created marker, goal locked.
    expect(screen.queryByRole("button", { name: "Create node Load" })).toBeNull();
    expect(screen.getByText("Created ✓")).toBeInTheDocument();
    expect(screen.getByLabelText("Goal for Load")).toBeDisabled();
    // The edited goal overlay renders; a new edit saves on blur.
    const goalB = screen.getByLabelText("Goal for Analyze");
    expect(goalB).toHaveValue("crunch 2024 only");
    fireEvent.change(goalB, { target: { value: "crunch 2025 instead" } });
    fireEvent.blur(goalB);
    await waitFor(() =>
      expect(onSavePlanGoal).toHaveBeenCalledWith("p7", "b", "crunch 2025 instead"),
    );
  });

  it("per-node Apply targets the row's ref", async () => {
    const onApplyPlanNode = jest.fn().mockResolvedValue(undefined);
    render(
      <AgentReviewCard
        part={planPart()}
        onApplyPlanNode={onApplyPlanNode}
        onSavePlanGoal={jest.fn()}
        planNodeState={{ appliedRefs: [], editedGoals: {} }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Create node Analyze" }));
    await waitFor(() => expect(onApplyPlanNode).toHaveBeenCalledWith("p7", "b"));
  });

  it("without the per-node callback the classic preview renders (regression)", () => {
    render(<AgentReviewCard part={planPart()} onApply={jest.fn()} />);
    expect(screen.getByText(/should not render when per-node rows do/)).toBeInTheDocument();
  });
});

describe("AgentReviewCard — dev/67-7 validation block", () => {
  const validated = (verdict: "pass" | "fail", evidence = {}): AgentProposalPart => ({
    ...part(),
    validation: { verdict, rounds: verdict === "pass" ? 1 : 3, evidence },
  });

  it("renders PASS with the output type", () => {
    render(
      <AgentReviewCard
        part={validated("pass", { outputDataType: "dataframe" })}
        onApply={jest.fn()}
      />,
    );
    expect(screen.getByText("PASS")).toBeInTheDocument();
    expect(screen.getByText(/output: dataframe/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply" })).toBeInTheDocument();
  });

  it("renders FAIL with the traceback and labels Apply honestly", () => {
    render(
      <AgentReviewCard
        part={validated("fail", { kind: "execution-error", stderrTail: "Traceback: KeyError" })}
        onApply={jest.fn()}
      />,
    );
    expect(screen.getByText("FAIL")).toBeInTheDocument();
    expect(screen.getByText("Traceback: KeyError")).toBeInTheDocument();
    // Apply stays available — honesty over gatekeeping, labeled plainly.
    expect(screen.getByRole("button", { name: "Apply anyway" })).toBeInTheDocument();
  });

  it("names an upstream blocker instead of blaming the node", () => {
    render(
      <AgentReviewCard
        part={validated("fail", { kind: "upstream-blocker", blockerLabel: "Load CSV" })}
        onApply={jest.fn()}
      />,
    );
    expect(screen.getByText(/Upstream node Load CSV failed/)).toBeInTheDocument();
  });

  it("proposals without validation render exactly as before (regression)", () => {
    render(<AgentReviewCard part={part()} onApply={jest.fn()} />);
    expect(screen.queryByText("PASS")).toBeNull();
    expect(screen.getByRole("button", { name: "Apply" })).toBeInTheDocument();
  });
});

describe("AgentReviewCard — dev/67-8 connection review stage", () => {
  const planWithEdges = (): AgentProposalPart => ({
    type: "proposal",
    proposalId: "p8",
    tool: "dataflow.plan.write",
    summary: "Apply plan · 2 nodes, 2 edges",
    preview: "…",
    pins: { baseGraphDigest: "abc" },
    status: "pending",
    plan: {
      goal: "g",
      nodes: [
        { ref: "a", nodeType: "t", title: "Load", intent: "load" },
        { ref: "b", nodeType: "t", title: "Merge", intent: "merge" },
      ],
      edgeCount: 2,
      edges: [
        { from: "a", to: "b", toHandle: "in_0", fromLabel: "Load", toLabel: "Merge" },
        { from: "b", to: "existing-1", fromLabel: "Merge", toLabel: "Old Analyze" },
      ],
    },
  });

  it("renders named rows, gates on endpoint creation, and connects per edge", async () => {
    const onApplyPlanEdges = jest.fn().mockResolvedValue(undefined);
    render(
      <AgentReviewCard
        part={planWithEdges()}
        onApplyPlanNode={jest.fn()}
        onApplyPlanEdges={onApplyPlanEdges}
        planNodeState={{ appliedRefs: ["a"], editedGoals: {}, edgeStates: {} }}
      />,
    );
    expect(screen.getByText("Load → Merge [in_0]")).toBeInTheDocument();
    // Edge 0: target ref "b" not created yet → disabled with the reason.
    const first = screen.getByRole("button", { name: "Connect Load to Merge" });
    expect(first).toBeDisabled();
    expect(first).toHaveAttribute("title", "create 'Merge' first");
    // Edge 1: source ref "b" not created either → disabled; existing-id
    // endpoints alone never block.
    expect(screen.getByRole("button", { name: "Connect Merge to Old Analyze" })).toBeDisabled();
    // With both refs created, rows enable and target their index.
    render(
      <AgentReviewCard
        part={planWithEdges()}
        onApplyPlanNode={jest.fn()}
        onApplyPlanEdges={onApplyPlanEdges}
        planNodeState={{ appliedRefs: ["a", "b"], editedGoals: {}, edgeStates: {} }}
      />,
    );
    const enabled = screen.getAllByRole("button", { name: "Connect Load to Merge" })[1] ??
      screen.getAllByRole("button", { name: "Connect Load to Merge" })[0];
    fireEvent.click(enabled);
    await waitFor(() => expect(onApplyPlanEdges).toHaveBeenCalledWith("p8", [0]));
  });

  it("shows per-edge states and Connect all", async () => {
    const onApplyPlanEdges = jest.fn().mockResolvedValue(undefined);
    render(
      <AgentReviewCard
        part={planWithEdges()}
        onApplyPlanNode={jest.fn()}
        onApplyPlanEdges={onApplyPlanEdges}
        planNodeState={{
          appliedRefs: ["a", "b"],
          editedGoals: {},
          edgeStates: { "0": "applied", "1": "refused" },
        }}
      />,
    );
    expect(screen.getByText("Connected ✓")).toBeInTheDocument();
    expect(screen.getByText("Refused ✗")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Connect all" }));
    await waitFor(() => expect(onApplyPlanEdges).toHaveBeenCalledWith("p8", undefined));
  });
});

describe("AgentReviewCard — dev/71 progressive lifecycle rows", () => {
  const progressivePlan = (): AgentProposalPart => ({
    type: "proposal",
    proposalId: "p9",
    tool: "dataflow.plan.write",
    summary: "Apply plan · 2 nodes, 1 edges",
    preview: "…",
    pins: { baseGraphDigest: "abc" },
    status: "pending",
    plan: {
      goal: "g",
      nodes: [
        { ref: "a", nodeType: "t", title: "Load", intent: "load" },
        { ref: "b", nodeType: "t", title: "Analyze", intent: "crunch" },
      ],
      edgeCount: 1,
      edges: [{ from: "a", to: "b", fromLabel: "Load", toLabel: "Analyze" }],
    },
  });

  const renderRows = (state: {
    appliedRefs: string[];
    nodeStates?: Record<string, string>;
    edgeStates?: Record<string, string>;
  }, handlers: { onSolve?: jest.Mock; onRun?: jest.Mock } = {}) =>
    render(
      <AgentReviewCard
        part={progressivePlan()}
        onApplyPlanNode={jest.fn()}
        onSolvePlanNode={handlers.onSolve ?? jest.fn()}
        onRunPlanNode={handlers.onRun ?? jest.fn()}
        planNodeState={{ editedGoals: {}, ...state }}
      />,
    );

  it("rows name their dependencies", () => {
    renderRows({ appliedRefs: [] });
    expect(screen.getByText("needs: Load")).toBeInTheDocument();
  });

  it("Solve gates on connected + solved dependencies, with the blocker named", () => {
    // b created but the edge not applied → disabled, names the connection.
    renderRows({
      appliedRefs: ["a", "b"],
      nodeStates: { a: "created", b: "created" },
      edgeStates: {},
    });
    const solveB = screen.getByRole("button", { name: "Solve node Analyze" });
    expect(solveB).toBeDisabled();
    expect(solveB).toHaveAttribute("title", "needs 'Load' connected first");
  });

  it("Solve enables when the edge is applied and upstream is approved", async () => {
    const onSolve = jest.fn().mockResolvedValue(undefined);
    renderRows(
      {
        appliedRefs: ["a", "b"],
        nodeStates: { a: "approved", b: "created" },
        edgeStates: { "0": "applied" },
      },
      { onSolve },
    );
    const solveB = screen.getByRole("button", { name: "Solve node Analyze" });
    expect(solveB).toBeEnabled();
    fireEvent.click(solveB);
    await waitFor(() => expect(onSolve).toHaveBeenCalledWith("b"));
    // Upstream approved rows show Run, not Solve.
    expect(screen.queryByRole("button", { name: "Solve node Load" })).toBeNull();
    expect(screen.getByText("Solved ✓")).toBeInTheDocument();
  });

  it("Run appears on approved rows and targets the ref", async () => {
    const onRun = jest.fn().mockResolvedValue(undefined);
    renderRows(
      {
        appliedRefs: ["a", "b"],
        nodeStates: { a: "approved", b: "approved" },
        edgeStates: { "0": "applied" },
      },
      { onRun },
    );
    fireEvent.click(screen.getByRole("button", { name: "Run through node Analyze" }));
    await waitFor(() => expect(onRun).toHaveBeenCalledWith("b"));
  });
});

describe("AgentReviewCard — dev/72 review-chip icon-link to the node agent", () => {
  const plan = (): AgentProposalPart => ({
    type: "proposal",
    proposalId: "p10",
    tool: "dataflow.plan.write",
    summary: "Apply plan · 1 node",
    preview: "…",
    pins: { baseGraphDigest: "abc" },
    status: "pending",
    plan: {
      goal: "g",
      nodes: [{ ref: "a", nodeType: "t", title: "Load", intent: "load" }],
      edgeCount: 0,
      edges: [],
    },
  });

  it("the chip links to the homed review's agent chat", () => {
    const onOpenAgentChat = jest.fn();
    render(
      <AgentReviewCard
        part={plan()}
        onApplyPlanNode={jest.fn()}
        onOpenAgentChat={onOpenAgentChat}
        delegateExists={(id) => id === "att-nb"}
        planNodeState={{
          appliedRefs: ["a"],
          editedGoals: {},
          nodeStates: { a: "solving" },
          nodeProposals: { a: { proposalId: "cp1", attachmentId: "att-nb" } },
        }}
      />,
    );
    expect(screen.getByText("Content review pending")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /open the node agent's chat/i }));
    expect(onOpenAgentChat).toHaveBeenCalledWith("att-nb");
  });

  it("legacy builder-homed (string) and stale homes render no link", () => {
    const { rerender } = render(
      <AgentReviewCard
        part={plan()}
        onApplyPlanNode={jest.fn()}
        onOpenAgentChat={jest.fn()}
        planNodeState={{
          appliedRefs: ["a"],
          editedGoals: {},
          nodeStates: { a: "solving" },
          nodeProposals: { a: "cp1" },
        }}
      />,
    );
    expect(screen.queryByRole("button", { name: /open the node agent/i })).toBeNull();
    rerender(
      <AgentReviewCard
        part={plan()}
        onApplyPlanNode={jest.fn()}
        onOpenAgentChat={jest.fn()}
        delegateExists={() => false}
        planNodeState={{
          appliedRefs: ["a"],
          editedGoals: {},
          nodeStates: { a: "solving" },
          nodeProposals: { a: { proposalId: "cp1", attachmentId: "gone" } },
        }}
      />,
    );
    expect(screen.queryByRole("button", { name: /open the node agent/i })).toBeNull();
  });
});

describe("AgentReviewCard backend trust edge (memo dev/91 §5)", () => {
  const backendPart = (network = false): AgentProposalPart => ({
    type: "proposal",
    proposalId: "p9",
    tool: "package.draft.apply",
    summary: "Build package · Word Count",
    preview: "1 added / 0 modified / 0 preserved files; 0 node(s) after install",
    pins: { artifactDigest: "d".repeat(64), target: "ai.agent.wordcount@1" },
    status: "pending",
    backend: {
      handlers: [{ name: "word-count", timeoutClass: "quick" }],
      permissions: network ? ["server-code", "server-network"] : ["server-code"],
      network,
    },
  });

  it("states the server-code edge, handlers, and permission meanings before Apply", () => {
    render(<AgentReviewCard part={backendPart()} onApply={jest.fn()} />);
    const block = screen.getByRole("group", {
      name: "Server-side code this package runs",
    });
    expect(block).toHaveTextContent("Runs server-side code in the package sandbox");
    expect(block).toHaveTextContent("no network access");
    expect(block).toHaveTextContent("handler word-count · quick limits");
    expect(block).toHaveTextContent("permission server-code");
    expect(block).toHaveTextContent("never inside Curio itself");
  });

  it("a declared server-network permission is impossible to miss", () => {
    render(<AgentReviewCard part={backendPart(true)} onApply={jest.fn()} />);
    const block = screen.getByRole("group", {
      name: "Server-side code this package runs",
    });
    expect(block).toHaveTextContent("may reach the network (server-network declared)");
    expect(block).toHaveTextContent("permission server-network");
  });

  it("a backend-less draft renders no server-code block", () => {
    const plain = { ...backendPart(), backend: undefined };
    render(<AgentReviewCard part={plain} onApply={jest.fn()} />);
    expect(
      screen.queryByRole("group", { name: "Server-side code this package runs" }),
    ).toBeNull();
  });
});

describe("AgentReviewCard rich draft sections (memo dev/96)", () => {
  const draftPart = (
    overrides: Partial<NonNullable<AgentProposalPart["draft"]>> = {},
  ): AgentProposalPart => ({
    type: "proposal",
    proposalId: "p10",
    tool: "package.draft.apply",
    summary: "Build package · Card",
    preview: "2 added / 0 modified / 0 preserved files; 1 node(s) after install",
    pins: { artifactDigest: "d".repeat(64), target: "ai.test.card@1" },
    status: "pending",
    draft: {
      mode: "create",
      target: "ai.test.card@1",
      files: { added: ["sources/note.tsx", "backend/handler.py"], modified: [],
               addedTotal: 2, modifiedTotal: 0, preservedTotal: 0 },
      templates: { added: ["note-kind"], modified: [], addedTotal: 1,
                   modifiedTotal: 0, preservedTotal: 0 },
      ...overrides,
    },
  });

  it("renders the three counts summaries collapsed, names on expand", () => {
    render(<AgentReviewCard part={draftPart()} onApply={jest.fn()} />);
    expect(screen.getByText("Files — 2 added · 0 modified · 0 preserved")).toBeInTheDocument();
    expect(screen.getByText("added sources/note.tsx")).toBeInTheDocument();
    expect(screen.getByText(/templates: 1 added/)).toBeInTheDocument();
  });

  it("states overflow honestly — never silent truncation", () => {
    const part = draftPart({
      files: { added: ["a.py"], modified: [], addedTotal: 21,
               modifiedTotal: 0, preservedTotal: 3 },
      templates: { added: [], modified: [], addedTotal: 0,
                   modifiedTotal: 0, preservedTotal: 0 },
    });
    render(<AgentReviewCard part={part} onApply={jest.fn()} />);
    expect(screen.getByText("…and 20 more added")).toBeInTheDocument();
  });

  it("a blocking finding renders OPEN with block styling", () => {
    const part = draftPart({
      dependencies: {
        python: [{ name: "torch", constraint: "2.4.0" }], pythonTotal: 1,
        js: [], jsTotal: 0,
        findings: [{ severity: "block", code: "py-conflict",
                     message: "torch conflicts with installed packages" }],
        findingsTotal: 1, blocked: true,
      },
    });
    const { container } = render(<AgentReviewCard part={part} onApply={jest.fn()} />);
    const deps = screen.getByText(/Dependencies — 1 python/).closest("details");
    expect(deps).toHaveAttribute("open");
    expect(screen.getByText("block: torch conflicts with installed packages")).toBeInTheDocument();
    expect(container.textContent).toContain("python · torch 2.4.0");
  });

  it("the skipped-preview honesty line renders verbatim", () => {
    const part = draftPart({
      preview: {
        status: "skipped",
        reasons: ["preview SKIPPED BY OPERATOR POLICY (CURIO_BUILD_PREVIEW_POLICY=skip; no pinned runner is configured) — this custom behavior was NOT rendered before review"],
        reasonsTotal: 1, templates: [], runnerVersion: "",
      },
    });
    render(<AgentReviewCard part={part} onApply={jest.fn()} />);
    expect(screen.getByText("Preview — skipped")).toBeInTheDocument();
    expect(screen.getByText(/NOT rendered before review/)).toBeInTheDocument();
  });

  it("a failed preview opens with its failed states named", () => {
    const part = draftPart({
      preview: {
        status: "failed", reasons: ["note-kind/error: console errors"],
        reasonsTotal: 1,
        templates: [{ templateId: "note-kind", ok: false, failedStates: ["error"] }],
        runnerVersion: "preview-runner/1",
      },
    });
    render(<AgentReviewCard part={part} onApply={jest.fn()} />);
    const preview = screen.getByText("Preview — failed").closest("details");
    expect(preview).toHaveAttribute("open");
    expect(screen.getByText("note-kind: failed states — error")).toBeInTheDocument();
  });

  it("requested nodes line carries titles and colors", () => {
    const part = draftPart({
      requestedNodes: { rows: [{ title: "Question", color: "#fef3c0" }], total: 3 },
    });
    render(<AgentReviewCard part={part} onApply={jest.fn()} />);
    expect(screen.getByText(/Creates 3 nodes after install: Question \(#fef3c0\), …and 2 more/)).toBeInTheDocument();
  });

  it("pre-dev/96 parts (no draft field) render exactly as before", () => {
    const legacy = { ...draftPart(), draft: undefined };
    render(<AgentReviewCard part={legacy} onApply={jest.fn()} />);
    expect(screen.queryByText(/Files —/)).toBeNull();
    expect(screen.getByRole("button", { name: "Apply" })).toBeInTheDocument();
  });
});

describe("dependency home line (memo dev/97)", () => {
  const withDeps = (home: string): AgentProposalPart => ({
    type: "proposal",
    proposalId: "p11",
    tool: "package.draft.apply",
    summary: "Build package · Card",
    preview: "counts",
    pins: { artifactDigest: "d".repeat(64), target: "ai.test.card@1" },
    status: "pending",
    draft: {
      mode: "create", target: "ai.test.card@1",
      files: { added: [], modified: [], addedTotal: 0, modifiedTotal: 0, preservedTotal: 0 },
      templates: { added: [], modified: [], addedTotal: 0, modifiedTotal: 0, preservedTotal: 0 },
      dependencies: { home, python: [{ name: "tinylib", constraint: "1.0.0" }],
                      pythonTotal: 1, js: [], jsTotal: 0, findings: [],
                      findingsTotal: 0, blocked: false },
    },
  });

  it("overlay routing states the isolation", () => {
    render(<AgentReviewCard part={withDeps("overlay")} onApply={jest.fn()} />);
    expect(screen.getByText(/isolated overlay —.*shared interpreter is not touched/s)).toBeInTheDocument();
  });

  it("both routing names the warm-sandbox half", () => {
    render(<AgentReviewCard part={withDeps("both")} onApply={jest.fn()} />);
    expect(screen.getByText(/plus the shared interpreter for its python node templates/)).toBeInTheDocument();
  });

  it("host routing adds no line (status quo)", () => {
    render(<AgentReviewCard part={withDeps("host")} onApply={jest.fn()} />);
    expect(screen.queryByText(/isolated overlay/)).toBeNull();
  });
});
