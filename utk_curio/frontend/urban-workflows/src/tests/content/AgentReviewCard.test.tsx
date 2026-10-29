import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { AgentReviewCard, nodeKindExecutable } from "../../components/agents/content/AgentReviewCard";
import { MADE_BEFORE_DIRECT_EDITS } from "../../components/agents/content/reviewCard/reviewCardText";
import { AGENT_CHANGE_TOOLS, type AgentProposalPart } from "../../services/agents";

/** An install an agent asked for: it changes the account, so it waits for review. */
const part = (status: AgentProposalPart["status"] = "pending"): AgentProposalPart => ({
  type: "proposal",
  proposalId: "p1",
  tool: "dataset.install",
  summary: "Install dataset · Cities",
  preview: "Cities · csv · imported",
  pins: { datasetId: "imported.abc@1" },
  status,
});

describe("AgentReviewCard (an install's review, memo dev/41)", () => {
  it("pending renders the preview and the system review controls", () => {
    render(<AgentReviewCard part={part()} onApply={jest.fn()} onDismiss={jest.fn()} />);
    expect(screen.getByText("Cities · csv · imported")).toBeInTheDocument();
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
    const onApply = jest.fn().mockRejectedValue(new Error("the dataset is no longer available"));
    render(<AgentReviewCard part={part()} onApply={onApply} />);
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() =>
      expect(screen.getByText(/no longer available/)).toBeInTheDocument(),
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

describe("AgentReviewCard: a review of a change saved before agents edited the dataflow directly", () => {
  /** A review the agent made of *tool* before its work landed by itself, as a
   * saved chat still holds it: pending, never applied. */
  const saved = (tool: string, status: AgentProposalPart["status"] = "pending"): AgentProposalPart => ({
    type: "proposal",
    proposalId: `saved-${tool}`,
    tool,
    summary: `Saved review · ${tool}`,
    preview: "print('the agent wrote this before')",
    pins: { nodeId: "n1" },
    status,
  });

  // Every tool whose work now lands as the agent's change, as the shared file
  // names them (contracts/agentChanges.json, which the server reads too).
  it.each([...AGENT_CHANGE_TOOLS].sort())(
    "a pending %s review says it can no longer be applied and keeps Dismiss alone",
    async (tool) => {
      const onApply = jest.fn().mockResolvedValue(undefined);
      const onDismiss = jest.fn().mockResolvedValue(undefined);
      render(<AgentReviewCard part={saved(tool)} onApply={onApply} onDismiss={onDismiss} />);
      expect(screen.getByText(MADE_BEFORE_DIRECT_EDITS)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
      await waitFor(() => expect(onDismiss).toHaveBeenCalledWith(`saved-${tool}`));
      expect(onApply).not.toHaveBeenCalled();
    },
  );

  it("one already dismissed keeps its outcome label and nothing more", () => {
    const { container } = render(
      <AgentReviewCard part={saved("node.create", "dismissed")} onApply={jest.fn()} onDismiss={jest.fn()} />,
    );
    expect(screen.getByText("Dismissed")).toBeInTheDocument();
    expect(screen.queryByText(MADE_BEFORE_DIRECT_EDITS)).toBeNull();
    expect(container.querySelector("button")).toBeNull();
  });

  it("an install keeps its Apply and says nothing of when it was made", () => {
    render(<AgentReviewCard part={part()} onApply={jest.fn()} onDismiss={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Apply" })).toBeInTheDocument();
    expect(screen.queryByText(MADE_BEFORE_DIRECT_EDITS)).toBeNull();
  });
});

describe("AgentReviewCard: dev/48 install kinds", () => {
  it("project.install states the install-only effect", () => {
    const install: AgentProposalPart = {
      type: "proposal",
      proposalId: "p3",
      tool: "project.install",
      summary: "Install Node Builder in this project",
      preview: "Capability node.content.generate requires Node Builder…",
      pins: { coord: "agent.curio.node-builder@1" },
      status: "pending",
    };
    render(<AgentReviewCard part={install} onApply={jest.fn()} />);
    expect(
      screen.getByText(/installs only this project template/),
    ).toBeInTheDocument();
  });

  it("a package draft that adds a node type renders its justification FIRST", () => {
    // A draft is the one way an agent makes a node type: its justification
    // is what the user judges, so it precedes the draft's details and preview.
    const draft: AgentProposalPart = {
      type: "proposal",
      proposalId: "p4",
      tool: "package.draft.apply",
      summary: "Build package · Sentiment",
      preview: "1 added / 0 modified / 0 preserved files; 1 node(s) after install",
      pins: { artifactDigest: "d".repeat(64), target: "ai.agent.sentiment@1" },
      status: "pending",
      justification: "Considered curio.builtin/computation-analysis: it cannot hold streaming output.",
      draft: {
        mode: "create",
        target: "ai.agent.sentiment@1",
        files: { added: ["sources/scorer.py"], modified: [], addedTotal: 1,
                 modifiedTotal: 0, preservedTotal: 0 },
        templates: { added: ["sentiment-scorer"], modified: [], addedTotal: 1,
                     modifiedTotal: 0, preservedTotal: 0 },
      },
    };
    const { container } = render(<AgentReviewCard part={draft} onApply={jest.fn()} />);
    const justification = screen.getByLabelText("Why a new node type is needed");
    expect(justification).toHaveTextContent("cannot hold streaming output");
    const text = container.textContent ?? "";
    const reasoning = text.indexOf("cannot hold streaming output");
    expect(reasoning).toBeLessThan(text.indexOf("Files: 1 added"));
    expect(reasoning).toBeLessThan(text.indexOf("1 added / 0 modified / 0 preserved files"));
    expect(
      screen.getByText(
        "Applying installs the exact reviewed artifact and creates its requested nodes; nothing else changes.",
      ),
    ).toBeInTheDocument();
  });

  it("a draft that adds no node type shows no justification block", () => {
    const extend: AgentProposalPart = {
      type: "proposal",
      proposalId: "p5",
      tool: "package.draft.apply",
      summary: "Extend package · Sentiment",
      preview: "0 added / 1 modified / 3 preserved files; 0 node(s) after install",
      pins: { artifactDigest: "e".repeat(64), target: "ai.agent.sentiment@1" },
      status: "pending",
    };
    render(<AgentReviewCard part={extend} onApply={jest.fn()} />);
    expect(screen.queryByLabelText("Why a new node type is needed")).toBeNull();
  });

  it("an install kind with no effect line of its own carries none (a Discovery download)", () => {
    render(<AgentReviewCard part={{ ...part(), tool: "discovery.acquire" }} onApply={jest.fn()} />);
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
    expect(block).toHaveTextContent("may reach the network, server-network declared");
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
    expect(screen.getByText("Files: 2 added · 0 modified · 0 preserved")).toBeInTheDocument();
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
    const deps = screen.getByText(/Dependencies: 1 python/).closest("details");
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
    expect(screen.getByText("Preview: skipped")).toBeInTheDocument();
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
    const preview = screen.getByText("Preview: failed").closest("details");
    expect(preview).toHaveAttribute("open");
    expect(screen.getByText("note-kind: failed states: error")).toBeInTheDocument();
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
    expect(screen.queryByText(/Files:/)).toBeNull();
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
    expect(screen.getByText(/isolated overlay;.*shared interpreter is not touched/s)).toBeInTheDocument();
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


describe("nodeKindExecutable (dev/118, dev/119)", () => {
  it("reads the roster's flag, and falls back to the registry descriptor for a part minted before it", () => {
    expect(nodeKindExecutable({ nodeType: "x", executable: true })).toBe(true);
    expect(nodeKindExecutable({ nodeType: "x", executable: false })).toBe(false);
    expect(nodeKindExecutable({ nodeType: "ghost.pkg/unknown@1" })).toBeNull();
    expect(nodeKindExecutable(undefined)).toBeNull();
  });
});
