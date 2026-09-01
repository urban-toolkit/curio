import React from "react";
import { render, screen, act } from "@testing-library/react";
import { useRunTicker } from "../../components/agents/attach/useRunTicker";

const Probe: React.FC<{ startedAt: number | null }> = ({ startedAt }) => {
  const { elapsedLabel, processingLabel } = useRunTicker(startedAt);
  return (
    <div data-testid="ticker">
      {processingLabel}|{elapsedLabel}
    </div>
  );
};

/** Stub matchMedia (absent in jsdom) with a fixed reduced-motion answer. */
function stubMatchMedia(reduce: boolean) {
  window.matchMedia = jest.fn().mockImplementation((query: string) => ({
    matches: reduce && query.includes("prefers-reduced-motion"),
    media: query,
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
  })) as unknown as typeof window.matchMedia;
}

describe("useRunTicker (memo dev/80)", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    stubMatchMedia(false);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("starts at the first label with 0:00", () => {
    render(<Probe startedAt={Date.now()} />);
    expect(screen.getByTestId("ticker")).toHaveTextContent("Cooking|0:00");
  });

  it("ticks the elapsed readout every second and rotates the label every 5s", () => {
    render(<Probe startedAt={Date.now()} />);
    act(() => jest.advanceTimersByTime(7_000));
    expect(screen.getByTestId("ticker")).toHaveTextContent("Baking|0:07");
    act(() => jest.advanceTimersByTime(24_000)); // 31s: 6th slot wraps to 0
    expect(screen.getByTestId("ticker")).toHaveTextContent("Cooking|0:31");
  });

  it("resumes mid-run: a startedAt in the past yields the correct elapsed and label", () => {
    render(<Probe startedAt={Date.now() - 12_000} />);
    expect(screen.getByTestId("ticker")).toHaveTextContent("Simmering|0:12");
  });

  it("pins the label under prefers-reduced-motion (elapsed still ticks)", () => {
    stubMatchMedia(true);
    render(<Probe startedAt={Date.now()} />);
    act(() => jest.advanceTimersByTime(7_000));
    expect(screen.getByTestId("ticker")).toHaveTextContent("Cooking|0:07");
  });

  it("a null startedAt runs no interval and reports an empty elapsed", () => {
    render(<Probe startedAt={null} />);
    expect(jest.getTimerCount()).toBe(0);
    expect(screen.getByTestId("ticker")).toHaveTextContent("Cooking|");
  });

  it("clears its interval on unmount", () => {
    const { unmount } = render(<Probe startedAt={Date.now()} />);
    expect(jest.getTimerCount()).toBeGreaterThan(0);
    unmount();
    expect(jest.getTimerCount()).toBe(0);
  });
});
