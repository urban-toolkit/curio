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
