import React from "react";
import { render } from "@testing-library/react";

import { useAutoGrowTextarea } from "../../components/agents/attach/useAutoGrowTextarea";

/** Minimal consumer: the hook's only contract is the ref + height writes. */
function Composer({ value, maxHeightPx = 120 }: { value: string; maxHeightPx?: number }) {
  const { textareaRef } = useAutoGrowTextarea({ value, maxHeightPx });
  return <textarea ref={textareaRef} value={value} readOnly data-testid="ta" />;
}

/** jsdom has no layout — scrollHeight is a mocked, settable measurement. */
function mockScrollHeight(el: HTMLElement, initial: number) {
  let current = initial;
  Object.defineProperty(el, "scrollHeight", {
    configurable: true,
    get: () => current,
  });
  return (next: number) => {
    current = next;
  };
}

describe("useAutoGrowTextarea", () => {
  it("sets the height from scrollHeight when the value changes", () => {
    const { getByTestId, rerender } = render(<Composer value="one line" />);
    const ta = getByTestId("ta") as HTMLTextAreaElement;
    const setScrollHeight = mockScrollHeight(ta, 38);

    rerender(<Composer value={"one line\nand another"} />);
    setScrollHeight(56);
    rerender(<Composer value={"one line\nand another\nmore"} />);
    expect(ta.style.height).toBe("56px");
    expect(ta.style.overflowY).toBe("hidden");
  });

  it("clamps at maxHeightPx and enables internal scrolling", () => {
    const { getByTestId, rerender } = render(<Composer value="" maxHeightPx={120} />);
    const ta = getByTestId("ta") as HTMLTextAreaElement;
    mockScrollHeight(ta, 400);

    rerender(<Composer value={"x\n".repeat(50)} maxHeightPx={120} />);
    expect(ta.style.height).toBe("120px");
    expect(ta.style.overflowY).toBe("auto");
  });

  it("re-measures on programmatic value changes (prefill path)", () => {
    const { getByTestId, rerender } = render(<Composer value="" />);
    const ta = getByTestId("ta") as HTMLTextAreaElement;
    const setScrollHeight = mockScrollHeight(ta, 38);

    setScrollHeight(74);
    // The value arrives via props (a suggested-prompt prefill), no keystroke.
    rerender(<Composer value={"suggested\nmulti-line\nprompt"} />);
    expect(ta.style.height).toBe("74px");
  });

  it("collapses back when the value resets to empty (post-send)", () => {
    const { getByTestId, rerender } = render(<Composer value="" />);
    const ta = getByTestId("ta") as HTMLTextAreaElement;
    const setScrollHeight = mockScrollHeight(ta, 38);

    setScrollHeight(96);
    rerender(<Composer value={"a\nb\nc\nd"} />);
    expect(ta.style.height).toBe("96px");

    setScrollHeight(38);
    rerender(<Composer value="" />);
    expect(ta.style.height).toBe("38px");
    expect(ta.style.overflowY).toBe("hidden");
  });

  it("tolerates a zero measurement (jsdom default) without writing a bogus height", () => {
    const { getByTestId } = render(<Composer value="anything" />);
    const ta = getByTestId("ta") as HTMLTextAreaElement;
    // No scrollHeight mock: jsdom measures 0 → rows-based natural height.
    expect(ta.style.height).toBe("");
    expect(ta.style.overflowY).toBe("hidden");
  });
});
