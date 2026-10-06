import React from "react";
import { act, render, screen, waitFor, fireEvent } from "@testing-library/react";

import {
  NodeOutcomeStrip,
  firstLine,
  isSettled,
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
  "rendered nothing: 0 rows arrived at this node, so there was nothing to draw. " +
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

  it("counts a success or a failure as settled, and nothing else", () => {
    expect(isSettled({ code: "success", content: "" })).toBe(true);
    expect(isSettled({ code: "error", content: "x" })).toBe(true);
    expect(isSettled({ code: "exec", content: "" })).toBe(false);
    expect(isSettled(null)).toBe(false);
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
    expect(strip).toHaveTextContent("rendered nothing: 0 rows arrived at this node");
    expect(strip).toHaveTextContent("Error");
  });

  it("lets a press select its text rather than move the node or the canvas", () => {
    // react-flow starts a node drag on any press outside a `nodrag` element,
    // and the drag cancels the selection: `user-select: text` alone let a
    // drag across the error move the node instead. In a node that cannot be
    // dragged (a read-only dataflow) it pans the canvas, and zooms it on a
    // double-click, unless the element is `nopan`.
    (global as any).fetch = jest.fn().mockResolvedValue({ ok: false });
    render(
      <NodeOutcomeStrip nodeId="vega-1" projectId="p-1"
        output={{ code: "error", content: VEGA_ERROR }} />,
    );
    const strip = screen.getByTestId("node-outcome-vega-1");
    expect(strip.className).toContain("nodrag");
    expect(strip.className).toContain("nopan");
    expect(strip.className).toContain("nowheel");
  });

  it("sits in a notebook cell's flow, under the output, rather than over the node's bottom", () => {
    (global as any).fetch = jest.fn().mockResolvedValue({ ok: false });
    const { rerender } = render(
      <NodeOutcomeStrip nodeId="vega-1" projectId="p-1"
        output={{ code: "error", content: VEGA_ERROR }} inCell />,
    );
    expect(screen.getByTestId("node-outcome-vega-1").className).toContain("inCell");
    rerender(
      <NodeOutcomeStrip nodeId="vega-1" projectId="p-1"
        output={{ code: "error", content: VEGA_ERROR }} />,
    );
    expect(screen.getByTestId("node-outcome-vega-1").className).not.toContain("inCell");
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
    const clean = render(<NodeOutcomeStrip nodeId="n2" projectId="p-1" output={null} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(clean.container).toBeEmptyDOMElement();
    clean.unmount();

    const noProject = render(<NodeOutcomeStrip nodeId="n3" projectId={null} output={null} />);
    expect(noProject.container).toBeEmptyDOMElement();
  });

  it("clears when a rerun succeeds, though the journal still holds the failure", async () => {
    // The success is posted to the journal after the node settles, so a read
    // at that moment returns the failure the rerun just replaced.
    (global as any).fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        nodeId: "map-1",
        run: null,
        render: { status: "error", stderrTail: VEGA_ERROR },
      }),
    });
    const { container, rerender } = render(
      <NodeOutcomeStrip nodeId="map-1" projectId="p-1" output={{ code: "exec", content: "" }} />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("node-outcome-map-1")).toHaveTextContent("Last run"),
    );

    rerender(
      <NodeOutcomeStrip nodeId="map-1" projectId="p-1"
        output={{ code: "success", content: "Rendered 1 map" }} />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("drops a journal read that answers after the node settled", async () => {
    let answer: (value: unknown) => void = () => undefined;
    (global as any).fetch = jest.fn().mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    const { container, rerender } = render(
      <NodeOutcomeStrip nodeId="map-2" projectId="p-1" output={null} />,
    );
    rerender(
      <NodeOutcomeStrip nodeId="map-2" projectId="p-1" output={{ code: "success", content: "" }} />,
    );
    await act(async () => {
      answer({
        ok: true,
        json: async () => ({ run: { status: "error", stderrTail: "KeyError" }, render: null }),
      });
      await Promise.resolve();
    });
    expect(container).toBeEmptyDOMElement();
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it("does not ask the journal about a node this tab has settled", () => {
    (global as any).fetch = jest.fn();
    render(
      <NodeOutcomeStrip nodeId="n6" projectId="p-1" output={{ code: "error", content: VEGA_ERROR }} />,
    );
    expect(global.fetch).not.toHaveBeenCalled();
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

  // #603: a code node's error is its stdout and then a traceback, so the
  // collapsed strip read "stdout:" or "Traceback (most recent call last):",
  // and the line that says what went wrong was behind "more".
  const TRACEBACK =
    "stdout:\nloading parcels\n" +
    "Traceback (most recent call last):\n" +
    '  File "/app/utk_curio/sandbox/app/worker.py", line 595, in execute_code\n' +
    "    output = ns['userCode'](incomingInput)\n" +
    '  File "<string>", line 2, in userCode\n' +
    "RuntimeError: upstream boom\n";

  it("collapses a Python traceback to its exception line (#603)", () => {
    (global as any).fetch = jest.fn();
    render(
      <NodeOutcomeStrip nodeId="n9" projectId="p-1" output={{ code: "error", content: TRACEBACK }} />,
    );
    const strip = screen.getByTestId("node-outcome-n9");
    expect(strip).toHaveTextContent("RuntimeError: upstream boom");
    expect(strip).not.toHaveTextContent("Traceback (most recent call last):");
    expect(strip).not.toHaveTextContent("stdout:");
    // The whole traceback is still one click away.
    fireEvent.click(screen.getByRole("button", { name: "more" }));
    expect(strip).toHaveTextContent("Traceback (most recent call last):");
    expect(strip).toHaveTextContent("loading parcels");
  });

  it("collapses a traceback read from the journal the same way (#603)", async () => {
    (global as any).fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        nodeId: "n10",
        run: { status: "error", stderrTail: "Traceback (most recent call last):\n  File \"<string>\", line 1\nKeyError: 'tract_id'" },
        render: null,
      }),
    });
    render(<NodeOutcomeStrip nodeId="n10" projectId="p-1" output={null} />);
    await waitFor(() =>
      expect(screen.getByTestId("node-outcome-n10")).toHaveTextContent("KeyError: 'tract_id'"),
    );
    expect(screen.getByTestId("node-outcome-n10")).not.toHaveTextContent("Traceback");
  });

  it("offers the rest of a single line the node's width cuts", () => {
    (global as any).fetch = jest.fn();
    const width = jest.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(400);
    const client = jest.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(120);
    try {
      render(
        <NodeOutcomeStrip nodeId="n7" projectId="p-1"
          output={{ code: "error", content: "This browser does not expose WebGPU. Use Chrome or Edge." }} />,
      );
      fireEvent.click(screen.getByRole("button", { name: "more" }));
      expect(screen.getByRole("button", { name: "less" })).toHaveAttribute("aria-expanded", "true");
    } finally {
      width.mockRestore();
      client.mockRestore();
    }
  });

  it("offers no disclosure for a line that fits", () => {
    (global as any).fetch = jest.fn();
    render(
      <NodeOutcomeStrip nodeId="n8" projectId="p-1" output={{ code: "error", content: "short" }} />,
    );
    expect(screen.queryByRole("button", { name: "more" })).toBeNull();
  });
});
