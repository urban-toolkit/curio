import React from "react";
import { render, screen, act } from "@testing-library/react";
import { AgentRunStatusLine } from "../../components/agents/attach/AgentRunStatusLine";

/** Stub matchMedia (absent in jsdom) with a fixed reduced-motion answer. */
function stubMatchMedia(reduce: boolean) {
  window.matchMedia = jest.fn().mockImplementation((query: string) => ({
    matches: reduce && query.includes("prefers-reduced-motion"),
    media: query,
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
  })) as unknown as typeof window.matchMedia;
}

describe("AgentRunStatusLine (dev/80 baseline + dev/83 batch props)", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    stubMatchMedia(false);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("REGRESSION: without the dev/83 props the dev/80 output is unchanged — rotating label, chat sr text, no suffix", () => {
    const { container } = render(
      <AgentRunStatusLine display={{ kind: "running", startedAt: Date.now() }} />,
    );
    expect(container).toHaveTextContent("Agent is working");
    expect(container).toHaveTextContent("Cooking… · 0:00");
    act(() => jest.advanceTimersByTime(7_000));
    expect(container).toHaveTextContent("Baking… · 0:07"); // rotation intact
    expect(container.textContent).not.toContain(" · 0:07 · "); // no detail suffix
  });

  it("runningLabel fixes the label — it never rotates past the 5s slots", () => {
    const { container } = render(
      <AgentRunStatusLine
        display={{ kind: "running", startedAt: Date.now() }}
        runningLabel="Solving"
      />,
    );
    expect(container).toHaveTextContent("Solving… · 0:00");
    act(() => jest.advanceTimersByTime(7_000));
    expect(container).toHaveTextContent("Solving… · 0:07");
    expect(container.textContent).not.toContain("Baking");
  });

  it("runningDetail appends after the elapsed readout", () => {
    const { container } = render(
      <AgentRunStatusLine
        display={{ kind: "running", startedAt: Date.now() }}
        runningLabel="Solving"
        runningDetail="3/7 nodes"
      />,
    );
    expect(container).toHaveTextContent("Solving… · 0:00 · 3/7 nodes");
  });

  it("srLabel replaces the visually-hidden live-region text", () => {
    render(
      <AgentRunStatusLine
        display={{ kind: "running", startedAt: Date.now() }}
        runningLabel="Solving"
        srLabel="Solve batch running"
      />,
    );
    expect(screen.getByText("Solve batch running")).toBeInTheDocument();
    expect(screen.queryByText("Agent is working")).toBeNull();
  });

  it("the ticking span (elapsed + detail) stays aria-hidden; the sr text is announced", () => {
    const { container } = render(
      <AgentRunStatusLine
        display={{ kind: "running", startedAt: Date.now() }}
        runningLabel="Solving"
        runningDetail="1/2 nodes"
        srLabel="Solve batch running"
      />,
    );
    const ticking = Array.from(container.querySelectorAll('[aria-hidden="true"]')).find(
      (el) => el.textContent?.includes("1/2 nodes"),
    );
    expect(ticking).toBeTruthy();
    expect(screen.getByText("Solve batch running")).not.toHaveAttribute("aria-hidden");
  });

  it("done and error variants ignore the running-only props", () => {
    const done = render(
      <AgentRunStatusLine
        display={{ kind: "done", durationMs: 12_000, usage: { inputTokens: 900, outputTokens: 500 } }}
        runningLabel="Solving"
        runningDetail="3/7 nodes"
        srLabel="Solve batch running"
      />,
    );
    expect(done.container).toHaveTextContent("Finished in 12s · 1.4k tokens");
    expect(done.container.textContent).not.toContain("3/7 nodes");
    expect(done.container.textContent).not.toContain("Solve batch running");

    const errored = render(
      <AgentRunStatusLine
        display={{ kind: "error", durationMs: 8_000 }}
        runningLabel="Solving"
      />,
    );
    expect(errored.container).toHaveTextContent("Failed after 8s");
    expect(errored.container.textContent).not.toContain("Solving");
  });
});
