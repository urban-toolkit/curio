/**
 * The shared copy control (#206).
 *
 * Extracted from ``AgentCodeBlock``, which had the codebase's only
 * implementation of this. #206 needed it on the dataset surfaces, and a second
 * hand-rolled copy is how two of them end up behaving differently.
 */
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import "@testing-library/jest-dom";

import { CopyButton } from "../../components/CopyButton";

function mockClipboard(impl: () => Promise<void>) {
  Object.assign(navigator, { clipboard: { writeText: jest.fn(impl) } });
  return (navigator as unknown as { clipboard: { writeText: jest.Mock } }).clipboard.writeText;
}

const button = () => screen.getByRole("button");

/**
 * Click, and let the clipboard promise settle inside act.
 *
 * The status update happens after an await, so a bare fireEvent leaves React
 * warning about an update outside act — noise that would later hide a real one.
 */
async function clickAndSettle() {
  await act(async () => {
    fireEvent.click(button());
  });
}

beforeEach(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  jest.runOnlyPendingTimers();
  jest.useRealTimers();
  jest.restoreAllMocks();
});

describe("CopyButton", () => {
  test("writes the value and confirms", async () => {
    const writeText = mockClipboard(() => Promise.resolve());
    render(<CopyButton value='curio_dataset_path("a@1")' label="Copy dataset reference" />);

    expect(button()).toHaveAccessibleName("Copy dataset reference");
    await clickAndSettle();

    expect(writeText).toHaveBeenCalledWith('curio_dataset_path("a@1")');
    expect(button()).toHaveAccessibleName("Copied");
  });

  test("reverts to idle", async () => {
    mockClipboard(() => Promise.resolve());
    render(<CopyButton value="x" label="Copy dataset reference" />);
    await clickAndSettle();
    expect(button()).toHaveAccessibleName("Copied");

    act(() => {
      jest.advanceTimersByTime(2000);
    });
    expect(button()).toHaveAccessibleName("Copy dataset reference");
  });

  test("says so when the clipboard refuses", async () => {
    // navigator.clipboard rejects on an insecure origin and when the document
    // is not focused. A button that silently does nothing there is worse than
    // one that says it failed.
    jest.spyOn(console, "warn").mockImplementation(() => {});
    mockClipboard(() => Promise.reject(new Error("denied")));
    render(<CopyButton value="x" label="Copy dataset reference" />);

    await clickAndSettle();
    expect(button()).toHaveAccessibleName("Copy dataset reference failed");
  });

  test("does not trigger the row it sits in", async () => {
    // Palette rows select their dataset's nodes on click, and cards open their
    // details — copying must not also do that.
    mockClipboard(() => Promise.resolve());
    const onRowClick = jest.fn();
    render(
      <div onClick={onRowClick}>
        <CopyButton value="x" label="Copy dataset reference" />
      </div>,
    );

    await clickAndSettle();
    expect(onRowClick).not.toHaveBeenCalled();
  });

  test("shows its label as text only when asked", () => {
    mockClipboard(() => Promise.resolve());
    const { rerender } = render(<CopyButton value="x" label="Copy reference" />);
    // Icon variant: the name is on the button, not rendered as text beside it.
    expect(screen.queryByText("Copy reference")).toBeNull();

    rerender(<CopyButton value="x" label="Copy reference" variant="labelled" />);
    expect(screen.getByText("Copy reference")).toBeInTheDocument();
  });
});
