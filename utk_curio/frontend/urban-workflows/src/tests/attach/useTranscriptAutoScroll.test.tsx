import React from "react";
import { act, render, fireEvent, createEvent } from "@testing-library/react";
import { useTranscriptAutoScroll } from "../../components/agents/attach/useTranscriptAutoScroll";

/** Exercises the hook against a real scrollable div with mocked geometry
 * (jsdom does no layout, so scrollHeight/clientHeight/scrollTop are stubbed).
 * Geometry: scrollHeight 1000, clientHeight 300 → bottom sits at 700. */

type HarnessProps = {
  items: string[];
  resetKey?: string;
  ready?: boolean;
  /** dev/83: pass items.length as itemCount (default); false = omit it. */
  withCount?: boolean;
};

const Harness: React.FC<HarnessProps> = ({ items, resetKey, ready, withCount = true }) => {
  const { containerRef, atBottom, unreadCount, jumpToLatest, pinToLatest } =
    useTranscriptAutoScroll({
      content: items,
      resetKey,
      ready,
      itemCount: withCount ? items.length : undefined,
    });
  return (
    <div>
      <div data-testid="scroller" ref={containerRef}>
        {items.map((t, i) => (
          <p key={i}>{t}</p>
        ))}
      </div>
      <output data-testid="atBottom">{String(atBottom)}</output>
      <output data-testid="unread">{String(unreadCount)}</output>
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

describe("unreadCount (dev/83)", () => {
  it("counts turns landed while detached and resets on bottom return", () => {
    const { el, rerender, getByTestId } = setup();
    expect(getByTestId("unread").textContent).toBe("0"); // pinned
    userScroll(el, 100); // detach — baseline is 1 item
    expect(getByTestId("unread").textContent).toBe("0"); // nothing new yet
    rerender(<Harness items={["a", "b"]} />);
    expect(getByTestId("unread").textContent).toBe("1");
    rerender(<Harness items={["a", "b", "c"]} />);
    expect(getByTestId("unread").textContent).toBe("2");
    userScroll(el, BOTTOM); // manual bottom return re-pins
    expect(getByTestId("unread").textContent).toBe("0");
  });

  it("streamed chunk growth never increments — the count keys off items, not content", () => {
    const { el, rerender, getByTestId } = setup();
    userScroll(el, 100);
    // New array references with the last item replaced — the streaming shape.
    rerender(<Harness items={["a (longer streamed text)"]} />);
    rerender(<Harness items={["a (even longer streamed text)"]} />);
    expect(getByTestId("unread").textContent).toBe("0");
    // The NEXT whole turn landing counts exactly once.
    rerender(<Harness items={["a (even longer streamed text)", "b"]} />);
    expect(getByTestId("unread").textContent).toBe("1");
  });

  it("jumpToLatest resets the count with the re-pin", () => {
    const { el, rerender, getByTestId } = setup();
    userScroll(el, 100);
    rerender(<Harness items={["a", "b"]} />);
    expect(getByTestId("unread").textContent).toBe("1");
    fireEvent.click(getByTestId("jump"));
    expect(getByTestId("unread").textContent).toBe("0");
  });

  it("pinToLatest (the send path) resets the count", () => {
    const { el, rerender, getByTestId } = setup();
    userScroll(el, 100);
    rerender(<Harness items={["a", "b"]} />);
    expect(getByTestId("unread").textContent).toBe("1");
    fireEvent.click(getByTestId("pin"));
    expect(getByTestId("unread").textContent).toBe("0");
  });

  it("a resetKey force-pin (chat switch) resets the count", () => {
    const { el, rerender, getByTestId } = setup({ resetKey: "chat-1" });
    userScroll(el, 100);
    rerender(<Harness items={["a", "b"]} resetKey="chat-1" />);
    expect(getByTestId("unread").textContent).toBe("1");
    rerender(<Harness items={["a", "b"]} resetKey="chat-2" />);
    expect(getByTestId("unread").textContent).toBe("0");
  });

  it("a fresh detach after a re-pin starts counting from the new baseline", () => {
    const { el, rerender, getByTestId } = setup();
    userScroll(el, 100);
    rerender(<Harness items={["a", "b"]} />);
    userScroll(el, BOTTOM); // re-pin: baseline forgotten
    userScroll(el, 100); // detach again — baseline is now 2 items
    expect(getByTestId("unread").textContent).toBe("0");
    rerender(<Harness items={["a", "b", "c"]} />);
    expect(getByTestId("unread").textContent).toBe("1");
  });

  it("a shrunken item count while detached never goes negative", () => {
    const { el, rerender, getByTestId } = setup({ items: ["a", "b", "c"] });
    userScroll(el, 100);
    rerender(<Harness items={["a"]} />);
    expect(getByTestId("unread").textContent).toBe("0");
  });

  it("itemCount omitted → always 0 (existing consumers unchanged)", () => {
    const { el, rerender, getByTestId } = setup({ withCount: false });
    userScroll(el, 100);
    rerender(<Harness items={["a", "b"]} withCount={false} />);
    expect(getByTestId("atBottom").textContent).toBe("false");
    expect(getByTestId("unread").textContent).toBe("0");
  });
});

/**
 * A browser tells a scroll on the frame after it, so the transcript reads
 * where it stands then, after what changed meanwhile. When the line above
 * the transcript goes (a build's narration as it pauses), the transcript's
 * box grows: on that frame the browser clamps its place at the new bottom,
 * a scroll no reader made, and the resize observer reports the box's new
 * size. When, before the next frame, the lines above it come back taller
 * (the paused plan's), the box is shorter than before, and the transcript
 * reads that scroll as a reader who left the bottom by more than the
 * threshold. The Builder's chat then stayed above the candidates card,
 * behind a pill, in the handoff's card frame.
 */
describe("a scroll the browser made for a change of size, read after a later one", () => {
  /** The resize observer the hook watches the transcript with, as jsdom has
   * none: a test reports a change of size as the browser does, after its
   * layout and before the scroll events of the next frame. */
  let reportSizes: () => void = () => undefined;
  const browserObserver = (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
  beforeEach(() => {
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
      private readonly callback: () => void;
      constructor(callback: () => void) {
        this.callback = callback;
      }
      observe() {
        reportSizes = () => act(() => this.callback());
      }
      unobserve() {}
      disconnect() {}
    };
  });
  afterEach(() => {
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = browserObserver;
    reportSizes = () => undefined;
  });

  /** The transcript's box and content as each test sets them, and where it
   * stands. */
  function sized(el: HTMLElement, box: { scrollHeight: number; clientHeight: number }) {
    let scrollTop = 0;
    Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => box.scrollHeight });
    Object.defineProperty(el, "clientHeight", { configurable: true, get: () => box.clientHeight });
    Object.defineProperty(el, "clientWidth", { configurable: true, get: () => 500 });
    Object.defineProperty(el, "scrollTop", {
      configurable: true,
      get: () => scrollTop,
      set: (v: number) => {
        scrollTop = v;
      },
    });
    (el as HTMLElement & { scrollTo: (opts: ScrollToOptions) => void }).scrollTo = (opts: ScrollToOptions) => {
      scrollTop = opts.top ?? 0;
    };
  }

  /** A transcript at its newest turn, which the browser has told. */
  function atTheBottom() {
    const box = { scrollHeight: 1000, clientHeight: 300 };
    const utils = render(<Harness items={["a"]} />);
    const el = utils.getByTestId("scroller");
    sized(el, box);
    utils.rerender(<Harness items={["a", "b"]} />);
    expect(el.scrollTop).toBe(700);
    fireEvent.scroll(el);
    expect(utils.getByTestId("atBottom").textContent).toBe("true");
    return { ...utils, el, box };
  }

  it("keeps a reader at the bottom there: the transcript follows to the new bottom, with no pill", () => {
    const { el, box, rerender, getByTestId } = atTheBottom();
    // The line above goes: the box grows by 100 px, the browser clamps the
    // place to the new bottom, and the observer reports the new size; the
    // scroll is told on the next frame.
    box.clientHeight = 400;
    el.scrollTop = 600;
    reportSizes();
    // Before that frame, the lines above come back taller than before.
    box.clientHeight = 250;
    fireEvent.scroll(el);
    expect(getByTestId("atBottom").textContent).toBe("true");
    expect(el.scrollTop).toBe(750);
    // And the newest turn that lands next is followed too.
    box.scrollHeight = 1300;
    rerender(<Harness items={["a", "b", "c"]} />);
    expect(el.scrollTop).toBe(1050);
    expect(getByTestId("unread").textContent).toBe("0");
  });

  it("a reader who scrolled up keeps their place and the pill when the box changes size", () => {
    const { el, box, rerender, getByTestId } = atTheBottom();
    userScroll(el, 100);
    expect(getByTestId("atBottom").textContent).toBe("false");
    box.clientHeight = 250;
    reportSizes();
    fireEvent.scroll(el);
    expect(getByTestId("atBottom").textContent).toBe("false");
    expect(el.scrollTop).toBe(100);
    box.scrollHeight = 1300;
    rerender(<Harness items={["a", "b", "c"]} />);
    expect(el.scrollTop).toBe(100);
    expect(getByTestId("unread").textContent).toBe("1");
  });

  it("a scroll that moved the transcript to an earlier card is the reader's, though the content changed size unseen", () => {
    const { el, box, getByTestId } = atTheBottom();
    // A turn above the last grows, which no observer watches; then the
    // transcript is scrolled to an earlier card (Show the card, or a test's
    // scroll into view).
    box.scrollHeight = 1100;
    el.scrollTop = 200;
    fireEvent.scroll(el);
    expect(el.scrollTop).toBe(200);
    expect(getByTestId("atBottom").textContent).toBe("false");
  });

  /**
   * A script that reads the page's layout between two frames (a check of
   * what is on screen, or this hook's own read as a turn lands) makes the
   * browser clamp the place there and then. The observer reports sizes only
   * on a frame, after that frame's scroll events, so no report says where
   * the clamp left the transcript before the browser tells its scroll.
   */
  it("keeps a reader at the bottom there when the browser clamped the place between frames, before any report", () => {
    const { el, box, getByTestId } = atTheBottom();
    // The line above goes, and a script reads the layout before the next
    // frame: the box grows by 100 px and the browser clamps the place to the
    // new bottom then. No observer reports the bigger box.
    box.clientHeight = 400;
    el.scrollTop = 600;
    // Before that frame, the lines above come back taller than before.
    box.clientHeight = 250;
    // The frame: the scroll is told first, then the observer reports.
    fireEvent.scroll(el);
    reportSizes();
    expect(getByTestId("atBottom").textContent).toBe("true");
    expect(el.scrollTop).toBe(750);
    expect(getByTestId("unread").textContent).toBe("0");
  });

  it("keeps a reader at the bottom there when the clamp came at this hook's own read of a chat read again", () => {
    const { el, box, rerender, getByTestId } = atTheBottom();
    // The line above goes, then the chat is read again with the same turns:
    // this hook's read of the layout is where the browser clamps the place to
    // the new bottom, which it finds the transcript at, so it moves nothing.
    box.clientHeight = 400;
    el.scrollTop = 600;
    rerender(<Harness items={["a", "b"]} />);
    expect(el.scrollTop).toBe(600);
    // Before the next frame, the lines above come back taller than before.
    box.clientHeight = 250;
    fireEvent.scroll(el);
    reportSizes();
    expect(getByTestId("atBottom").textContent).toBe("true");
    expect(el.scrollTop).toBe(750);
    expect(getByTestId("unread").textContent).toBe("0");
  });
});
