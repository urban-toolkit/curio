/**
 * The Note node: a title and simple markdown on a color, written by a person
 * or by the Researcher. It runs nothing and takes no edge. Its text never
 * renders HTML, and only an https link is a link, opened in a new tab with the
 * arrow every new-tab link carries.
 */
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { NodeBehaviorData, NodeBehaviorResult, UseNodeStateReturn } from "../../../registry/types";

const mockUpdateDataNode = jest.fn();
const mockMarkDirty = jest.fn();
let mockDashboardOn = false;
let mockSharedView = false;
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    updateDataNode: mockUpdateDataNode,
    markDirty: mockMarkDirty,
    dashboardOn: mockDashboardOn,
  }),
}));
jest.mock("../../../hook/useSharedView", () => ({
  useSharedView: () => mockSharedView,
}));

import { useNoteBehavior } from "../../../adapters/node/noteBehavior";
import { NOTE_COLORS } from "../../../generated/noteColors";

const NOTE = "curio.builtin/note@1";

function behaviorOf(data: Record<string, unknown>): NodeBehaviorResult {
  return useNoteBehavior(
    { nodeId: "n1", nodeType: NOTE, ...data } as unknown as NodeBehaviorData,
    {} as UseNodeStateReturn,
  );
}

function Harness({ data }: { data: Record<string, unknown> }) {
  return <>{behaviorOf(data).contentComponent}</>;
}

beforeEach(() => {
  mockUpdateDataNode.mockReset();
  mockMarkDirty.mockReset();
  mockDashboardOn = false;
  mockSharedView = false;
});

describe("the Note node", () => {
  test("runs nothing", () => {
    let behavior: NodeBehaviorResult | undefined;
    function Probe() {
      behavior = behaviorOf({ code: "x" });
      return null;
    }
    render(<Probe />);
    expect(behavior?.disablePlay).toBe(true);
  });

  test("shows its title and its text as simple markdown, on its color", () => {
    render(
      <Harness
        data={{
          title: "Cool roofs in Chicago",
          code: "## Findings\n**Roof surface:** about 30°F cooler\n\n- one\n- two\n\n*by day*",
          appearance: { backgroundColor: "green" },
        }}
      />,
    );
    const note = screen.getByRole("note", { name: "Cool roofs in Chicago" });
    expect(within(note).getByText("Cool roofs in Chicago")).toBeInTheDocument();
    expect(within(note).getByRole("heading", { name: "Findings" })).toBeInTheDocument();
    expect(within(note).getByText("Roof surface:").tagName).toBe("STRONG");
    expect(within(note).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["one", "two"]);
    expect(within(note).getByText("by day").tagName).toBe("EM");
    expect(note).toHaveStyle({ backgroundColor: NOTE_COLORS.green, color: "#1f2430" });
  });

  test("its text can be selected and scrolled without moving the canvas", () => {
    render(<Harness data={{ code: "Some text" }} />);
    expect(screen.getByRole("note")).toHaveClass("nodrag", "nopan", "nowheel");
  });

  test("an https link opens in a new tab and says so", () => {
    render(<Harness data={{ code: "Read [the study](https://example.org/roofs)." }} />);
    const link = screen.getByRole("link", { name: "the study ↗" });
    expect(link).toHaveAttribute("href", "https://example.org/roofs");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  test("an https link written any way markdown allows is a link", () => {
    render(
      <Harness
        data={{
          code: "[upper](HTTPS://EXAMPLE.ORG/a) and [by reference][r] and <https://example.org/auto>\n\n[r]: https://example.org/ref",
        }}
      />,
    );
    expect(screen.getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      "HTTPS://EXAMPLE.ORG/a",
      "https://example.org/ref",
      "https://example.org/auto",
    ]);
  });

  test("any other link is its text, never a link", () => {
    const { container } = render(
      <Harness
        data={{
          code: [
            "[plain](http://example.org/a)",
            "[script](javascript:alert(1))",
            "[loud script](JAVASCRIPT:alert(1))",
            "[spaced script](<  javascript:alert(1)>)",
            "[inline data](data:text/html;base64,PHNjcmlwdD4=)",
            "[relative](/catalog/data)",
            "[protocol relative](//example.org/x)",
            "[mail](mailto:someone@example.org)",
            "<http://example.org/auto> <javascript:alert(3)>",
            "[by reference][bad]",
            "",
            "[bad]: javascript:alert(2)",
          ].join("\n"),
        }}
      />,
    );
    expect(container.querySelectorAll("a")).toHaveLength(0);
    for (const text of [
      "plain", "script", "loud script", "spaced script", "inline data", "relative",
      "protocol relative", "mail", "http://example.org/auto", "by reference",
    ]) {
      expect(container.textContent).toContain(text);
    }
  });

  test("HTML in its text never renders", () => {
    const { container } = render(
      <Harness
        data={{
          code:
            'Hi <img src=x onerror="window.__notePwned=1"> <a href="https://example.org">raw</a> <b>bold</b>\n\n' +
            "<script>window.__notePwned2 = 1</script>\n\n<iframe src=\"https://example.org\"></iframe>",
        }}
      />,
    );
    expect(container.querySelector("img, script, iframe, a, b")).toBeNull();
    expect((window as unknown as { __notePwned?: number }).__notePwned).toBeUndefined();
    expect((window as unknown as { __notePwned2?: number }).__notePwned2).toBeUndefined();
  });

  test("an image is its alt text, and nothing is fetched", () => {
    const { container } = render(<Harness data={{ code: "![a cool roof](https://example.org/roof.png)" }} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("a cool roof");
  });
});

describe("writing a note", () => {
  test("a new note asks for its title, text and color, and saves them on the node", () => {
    render(<Harness data={{}} />);
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Threshold" } });
    fireEvent.change(screen.getByLabelText("Text"), { target: { value: "**Depth:** 0.3 m" } });
    fireEvent.click(screen.getByRole("radio", { name: "blue" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(mockUpdateDataNode).toHaveBeenCalledWith(
      "n1",
      expect.objectContaining({
        title: "Threshold",
        code: "**Depth:** 0.3 m",
        defaultCode: "**Depth:** 0.3 m",
        appearance: { backgroundColor: NOTE_COLORS.blue },
      }),
    );
    expect(mockMarkDirty).toHaveBeenCalled();
  });

  test("Edit opens the note's own title, text and color, and Cancel changes nothing", () => {
    render(<Harness data={{ title: "Question", code: "Which roofs?", appearance: { backgroundColor: NOTE_COLORS.pink } }} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit note" }));
    expect(screen.getByLabelText("Title")).toHaveValue("Question");
    expect(screen.getByLabelText("Text")).toHaveValue("Which roofs?");
    expect(screen.getByRole("radio", { name: "pink" })).toHaveAttribute("aria-checked", "true");
    fireEvent.change(screen.getByLabelText("Text"), { target: { value: "changed" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mockUpdateDataNode).not.toHaveBeenCalled();
    expect(screen.getByText("Which roofs?")).toBeInTheDocument();
  });

  test("a blank title is no title", () => {
    render(<Harness data={{ title: "Old", code: "x" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit note" }));
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(mockUpdateDataNode.mock.calls[0][1].title).toBeUndefined();
  });

  test("a color an agent set stays until another is picked", () => {
    render(<Harness data={{ code: "x", appearance: { backgroundColor: "#123456" } }} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit note" }));
    expect(screen.getAllByRole("radio").map((r) => r.getAttribute("aria-checked"))).not.toContain("true");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(mockUpdateDataNode.mock.calls[0][1].appearance).toEqual({ backgroundColor: "#123456" });
  });
});

describe("where a note cannot be written", () => {
  test.each([
    ["the dashboard", () => { mockDashboardOn = true; }],
    ["a read-only canvas", () => { mockSharedView = true; }],
  ])("on %s it shows its text and offers no Edit", (_where, set) => {
    set();
    render(<Harness data={{ title: "Question", code: "Which roofs?" }} />);
    expect(screen.getByText("Which roofs?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit note" })).toBeNull();
  });

  test("an empty note there says so, with no form", () => {
    mockDashboardOn = true;
    render(<Harness data={{}} />);
    expect(screen.getByText("An empty note.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Text")).toBeNull();
  });
});
