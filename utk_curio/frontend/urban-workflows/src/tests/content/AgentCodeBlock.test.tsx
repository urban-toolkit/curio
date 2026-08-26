import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";

import {
  AgentCodeBlock,
  extractNodeText,
} from "../../components/agents/content/AgentCodeBlock";

// jsdom ships no navigator.clipboard — this is the app's first clipboard
// integration (memo dev/78), so the mock lives here, not in setupTests.
const writeText = jest.fn<Promise<void>, [string]>();
beforeEach(() => {
  writeText.mockReset().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
});

describe("extractNodeText", () => {
  it("returns strings and numbers as text", () => {
    expect(extractNodeText("abc")).toBe("abc");
    expect(extractNodeText(42)).toBe("42");
  });

  it("returns empty for null/undefined/booleans", () => {
    expect(extractNodeText(null)).toBe("");
    expect(extractNodeText(undefined)).toBe("");
    expect(extractNodeText(true)).toBe("");
  });

  it("joins arrays and recurses into elements", () => {
    expect(extractNodeText(["a", <code key="k">{["b", "c"]}</code>, "d"])).toBe(
      "abcd",
    );
  });

  it("recurses through nested elements", () => {
    expect(
      extractNodeText(
        <code>
          <span>line1{"\n"}</span>
          <span>line2</span>
        </code>,
      ),
    ).toBe("line1\nline2");
  });
});

describe("AgentCodeBlock (memo dev/78)", () => {
  const fence = (text: string) => (
    <AgentCodeBlock>
      <code className="language-python">{text}</code>
    </AgentCodeBlock>
  );

  it("copies exactly the code content — no fences, no language tag, one trailing newline stripped", async () => {
    render(fence("print('hi')\n"));
    fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
    await act(async () => {});
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith("print('hi')");
  });

  it("preserves interior newlines and indentation; strips only the fence terminator", async () => {
    render(fence("a\n\n  b\n"));
    fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
    await act(async () => {});
    expect(writeText).toHaveBeenCalledWith("a\n\n  b");
  });

  it("shows Copied feedback, then reverts to idle after the window", async () => {
    jest.useFakeTimers();
    try {
      render(fence("x = 1\n"));
      fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
      await act(async () => {});
      expect(
        screen.getByRole("button", { name: "Copied" }),
      ).toBeInTheDocument();
      act(() => {
        jest.advanceTimersByTime(1800);
      });
      expect(
        screen.getByRole("button", { name: "Copy code" }),
      ).toBeInTheDocument();
    } finally {
      jest.useRealTimers();
    }
  });

  it("shows a loud failure state when the clipboard write rejects, then reverts", async () => {
    jest.useFakeTimers();
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    try {
      writeText.mockRejectedValue(new Error("denied"));
      render(fence("x = 1\n"));
      fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
      await act(async () => {});
      expect(
        screen.getByRole("button", { name: "Copy failed" }),
      ).toBeInTheDocument();
      expect(warn).toHaveBeenCalled();
      act(() => {
        jest.advanceTimersByTime(1800);
      });
      expect(
        screen.getByRole("button", { name: "Copy code" }),
      ).toBeInTheDocument();
    } finally {
      warn.mockRestore();
      jest.useRealTimers();
    }
  });

  it("keeps blocks independent — copying one leaves the other idle", async () => {
    render(
      <>
        {fence("first\n")}
        {fence("second\n")}
      </>,
    );
    const buttons = screen.getAllByRole("button", { name: "Copy code" });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[0]);
    await act(async () => {});
    expect(writeText).toHaveBeenCalledWith("first");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Copy code" }),
    ).toHaveLength(1);
  });

  it("renders no button for an empty or whitespace-only fence", () => {
    const { container } = render(fence("\n"));
    expect(container.querySelector("pre")).toBeInTheDocument();
    expect(container.querySelector("button")).toBeNull();
  });

  it("unmounting during the feedback window neither warns nor sets state late", async () => {
    jest.useFakeTimers();
    const error = jest.spyOn(console, "error").mockImplementation(() => {});
    try {
      const { unmount } = render(fence("x = 1\n"));
      fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
      await act(async () => {});
      unmount();
      act(() => {
        jest.advanceTimersByTime(1800);
      });
      expect(error).not.toHaveBeenCalled();
    } finally {
      error.mockRestore();
      jest.useRealTimers();
    }
  });

  it("rapid repeated clicks restart the feedback window instead of stacking timers", async () => {
    jest.useFakeTimers();
    try {
      render(fence("x = 1\n"));
      fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
      await act(async () => {});
      act(() => {
        jest.advanceTimersByTime(1000);
      });
      fireEvent.click(screen.getByRole("button", { name: "Copied" }));
      await act(async () => {});
      // The first timer (due at 1800ms from the first click) must not fire
      // 800ms after the second click — the window restarted.
      act(() => {
        jest.advanceTimersByTime(1000);
      });
      expect(
        screen.getByRole("button", { name: "Copied" }),
      ).toBeInTheDocument();
      act(() => {
        jest.advanceTimersByTime(800);
      });
      expect(
        screen.getByRole("button", { name: "Copy code" }),
      ).toBeInTheDocument();
      expect(writeText).toHaveBeenCalledTimes(2);
    } finally {
      jest.useRealTimers();
    }
  });
});
