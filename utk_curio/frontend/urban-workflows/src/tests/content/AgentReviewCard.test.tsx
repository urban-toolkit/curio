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
