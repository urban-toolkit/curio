import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import {
  NodeOutcomeStrip,
  firstLine,
  liveOutcome,
  recordOutcome,
} from "../../components/nodes/NodeOutcomeStrip";

/**
 * dev/138, the owner's report: *"the error message seems to be through the
 * toast and not carried into node's spec object."* A toast fades; a grammar
 * node has no output area; so a failed render was a red word with no text, and
 * nothing at all after a reload.
 */

const VEGA_ERROR =
  "rendered nothing — 0 rows arrived at this node, so there was nothing to draw. " +
  "The upstream node that feeds it is what must change; this document is not at fault.";

describe("the strip's readings", () => {
  it("takes a live error as the node's current reason", () => {
    expect(liveOutcome({ code: "error", content: VEGA_ERROR })).toEqual({
      level: "error", text: VEGA_ERROR, live: true,
    });
  });

  it("says nothing for a success, a run in flight or an absent output", () => {
    expect(liveOutcome({ code: "success", content: "" })).toBeNull();
    expect(liveOutcome({ code: "exec", content: "" })).toBeNull();
    expect(liveOutcome(undefined)).toBeNull();
  });

  it("reads a failed journal record and ignores a passing one", () => {
    expect(recordOutcome({ status: "error", stderrTail: "KeyError: 'tract_id'" })?.text)
      .toBe("KeyError: 'tract_id'");
    expect(recordOutcome({ status: "ok", stdoutTail: "ran" })).toBeNull();
    expect(recordOutcome(null)).toBeNull();
  });

  it("collapses to the first line and keeps the rest for the disclosure", () => {
    expect(firstLine("first\nsecond\nthird")).toBe("first");
    expect(firstLine("x".repeat(400)).length).toBeLessThanOrEqual(140);
  });
});

describe("NodeOutcomeStrip", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    (global as any).fetch = originalFetch;
  });

  it("shows a live render failure immediately, in the node", () => {
    (global as any).fetch = jest.fn().mockResolvedValue({ ok: false });
    render(
      <NodeOutcomeStrip nodeId="vega-1" projectId="p-1"
        output={{ code: "error", content: VEGA_ERROR }} />,
    );
    const strip = screen.getByTestId("node-outcome-vega-1");
    expect(strip).toHaveTextContent("rendered nothing — 0 rows arrived at this node");
    expect(strip).toHaveTextContent("Error");
  });

  it("hydrates from the journal when this tab has no live outcome (a reload)", async () => {
    (global as any).fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        nodeId: "vega-1",
        run: null,
        render: { status: "error", stderrTail: VEGA_ERROR, origin: "browser" },
      }),
    });
    render(<NodeOutcomeStrip nodeId="vega-1" projectId="p-1" output={null} />);
    await waitFor(() =>
      expect(screen.getByTestId("node-outcome-vega-1")).toHaveTextContent(
        "rendered nothing",
      ),
    );
    // Labeled as the LAST run, not as something happening now.
    expect(screen.getByTestId("node-outcome-vega-1")).toHaveTextContent("Last run");
  });

  it("leads with the RUN's failure when a node has both records", async () => {
    (global as any).fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        nodeId: "n1",
        run: { status: "error", stderrTail: "KeyError: 'tract_id'" },
        render: { status: "error", stderrTail: VEGA_ERROR },
      }),
    });
    render(<NodeOutcomeStrip nodeId="n1" projectId="p-1" output={null} />);
    await waitFor(() =>
      expect(screen.getByTestId("node-outcome-n1")).toHaveTextContent("KeyError"),
    );
  });

  it("renders nothing for a clean node, and nothing without a project", async () => {
    (global as any).fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ nodeId: "n2", run: { status: "ok" }, render: null }),
    });
    const clean = render(
      <NodeOutcomeStrip nodeId="n2" projectId="p-1" output={{ code: "success", content: "" }} />,
    );
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(clean.container).toBeEmptyDOMElement();
    clean.unmount();

    const noProject = render(<NodeOutcomeStrip nodeId="n3" projectId={null} output={null} />);
    expect(noProject.container).toBeEmptyDOMElement();
  });

  it("survives an unreachable backend without claiming anything", async () => {
    (global as any).fetch = jest.fn().mockRejectedValue(new Error("offline"));
    const { container } = render(
      <NodeOutcomeStrip nodeId="n4" projectId="p-1" output={null} />,
    );
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("expands a multi-line reason on demand", () => {
    (global as any).fetch = jest.fn().mockResolvedValue({ ok: false });
    render(
      <NodeOutcomeStrip nodeId="n5" projectId="p-1"
        output={{ code: "error", content: "Traceback:\n  line two\n  line three" }} />,
    );
    expect(screen.getByTestId("node-outcome-n5")).not.toHaveTextContent("line three");
    fireEvent.click(screen.getByRole("button", { name: "more" }));
    expect(screen.getByTestId("node-outcome-n5")).toHaveTextContent("line three");
  });
});
