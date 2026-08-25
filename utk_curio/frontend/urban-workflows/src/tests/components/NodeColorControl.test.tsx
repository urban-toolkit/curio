/**
 * dev/89 commit 8 — the accessible per-node color control: labeled
 * keyboard-operable swatches, validated custom hex, announced errors, and
 * normalized-only onChange values.
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { NodeColorControl } from "../../components/NodeColorControl";
import { NAMED_COLORS } from "../../utils/nodeAppearance";

describe("NodeColorControl", () => {
  it("renders the six labeled palette swatches as a radio group", () => {
    render(<NodeColorControl value="#fef3c0" onChange={jest.fn()} />);
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(6);
    expect(screen.getByRole("radio", { name: /pink/i })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /yellow/i })).toBeChecked();
  });

  it("selecting a swatch emits the normalized palette hex", () => {
    const onChange = jest.fn();
    render(<NodeColorControl value="#fef3c0" onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: /lavender/i }));
    expect(onChange).toHaveBeenCalledWith(NAMED_COLORS.lavender);
  });

  it("a valid custom hex commits normalized on Enter", () => {
    const onChange = jest.fn();
    render(<NodeColorControl value="#fef3c0" onChange={onChange} />);
    const hex = screen.getByLabelText(/custom hex/i);
    fireEvent.change(hex, { target: { value: "#336699" } });
    fireEvent.keyDown(hex, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("#336699");
    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  it("invalid hex announces the reason and never propagates", () => {
    const onChange = jest.fn();
    render(<NodeColorControl value="#fef3c0" onChange={onChange} />);
    const hex = screen.getByLabelText(/custom hex/i);
    fireEvent.change(hex, { target: { value: "#abc" } });
    fireEvent.blur(hex);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toMatch(/six-digit/i);
    expect(hex).toHaveAttribute("aria-invalid", "true");
  });

  it("an inaccessible hex is refused with the contrast explanation", () => {
    const onChange = jest.fn();
    render(<NodeColorControl value="#fef3c0" onChange={onChange} />);
    const hex = screen.getByLabelText(/custom hex/i);
    fireEvent.change(hex, { target: { value: "#777777" } });
    fireEvent.blur(hex);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toMatch(/readable text/i);
  });

  it("a legacy-invalid stored value displays as the default yellow selection", () => {
    render(<NodeColorControl value="not-a-color" onChange={jest.fn()} />);
    expect(screen.getByRole("radio", { name: /yellow/i })).toBeChecked();
  });
});
