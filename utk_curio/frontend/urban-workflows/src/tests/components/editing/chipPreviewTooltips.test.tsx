/**
 * A chip's preview in the one Curio tooltip (#662): a header tag's hover and
 * the hover of its chip in the editor show one ChipPreview, through the
 * TooltipLayer, from the node's preview source (chipPreviewSource). What the
 * chip shows is read only when its tooltip shows: a pointer that passes over
 * a tag reads nothing, and the open tooltip follows the read as it comes back.
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
const SCOPE: ReferenceScope = { widgets: [], inputs: JOIN_INPUTS, shared: [] };
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

/** What the test changes: the node's data, as a read coming back changes it. */
const controls: { setData: (data: ChipPreviewData) => void } = { setData: () => undefined };

/** The join's header and its code's hover, from one preview source whose
 * reads go to *load*. */
function Join({ editor, monaco, load }: { editor: unknown; monaco: unknown; load: (inner: string) => void }) {
  const [data, setData] = useState<ChipPreviewData>({ inputs: { 1: { source: SUMMARY } } });
  controls.setData = setData;
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

function mount(monaco: unknown) {
  const { editor, dom, emit } = fakeEditor(CODE);
  const loads: string[] = [];
  render(
    <>
      <TooltipLayer />
      <Join editor={editor} monaco={monaco} load={(inner) => loads.push(inner)} />
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

    // The read comes back: the open tooltip shows the tuple.
    act(() => controls.setData({ inputs: { 1: { source: SUMMARY, preview: tuplePreview } } }));
    await advance(FRAME);
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
    expect(loads).toEqual(["input_1", "input_1"]);
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
