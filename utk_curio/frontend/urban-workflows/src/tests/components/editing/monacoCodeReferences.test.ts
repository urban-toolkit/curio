/**
 * Widget references inside Monaco (#662): where a dropped or clicked tag lands,
 * what each chip covers and says, and which JSON errors a reference accounts
 * for. Monaco itself is not mounted under Jest; these are the pure helpers the
 * editors wire to it.
 */
import {
  WIDGET_REF_MIME,
  dropReference,
  insertReference,
  isWidgetDrag,
  markersOutsideReferences,
  offsetToPosition,
  referenceMarks,
  referenceText,
} from "../../../components/editing/widgets/monacoWidgetRefs";
import type { WidgetDef } from "../../../utils/widgets/widgetModel";

function fakeEditor(position: { lineNumber: number; column: number } | null = { lineNumber: 2, column: 5 }) {
  return {
    executeEdits: jest.fn(),
    focus: jest.fn(),
    getPosition: jest.fn(() => position),
    getTargetAtClientPoint: jest.fn(() => ({ position: { lineNumber: 7, column: 3 } })),
  };
}

const widgets: WidgetDef[] = [{ name: "season", type: "text", default: "summer", value: "winter" }];

describe("inserting a reference", () => {
  test("a click inserts at the cursor", () => {
    const editor = fakeEditor();
    expect(insertReference(editor, "season")).toBe(true);
    expect(editor.executeEdits).toHaveBeenCalledWith("curio-widget-tag", [
      expect.objectContaining({
        text: "[!! season !!]",
        range: { startLineNumber: 2, startColumn: 5, endLineNumber: 2, endColumn: 5 },
      }),
    ]);
    expect(editor.focus).toHaveBeenCalled();
  });

  test("nothing happens without an editor or a position", () => {
    expect(insertReference(undefined, "season")).toBe(false);
    expect(insertReference(fakeEditor(null), "season")).toBe(false);
  });

  test("a drop inserts where it lands, not at the cursor", () => {
    const editor = fakeEditor();
    const event = {
      clientX: 10,
      clientY: 20,
      dataTransfer: { types: [WIDGET_REF_MIME], getData: (t: string) => (t === WIDGET_REF_MIME ? "season" : "") },
    } as unknown as DragEvent;
    expect(isWidgetDrag(event)).toBe(true);
    expect(dropReference(editor, event)).toBe(true);
    expect(editor.getTargetAtClientPoint).toHaveBeenCalledWith(10, 20);
    expect(editor.executeEdits.mock.calls[0][1][0].range).toEqual({
      startLineNumber: 7,
      startColumn: 3,
      endLineNumber: 7,
      endColumn: 3,
    });
  });

  test("other drags are left alone", () => {
    const event = { dataTransfer: { types: ["text/plain"] } } as unknown as DragEvent;
    expect(isWidgetDrag(event)).toBe(false);
  });

  test("the reference text", () => {
    expect(referenceText("n")).toBe("[!! n !!]");
  });
});

describe("chips", () => {
  test("offsets become 1-based lines and columns", () => {
    expect(offsetToPosition("ab\ncd", 0)).toEqual({ lineNumber: 1, column: 1 });
    expect(offsetToPosition("ab\ncd", 4)).toEqual({ lineNumber: 2, column: 2 });
  });

  test("a chip covers its reference and shows the value", () => {
    const [mark] = referenceMarks('x = 1\ns = [!! season !!]', widgets, "python");
    expect(mark.range).toEqual({ startLineNumber: 2, startColumn: 5, endLineNumber: 2, endColumn: 19 });
    expect(mark.problem).toBeNull();
    expect(mark.hover).toBe('season = "winter"');
  });

  test("a chip for a name the node does not have says so", () => {
    const [mark] = referenceMarks("[!! missing !!]", widgets, "python");
    expect(mark.problem).toMatch(/no widget named missing/);
    expect(mark.hover).toBe(mark.problem);
  });
});

describe("JSON errors a reference causes", () => {
  const ref = { startLineNumber: 1, startColumn: 13, endLineNumber: 1, endColumn: 27 };
  const marker = (startColumn: number, endColumn: number) => ({
    startLineNumber: 1,
    startColumn,
    endLineNumber: 1,
    endColumn,
  });

  test("errors inside or right after a reference are hidden", () => {
    expect(markersOutsideReferences([marker(14, 15), marker(27, 28)], [ref])).toEqual([]);
  });

  test("errors elsewhere stay", () => {
    const elsewhere = [marker(1, 3), { startLineNumber: 2, startColumn: 1, endLineNumber: 2, endColumn: 4 }];
    expect(markersOutsideReferences(elsewhere, [ref])).toEqual(elsewhere);
  });
});
