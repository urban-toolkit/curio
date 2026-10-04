/**
 * References inside Monaco (#662): where a dropped or clicked tag lands, what
 * each chip covers and says, and which JSON errors a reference accounts for.
 * Monaco itself is not mounted under Jest; these are the pure helpers the
 * editors wire to it.
 */
import {
  INPUT_REF_MIME,
  WIDGET_REF_MIME,
  chipClass,
  dropReference,
  insertReference,
  isReferenceDrag,
  markersOutsideReferences,
  offsetToPosition,
  referenceMarks,
} from "../../../components/editing/widgets/monacoCodeReferences";
import { referenceText, type ReferenceScope } from "../../../utils/references/codeReferences";
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
const scope: ReferenceScope = { widgets, inputs: [], shared: [] };
const withInputs: ReferenceScope = {
  widgets,
  inputs: [
    { slot: 0, label: "Roads", dataType: "geodataframe", columns: ["length"], dtypes: { length: "float64" } },
    { slot: 1, label: "Parcels" },
  ],
  shared: [],
};

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
    expect(isReferenceDrag(event)).toBe(true);
    expect(dropReference(editor, event)).toBe(true);
    expect(editor.getTargetAtClientPoint).toHaveBeenCalledWith(10, 20);
    expect(editor.executeEdits.mock.calls[0][1][0].range).toEqual({
      startLineNumber: 7,
      startColumn: 3,
      endLineNumber: 7,
      endColumn: 3,
    });
  });

  test("an input or column tag drops its own reference", () => {
    const editor = fakeEditor();
    const event = {
      clientX: 1,
      clientY: 2,
      dataTransfer: { types: [INPUT_REF_MIME], getData: (t: string) => (t === INPUT_REF_MIME ? "input 1.area" : "") },
    } as unknown as DragEvent;
    expect(isReferenceDrag(event)).toBe(true);
    expect(dropReference(editor, event)).toBe(true);
    expect(editor.executeEdits.mock.calls[0][1][0].text).toBe("[!! input 1.area !!]");
  });

  test("other drags are left alone", () => {
    const event = { dataTransfer: { types: ["text/plain"] } } as unknown as DragEvent;
    expect(isReferenceDrag(event)).toBe(false);
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
    const [mark] = referenceMarks('x = 1\ns = [!! season !!]', scope, "python");
    expect(mark.range).toEqual({ startLineNumber: 2, startColumn: 5, endLineNumber: 2, endColumn: 19 });
    expect(mark.problem).toBeNull();
    expect(mark.hover).toBe('season = "winter"');
    expect(chipClass(mark)).toBe("curio-widget-ref");
  });

  test("a chip for a name the node does not have says so", () => {
    const [mark] = referenceMarks("[!! missing !!]", scope, "python");
    expect(mark.problem).toMatch(/no widget named missing/);
    expect(mark.hover).toBe(mark.problem);
    expect(chipClass(mark)).toBe("curio-widget-ref-problem");
  });

  test("an input chip names the node that feeds it", () => {
    const [input, column] = referenceMarks("a = [!! input 0 !!]\nb = [!! input 0.length !!]", withInputs, "python");
    expect(input.kind).toBe("input");
    expect(input.hover).toBe("input 0, from Roads (geodataframe)");
    expect(chipClass(input)).toBe("curio-input-ref");
    expect(column.hover).toBe("column length of input 0, from Roads (float64)");
  });

  test("an input chip with no edge, or for a column the input lacks, is a problem chip", () => {
    const [missing, column] = referenceMarks("[!! input 4 !!] [!! input 0.width !!]", withInputs, "python");
    expect(missing.problem).toMatch(/input 4 has no edge/);
    expect(chipClass(missing)).toBe("curio-input-ref-problem");
    expect(column.problem).toMatch(/input 0 has no column width/);
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
