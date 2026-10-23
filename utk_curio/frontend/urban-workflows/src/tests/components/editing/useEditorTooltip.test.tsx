/**
 * A Monaco editor's hovers in the one Curio tooltip. Monaco draws its own
 * inside the node, so the canvas's zoom scales them and the card clips them;
 * both editors turn it off, and one hook on the editor's mouse moves shows in
 * the Curio tooltip what Monaco showed there, anchored to the hovered span:
 * a chip's text, the messages of the markers at that place (the credential
 * warning, a JSON error), and in a JavaScript node the type information
 * TypeScript's worker gives, as Monaco's own hover showed it.
 *
 * A pointer that rests on a chip sends no new move, so what the editor does
 * meanwhile must not lose the chip's tooltip: a scroll that moves no text,
 * and a redraw of the chip's line, which replaces the span under the pointer.
 *
 * Monaco is not mounted under Jest: the hook is driven through a fake editor
 * that hands its listeners to the test, as referenceChips.test.ts does, and a
 * fake `monaco` with the markers and the worker each case needs.
 */
import React from "react";
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { TooltipLayer } from "../../../components/tooltip/TooltipLayer";
import { resetTooltipStore } from "../../../components/tooltip/tooltipStore";
import { useEditorTooltip } from "../../../components/editing/useEditorTooltip";
import type { CodeLanguage, ReferenceScope } from "../../../utils/references/codeReferences";
import type { WidgetDef } from "../../../utils/widgets/widgetModel";

/** The layer may place a tooltip in the animation frame after it decides to show it. */
const FRAME = 16;

/** A mouse's pointer events, as the layer hears them. */
const MOUSE = { pointerType: "mouse", isPrimary: true, pointerId: 1 };

/** Monaco's `editor.MouseTargetType`, as its typings number it. */
const MOUSE_TARGET_TYPE = {
  UNKNOWN: 0,
  TEXTAREA: 1,
  GUTTER_GLYPH_MARGIN: 2,
  GUTTER_LINE_NUMBERS: 3,
  GUTTER_LINE_DECORATIONS: 4,
  GUTTER_VIEW_ZONE: 5,
  CONTENT_TEXT: 6,
  CONTENT_EMPTY: 7,
  CONTENT_VIEW_ZONE: 8,
  CONTENT_WIDGET: 9,
  OVERVIEW_RULER: 10,
  SCROLLBAR: 11,
  OVERLAY_WIDGET: 12,
  OUTSIDE_EDITOR: 13,
};

const widgets: WidgetDef[] = [{ name: "season", type: "text", default: "summer" }];
const scope: ReferenceScope = { widgets, inputs: [{ slot: 0, columns: ["height"] }], shared: [] };

type Listener = (event: unknown) => void;
type Position = { lineNumber: number; column: number };

/** The tooltips on screen. */
function shown(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>('[role="tooltip"]')).filter(
    (tip) => !tip.hidden && tip.getAttribute("aria-hidden") !== "true",
  );
}

/** What the one tooltip on screen says, its white space run together. */
function said(): string {
  const tips = shown();
  expect(tips.length).toBeLessThanOrEqual(1);
  return (tips[0]?.textContent ?? "").replace(/\s+/g, " ").trim();
}

/** Run the clock *ms* on, then whatever that started, a worker's answer included. */
async function advance(ms: number) {
  await act(async () => {
    jest.advanceTimersByTime(ms);
    for (let i = 0; i < 20; i += 1) await Promise.resolve();
  });
}

/** A Monaco model over *code*: what the hook may read of one. */
function fakeModel(code: string) {
  const lines = code.split("\n");
  const offsetAt = ({ lineNumber, column }: Position) =>
    lines.slice(0, lineNumber - 1).reduce((n, line) => n + line.length + 1, 0) + column - 1;
  return {
    uri: { scheme: "inmemory", path: "/model/1", toString: () => "inmemory://model/1" },
    getValue: () => code,
    getLineCount: () => lines.length,
    getLineContent: (lineNumber: number) => lines[lineNumber - 1] ?? "",
    getLineMaxColumn: (lineNumber: number) => (lines[lineNumber - 1] ?? "").length + 1,
    getOffsetAt: offsetAt,
    getPositionAt: (offset: number) => {
      let left = offset;
      for (let i = 0; i < lines.length; i += 1) {
        if (left <= lines[i].length) return { lineNumber: i + 1, column: left + 1 };
        left -= lines[i].length + 1;
      }
      return { lineNumber: lines.length, column: lines[lines.length - 1].length + 1 };
    },
    getWordAtPosition: ({ lineNumber, column }: Position) => {
      const line = lines[lineNumber - 1] ?? "";
      for (const match of line.matchAll(/[A-Za-z_$][\w$]*/g)) {
        const startColumn = (match.index ?? 0) + 1;
        const endColumn = startColumn + match[0].length;
        if (column >= startColumn && column <= endColumn) return { word: match[0], startColumn, endColumn };
      }
      return null;
    },
  };
}

/** The editors' own elements, taken off the page after each test. */
const editorNodes: HTMLElement[] = [];

/**
 * Where a fake editor draws its text, from its top left corner, which jsdom
 * puts at the page's: a line every 18 px from 200 px down, a character every
 * 8 px from 56 px across. So "season" in `s = [!! season !!]`, columns 9 to
 * 15, is drawn 120 to 168 px across, as `spanAt(dom, 120, 200, 48)` draws it.
 */
const TEXT_LEFT = 56;
const TEXT_TOP = 200;
const CHAR_WIDTH = 8;
const LINE_HEIGHT = 18;

/**
 * A mounted editor over *code*. Every `on...` event it offers keeps its
 * listener for `emit`; any other call (an action, a command, a key binding)
 * does nothing and returns something disposable.
 */
function fakeEditor(code: string) {
  const model = fakeModel(code);
  const dom = document.createElement("div");
  document.body.appendChild(dom);
  editorNodes.push(dom);
  const listeners: Record<string, Listener[]> = {};
  const known: Record<string, unknown> = {
    getModel: () => model,
    getDomNode: () => dom,
    getValue: () => code,
    getPosition: () => ({ lineNumber: 1, column: 1 }),
    // Monaco's place for a position, from the editor's top left corner.
    getScrolledVisiblePosition: ({ lineNumber, column }: Position) => ({
      left: TEXT_LEFT + (column - 1) * CHAR_WIDTH,
      top: TEXT_TOP + (lineNumber - 1) * LINE_HEIGHT,
      height: LINE_HEIGHT,
    }),
  };
  const editor = new Proxy(known, {
    get(target, prop) {
      if (typeof prop !== "string" || prop === "then") return undefined;
      if (prop in target) return target[prop];
      if (/^on[A-Z]/.test(prop)) {
        return (listener: Listener) => {
          (listeners[prop] ??= []).push(listener);
          return {
            dispose: () => {
              listeners[prop] = (listeners[prop] ?? []).filter((l) => l !== listener);
            },
          };
        };
      }
      return () => ({ dispose() {} });
    },
  });
  const emit = (name: string, event: unknown) => act(() => (listeners[name] ?? []).forEach((l) => l(event)));
  return { editor, model, dom, emit };
}

/** A span of the editor's text, drawn at *left*, *top*. */
function spanAt(dom: HTMLElement, left: number, top: number, width: number): HTMLElement {
  const span = document.createElement("span");
  span.getBoundingClientRect = () =>
    ({ left, top, width, height: 18, right: left + width, bottom: top + 18, x: left, y: top, toJSON: () => ({}) }) as DOMRect;
  dom.appendChild(span);
  return span;
}

/**
 * What `document.elementFromPoint` finds from now on, wherever it is asked:
 * jsdom, which lays nothing out, has no such call.
 */
function underThePointer(element: Element) {
  (document as any).elementFromPoint = jest.fn(() => element);
}

/** The move that brings the mouse onto *span*, its browser event sent to the span. */
function arriveOn(span: HTMLElement, position: Position) {
  const arrival = mouseOver(span, position);
  span.dispatchEvent(arrival.event.browserEvent);
  return arrival;
}

type ScrollChange = "scrollTopChanged" | "scrollLeftChanged" | "scrollWidthChanged" | "scrollHeightChanged";

/**
 * Monaco's IScrollEvent with *changed* set. Monaco sends one whenever its
 * scroll state changes: the text scrolled, or only the size it can scroll,
 * as when it measures its lines' widths again after drawing them.
 */
function scrolled(...changed: ScrollChange[]) {
  const flags = { scrollTopChanged: false, scrollLeftChanged: false, scrollWidthChanged: false, scrollHeightChanged: false };
  for (const flag of changed) flags[flag] = true;
  return {
    scrollTop: flags.scrollTopChanged ? LINE_HEIGHT : 0,
    scrollLeft: flags.scrollLeftChanged ? 3 * CHAR_WIDTH : 0,
    scrollWidth: flags.scrollWidthChanged ? 640 : 600,
    scrollHeight: flags.scrollHeightChanged ? 420 : 400,
    ...flags,
  };
}

/** The mouse over *span*, at *position* of the text: Monaco's IEditorMouseEvent. */
function mouseOver(span: HTMLElement, position: Position) {
  const box = span.getBoundingClientRect();
  const browserEvent = new MouseEvent("mousemove", { clientX: box.left + 2, clientY: box.top + 2 });
  return {
    target: {
      type: MOUSE_TARGET_TYPE.CONTENT_TEXT,
      element: span,
      position,
      mouseColumn: position.column,
      range: { startLineNumber: position.lineNumber, startColumn: position.column, endLineNumber: position.lineNumber, endColumn: position.column },
      detail: undefined,
    },
    event: { browserEvent, posx: box.left + 2, posy: box.top + 2, target: span, leftButton: false, rightButton: false },
  };
}

interface Marker {
  owner: string;
  severity: number;
  message: string;
  startLineNumber: number;
  startColumn: number;
  endLineNumber: number;
  endColumn: number;
}

/** `monaco` with *markers* on the model, and TypeScript's worker answering *quickInfo*. */
function fakeMonaco(markers: Marker[] = [], quickInfo?: unknown) {
  const worker = { getQuickInfoAtPosition: jest.fn(async (_file: string, _offset: number) => quickInfo) };
  const getWorker = jest.fn(async (..._uris: unknown[]) => worker);
  const getJavaScriptWorker = jest.fn(async () => getWorker);
  // Monaco 0.55 moved the TypeScript API to `monaco.typescript`, and keeps the old place too.
  const typescript = { getJavaScriptWorker };
  const monaco = {
    editor: {
      MouseTargetType: MOUSE_TARGET_TYPE,
      getModelMarkers: jest.fn((filter?: { owner?: string }) =>
        markers.filter((marker) => !filter?.owner || marker.owner === filter.owner),
      ),
    },
    typescript,
    languages: { typescript },
    MarkerSeverity: { Hint: 1, Info: 2, Warning: 4, Error: 8 },
  };
  return { monaco, worker, getJavaScriptWorker };
}

function Harness({ editor, monaco, language }: { editor: unknown; monaco: unknown; language: CodeLanguage }) {
  useEditorTooltip(editor as any, monaco as any, scope, language);
  return null;
}

function mount(editor: unknown, monaco: unknown, language: CodeLanguage) {
  return render(
    <>
      <TooltipLayer />
      <Harness editor={editor} monaco={monaco} language={language} />
    </>,
  );
}

describe("an editor's hover, in the Curio tooltip", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    // Each test's fake clock starts again near where an earlier one closed a
    // tooltip: the store starts as a page does, with none warm.
    resetTooltipStore();
  });

  // In this block, so it runs before Testing Library unmounts the page: no
  // tooltip is left open for the next test.
  afterEach(async () => {
    fireEvent.keyDown(document.body, { key: "Escape", code: "Escape" });
    await advance(1000);
    cleanup();
    jest.useRealTimers();
    for (const node of editorNodes.splice(0)) node.remove();
    delete (document as any).elementFromPoint;
  });

  test("a chip under the mouse shows its text, 400 ms after the mouse rests", async () => {
    // "s = [!! season !!]": the chip's name runs from column 9 to 15.
    const { editor, dom, emit } = fakeEditor("s = [!! season !!]\nprint(s)");
    const { monaco, getJavaScriptWorker } = fakeMonaco();
    mount(editor, monaco, "python");
    emit("onMouseMove", mouseOver(spanAt(dom, 120, 200, 48), { lineNumber: 1, column: 11 }));
    await advance(399);
    expect(shown()).toHaveLength(0);
    await advance(1 + FRAME);
    expect(said()).toBe('season = "summer"');
    // Python has no type information to ask TypeScript for.
    expect(getJavaScriptWorker).not.toHaveBeenCalled();
  });

  test("the messages of the markers at the mouse show, and no other marker's", async () => {
    const { editor, dom, emit } = fakeEditor('value = "a literal the scan took for a key"\nprin(value)\n');
    const { monaco } = fakeMonaco([
      {
        owner: "curio-credential",
        severity: 4,
        message: "Looks like an API key, use a connection key (curio_secret) instead.",
        startLineNumber: 1,
        startColumn: 1,
        endLineNumber: 1,
        endColumn: 1e6,
      },
      {
        owner: "python",
        severity: 8,
        message: "String literal is too long",
        startLineNumber: 1,
        startColumn: 7,
        endLineNumber: 1,
        endColumn: 33,
      },
      {
        owner: "python",
        severity: 8,
        message: "Name 'prin' is not defined",
        startLineNumber: 2,
        startColumn: 1,
        endLineNumber: 2,
        endColumn: 6,
      },
    ]);
    mount(editor, monaco, "python");
    emit("onMouseMove", mouseOver(spanAt(dom, 80, 200, 120), { lineNumber: 1, column: 12 }));
    await advance(400 + FRAME);
    expect(said()).toContain("Looks like an API key, use a connection key (curio_secret) instead.");
    expect(said()).toContain("String literal is too long");
    expect(said()).not.toContain("is not defined");
  });

  test("in a JavaScript node, the type information TypeScript's worker gives for what is under the mouse", async () => {
    // "zips" on line 2 runs from offset 37 to 41.
    const { editor, model, dom, emit } = fakeEditor("const zips = [!! input_0 !!];\nreturn zips.features;");
    const { monaco, worker } = fakeMonaco([], {
      kind: "const",
      kindModifiers: "",
      textSpan: { start: 37, length: 4 },
      displayParts: [
        { text: "const", kind: "keyword" },
        { text: " ", kind: "space" },
        { text: "zips", kind: "localName" },
        { text: ":", kind: "punctuation" },
        { text: " ", kind: "space" },
        { text: "any", kind: "keyword" },
      ],
      documentation: [{ text: "The ZIP code polygons.", kind: "text" }],
      tags: [],
    });
    mount(editor, monaco, "javascript");
    emit("onMouseMove", mouseOver(spanAt(dom, 64, 218, 32), { lineNumber: 2, column: 10 }));
    await advance(400 + FRAME);
    await advance(FRAME);
    expect(said()).toContain("const zips: any");
    expect(said()).toContain("The ZIP code polygons.");
    expect(worker.getQuickInfoAtPosition).toHaveBeenCalled();
    const [file, offset] = worker.getQuickInfoAtPosition.mock.calls[0];
    expect(file).toBe(model.uri.toString());
    expect(offset).toBeGreaterThanOrEqual(37);
    expect(offset).toBeLessThanOrEqual(41);
  });

  test("in a JavaScript node, a marker's message and the type information both show, the marker's first", async () => {
    // "featurs" on line 2 runs from column 13 to 20.
    const { editor, dom, emit } = fakeEditor("const zips = [!! input_0 !!];\nreturn zips.featurs;");
    const { monaco } = fakeMonaco(
      [
        {
          owner: "typescript",
          severity: 8,
          message: "Cannot find name 'featurs'.",
          startLineNumber: 2,
          startColumn: 13,
          endLineNumber: 2,
          endColumn: 20,
        },
      ],
      {
        kind: "let",
        kindModifiers: "",
        textSpan: { start: 42, length: 7 },
        displayParts: [{ text: "let featurs: number", kind: "text" }],
        documentation: [],
        tags: [],
      },
    );
    mount(editor, monaco, "javascript");
    emit("onMouseMove", mouseOver(spanAt(dom, 100, 218, 56), { lineNumber: 2, column: 15 }));
    await advance(400 + FRAME);
    await advance(FRAME);
    const text = said();
    expect(text).toContain("Cannot find name 'featurs'.");
    expect(text).toContain("let featurs: number");
    expect(text.indexOf("Cannot find name")).toBeLessThan(text.indexOf("let featurs: number"));
  });

  test("a place with no chip, marker or type information shows nothing", async () => {
    const { editor, dom, emit } = fakeEditor("x = 1\nprint(x)");
    const { monaco } = fakeMonaco();
    mount(editor, monaco, "python");
    emit("onMouseMove", mouseOver(spanAt(dom, 40, 200, 8), { lineNumber: 1, column: 1 }));
    await advance(1000);
    expect(shown()).toHaveLength(0);
  });

  test("leaving the chip, or the editor, hides it", async () => {
    const { editor, dom, emit } = fakeEditor("s = [!! season !!]\nprint(s)");
    const { monaco } = fakeMonaco();
    mount(editor, monaco, "python");
    const chip = spanAt(dom, 120, 200, 48);

    emit("onMouseMove", mouseOver(chip, { lineNumber: 1, column: 11 }));
    await advance(400 + FRAME);
    expect(said()).toBe('season = "summer"');
    // Off the chip, onto plain code.
    emit("onMouseMove", mouseOver(spanAt(dom, 40, 218, 40), { lineNumber: 2, column: 3 }));
    await advance(100 + FRAME);
    expect(shown()).toHaveLength(0);

    emit("onMouseMove", mouseOver(chip, { lineNumber: 1, column: 11 }));
    await advance(400 + FRAME);
    expect(said()).toBe('season = "summer"');
    // Out of the editor.
    emit("onMouseLeave", { target: null, event: { browserEvent: new MouseEvent("mouseleave") } });
    await advance(100 + FRAME);
    expect(shown()).toHaveLength(0);
  });

  test("the mouse may leave the editor for the tooltip, and it hides 100 ms after leaving the tooltip", async () => {
    const { editor, dom, emit } = fakeEditor("s = [!! season !!]\nprint(s)");
    const { monaco } = fakeMonaco();
    mount(editor, monaco, "python");
    emit("onMouseMove", mouseOver(spanAt(dom, 120, 200, 48), { lineNumber: 1, column: 11 }));
    await advance(400 + FRAME);
    expect(said()).toBe('season = "summer"');
    // Up out of the editor, which Monaco reports as a leave, and onto the tooltip.
    emit("onMouseLeave", { target: null, event: { browserEvent: new MouseEvent("mouseleave") } });
    fireEvent.pointerMove(shown()[0], { ...MOUSE, clientX: 140, clientY: 190 });
    await advance(1000);
    expect(said()).toBe('season = "summer"');
    // Off the tooltip, onto the page.
    fireEvent.pointerMove(document.body, { ...MOUSE, clientX: 600, clientY: 600 });
    await advance(99);
    expect(shown()).toHaveLength(1);
    await advance(1);
    expect(shown()).toHaveLength(0);
  });

  test("a change in the size the editor can scroll leaves the chip's tooltip open: no text moved", async () => {
    // A pointer that rests sends no new move, so a tooltip hidden now would
    // not come back while it rests.
    const { editor, dom, emit } = fakeEditor("s = [!! season !!]\nprint(s)");
    const { monaco } = fakeMonaco();
    mount(editor, monaco, "python");
    emit("onMouseMove", mouseOver(spanAt(dom, 120, 200, 48), { lineNumber: 1, column: 11 }));
    await advance(400 + FRAME);
    expect(said()).toBe('season = "summer"');
    // Its lines measured wider, then a taller content: the text stays put.
    emit("onDidScrollChange", scrolled("scrollWidthChanged"));
    emit("onDidScrollChange", scrolled("scrollHeightChanged"));
    await advance(100 + FRAME);
    expect(said()).toBe('season = "summer"');
  });

  test("a scroll of the text hides it at once, down or sideways", async () => {
    const { editor, dom, emit } = fakeEditor("s = [!! season !!]\nprint(s)");
    const { monaco } = fakeMonaco();
    mount(editor, monaco, "python");
    const chip = spanAt(dom, 120, 200, 48);

    emit("onMouseMove", mouseOver(chip, { lineNumber: 1, column: 11 }));
    await advance(400 + FRAME);
    expect(said()).toBe('season = "summer"');
    emit("onDidScrollChange", scrolled("scrollTopChanged", "scrollHeightChanged"));
    await advance(FRAME);
    expect(shown()).toHaveLength(0);

    emit("onMouseMove", mouseOver(chip, { lineNumber: 1, column: 11 }));
    await advance(400 + FRAME);
    expect(said()).toBe('season = "summer"');
    emit("onDidScrollChange", scrolled("scrollLeftChanged"));
    await advance(FRAME);
    expect(shown()).toHaveLength(0);
  });

  test("a chip whose line Monaco draws again before its tooltip shows: the tooltip goes beside the chip all the same", async () => {
    // Monaco draws a line again when its decorations or tokens change, and
    // the span under the pointer is a new one; the pointer sends no move.
    const { editor, dom, emit } = fakeEditor("s = [!! season !!]\nprint(s)");
    const { monaco } = fakeMonaco();
    mount(editor, monaco, "python");
    const first = spanAt(dom, 120, 200, 48);
    emit("onMouseMove", mouseOver(first, { lineNumber: 1, column: 11 }));
    await advance(200);
    first.remove();
    spanAt(dom, 120, 200, 48);
    await advance(200 + FRAME);
    expect(said()).toBe('season = "summer"');
    // Centered over "season", 120 to 168 px across, and 6 px above it; jsdom
    // gives the tooltip no size.
    const tip = shown()[0];
    expect(tip.dataset.placement).toBe("top");
    expect([tip.style.left, tip.style.top]).toEqual(["144px", "194px"]);
  });

  test("a leave Monaco reports as it draws the chip's line again under the resting mouse: the tooltip still shows", async () => {
    // Monaco takes a move whose element is not in the editor for a leave, and
    // its hit test of that move first draws what it holds to draw: the line
    // is drawn again, the move's span leaves the page, and the mouse rests on
    // the new span with no move to come.
    const { editor, dom, emit } = fakeEditor("s = [!! season !!]\nprint(s)");
    const { monaco } = fakeMonaco();
    mount(editor, monaco, "python");
    const first = spanAt(dom, 120, 200, 48);
    const arrival = arriveOn(first, { lineNumber: 1, column: 11 });
    emit("onMouseMove", arrival);
    first.remove();
    underThePointer(spanAt(dom, 120, 200, 48));
    emit("onMouseLeave", { target: null, event: arrival.event });
    await advance(399);
    expect(shown()).toHaveLength(0);
    await advance(1 + FRAME);
    expect(said()).toBe('season = "summer"');
  });

  test("a leave as the chip's line is drawn again, with the mouse no longer over the editor, hides it", async () => {
    const { editor, dom, emit } = fakeEditor("s = [!! season !!]\nprint(s)");
    const { monaco } = fakeMonaco();
    mount(editor, monaco, "python");
    const page = document.createElement("div");
    document.body.appendChild(page);
    editorNodes.push(page);
    const first = spanAt(dom, 120, 200, 48);
    const arrival = arriveOn(first, { lineNumber: 1, column: 11 });
    emit("onMouseMove", arrival);
    first.remove();
    underThePointer(page);
    emit("onMouseLeave", { target: null, event: arrival.event });
    await advance(400 + FRAME);
    expect(shown()).toHaveLength(0);
  });

  test("an editor that has not mounted yet does nothing", async () => {
    expect(() => mount(undefined, undefined, "python")).not.toThrow();
    await advance(1000);
    expect(shown()).toHaveLength(0);
  });
});
