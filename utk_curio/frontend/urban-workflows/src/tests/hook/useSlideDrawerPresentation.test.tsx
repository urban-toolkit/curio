/**
 * The shared two-phase presentation (#295).
 *
 * These are the claims the three drawer providers used to each assert for
 * themselves - and did not all hold, which is why they are here now:
 *
 * - opening mounts CLOSED and presents on a later frame, or there is nothing to
 *   animate from (the dataset drawer's single rAF was the one that sometimes
 *   appeared without sliding);
 * - closing keeps the panel mounted until the slide reports it is done;
 * - `mounted` is the open signal, because during the exit the panel is still
 *   on screen;
 * - and the exit settles exactly once, however many things report it.
 */
import React from "react";
import { render, screen, act } from "@testing-library/react";
import "@testing-library/jest-dom";

import {
  DRAWER_MOTION_MS,
  EXIT_FALLBACK_GRACE_MS,
  useSlideDrawerPresentation,
} from "../../hook/useSlideDrawerPresentation";

function Harness() {
  const { mounted, presented, open, close, finishExit } =
    useSlideDrawerPresentation();
  return (
    <div>
      <span data-testid="state">{`${mounted ? "mounted" : "-"}/${presented ? "presented" : "-"}`}</span>
      <button onClick={open}>open</button>
      <button onClick={close}>close</button>
      <button onClick={finishExit}>settle</button>
    </div>
  );
}

const state = () => screen.getByTestId("state").textContent;
const press = (name: string) => act(() => { screen.getByText(name).click(); });

/** Run the two queued animation frames the present ramp waits on. */
async function paintTwoFrames() {
  await act(async () => {
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    await new Promise((r) => setTimeout(r, 0));
  });
}

describe("useSlideDrawerPresentation", () => {
  it("starts unmounted", () => {
    render(<Harness />);
    expect(state()).toBe("-/-");
  });

  it("mounts closed, then presents on a later frame", async () => {
    render(<Harness />);
    press("open");
    // The load-bearing half: if this were already "presented" the browser would
    // paint the panel at its resting transform and no slide would happen.
    expect(state()).toBe("mounted/-");
    await paintTwoFrames();
    expect(state()).toBe("mounted/presented");
  });

  it("keeps the panel mounted through the exit slide", async () => {
    render(<Harness />);
    press("open");
    await paintTwoFrames();
    press("close");
    // Un-presented, so it is sliding out - and still in the DOM, or there
    // would be nothing to slide.
    expect(state()).toBe("mounted/-");
  });

  it("unmounts when the slide reports it is done", async () => {
    render(<Harness />);
    press("open");
    await paintTwoFrames();
    press("close");
    press("settle");
    expect(state()).toBe("-/-");
  });

  it("settles only once, however many times it is told", async () => {
    render(<Harness />);
    press("open");
    await paintTwoFrames();
    press("close");
    press("settle");
    press("settle");
    expect(state()).toBe("-/-");
  });

  it("unmounts on the fallback timer when no transition ever ends", async () => {
    jest.useFakeTimers();
    try {
      render(<Harness />);
      press("open");
      act(() => { jest.advanceTimersByTime(50); });
      press("close");
      expect(state()).toBe("mounted/-");
      act(() => {
        jest.advanceTimersByTime(DRAWER_MOTION_MS + EXIT_FALLBACK_GRACE_MS + 1);
      });
      expect(state()).toBe("-/-");
    } finally {
      jest.useRealTimers();
    }
  });

  it("reopening during the exit cancels the pending unmount", async () => {
    jest.useFakeTimers();
    try {
      render(<Harness />);
      press("open");
      act(() => { jest.advanceTimersByTime(50); });
      press("close");
      press("open");
      // The fallback timer from the close must not fire against the reopen.
      act(() => { jest.advanceTimersByTime(1000); });
      expect(state()).toContain("mounted");
    } finally {
      jest.useRealTimers();
    }
  });

  it("restores focus to whatever had it before opening", async () => {
    render(
      <div>
        <button>outside</button>
        <Harness />
      </div>,
    );
    const outside = screen.getByText("outside");
    outside.focus();
    expect(document.activeElement).toBe(outside);

    press("open");
    await paintTwoFrames();
    (screen.getByText("close") as HTMLElement).focus();
    press("close");
    press("settle");
    await act(async () => { await Promise.resolve(); });
    expect(document.activeElement).toBe(outside);
  });

  it("survives jsdom, which has no matchMedia", () => {
    // Only one of the three providers guarded this, and it was the only one
    // with a render test - the other two threw on mount here.
    expect(typeof window.matchMedia).not.toBe("function");
    expect(() => render(<Harness />)).not.toThrow();
  });
});
