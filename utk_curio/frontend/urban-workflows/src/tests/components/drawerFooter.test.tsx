import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { DrawerFooter } from "../../components/packages/publishing/DrawerFooter";

/**
 * The only archive-import affordance in the app, and it had no test.
 *
 * Two behaviours here are load-bearing and easy to break silently: the hidden
 * input is cleared after every pick (without it, re-selecting the *same* file
 * fires no `change` event, so a retry after a failed import does nothing), and
 * `accept` is overridable to `null` so the Data Catalog can reuse the footer for
 * dataset files rather than `.curio.zip` archives.
 */

const zip = (name = "pack.curio.zip") =>
  new File(["PK"], name, { type: "application/zip" });

const fileInput = (container: HTMLElement) =>
  container.querySelector('input[type="file"]') as HTMLInputElement;

describe("DrawerFooter", () => {
  it("defaults to the Node Catalog's label and archive filter", () => {
    const { container } = render(<DrawerFooter busy={false} onSideload={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Import package" })).toBeTruthy();
    expect(fileInput(container).getAttribute("accept")).toBe(
      ".curio.zip,.zip,application/zip",
    );
  });

  it("keeps the input out of the layout", () => {
    const { container } = render(<DrawerFooter busy={false} onSideload={jest.fn()} />);
    expect(fileInput(container).hidden).toBe(true);
  });

  it("opens the picker when the button is clicked", () => {
    const { container } = render(<DrawerFooter busy={false} onSideload={jest.fn()} />);
    const click = jest.spyOn(fileInput(container), "click");
    fireEvent.click(screen.getByRole("button", { name: "Import package" }));
    expect(click).toHaveBeenCalledTimes(1);
  });

  it("hands the picked file to onSideload", () => {
    const onSideload = jest.fn();
    const { container } = render(<DrawerFooter busy={false} onSideload={onSideload} />);
    const file = zip();
    fireEvent.change(fileInput(container), { target: { files: [file] } });
    expect(onSideload).toHaveBeenCalledTimes(1);
    expect(onSideload.mock.calls[0][0].name).toBe("pack.curio.zip");
  });

  it("resets the input so the same file can be picked again", () => {
    // Browsers fire no `change` when the selection is unchanged. If the value
    // were left in place, retrying a failed import with the same archive would
    // silently do nothing.
    const onSideload = jest.fn();
    const { container } = render(<DrawerFooter busy={false} onSideload={onSideload} />);
    const input = fileInput(container);
    fireEvent.change(input, { target: { files: [zip()] } });
    expect(onSideload).toHaveBeenCalledTimes(1);
    expect(input.value).toBe("");
  });

  it("ignores a cancelled picker", () => {
    const onSideload = jest.fn();
    const { container } = render(<DrawerFooter busy={false} onSideload={onSideload} />);
    fireEvent.change(fileInput(container), { target: { files: [] } });
    expect(onSideload).not.toHaveBeenCalled();
  });

  it("disables the button while an import is in flight", () => {
    render(<DrawerFooter busy onSideload={jest.fn()} />);
    expect(
      screen.getByRole("button", { name: "Importing…" }).hasAttribute("disabled"),
    ).toBe(true);
  });

  it("says it is working, because the click can now sit in pip for minutes", () => {
    // Sideloading installs the archive's declared python deps now. It used to
    // return in well under a second; a disabled button still reading "Import
    // package" for two minutes reads as broken rather than busy.
    const { rerender } = render(<DrawerFooter busy={false} onSideload={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Import package" })).toBeTruthy();

    rerender(<DrawerFooter busy onSideload={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Importing…" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Import package" })).toBeNull();
  });

  it("lets a caller name its own in-flight wording", () => {
    render(
      <DrawerFooter busy onSideload={jest.fn()} label="Import dataset"
                    busyLabel="Importing dataset…" />,
    );
    expect(screen.getByRole("button", { name: "Importing dataset…" })).toBeTruthy();
  });

  it("accepts a custom label and an unrestricted filter", () => {
    // The Data Catalog reuses this footer for dataset files, which are not zips.
    const { container } = render(
      <DrawerFooter busy={false} onSideload={jest.fn()} accept={null} label="Import dataset" />,
    );
    expect(screen.getByRole("button", { name: "Import dataset" })).toBeTruthy();
    expect(fileInput(container).hasAttribute("accept")).toBe(false);
  });
});
