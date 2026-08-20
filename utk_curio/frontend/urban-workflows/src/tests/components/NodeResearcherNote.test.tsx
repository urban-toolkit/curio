/**
 * dev/89 commit 9 — RTL coverage of the Node Researcher reference behavior
 * (the byte-identical mirror of the backend's packaged TSX fixture; parity is
 * asserted by the backend DOD test). Covers the DOD profile: safe
 * markdown-lite (raw HTML inert), empty state, bounded body, per-instance
 * color with AA ink, no Run control, and the in-note recolor row.
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import {
  BEHAVIOR_KEY,
  NodeResearcherNote,
  useNodeResearcherNoteBehavior,
} from "../fixtures/NodeResearcherNote";
import { NAMED_COLORS, contrastRatio, MIN_CONTRAST } from "../../utils/nodeAppearance";

describe("NodeResearcherNote (dev/89 DOD)", () => {
  it("renders markdown-lite: headings, bullets, bold, https links", () => {
    render(
      <NodeResearcherNote
        data={{
          code: "# Findings\n- **Headways** doubled\n- [source](https://data.test/gtfs)",
          title: "Transit findings",
        }}
      />,
    );
    expect(screen.getByRole("note", { name: "Transit findings" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Findings");
    expect(screen.getByText("Headways").tagName).toBe("STRONG");
    const link = screen.getByRole("link", { name: "source" });
    expect(link).toHaveAttribute("href", "https://data.test/gtfs");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("raw HTML and script URLs render as inert text, never markup", () => {
    render(
      <NodeResearcherNote
        data={{ code: '<script>alert(1)</script>\n[x](javascript:alert(1))' }}
      />,
    );
    // The literal tag text is visible; no script element exists.
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    // The javascript: pseudo-link never becomes an anchor (https-only).
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("empty content shows the quiet empty-note state", () => {
    render(<NodeResearcherNote data={{ code: "  " }} />);
    expect(screen.getByText(/nothing here yet/i)).toBeInTheDocument();
  });

  it("long content stays inside a bounded scrolling body", () => {
    render(<NodeResearcherNote data={{ code: "line\n".repeat(400) }} />);
    const body = screen.getByTestId("note-body");
    expect(body).toHaveStyle({ overflowY: "auto" });
    const note = screen.getByRole("note");
    expect(note).toHaveStyle({ maxHeight: "340px" });
  });

  it("per-instance color drives the surface with AA ink; legacy junk falls back", () => {
    const { rerender } = render(
      <NodeResearcherNote data={{ code: "x", appearance: { backgroundColor: NAMED_COLORS.pink } }} />,
    );
    const note = () => screen.getByRole("note");
    expect(note()).toHaveStyle({ background: NAMED_COLORS.pink });
    const ink = note().style.color;
    expect(contrastRatio(NAMED_COLORS.pink, "#1f2430")).toBeGreaterThanOrEqual(MIN_CONTRAST);
    expect(ink).toBeTruthy();
    rerender(<NodeResearcherNote data={{ code: "x", appearance: { backgroundColor: "#777777" } }} />);
    expect(note()).toHaveStyle({ background: NAMED_COLORS.yellow }); // fallback
  });

  it("has no Run/play control and no editor", () => {
    render(<NodeResearcherNote data={{ code: "content" }} />);
    expect(screen.queryByRole("button", { name: /run|play|execute/i })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull(); // no recolor sink → no hex input
  });

  it("the recolor row appears only with a host sink and emits normalized values", () => {
    const onChange = jest.fn();
    render(<NodeResearcherNote data={{ code: "x", onAppearanceChange: onChange }} />);
    fireEvent.click(screen.getByRole("button", { name: /set color lavender/i }));
    expect(onChange).toHaveBeenCalledWith(NAMED_COLORS.lavender);
    const hex = screen.getByLabelText(/custom hex/i);
    fireEvent.change(hex, { target: { value: "#777777" } });
    fireEvent.blur(hex);
    expect(onChange).toHaveBeenCalledTimes(1); // inaccessible hex refused
    expect(screen.getByRole("status").textContent).toMatch(/accessible/i);
    fireEvent.change(hex, { target: { value: "#336699" } });
    fireEvent.keyDown(hex, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith("#336699");
  });

  it("the behavior hook returns the note as contentComponent only", () => {
    const result = useNodeResearcherNoteBehavior({ code: "x" });
    expect(Object.keys(result)).toEqual(["contentComponent"]);
    expect(BEHAVIOR_KEY).toBe("node-researcher-note");
  });
});
