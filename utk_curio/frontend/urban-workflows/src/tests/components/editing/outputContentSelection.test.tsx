/**
 * The Data Summary node's Output / Error / Warning panel must let its text be
 * selected.
 *
 * react-flow starts a node drag on any press outside a `nodrag` element, and
 * the drag cancels the selection, so `userSelect: "text"` alone did not make
 * the traceback selectable: the panel needs `nodrag` around it, as the code
 * node's output box and Simple View's text pane have.
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import OutputContent from "../../../components/editing/OutputContent";

const TRACEBACK = 'Traceback (most recent call last):\n  File "<node>", line 2\nValueError: boom';

describe("OutputContent", () => {
  it("puts the error inside a nodrag, nowheel wrapper", () => {
    render(<OutputContent output={{ code: "error", content: TRACEBACK }} />);
    const traceback = screen.getAllByText(/ValueError: boom/)[0];
    const wrapper = traceback.closest(".nodrag");
    expect(wrapper).not.toBeNull();
    expect(wrapper?.className).toContain("nopan");
    expect(wrapper?.className).toContain("nowheel");
    expect(traceback).toHaveStyle({ userSelect: "text" });
  });

  it("puts the output inside it too", () => {
    render(<OutputContent output={{ code: "success", content: "Saved to file: summary.csv" }} />);
    const output = screen.getByText("Saved to file: summary.csv");
    expect(output.closest(".nodrag")).not.toBeNull();
  });
});
