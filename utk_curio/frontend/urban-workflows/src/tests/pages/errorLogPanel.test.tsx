/**
 * The error log panel.
 *
 * The XSS test at the bottom is the important one. `POST /api/monitor/errors/client`
 * is public and unauthenticated, so an attacker picks the `summary` and
 * `detail` strings verbatim, and this panel renders them on a page operators
 * open. React's escaping is the only thing standing between those two facts.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import ErrorLogPanel from "../../pages/monitor/ErrorLogPanel";
import type { MonitorError } from "../../api/monitorApi";

function entry(over: Partial<MonitorError> = {}): MonitorError {
  return {
    at: "2026-09-22T14:02:57Z",
    source: "node",
    summary: "KeyError: 'population'",
    detail: "Traceback (most recent call last):\n  File \"/tmp/node.py\"",
    context: {},
    count: 1,
    ...over,
  };
}

describe("ErrorLogPanel", () => {
  test("renders entries in the order given", () => {
    render(
      <ErrorLogPanel
        errors={[
          entry({ summary: "newest" }),
          entry({ summary: "oldest" }),
        ]}
        droppedClient={0}
        loading={false}
      />
    );
    const rows = screen.getAllByRole("button", { expanded: false });
    // The filter buttons come first; the entry rows follow in payload order.
    const text = rows.map((r) => r.textContent || "").join("|");
    expect(text.indexOf("newest")).toBeLessThan(text.indexOf("oldest"));
  });

  test("a healthy instance says so rather than showing an empty box", () => {
    render(<ErrorLogPanel errors={[]} droppedClient={0} loading={false} />);
    expect(screen.getByText("No errors since launch.")).toBeInTheDocument();
  });

  test("a repeat count is shown as a pill", () => {
    render(
      <ErrorLogPanel errors={[entry({ count: 12 })]} droppedClient={0} loading={false} />
    );
    expect(screen.getByText("x12")).toBeInTheDocument();
  });

  test("the detail is hidden until the row is expanded", () => {
    render(<ErrorLogPanel errors={[entry()]} droppedClient={0} loading={false} />);
    expect(screen.queryByText(/most recent call last/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("KeyError: 'population'"));
    expect(screen.getByText(/most recent call last/)).toBeInTheDocument();
  });

  test("a source filter narrows the list", () => {
    render(
      <ErrorLogPanel
        errors={[
          entry({ source: "node", summary: "from a node" }),
          entry({ source: "client", summary: "from a browser" }),
        ]}
        droppedClient={0}
        loading={false}
      />
    );
    expect(screen.getByText("from a browser")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^client \(1\)$/ }));
    expect(screen.queryByText("from a browser")).not.toBeInTheDocument();
    expect(screen.getByText("from a node")).toBeInTheDocument();
  });

  test("dropped browser reports are surfaced", () => {
    render(<ErrorLogPanel errors={[]} droppedClient={14} loading={false} />);
    expect(screen.getByText("14 browser reports dropped")).toBeInTheDocument();
  });

  describe("untrusted content", () => {
    test("a client-supplied payload is rendered as text, never as markup", () => {
      const hostile =
        '<img src=x onerror="document.title=\'pwned\'"><script>alert(1)</script>';
      const { container } = render(
        <ErrorLogPanel
          errors={[entry({ source: "client", summary: hostile, detail: hostile })]}
          droppedClient={0}
          loading={false}
        />
      );

      // Nothing from the payload became an element.
      expect(container.querySelector("img")).toBeNull();
      expect(container.querySelector("script")).toBeNull();
      expect(document.title).not.toBe("pwned");
      // And it is still visible to the operator, as text.
      expect(screen.getByText(hostile)).toBeInTheDocument();
    });

    test("the same holds once the row is expanded", () => {
      const hostile = '<img src=x onerror="document.title=\'pwned-detail\'">';
      const { container } = render(
        <ErrorLogPanel
          errors={[entry({ source: "client", summary: "boom", detail: hostile })]}
          droppedClient={0}
          loading={false}
        />
      );
      fireEvent.click(screen.getByText("boom"));

      expect(container.querySelector("img")).toBeNull();
      expect(document.title).not.toBe("pwned-detail");
      expect(container.querySelector("pre")?.textContent).toBe(hostile);
    });
  });
});
