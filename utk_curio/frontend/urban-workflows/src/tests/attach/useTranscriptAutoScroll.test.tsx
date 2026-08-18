import React from "react";
import { render, fireEvent, createEvent } from "@testing-library/react";
import { useTranscriptAutoScroll } from "../../components/agents/attach/useTranscriptAutoScroll";

/** Exercises the hook against a real scrollable div with mocked geometry
 * (jsdom does no layout, so scrollHeight/clientHeight/scrollTop are stubbed).
 * Geometry: scrollHeight 1000, clientHeight 300 → bottom sits at 700. */

type HarnessProps = { items: string[]; resetKey?: string; ready?: boolean };

const Harness: React.FC<HarnessProps> = ({ items, resetKey, ready }) => {
  const { containerRef, atBottom, jumpToLatest, pinToLatest } = useTranscriptAutoScroll({
    content: items,
    resetKey,
    ready,
  });
  return (
    <div>
      <div data-testid="scroller" ref={containerRef}>
        {items.map((t, i) => (
          <p key={i}>{t}</p>
        ))}
      </div>
      <output data-testid="atBottom">{String(atBottom)}</output>
      <button data-testid="jump" onClick={jumpToLatest} />
      <button data-testid="pin" onClick={pinToLatest} />
    </div>
  );
};

const BOTTOM = 700; // scrollHeight - clientHeight

function mockGeometry(el: HTMLElement) {
  let scrollTop = 0;
  Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => 1000 });
  Object.defineProperty(el, "clientHeight", { configurable: true, get: () => 300 });
  Object.defineProperty(el, "clientWidth", { configurable: true, get: () => 500 });
  Object.defineProperty(el, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: (v: number) => {
      scrollTop = v;
    },
  });
  // Instant-landing scrollTo (real browsers also fire a scroll event, which
  // tests emulate explicitly where the suppress handshake matters).
  (el as HTMLElement & { scrollTo: (opts: ScrollToOptions) => void }).scrollTo = (
    opts: ScrollToOptions,
  ) => {
    scrollTop = opts.top ?? 0;
  };
}

function setup(props: Partial<HarnessProps> = {}) {
  const utils = render(<Harness items={["a"]} {...props} />);
  const el = utils.getByTestId("scroller");
  mockGeometry(el);
  return { ...utils, el };
}

/** Emulate the user scrolling to a position (browser fires scroll after). */
function userScroll(el: HTMLElement, top: number) {
  el.scrollTop = top;
  fireEvent.scroll(el);
}

describe("useTranscriptAutoScroll", () => {
  it("follows content growth while pinned at the bottom", () => {
    const { el, rerender } = setup();
    rerender(<Harness items={["a", "b"]} />);
    expect(el.scrollTop).toBe(BOTTOM);
  });

  it("streamed growth while detached leaves the scroll position untouched (dev/75 regression)", () => {
    const { el, rerender, getByTestId } = setup();
    userScroll(el, 100);
    expect(getByTestId("atBottom").textContent).toBe("false");
    // New array reference with the last item replaced — the streaming shape.
    rerender(<Harness items={["a (longer streamed text)"]} />);
    rerender(<Harness items={["a (even longer streamed text)"]} />);
    expect(el.scrollTop).toBe(100);
    expect(getByTestId("atBottom").textContent).toBe("false");
  });

  it("manually returning near the bottom resumes follow", () => {
    const { el, rerender, getByTestId } = setup();
    userScroll(el, 100);
    userScroll(el, 660); // 40px away — within the threshold
    expect(getByTestId("atBottom").textContent).toBe("true");
    rerender(<Harness items={["a", "b"]} />);
    expect(el.scrollTop).toBe(BOTTOM);
  });

  it("treats exactly 48px from the bottom as bottom, 49px as detached", () => {
    const { el, getByTestId } = setup();
    userScroll(el, BOTTOM - 48);
    expect(getByTestId("atBottom").textContent).toBe("true");
    userScroll(el, BOTTOM - 49);
    expect(getByTestId("atBottom").textContent).toBe("false");
  });

  it("jumpToLatest scrolls to the newest message and re-pins", () => {
    const { el, getByTestId, rerender } = setup();
    userScroll(el, 100);
    fireEvent.click(getByTestId("jump"));
    expect(el.scrollTop).toBe(BOTTOM);
    expect(getByTestId("atBottom").textContent).toBe("true");
    rerender(<Harness items={["a", "b"]} />);
    expect(el.scrollTop).toBe(BOTTOM); // follow re-engaged
  });

  it("a smooth jump's intermediate scroll positions never read as a detach", () => {
    const { el, getByTestId } = setup();
    // A scrollTo whose animation hasn't landed yet.
    (el as HTMLElement & { scrollTo: () => void }).scrollTo = () => {};
    userScroll(el, 100);
    fireEvent.click(getByTestId("jump"));
    // Animation passes through mid positions: still pinned.
    el.scrollTop = 300;
    fireEvent.scroll(el);
    expect(getByTestId("atBottom").textContent).toBe("true");
    // Animation lands: the suppress handshake completes...
    el.scrollTop = BOTTOM;
    fireEvent.scroll(el);
    expect(getByTestId("atBottom").textContent).toBe("true");
    // ...so a genuine scroll-up afterwards detaches normally.
    userScroll(el, 100);
    expect(getByTestId("atBottom").textContent).toBe("false");
  });

  it("RACE REGRESSION (dev/79): wheel-up detaches before the next streamed chunk can re-pin", () => {
    const { el, rerender, getByTestId } = setup();
    rerender(<Harness items={["a."]} />); // pinned steady state at the bottom
    expect(el.scrollTop).toBe(BOTTOM);
    // The wheel fires and moves scrollTop synchronously…
    fireEvent.wheel(el, { deltaY: -120 });
    el.scrollTop = 400;
    // …and the next chunk is processed BEFORE the browser dispatches the
    // coalesced scroll event (real-browser ordering during streaming):
    rerender(<Harness items={["a.."]} />);
    expect(el.scrollTop).toBe(400); // held — not yanked back to the bottom
    fireEvent.scroll(el); // the coalesced scroll event arrives late
    expect(getByTestId("atBottom").textContent).toBe("false");
  });

  it("wheel-down never detaches — follow stays position-driven", () => {
    const { el, rerender, getByTestId } = setup();
    fireEvent.wheel(el, { deltaY: 120 });
    expect(getByTestId("atBottom").textContent).toBe("true");
    rerender(<Harness items={["a", "b"]} />);
    expect(el.scrollTop).toBe(BOTTOM); // still following
  });

  it("touchmove detaches eagerly; a scroll event still near the bottom re-pins (self-heal)", () => {
    const { el, getByTestId } = setup();
    fireEvent.touchMove(el);
    expect(getByTestId("atBottom").textContent).toBe("false");
    el.scrollTop = BOTTOM; // the gesture never actually left the bottom zone
    fireEvent.scroll(el);
    expect(getByTestId("atBottom").textContent).toBe("true");
  });

  it("up-scroll keys detach eagerly", () => {
    const { el, getByTestId } = setup();
    fireEvent.keyDown(el, { key: "ArrowUp" });
    expect(getByTestId("atBottom").textContent).toBe("false");
  });

  it("pointerdown detaches only from the scrollbar gutter, never content clicks", () => {
    const { el, getByTestId } = setup();
    const contentClick = createEvent.pointerDown(el);
    Object.defineProperty(contentClick, "offsetX", { value: 200 }); // < clientWidth 500
    fireEvent(el, contentClick);
    expect(getByTestId("atBottom").textContent).toBe("true");
    const gutterClick = createEvent.pointerDown(el);
    Object.defineProperty(gutterClick, "offsetX", { value: 505 }); // in the gutter
    fireEvent(el, gutterClick);
    expect(getByTestId("atBottom").textContent).toBe("false");
  });

  it("momentum wheel during a jump flight cannot cancel it; the deadline snap lands it", () => {
    jest.useFakeTimers();
    try {
      const { el, getByTestId } = setup();
      // A smooth engine that never lands — the canceled-by-momentum case.
      (el as HTMLElement & { scrollTo: () => void }).scrollTo = () => {};
      userScroll(el, 100);
      fireEvent.click(getByTestId("jump"));
      expect(getByTestId("atBottom").textContent).toBe("true");
      // Trackpad momentum keeps arriving right after the click — ignored:
      fireEvent.wheel(el, { deltaY: -40 });
      fireEvent.wheel(el, { deltaY: -12 });
      expect(getByTestId("atBottom").textContent).toBe("true");
      expect(el.scrollTop).toBe(100); // the animation is dead, nothing moved…
      jest.advanceTimersByTime(450);
      expect(el.scrollTop).toBe(BOTTOM); // …so the deadline snap landed it
      expect(getByTestId("atBottom").textContent).toBe("true");
    } finally {
      jest.useRealTimers();
    }
  });

  it("after a jump lands, a genuine wheel-up detaches normally again", () => {
    const { el, getByTestId } = setup();
    (el as HTMLElement & { scrollTo: () => void }).scrollTo = () => {};
    userScroll(el, 100);
    fireEvent.click(getByTestId("jump"));
    el.scrollTop = BOTTOM;
    fireEvent.scroll(el); // lands → suppress cleared, flight disarmed
    fireEvent.wheel(el, { deltaY: -120 });
    expect(getByTestId("atBottom").textContent).toBe("false");
  });

  it("pinToLatest instantly re-pins from a detached position", () => {
    const { el, getByTestId } = setup();
    userScroll(el, 100);
    fireEvent.click(getByTestId("pin"));
    expect(el.scrollTop).toBe(BOTTOM);
    expect(getByTestId("atBottom").textContent).toBe("true");
  });

  it("ready=false defers following; flipping ready pins once (history hydration)", () => {
    const { el, rerender } = setup({ ready: false });
    rerender(<Harness items={["a", "b"]} ready={false} />);
    expect(el.scrollTop).toBe(0);
    rerender(<Harness items={["a", "b"]} ready={true} />);
    expect(el.scrollTop).toBe(BOTTOM);
  });

  it("a resetKey change force-pins even when detached (attachment switch)", () => {
    const { el, rerender, getByTestId } = setup({ resetKey: "chat-1" });
    userScroll(el, 100);
    rerender(<Harness items={["a"]} resetKey="chat-2" />);
    expect(el.scrollTop).toBe(BOTTOM);
    expect(getByTestId("atBottom").textContent).toBe("true");
  });
});
