/**
 * A chip's preview in the one Curio tooltip (#662): a header tag's hover and
 * the hover of its chip in the editor show one ChipPreview, through the
 * TooltipLayer, from the node's preview source (chipPreviewSource). What the
 * chip shows is read only when its tooltip shows: a pointer that passes over
 * a tag reads nothing, and the open tooltip follows the read as it comes back,
 * placed again as it grows, so it never covers the chip it describes.
 *
 * Example 26's join: its input_1 is Summarize's tuple. Monaco is not mounted
 * under Jest: the editor hook is driven through a fake editor that hands its
 * listeners to the test, as useEditorTooltip.test.tsx does.
 */
const mockFetchPreviewData = jest.fn();
jest.mock("../../../services/api", () => ({
  fetchData: jest.fn(),
  fetchPreviewData: (...args: any[]) => mockFetchPreviewData(...args),
}));

import React, { useMemo, useState } from "react";
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { TooltipLayer } from "../../../components/tooltip/TooltipLayer";
import { resetTooltipStore } from "../../../components/tooltip/tooltipStore";
import { useEditorTooltip } from "../../../components/editing/useEditorTooltip";
import { ReferenceStrip } from "../../../components/editing/widgets/WidgetTag";
import { TAG_HOW, type ChipPreviewData } from "../../../components/editing/widgets/ChipPreview";
import { useChipPreviewSource } from "../../../components/editing/widgets/chipPreviewSource";
import { closeEveryCategory } from "../../../components/editing/widgets/stripCategories";
import type { InputScope, ReferenceScope } from "../../../utils/references/codeReferences";
import { readInputPreview, type InputPreview, type InputSource } from "../../../utils/references/inputScope";
import { SUMMARY_REF, SUMMARY_TUPLE } from "../../_support/chipPreviewFixtures";

/** The layer may place a tooltip in the animation frame after it decides to show it. */
const FRAME = 16;
/** A mouse's pointer events, as the layer hears them. */
const MOUSE = { pointerType: "mouse", isPrimary: true, pointerId: 1, buttons: 0 };
/** Monaco's `editor.MouseTargetType.CONTENT_TEXT`. */
const CONTENT_TEXT = 6;

const JOIN_INPUTS: InputScope[] = [
  { slot: 0, edge: "e0", label: "Data Loading", dataType: "geodataframe" },
  { slot: 1, edge: "e1", label: "Python Computation", dataType: "outputs", columns: [], dtypes: {}, layers: [], tuple: 2 },
  { slot: 2, edge: "e2", label: "Data Loading", dataType: "geodataframe" },
];
const SCOPE: ReferenceScope = { widgets: [], inputs: JOIN_INPUTS };
const SUMMARY: InputSource = { title: "Summarize", type: "Python Computation", status: "done" };
/** The join's line that unpacks the tuple: its chip runs from column 16 to 31. */
const CODE = "means, peaks = [!! input_1 !!]\n";

let tuplePreview: InputPreview;

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

/** Run the clock *ms* on, then whatever that started. */
async function advance(ms: number) {
  await act(async () => {
    jest.advanceTimersByTime(ms);
    for (let i = 0; i < 20; i += 1) await Promise.resolve();
  });
}

/** Where the mouse is. */
let at: Element = document.body;

/** The mouse moves from where it is onto *el*. */
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

/** A mounted editor over *code*: each `on...` event keeps its listener for `emit`. */
function fakeEditor(code: string) {
  const lines = code.split("\n");
  const model = {
    uri: { toString: () => "inmemory://model/1" },
    getValue: () => code,
    getLineCount: () => lines.length,
    getLineContent: (lineNumber: number) => lines[lineNumber - 1] ?? "",
    getWordAtPosition: () => null,
  };
  const dom = document.createElement("div");
  document.body.appendChild(dom);
  const listeners: Record<string, Array<(event: unknown) => void>> = {};
  const known: Record<string, unknown> = {
    getModel: () => model,
    getDomNode: () => dom,
    getPosition: () => ({ lineNumber: 1, column: 1 }),
  };
  const editor = new Proxy(known, {
    get(target, prop) {
      if (typeof prop !== "string" || prop === "then") return undefined;
      if (prop in target) return target[prop];
      if (/^on[A-Z]/.test(prop)) {
        return (listener: (event: unknown) => void) => {
          (listeners[prop] ??= []).push(listener);
          return { dispose: () => undefined };
        };
      }
      return () => ({ dispose() {} });
    },
  });
  const emit = (name: string, event: unknown) => act(() => (listeners[name] ?? []).forEach((l) => l(event)));
  return { editor, dom, emit };
}

/** The mouse over a span of the editor's text drawn at *left*, *top*, at *column* of line 1. */
function overChip(dom: HTMLElement, left: number, top: number, column: number) {
  const span = document.createElement("span");
  span.getBoundingClientRect = () =>
    ({ left, top, width: 56, height: 18, right: left + 56, bottom: top + 18, x: left, y: top, toJSON: () => ({}) }) as DOMRect;
  dom.appendChild(span);
  return { target: { type: CONTENT_TEXT, element: span, position: { lineNumber: 1, column } } };
}

/** `monaco` with *markers* on the model. */
function fakeMonaco(markers: Array<{ message: string; startLineNumber: number; startColumn: number; endLineNumber: number; endColumn: number }> = []) {
  return { editor: { MouseTargetType: { CONTENT_TEXT }, getModelMarkers: () => markers } };
}

type Observed = { targets: Set<Element>; callback: ResizeObserverCallback; observer: unknown };

/**
 * The browser's ResizeObserver, which jsdom lacks, until `uninstall`: each
 * observer keeps what it observes, and `report(el)` tells those observing *el*
 * that its size changed, as the browser does after a layout.
 */
function installResizeObserver() {
  const observing = new Set<Observed>();
  class FakeResizeObserver {
    private readonly observed: Observed;
    constructor(callback: ResizeObserverCallback) {
      this.observed = { targets: new Set(), callback, observer: this };
      observing.add(this.observed);
    }
    observe(target: Element) {
      this.observed.targets.add(target);
    }
    unobserve(target: Element) {
      this.observed.targets.delete(target);
    }
    disconnect() {
      observing.delete(this.observed);
    }
  }
  const scope = window as unknown as { ResizeObserver?: unknown };
  const before = scope.ResizeObserver;
  scope.ResizeObserver = FakeResizeObserver;
  return {
    report(target: Element) {
      act(() => {
        for (const { targets, callback, observer } of [...observing]) {
          if (targets.has(target)) callback([{ target } as unknown as ResizeObserverEntry], observer as ResizeObserver);
        }
      });
    },
    uninstall() {
      if (before === undefined) delete scope.ResizeObserver;
      else scope.ResizeObserver = before;
    },
  };
}

/** What the test reads and changes: the node's data, as a run or a read coming back changes it. */
const controls: { data: ChipPreviewData; setData: (data: ChipPreviewData) => void } = {
  data: {},
  setData: () => undefined,
};

/** The join's header and its code's hover, from one preview source whose
 * reads go to *load*. */
function Join({
  editor,
  monaco,
  load,
  initial,
}: {
  editor: unknown;
  monaco: unknown;
  load: (inner: string) => void;
  initial: ChipPreviewData;
}) {
  const [data, setData] = useState<ChipPreviewData>(initial);
  controls.setData = setData;
  controls.data = data;
  const snapshot = useMemo(() => ({ scope: SCOPE, language: "python" as const, data }), [data]);
  const source = useChipPreviewSource(snapshot, load);
  useEditorTooltip(editor, monaco, SCOPE, "python", source);
  return (
    <ReferenceStrip
      nodeId="several-join"
      widgets={[]}
      inputs={JOIN_INPUTS}
      language="python"
      onInsert={() => undefined}
      previews={source}
    />
  );
}

function mount(
  monaco: unknown,
  { initial = { inputs: { 1: { source: SUMMARY } } }, onLoad }: { initial?: ChipPreviewData; onLoad?: (inner: string) => void } = {},
) {
  const { editor, dom, emit } = fakeEditor(CODE);
  const loads: string[] = [];
  const load = (inner: string) => {
    loads.push(inner);
    onLoad?.(inner);
  };
  render(
    <>
      <TooltipLayer />
      <Join editor={editor} monaco={monaco} load={load} initial={initial} />
    </>,
  );
  // Inputs open, so the input tags show.
  fireEvent.click(document.querySelector('[data-strip-category="inputs"]') as Element);
  const tag = document.querySelector('[data-input-tag="1"]') as HTMLElement;
  expect(tag).not.toBeNull();
  return { dom, emit, loads, tag };
}

beforeAll(async () => {
  mockFetchPreviewData.mockResolvedValue(SUMMARY_TUPLE);
  tuplePreview = await readInputPreview(SUMMARY_REF);
});

describe("a chip's preview in the one Curio tooltip", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    resetTooltipStore();
    // The header opens as it does on a page just loaded: every category closed.
    closeEveryCategory();
    at = document.body;
  });

  afterEach(async () => {
    fireEvent.keyDown(document.body, { key: "Escape", code: "Escape" });
    await advance(1000);
    cleanup();
    jest.useRealTimers();
    document.body.innerHTML = "";
  });

  test("the header tag and the chip in the code show one preview, read only once the tooltip shows", async () => {
    const { dom, emit, loads, tag } = mount(fakeMonaco());

    // A pointer that passes over the tag shows nothing, and reads nothing.
    moveTo(tag);
    await advance(200);
    moveTo(document.body);
    await advance(1000);
    expect(shown()).toHaveLength(0);
    expect(loads).toEqual([]);

    // Resting on it shows its preview, which asks for input_1's read as it shows.
    moveTo(tag);
    await advance(399);
    expect(loads).toEqual([]);
    await advance(1 + FRAME);
    expect(said()).toContain("Reading input_1...");
    expect(loads).toEqual(["input_1"]);

    // The read comes back: the open tooltip shows the tuple. It asks again as
    // its input changes, which reads nothing once the read is kept.
    act(() => controls.setData({ inputs: { 1: { source: SUMMARY, preview: tuplePreview } } }));
    await advance(FRAME);
    expect(loads).toEqual(["input_1", "input_1"]);
    const tagText = said();
    expect(tagText).toContain("input_1 from Summarize · a Python Computation node");
    expect(tagText).toContain("A tuple of 2 values. Read them in code as input_1[0] and input_1[1].");
    expect(tagText).toContain("8.0417");
    expect(tagText.endsWith(TAG_HOW)).toBe(true);

    // The chip in the code: the same preview, without the tag's last line.
    moveTo(document.body);
    await advance(1000);
    expect(shown()).toHaveLength(0);
    emit("onMouseMove", overChip(dom, 120, 200, 21));
    await advance(399);
    expect(shown()).toHaveLength(0);
    await advance(1 + FRAME);
    expect(said()).toBe(tagText.slice(0, -TAG_HOW.length).trim());
    expect(shown()[0].querySelector('[data-chip-preview="input"]')).not.toBeNull();
    expect(loads).toEqual(["input_1", "input_1", "input_1"]);
  });

  test("the pointer going straight from the tag to its chip in the code gets the chip's preview, which stays", async () => {
    const { dom, emit, tag } = mount(fakeMonaco(), {
      initial: { inputs: { 1: { source: SUMMARY, preview: tuplePreview } } },
    });
    moveTo(tag);
    await advance(400 + FRAME);
    expect(said().endsWith(TAG_HOW)).toBe(true);

    // Onto the chip within the 100 ms the tag's tooltip waits before it hides.
    const chip = overChip(dom, 120, 200, 21);
    moveTo(chip.target.element);
    emit("onMouseMove", chip);
    await advance(50);
    expect(said()).toContain("A tuple of 2 values");
    expect(said()).not.toContain(TAG_HOW);

    // The tag's pending hide does not close it: it stays while the pointer rests on the chip.
    await advance(1000);
    expect(shown()).toHaveLength(1);
    expect(said()).toContain("A tuple of 2 values");
    expect(said()).not.toContain(TAG_HOW);
  });

  test("a chip's open tooltip reads its input once a value arrives, then shows its rows", async () => {
    let reads = 0;
    const notRun: InputSource = { ...SUMMARY, status: "not-run" };
    const { dom, emit } = mount(fakeMonaco(), {
      initial: { inputs: { 1: { source: notRun } } },
      // As useInputScope's loadPreview: a value not read yet is read once.
      onLoad: () => {
        const held = controls.data.inputs?.[1];
        if (!held || held.source.status === "not-run" || held.preview) return;
        reads += 1;
        void Promise.resolve().then(() =>
          controls.setData({ inputs: { 1: { source: held.source, preview: tuplePreview } } }),
        );
      },
    });
    emit("onMouseMove", overChip(dom, 120, 200, 21));
    await advance(400 + FRAME);
    expect(said()).toContain("Not run yet. Run Summarize to see its rows.");
    expect(reads).toBe(0);

    // Summarize runs, and input_1 holds a value under the open tooltip.
    act(() => controls.setData({ inputs: { 1: { source: SUMMARY } } }));
    expect(reads).toBe(1);
    await advance(FRAME);
    expect(said()).toContain("A tuple of 2 values");
    expect(said()).toContain("8.0417");
    expect(reads).toBe(1);
  });

  test("an editor chip's open tooltip that grows as its read comes back is placed again above the chip, and stays open", async () => {
    // jsdom lays nothing out. The card is 300 px wide: 60 px tall while it
    // reads, 220 px once it holds the tuple's rows.
    const original = Element.prototype.getBoundingClientRect;
    const measure = jest.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      if (this.getAttribute("role") !== "tooltip") return original.call(this);
      const card = this as HTMLElement;
      const left = parseFloat(card.style.left) || 0;
      const top = parseFloat(card.style.top) || 0;
      const height = (card.textContent ?? "").includes("A tuple of 2 values") ? 220 : 60;
      return { left, top, width: 300, height, right: left + 300, bottom: top + height, x: left, y: top, toJSON: () => ({}) } as DOMRect;
    });
    const resize = installResizeObserver();
    try {
      const { dom, emit } = mount(fakeMonaco());
      emit("onMouseMove", overChip(dom, 320, 400, 21));
      await advance(400 + FRAME);
      expect(said()).toContain("Reading input_1...");
      // Centered over the chip, 320 to 376 px across, its foot 6 px above it.
      const card = shown()[0];
      expect([card.style.left, card.style.top]).toEqual(["198px", "334px"]);

      // The read comes back under the pointer that rests on the chip, and the
      // card grows by the tuple's rows; the browser reports its new size.
      act(() => controls.setData({ inputs: { 1: { source: SUMMARY, preview: tuplePreview } } }));
      await advance(FRAME);
      expect(said()).toContain("A tuple of 2 values");
      resize.report(card);
      await advance(FRAME);
      // Placed again, all of it above the chip. Grown down from where it was,
      // it would cover the chip and the pointer, which would leave the editor
      // for the card, and the editor would hide its tooltip.
      expect([card.style.left, card.style.top]).toEqual(["198px", "174px"]);
      expect(card.dataset.placement).toBe("top");

      await advance(1000);
      expect(shown()).toHaveLength(1);
      expect(shown()[0]).toBe(card);
    } finally {
      resize.uninstall();
      measure.mockRestore();
    }
  });

  test("an editor chip's preview comes after the messages of the markers on it", async () => {
    const message = "Expected a comma.";
    const { dom, emit, loads } = mount(
      fakeMonaco([{ message, startLineNumber: 1, startColumn: 16, endLineNumber: 1, endColumn: 31 }]),
    );
    emit("onMouseMove", overChip(dom, 120, 200, 21));
    await advance(400 + FRAME);
    const tip = shown()[0];
    const parts = Array.from(tip.querySelectorAll("[data-preview-message], [data-chip-preview]"));
    expect(parts.map((part) => (part.hasAttribute("data-preview-message") ? "message" : "preview"))).toEqual([
      "message",
      "preview",
    ]);
    expect(said().startsWith(message)).toBe(true);
    expect(said()).toContain("Reading input_1...");
    expect(loads).toEqual(["input_1"]);
  });
});
