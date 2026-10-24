/**
 * The one Curio tooltip (components/tooltip/TooltipLayer.tsx). One layer,
 * mounted once, shows the `data-tooltip` of whatever the pointer rests on, or
 * the content a target registered with useTooltipContent, in one tooltip on
 * document.body. These are its rules, timed with Jest's fake clock:
 *
 * - it shows 400 ms after the pointer rests, and at once on a target reached
 *   within 600 ms of one closing;
 * - it hides 100 ms after the pointer leaves both the target and the tooltip,
 *   so the pointer can move onto it; and at once on a press on the target
 *   (then it stays off until the pointer leaves), a wheel, a scroll, a drag,
 *   Escape, or the window losing focus. A press inside it keeps it;
 * - focus from the keyboard shows it at once, until blur or Escape; focus from
 *   a click shows nothing;
 * - a touch held 500 ms shows it, and the next touch anywhere hides it; a tap
 *   works as before;
 * - an open tooltip follows its target's `data-tooltip` as it changes (Vega
 *   rewrites it as the pointer crosses marks), and hides when it is cleared;
 * - one tooltip at a time, `role="tooltip"` with an id, and its target's
 *   `aria-describedby` points at it only while it shows.
 *
 * The targets sit in a box that stops presses, wheels and touches from
 * bubbling, as React Flow's pane and nodes do (d3's drag and zoom stop them
 * there), so the layer has to hear them on their way down. A pointer is moved
 * with the events a browser sends for a mouse: pointer events, then their
 * mouse twins.
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { TooltipLayer } from "../../../components/tooltip/TooltipLayer";
import { resetTooltipStore } from "../../../components/tooltip/tooltipStore";
import { useTooltipContent } from "../../../components/tooltip/useTooltipContent";

/** The layer may place a tooltip in the animation frame after it decides to show it. */
const FRAME = 16;

const MOUSE = { pointerType: "mouse", isPrimary: true, pointerId: 1 };
const TOUCH = { pointerType: "touch", isPrimary: true, pointerId: 2 };

/** The tooltips on screen. */
function shown(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>('[role="tooltip"]')).filter(
    (tip) => !tip.hidden && tip.getAttribute("aria-hidden") !== "true",
  );
}

/** The one tooltip on screen, or null. */
function tooltip(): HTMLElement | null {
  const tips = shown();
  expect(tips.length).toBeLessThanOrEqual(1);
  return tips[0] ?? null;
}

/** What the tooltip on screen says, its white space run together. */
const said = () => (tooltip()?.textContent ?? "").replace(/\s+/g, " ").trim();

/** The ids an element's aria-describedby names. */
const describedBy = (el: Element) => (el.getAttribute("aria-describedby") ?? "").split(/\s+/).filter(Boolean);

/** Run the clock *ms* on, then whatever that started. */
async function advance(ms: number) {
  await act(async () => {
    jest.advanceTimersByTime(ms);
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  });
}

/** Where the mouse is. */
let at: Element = document.body;

/** The mouse moves from where it is onto *el*: it leaves the one, enters the other, and moves. */
function moveTo(el: Element) {
  const from = at;
  if (from !== el) {
    fireEvent.pointerLeave(from, { ...MOUSE, relatedTarget: el });
    fireEvent.mouseLeave(from, { relatedTarget: el });
    fireEvent.pointerEnter(el, { ...MOUSE, relatedTarget: from });
    fireEvent.mouseEnter(el, { relatedTarget: from });
  }
  at = el;
  fireEvent.pointerMove(el, { ...MOUSE, clientX: 10, clientY: 10 });
  fireEvent.mouseMove(el, { clientX: 10, clientY: 10 });
}

/** The mouse button goes down on *el*; a button takes the focus, as it does in a browser. */
function press(el: Element) {
  fireEvent.pointerDown(el, { ...MOUSE, button: 0 });
  fireEvent.mouseDown(el, { button: 0 });
  if (el instanceof HTMLButtonElement) act(() => el.focus());
}

/** The mouse button comes up on *el*: a click. */
function release(el: Element) {
  fireEvent.pointerUp(el, { ...MOUSE, button: 0 });
  fireEvent.mouseUp(el, { button: 0 });
  fireEvent.click(el, { button: 0 });
}

/** Tab moves the keyboard's focus onto *el*. */
function tabTo(el: HTMLElement) {
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Tab", code: "Tab" });
  act(() => el.focus());
  fireEvent.keyUp(el, { key: "Tab", code: "Tab" });
}

/** A finger comes down on *el*. */
function touchDown(el: Element) {
  fireEvent.pointerEnter(el, TOUCH);
  fireEvent.pointerDown(el, TOUCH);
  fireEvent.touchStart(el, { touches: [{ clientX: 10, clientY: 10 }] });
}

/** The finger lifts off *el*. */
function touchUp(el: Element) {
  fireEvent.pointerUp(el, TOUCH);
  fireEvent.pointerLeave(el, TOUCH);
  fireEvent.touchEnd(el, { changedTouches: [{ clientX: 10, clientY: 10 }] });
}

/** The layer, once, and *ui* in a box that keeps presses, wheels and touches from bubbling. */
function setup(ui: React.ReactElement) {
  const result = render(
    <>
      <TooltipLayer />
      <div data-testid="canvas">{ui}</div>
    </>,
  );
  const canvas = screen.getByTestId("canvas");
  for (const type of ["pointerdown", "mousedown", "touchstart", "wheel"]) {
    canvas.addEventListener(type, (event) => event.stopImmediatePropagation());
  }
  return result;
}

describe("the one Curio tooltip", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    // Each test's fake clock starts again near where an earlier one closed a
    // tooltip: the store starts as a page does, with none warm.
    resetTooltipStore();
    at = document.body;
  });

  // In this block, so it runs before Testing Library unmounts the page: no
  // tooltip is left open for the next test.
  afterEach(async () => {
    moveTo(document.body);
    act(() => (document.activeElement as HTMLElement | null)?.blur());
    fireEvent.keyDown(document.body, { key: "Escape", code: "Escape" });
    await advance(1000);
    cleanup();
    jest.useRealTimers();
  });

  describe("showing it", () => {
    test("400 ms after the pointer rests on a target, in one tooltip on document.body", async () => {
      const { container } = setup(<button data-tooltip="Delete node">x</button>);
      const button = screen.getByText("x");
      moveTo(button);
      expect(shown()).toHaveLength(0);
      await advance(399);
      expect(shown()).toHaveLength(0);
      await advance(1 + FRAME);
      expect(said()).toBe("Delete node");
      const tip = tooltip() as HTMLElement;
      // In a portal on document.body, outside everything the page renders.
      expect(document.body.contains(tip)).toBe(true);
      expect(container.contains(tip)).toBe(false);
      expect(tip.id).not.toBe("");
      expect(describedBy(button)).toEqual([tip.id]);
    });

    test("the 400 ms count from where the pointer last moved", async () => {
      setup(<button data-tooltip="Minimize">m</button>);
      const button = screen.getByText("m");
      moveTo(button);
      await advance(300);
      moveTo(button);
      await advance(300);
      // 600 ms after it came, 300 after it last moved: not yet.
      expect(shown()).toHaveLength(0);
      await advance(100 + FRAME);
      expect(said()).toBe("Minimize");
    });

    test("a target reached within 600 ms of one closing shows at once; later ones wait again", async () => {
      setup(
        <>
          <button data-tooltip="First">a</button>
          <button data-tooltip="Second">b</button>
        </>,
      );
      moveTo(screen.getByText("a"));
      await advance(400 + FRAME);
      expect(said()).toBe("First");
      moveTo(document.body);
      await advance(100);
      expect(shown()).toHaveLength(0);

      // 300 ms after it closed.
      await advance(300);
      moveTo(screen.getByText("b"));
      await advance(FRAME);
      expect(said()).toBe("Second");
      moveTo(document.body);
      await advance(100);
      expect(shown()).toHaveLength(0);

      // 700 ms after that one closed.
      await advance(700);
      moveTo(screen.getByText("a"));
      await advance(399);
      expect(shown()).toHaveLength(0);
      await advance(1 + FRAME);
      expect(said()).toBe("First");
    });

    test("the nearest target holds it: a tag in a line that has its own", async () => {
      setup(
        <div data-tooltip="From Summarize: 2 values, a tuple">
          <span data-tooltip="input_1">tag</span>
          <span>about</span>
        </div>,
      );
      moveTo(screen.getByText("tag"));
      await advance(400 + FRAME);
      expect(said()).toBe("input_1");
      moveTo(screen.getByText("about"));
      await advance(FRAME);
      expect(said()).toBe("From Summarize: 2 values, a tuple");
    });

    test("an empty data-tooltip shows nothing", async () => {
      setup(<button data-tooltip="">e</button>);
      moveTo(screen.getByText("e"));
      await advance(1000);
      expect(shown()).toHaveLength(0);
    });
  });

  describe("hiding it", () => {
    test("100 ms after the pointer leaves the target", async () => {
      setup(<button data-tooltip="Pin to dashboard">p</button>);
      const button = screen.getByText("p");
      moveTo(button);
      await advance(400 + FRAME);
      moveTo(document.body);
      await advance(99);
      expect(said()).toBe("Pin to dashboard");
      await advance(1);
      expect(shown()).toHaveLength(0);
      expect(describedBy(button)).toEqual([]);
    });

    test("the pointer may move onto the tooltip; it hides 100 ms after leaving both", async () => {
      setup(<button data-tooltip="From Summarize: 2 values, a tuple">i</button>);
      moveTo(screen.getByText("i"));
      await advance(400 + FRAME);
      moveTo(tooltip() as HTMLElement);
      await advance(1000);
      expect(said()).toBe("From Summarize: 2 values, a tuple");
      moveTo(document.body);
      await advance(99);
      expect(shown()).toHaveLength(1);
      await advance(1);
      expect(shown()).toHaveLength(0);
    });

    test("over the gap between the target and the tooltip, onto it and off it: it hides 100 ms after", async () => {
      setup(
        <>
          <button data-tooltip="From Summarize: 2 values, a tuple">i</button>
          <span>gap</span>
        </>,
      );
      moveTo(screen.getByText("i"));
      await advance(400 + FRAME);
      // The 6 px between the target and the tooltip, on the way up to it.
      moveTo(screen.getByText("gap"));
      await advance(50);
      moveTo(tooltip() as HTMLElement);
      await advance(1000);
      expect(said()).toBe("From Summarize: 2 values, a tuple");
      moveTo(document.body);
      await advance(99);
      expect(shown()).toHaveLength(1);
      await advance(1);
      expect(shown()).toHaveLength(0);
    });

    test("a press inside the tooltip keeps it", async () => {
      setup(<button data-tooltip="sensor, pm25_mean">c</button>);
      moveTo(screen.getByText("c"));
      await advance(400 + FRAME);
      const tip = tooltip() as HTMLElement;
      moveTo(tip);
      press(tip);
      release(tip);
      await advance(1000);
      expect(said()).toBe("sensor, pm25_mean");
    });

    test("a press on the target hides it at once, and it stays off until the pointer leaves", async () => {
      setup(<button data-tooltip="Run this node">r</button>);
      const button = screen.getByText("r");
      moveTo(button);
      await advance(400 + FRAME);
      expect(said()).toBe("Run this node");
      press(button);
      await advance(0);
      expect(shown()).toHaveLength(0);
      release(button);
      moveTo(button);
      await advance(1000);
      expect(shown()).toHaveLength(0);

      moveTo(document.body);
      await advance(1000);
      moveTo(button);
      await advance(400 + FRAME);
      expect(said()).toBe("Run this node");
    });

    test("a press keeps off only its own target's: a chart's next mark, a button in a pressed row", async () => {
      setup(
        <>
          <div data-testid="chart" data-tooltip="zip: 60614" data-tooltip-side="pointer" />
          <div data-tooltip="Drag onto the canvas">
            <span>row</span>
            <button data-tooltip="Copy the id">copy</button>
          </div>
        </>,
      );
      const chart = screen.getByTestId("chart");
      moveTo(chart);
      await advance(400 + FRAME);
      expect(said()).toBe("zip: 60614");
      press(chart);
      release(chart);
      await advance(0);
      expect(shown()).toHaveLength(0);
      // The pointer moves on to the next mark, which writes its own tooltip.
      act(() => chart.setAttribute("data-tooltip", "zip: 60622"));
      moveTo(chart);
      await advance(400 + FRAME);
      expect(said()).toBe("zip: 60622");

      moveTo(document.body);
      await advance(1000);
      const row = screen.getByText("row");
      moveTo(row);
      await advance(400 + FRAME);
      expect(said()).toBe("Drag onto the canvas");
      press(row);
      release(row);
      await advance(0);
      expect(shown()).toHaveLength(0);
      moveTo(screen.getByText("copy"));
      await advance(400 + FRAME);
      expect(said()).toBe("Copy the id");
    });

    test("Escape hides it at once", async () => {
      setup(<button data-tooltip="Save template">s</button>);
      moveTo(screen.getByText("s"));
      await advance(400 + FRAME);
      expect(said()).toBe("Save template");
      fireEvent.keyDown(document.body, { key: "Escape", code: "Escape" });
      await advance(0);
      expect(shown()).toHaveLength(0);
    });

    test("a wheel, a scroll, a drag and the window losing focus each hide it at once", async () => {
      setup(
        <div data-testid="scroller" style={{ overflow: "auto", height: 40 }}>
          <button data-tooltip="Fit view">f</button>
        </div>,
      );
      const button = screen.getByText("f");
      const hides: Array<[string, () => void]> = [
        ["a wheel", () => fireEvent.wheel(button, { deltaY: 40 })],
        ["a scroll", () => fireEvent.scroll(screen.getByTestId("scroller"))],
        ["a drag", () => fireEvent.dragStart(button)],
        ["the window losing focus", () => fireEvent.blur(window)],
      ];
      for (const [what, happen] of hides) {
        moveTo(document.body);
        await advance(1000);
        moveTo(button);
        await advance(400 + FRAME);
        expect({ what, said: said() }).toEqual({ what, said: "Fit view" });
        happen();
        await advance(0);
        expect({ what, shown: shown().length }).toEqual({ what, shown: 0 });
      }
    });

    test("a scroll elsewhere leaves it: a chat that scrolls as it streams", async () => {
      setup(
        <>
          <div data-testid="chat" style={{ overflow: "auto", height: 40 }}>
            <p>streaming</p>
          </div>
          <div data-testid="panel" style={{ overflow: "auto", height: 40 }}>
            <button data-tooltip="Fit view">f</button>
          </div>
        </>,
      );
      moveTo(screen.getByText("f"));
      await advance(400 + FRAME);
      expect(said()).toBe("Fit view");
      fireEvent.scroll(screen.getByTestId("chat"));
      await advance(0);
      expect(said()).toBe("Fit view");
      // What holds its target scrolls: the target moved from under it.
      fireEvent.scroll(screen.getByTestId("panel"));
      await advance(0);
      expect(shown()).toHaveLength(0);
    });
  });

  describe("the keyboard and touch", () => {
    test("focus from the keyboard shows it at once, until Escape or blur", async () => {
      setup(
        <>
          <button data-tooltip="Minimize">m</button>
          <button data-tooltip="Delete node">d</button>
        </>,
      );
      const minimize = screen.getByText("m");
      const remove = screen.getByText("d");
      tabTo(minimize);
      await advance(FRAME);
      expect(said()).toBe("Minimize");
      expect(describedBy(minimize)).toEqual([(tooltip() as HTMLElement).id]);
      fireEvent.keyDown(minimize, { key: "Escape", code: "Escape" });
      await advance(0);
      expect(shown()).toHaveLength(0);

      tabTo(remove);
      await advance(FRAME);
      expect(said()).toBe("Delete node");
      act(() => remove.blur());
      await advance(0);
      expect(shown()).toHaveLength(0);
    });

    test("one the keyboard opened goes when its target's data-tooltip is taken off", async () => {
      setup(<button data-tooltip="Unsaved changes">u</button>);
      const button = screen.getByText("u");
      tabTo(button);
      await advance(FRAME);
      expect(said()).toBe("Unsaved changes");
      act(() => button.removeAttribute("data-tooltip"));
      await advance(0);
      expect(shown()).toHaveLength(0);
    });

    test("keyboard focus on a control inside a target: that control is the one it describes", async () => {
      setup(
        <span data-testid="thumb" data-tooltip="12 m">
          <input type="range" aria-label="Height" />
        </span>,
      );
      const input = screen.getByLabelText("Height");
      tabTo(input);
      await advance(FRAME);
      expect(said()).toBe("12 m");
      expect(describedBy(input)).toEqual([(tooltip() as HTMLElement).id]);
      expect(describedBy(screen.getByTestId("thumb"))).toEqual([]);
    });

    test("focus from a click shows nothing, under the pointer or after it leaves", async () => {
      setup(<button data-tooltip="Save template">s</button>);
      const button = screen.getByText("s");
      moveTo(button);
      press(button);
      release(button);
      expect(document.activeElement).toBe(button);
      await advance(1000);
      expect(shown()).toHaveLength(0);
      moveTo(document.body);
      await advance(1000);
      expect(shown()).toHaveLength(0);
    });

    test("a touch held 500 ms shows it, and it stays until the next touch anywhere", async () => {
      setup(
        <>
          <button data-tooltip="Open chat with Researcher">o</button>
          <span>elsewhere</span>
        </>,
      );
      const badge = screen.getByText("o");
      touchDown(badge);
      await advance(499);
      expect(shown()).toHaveLength(0);
      await advance(1 + FRAME);
      expect(said()).toBe("Open chat with Researcher");
      touchUp(badge);
      await advance(1000);
      expect(said()).toBe("Open chat with Researcher");

      const elsewhere = screen.getByText("elsewhere");
      touchDown(elsewhere);
      await advance(0);
      expect(shown()).toHaveLength(0);
      touchUp(elsewhere);
    });

    test("a tap works as before and shows nothing", async () => {
      const onClick = jest.fn();
      setup(
        <button data-tooltip="Add to project" onClick={onClick}>
          t
        </button>,
      );
      const button = screen.getByText("t");
      touchDown(button);
      await advance(100);
      touchUp(button);
      // What a browser sends after a tap, for pages that only listen to the mouse.
      fireEvent.mouseEnter(button);
      fireEvent.mouseMove(button);
      fireEvent.mouseDown(button);
      fireEvent.mouseUp(button);
      fireEvent.click(button);
      expect(onClick).toHaveBeenCalledTimes(1);
      await advance(1000);
      expect(shown()).toHaveLength(0);
    });
  });

  describe("what it shows, and for whom", () => {
    test("it follows its target's data-tooltip as it changes, and hides when it is cleared", async () => {
      setup(<div data-testid="chart" />);
      const chart = screen.getByTestId("chart");
      // As Vega does: the chart writes the tooltip of the mark under the
      // pointer at each move over it, and clears it off every mark.
      let mark: string | null = "label: a\nvalue: 1";
      const draw = () =>
        mark === null ? chart.removeAttribute("data-tooltip") : chart.setAttribute("data-tooltip", mark);
      chart.addEventListener("pointermove", draw);
      chart.addEventListener("mousemove", draw);

      moveTo(chart);
      await advance(400 + FRAME);
      expect(said()).toBe("label: a value: 1");

      mark = "label: b\nvalue: 2";
      moveTo(chart);
      await advance(FRAME);
      expect(said()).toBe("label: b value: 2");

      mark = null;
      moveTo(chart);
      await advance(100);
      expect(shown()).toHaveLength(0);

      // Back on a mark within 600 ms of closing: at once.
      mark = "label: c\nvalue: 3";
      moveTo(chart);
      await advance(FRAME);
      expect(said()).toBe("label: c value: 3");

      // Emptied rather than removed: hidden all the same.
      mark = "";
      moveTo(chart);
      await advance(100);
      expect(shown()).toHaveLength(0);
    });

    test("one tooltip at a time, and aria-describedby only on the target it describes", async () => {
      setup(
        <>
          <button data-tooltip="First">a</button>
          <button data-tooltip="Second">b</button>
          <button data-tooltip="Third">c</button>
        </>,
      );
      const [a, b, c] = ["a", "b", "c"].map((text) => screen.getByText(text));
      moveTo(a);
      await advance(400 + FRAME);
      moveTo(b);
      await advance(FRAME);
      expect(shown()).toHaveLength(1);
      expect(said()).toBe("Second");
      expect(describedBy(a)).toEqual([]);
      expect(describedBy(b)).toEqual([(tooltip() as HTMLElement).id]);

      // Keyboard focus elsewhere takes it over.
      tabTo(c);
      await advance(FRAME);
      expect(shown()).toHaveLength(1);
      expect(said()).toBe("Third");
      expect(describedBy(b)).toEqual([]);
      expect(describedBy(c)).toEqual([(tooltip() as HTMLElement).id]);
    });

    test("a target's own aria-describedby is kept, with the tooltip's id beside it", async () => {
      setup(
        <>
          <p id="help">Opens the agent's chat beside the canvas</p>
          <button data-tooltip="Open chat" aria-describedby="help">
            o
          </button>
        </>,
      );
      const button = screen.getByText("o");
      moveTo(button);
      await advance(400 + FRAME);
      const tip = tooltip() as HTMLElement;
      expect(describedBy(button).sort()).toEqual(["help", tip.id].sort());
      moveTo(document.body);
      await advance(100);
      expect(describedBy(button)).toEqual(["help"]);
    });

    test("content registered with useTooltipContent shows in the same tooltip", async () => {
      function Warnings() {
        const tip = useTooltipContent(
          <ul aria-label="Warnings">
            <li>Column zip is missing</li>
            <li>2 rows were dropped</li>
          </ul>,
        );
        return <span {...tip}>2 warnings</span>;
      }
      setup(<Warnings />);
      const target = screen.getByText("2 warnings");
      moveTo(target);
      await advance(399);
      expect(shown()).toHaveLength(0);
      await advance(1 + FRAME);
      const tip = tooltip() as HTMLElement;
      expect(within(tip).getByRole("list", { name: "Warnings" })).toBeTruthy();
      expect(within(tip).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
        "Column zip is missing",
        "2 rows were dropped",
      ]);
      expect(describedBy(target)).toEqual([tip.id]);
    });
  });
});
