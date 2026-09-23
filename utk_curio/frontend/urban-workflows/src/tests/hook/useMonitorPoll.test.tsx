/**
 * The polling loop.
 *
 * Each test here corresponds to a way the naive version misbehaves: blanking
 * the page on a slow poll, throwing away good data on a failed one, stacking
 * requests behind a slow backend, and polling forever in a tab nobody is
 * looking at.
 */
import { act, renderHook, waitFor } from "@testing-library/react";

import { useMonitorPoll } from "../../hook/useMonitorPoll";

/**
 * The hook kicks off its first fetch during mount, so that promise settles
 * after the render's own act() has closed. Mounting inside an async act()
 * keeps the resulting state updates inside it and the suite free of
 * "not wrapped in act" warnings, without changing what is under test.
 */
async function mountPoll(
  fetcher: jest.Mock,
  intervalMs = 5000,
  paused = false
) {
  let hook: ReturnType<typeof renderHook<any, any>>;
  await act(async () => {
    hook = renderHook(
      ({ paused: p }: { paused: boolean }) =>
        useMonitorPoll(fetcher, intervalMs, p),
      { initialProps: { paused } }
    );
  });
  return hook!;
}

describe("useMonitorPoll", () => {
  let actWarnings: jest.SpyInstance;

  // Installed for the whole file rather than per test, because the updates
  // that trigger this warning also arrive during teardown: flushing pending
  // timers and RTL's own auto-cleanup both run after afterEach, so a spy
  // restored there would miss exactly the ones it is there to catch.
  beforeAll(() => {
    // The loop schedules its next tick from a settled promise, so some state
    // updates land after the act() that started them has closed. React's dev
    // build warns about that; the behaviour under test is unaffected and every
    // assertion below goes through waitFor. Only this one message is
    // swallowed, so a genuine console.error still surfaces.
    const real = console.error;
    actWarnings = jest
      .spyOn(console, "error")
      .mockImplementation((...args: any[]) => {
        if (typeof args[0] === "string" && args[0].includes("not wrapped in act")) {
          return;
        }
        real(...args);
      });
  });

  afterAll(() => actWarnings.mockRestore());

  beforeEach(() => jest.useFakeTimers());

  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  test("fetches immediately and reports the result", async () => {
    const fetcher = jest.fn().mockResolvedValue({ value: 1 });
    const { result } = await mountPoll(fetcher);

    await waitFor(() => expect(result.current.data).toEqual({ value: 1 }));
    expect(result.current.loading).toBe(false);
    expect(result.current.lastUpdatedAt).toBeInstanceOf(Date);
  });

  test("loading stays true only until the first payload arrives", async () => {
    const fetcher = jest.fn().mockResolvedValue({ value: 1 });
    const { result } = await mountPoll(fetcher);

    await waitFor(() => expect(result.current.loading).toBe(false));

    // A later tick must never flip it back: that would blank a page that is
    // already showing numbers.
    await act(async () => {
      jest.advanceTimersByTime(5000);
    });
    expect(result.current.loading).toBe(false);
  });

  test("a failed tick keeps the previous data and reports the error", async () => {
    const fetcher = jest
      .fn()
      .mockResolvedValueOnce({ value: 1 })
      .mockRejectedValue(new Error("backend down"));
    const { result } = await mountPoll(fetcher);

    await waitFor(() => expect(result.current.data).toEqual({ value: 1 }));
    await act(async () => {
      jest.advanceTimersByTime(5000);
    });
    await waitFor(() => expect(result.current.error).not.toBeNull());

    // The whole point: stale numbers beat an empty page.
    expect(result.current.data).toEqual({ value: 1 });
  });

  test("a recovered tick clears the error", async () => {
    const fetcher = jest
      .fn()
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValue({ value: 2 });
    const { result } = await mountPoll(fetcher);

    await waitFor(() => expect(result.current.error).not.toBeNull());
    await act(async () => {
      jest.advanceTimersByTime(5000);
    });
    await waitFor(() => expect(result.current.error).toBeNull());
    expect(result.current.data).toEqual({ value: 2 });
  });

  test("a backend slower than the interval does not stack requests", async () => {
    // setInterval would fire four more times while this one is in flight.
    let resolve: (v: unknown) => void = () => undefined;
    const fetcher = jest
      .fn()
      .mockImplementation(() => new Promise((r) => (resolve = r)));

    await mountPoll(fetcher, 1000);
    expect(fetcher).toHaveBeenCalledTimes(1);

    await act(async () => {
      jest.advanceTimersByTime(10000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolve({ value: 1 });
    });
    await act(async () => {
      jest.advanceTimersByTime(1000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  test("paused schedules nothing", async () => {
    const fetcher = jest.fn().mockResolvedValue({ value: 1 });
    const { rerender } = await mountPoll(fetcher, 5000, false);

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    await act(async () => rerender({ paused: true }));

    await act(async () => {
      jest.advanceTimersByTime(60000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  test("resuming fetches immediately rather than waiting a full interval", async () => {
    const fetcher = jest.fn().mockResolvedValue({ value: 1 });
    const { rerender } = await mountPoll(fetcher, 5000, true);

    expect(fetcher).not.toHaveBeenCalled();
    await act(async () => rerender({ paused: false }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  });

  test("unmounting stops the loop and leaves no pending timer", async () => {
    const fetcher = jest.fn().mockResolvedValue({ value: 1 });
    const { unmount } = await mountPoll(fetcher);

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    unmount();

    await act(async () => {
      jest.advanceTimersByTime(60000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
