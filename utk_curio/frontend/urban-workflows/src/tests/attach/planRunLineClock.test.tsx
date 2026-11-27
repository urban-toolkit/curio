/**
 * The plan line's running clock is the run's own: a chat opened again while a
 * batch or a build of the plan runs goes on counting from when the server says
 * it began (`solvingSince`, `simulatingSince`, in epoch seconds), never from
 * 0:00 as if it had just begun. A server clock ahead of the browser's never
 * counts below 0:00, nor from later than the line first saw the run.
 */
import React from "react";
import { render, screen } from "@testing-library/react";

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: jest.fn() }),
}));

import { AgentBuilderStrip } from "../../components/agents/attach/AgentBuilderStrip";
import type { AgentAttachment } from "../../services/agents";

/** The Dataflow Builder, its plan landed: one node left, one solved. */
const builder = (session: Record<string, unknown>, extra: Record<string, unknown> = {}): AgentAttachment =>
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
    builderSession: { appliedPlanId: "p1", nodeRuns: { n1: "pending", n2: "solved" }, ...session },
    ...extra,
  }) as unknown as AgentAttachment;

/** When a run began two minutes and five seconds ago, by the server's clock. */
const aWhileAgo = () => Date.now() / 1000 - 125;

/** The plan line. */
const line = () => screen.getByRole("group", { name: "Dataflow Builder" });

describe("the plan line's running clock, drawn again mid-run", () => {
  it("a batch counts from when it began, not from when the line was drawn", () => {
    render(
      <AgentBuilderStrip
        attachment={builder({ phase: "solving", solvingSince: aWhileAgo() })}
        onSolve={jest.fn()}
        onCancelSolve={jest.fn()}
      />,
    );
    expect(line()).toHaveTextContent(/\b2:0\d\b/);
  });

  it("a build counts from when it began, not from when the line was drawn", () => {
    render(
      <AgentBuilderStrip
        attachment={builder(
          { phase: "applied", simulateMode: "auto", simulatingSince: aWhileAgo() },
          { buildRunning: "auto" },
        )}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
        onCancelSimulate={jest.fn()}
      />,
    );
    expect(line()).toHaveTextContent(/\b2:0\d\b/);
  });

  it("a server clock ahead of the browser's counts from when the line first saw the run", () => {
    render(
      <AgentBuilderStrip
        attachment={builder(
          { phase: "applied", simulateMode: "auto", simulatingSince: Date.now() / 1000 + 600 },
          { buildRunning: "auto" },
        )}
        onSolve={jest.fn()}
        onSimulate={jest.fn()}
        onCancelSimulate={jest.fn()}
      />,
    );
    expect(line()).toHaveTextContent(/\b0:00\b/);
  });
});
