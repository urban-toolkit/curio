/**
 * Closing or reloading the tab asks first only while something would be lost
 * (`useLeavePageGuard`): on a dataflow bound to its doc, a change the server
 * does not have yet, read as the tab closes; on a canvas bound to no doc,
 * changes no one keeps. A bound dataflow the server has every change of
 * closes without a question, though nothing saved it.
 */
import { renderHook } from "@testing-library/react";

import { useLeavePageGuard } from "../../providers/flow/useSaveState";

/** A doc provider, as the guard reads it: whether the server has every change. */
function provider(kept: { now: boolean }): any {
  return { isKept: () => kept.now };
}

/** Whether closing the tab now asks first. */
function closingAsks(): boolean {
  const event = new Event("beforeunload", { cancelable: true }) as BeforeUnloadEvent;
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

describe("closing the tab of a dataflow bound to its doc", () => {
  test("goes without a question once the server has every change", () => {
    const kept = { now: true };
    renderHook(() => useLeavePageGuard(provider(kept), false));

    expect(closingAsks()).toBe(false);
  });

  test("asks while a change is on its way, as the tab closes", () => {
    const kept = { now: true };
    renderHook(() => useLeavePageGuard(provider(kept), false));

    kept.now = false;
    expect(closingAsks()).toBe(true);
    kept.now = true;
    expect(closingAsks()).toBe(false);
  });

  test("goes without a question whatever the canvas marked: the doc keeps it", () => {
    renderHook(() => useLeavePageGuard(provider({ now: true }), true));

    expect(closingAsks()).toBe(false);
  });
});

describe("closing the tab of a canvas bound to no doc", () => {
  test("asks while it holds changes no one keeps", () => {
    const { rerender, unmount } = renderHook(({ dirty }) => useLeavePageGuard(null, dirty), {
      initialProps: { dirty: true },
    });
    expect(closingAsks()).toBe(true);

    rerender({ dirty: false });
    expect(closingAsks()).toBe(false);
    unmount();
  });

  test("goes without a question when it holds none", () => {
    renderHook(() => useLeavePageGuard(null, false));

    expect(closingAsks()).toBe(false);
  });
});
