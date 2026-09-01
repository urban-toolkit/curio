/**
 * Node-header controls must be findable by their name.
 *
 * The regression: `HeaderIconButton` put `role="button"` and `tabIndex={0}` on a
 * FontAwesome SVG and handed it a `title` prop. `title` is in FontAwesome's
 * `DEFAULT_PROP_KEYS`, so the component consumed it rather than forwarding it,
 * and FontAwesome stamps `aria-hidden="true"` on any icon given no
 * `aria-label`. Every header control — minimize, pin, comments, delete — was
 * therefore keyboard-focusable *and* absent from the accessibility tree, with no
 * hover tooltip either. A DOM probe during the stress run returned
 * `title: null, aria-label: null, aria-labelledby: null` and no `<title>` child
 * for all four.
 *
 * A test asserting the accessible name is the cheapest thing that pins this: it
 * is exactly the query that could not be used before, and the reason the stress
 * harness had to address these controls by FontAwesome class instead.
 */
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { faXmark, faComments } from "@fortawesome/free-solid-svg-icons";

import { HeaderIconButton } from "../../components/HeaderIconButton";

describe("HeaderIconButton", () => {
  it("exposes its title as the accessible name", () => {
    render(
      <HeaderIconButton icon={faXmark} title="Delete node" onActivate={() => {}} />,
    );
    expect(
      screen.getByRole("button", { name: "Delete node" }),
    ).toBeInTheDocument();
  });

  it("keeps a hover tooltip", () => {
    render(
      <HeaderIconButton icon={faComments} title="Comments" onActivate={() => {}} />,
    );
    expect(screen.getByRole("button", { name: "Comments" })).toHaveAttribute(
      "title",
      "Comments",
    );
  });

  it("does not hide itself from assistive technology", () => {
    render(
      <HeaderIconButton icon={faXmark} title="Delete node" onActivate={() => {}} />,
    );
    const button = screen.getByRole("button", { name: "Delete node" });
    expect(button).not.toHaveAttribute("aria-hidden", "true");
    // The glyph itself is decorative; the name lives on the control.
    expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("still activates on pointerdown + pointerup", () => {
    // The drag-click hook activates on the pointer pair and swallows the native
    // click so press-and-drag on the header can still move the node.
    const onActivate = jest.fn();
    render(
      <HeaderIconButton icon={faXmark} title="Delete node" onActivate={onActivate} />,
    );
    const button = screen.getByRole("button", { name: "Delete node" });
    fireEvent.pointerDown(button, { clientX: 0, clientY: 0 });
    fireEvent.pointerUp(button, { clientX: 0, clientY: 0 });
    expect(onActivate).toHaveBeenCalledTimes(1);
  });

  it("does not activate when the pointer travelled — that is a node drag", () => {
    const onActivate = jest.fn();
    render(
      <HeaderIconButton icon={faXmark} title="Delete node" onActivate={onActivate} />,
    );
    const button = screen.getByRole("button", { name: "Delete node" });
    fireEvent.pointerDown(button, { clientX: 0, clientY: 0 });
    fireEvent.pointerUp(button, { clientX: 40, clientY: 25 });
    expect(onActivate).not.toHaveBeenCalled();
  });
});
