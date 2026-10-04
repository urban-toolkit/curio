/**
 * The Canvas | Notebook switch in the canvas bar (menus/top/CanvasViewSwitch):
 * two options in one group, the one showing checked, each named in full for
 * assistive technology and on hover while its word can give way to its icon.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import { CanvasViewSwitch } from "../../components/menus/top/CanvasViewSwitch";

describe("the canvas view switch", () => {
  test("offers the canvas and the notebook view, the one showing checked", () => {
    render(<CanvasViewSwitch value="canvas" onChange={() => {}} />);
    const group = screen.getByRole("radiogroup", { name: "Dataflow view" });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Canvas view" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Notebook view" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("radio", { name: "Notebook view" })).toHaveAttribute("title", "Notebook view");
    expect(screen.getByText("Notebook")).toHaveClass("label");
  });

  test("asks for the other view when it is picked", () => {
    const onChange = jest.fn();
    render(<CanvasViewSwitch value="canvas" onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: "Notebook view" }));
    expect(onChange).toHaveBeenCalledWith("notebook");
  });

  test("asks nothing when the view showing is picked again", () => {
    const onChange = jest.fn();
    render(<CanvasViewSwitch value="notebook" onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: "Notebook view" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  test("gives way sooner next to the collaboration button", () => {
    render(<CanvasViewSwitch value="canvas" onChange={() => {}} crowded />);
    expect(screen.getByRole("radiogroup")).toHaveClass("switchCrowded");
  });
});
