/**
 * A widget reference drawn and edited as one chip (#662): its brackets kept in
 * the code but not drawn, the caret stepping over it in one move, and
 * Backspace or Delete removing it whole. Monaco is not mounted under Jest; the
 * hook is driven through a fake editor that records what it is asked to do.
 */
import { renderHook } from "@testing-library/react";
import {
  CHIP_CLASS,
  CHIP_FIRST_CLASS,
  CHIP_HIDDEN_CLASS,
  CHIP_LAST_CLASS,
  CHIP_PROBLEM_CLASS,
  chipDecorations,
  chipSpans,
  chipToDelete,
  snapPosition,
} from "../../../components/editing/widgets/referenceChips";
import { referenceMarks, useCodeReferences } from "../../../components/editing/widgets/monacoCodeReferences";
import type { ReferenceScope } from "../../../utils/references/codeReferences";
import type { WidgetDef } from "../../../utils/widgets/widgetModel";

const widgets: WidgetDef[] = [{ name: "season", type: "text", default: "summer" }];
const scope: ReferenceScope = { widgets, inputs: [{ slot: 0, columns: ["height"] }], shared: [] };
// "s = " puts the reference at columns 5 to 19, and its name at 9 to 15.
const CODE = "s = [!! season !!]";
const line = (startColumn: number, endColumn: number) => ({
  startLineNumber: 1,
  startColumn,
  endLineNumber: 1,
  endColumn,
});

describe("what a reference is drawn as", () => {
  test("the name in a box; the brackets kept but not drawn", () => {
    const decorations = chipDecorations(referenceMarks(CODE, scope, "python"));
    const byClass = (cls: string) =>
      decorations.filter((d) => d.options.inlineClassName === cls).map((d) => d.range);
    expect(byClass(CHIP_HIDDEN_CLASS)).toEqual([line(5, 9), line(15, 19)]);
    expect(byClass(CHIP_CLASS)).toEqual([line(9, 15)]);
    expect(byClass(CHIP_FIRST_CLASS)).toEqual([line(9, 10)]);
    expect(byClass(CHIP_LAST_CLASS)).toEqual([line(14, 15)]);
    expect(decorations.find((d) => d.options.inlineClassName === CHIP_CLASS)?.options.hoverMessage).toEqual({
      value: 'season = "summer"',
    });
  });

  test("every decoration takes the line off Monaco's fixed-width path", () => {
    for (const d of chipDecorations(referenceMarks(CODE, scope, "python"))) {
      expect(d.options.inlineClassNameAffectsLetterSpacing).toBe(true);
    }
  });

  test("a reference with a problem is drawn whole, in a red box, with nothing hidden", () => {
    const decorations = chipDecorations(referenceMarks("[!! missing !!]", scope, "python"));
    const classes = decorations.map((d) => d.options.inlineClassName);
    expect(classes).not.toContain(CHIP_HIDDEN_CLASS);
    expect(decorations.find((d) => d.options.inlineClassName === CHIP_PROBLEM_CLASS)?.range).toEqual(line(1, 16));
  });

  test("a reference broken over two lines is drawn whole", () => {
    const [mark] = referenceMarks("[!!\nseason !!]", scope, "python");
    expect(mark.nameRange).toBeNull();
    const classes = chipDecorations([mark]).map((d) => d.options.inlineClassName);
    expect(classes).not.toContain(CHIP_HIDDEN_CLASS);
    expect(classes).toContain(CHIP_CLASS);
    expect(chipSpans([mark])).toEqual([]);
  });

  test("the name's range skips however many spaces stand before it", () => {
    const [mark] = referenceMarks("[!!   season!!]", scope, "python");
    expect(mark.nameRange).toEqual(line(7, 13));
  });

  test("an input or column chip is the same box with the input class beside the chip's", () => {
    // "c = [!! input 0.height !!]": the reference spans 5 to 27, its name 9 to 23.
    const decorations = chipDecorations(referenceMarks("c = [!! input 0.height !!]", scope, "python"));
    const box = decorations.find((d) => String(d.options.inlineClassName).split(" ")[0] === CHIP_CLASS);
    expect(box?.options.inlineClassName).toBe(`${CHIP_CLASS} curio-input-ref`);
    expect(box?.range).toEqual(line(9, 23));
    expect(decorations.filter((d) => d.options.inlineClassName === CHIP_HIDDEN_CLASS).map((d) => d.range)).toEqual([
      line(5, 9),
      line(23, 27),
    ]);
    const [problem] = referenceMarks("[!! input 4 !!]", scope, "python");
    expect(problem.problem).not.toBeNull();
    expect(chipDecorations([problem]).map((d) => d.options.inlineClassName)).toContain(
      `${CHIP_PROBLEM_CLASS} curio-input-ref-problem`,
    );
  });
});

describe("the caret steps over a chip", () => {
  const spans = chipSpans(referenceMarks(CODE, scope, "python"));

  test("one step right from its start lands at its end, and back", () => {
    expect(snapPosition(spans, { lineNumber: 1, column: 6 }, { lineNumber: 1, column: 5 })).toEqual({
      lineNumber: 1,
      column: 19,
    });
    expect(snapPosition(spans, { lineNumber: 1, column: 18 }, { lineNumber: 1, column: 19 })).toEqual({
      lineNumber: 1,
      column: 5,
    });
  });

  test("a click inside goes to the nearer edge", () => {
    expect(snapPosition(spans, { lineNumber: 1, column: 7 }, { lineNumber: 3, column: 1 })).toEqual({
      lineNumber: 1,
      column: 5,
    });
    expect(snapPosition(spans, { lineNumber: 1, column: 16 }, null)).toEqual({ lineNumber: 1, column: 19 });
  });

  test("its edges and the rest of the line are left alone", () => {
    expect(snapPosition(spans, { lineNumber: 1, column: 5 }, null)).toBeNull();
    expect(snapPosition(spans, { lineNumber: 1, column: 19 }, null)).toBeNull();
    expect(snapPosition(spans, { lineNumber: 1, column: 2 }, null)).toBeNull();
  });

  test("a reference with a problem can be edited inside", () => {
    expect(chipSpans(referenceMarks("[!! missing !!]", scope, "python"))).toEqual([]);
  });
});

describe("Backspace and Delete remove a chip whole", () => {
  const spans = chipSpans(referenceMarks(CODE, scope, "python"));

  test("Backspace right after it, Delete right before it", () => {
    expect(chipToDelete(spans, { lineNumber: 1, column: 19 }, "Backspace")).toEqual({
      lineNumber: 1,
      startColumn: 5,
      endColumn: 19,
    });
    expect(chipToDelete(spans, { lineNumber: 1, column: 5 }, "Delete")).toEqual({
      lineNumber: 1,
      startColumn: 5,
      endColumn: 19,
    });
  });

  test("anywhere else they do what they always do", () => {
    expect(chipToDelete(spans, { lineNumber: 1, column: 5 }, "Backspace")).toBeNull();
    expect(chipToDelete(spans, { lineNumber: 1, column: 19 }, "Delete")).toBeNull();
    expect(chipToDelete(spans, { lineNumber: 1, column: 3 }, "Backspace")).toBeNull();
  });
});

describe("the editor wiring", () => {
  function fakeEditor(code: string) {
    const handlers: Record<string, (event: any) => void> = {};
    const subscription = (name: string) => (fn: (event: any) => void) => {
      handlers[name] = fn;
      return { dispose: jest.fn() };
    };
    let position = { lineNumber: 1, column: 1 };
    const collection = { set: jest.fn(), clear: jest.fn() };
    const editor = {
      handlers,
      collection,
      createDecorationsCollection: jest.fn(() => collection),
      getModel: () => ({ getValue: () => code }),
      onDidChangeModelContent: subscription("content"),
      onDidChangeCursorPosition: subscription("cursor"),
      onKeyDown: subscription("key"),
      getPosition: () => position,
      setPosition: jest.fn((p: typeof position) => {
        position = p;
      }),
      moveTo: (p: typeof position) => {
        position = p;
      },
      getSelection: () => ({ isEmpty: () => true }),
      setSelection: jest.fn(),
      executeEdits: jest.fn(),
      pushUndoStop: jest.fn(),
      getDomNode: () => null,
    };
    return editor;
  }

  const keyEvent = (key: string) => ({
    browserEvent: { key },
    preventDefault: jest.fn(),
    stopPropagation: jest.fn(),
  });

  test("the chips are drawn when the hook mounts", () => {
    const editor = fakeEditor(CODE);
    renderHook(() => useCodeReferences(editor, undefined, scope, "python"));
    expect(editor.collection.set).toHaveBeenCalledWith(chipDecorations(referenceMarks(CODE, scope, "python")));
  });

  test("a caret that lands inside a chip is moved past it", () => {
    const editor = fakeEditor(CODE);
    editor.moveTo({ lineNumber: 1, column: 5 });
    renderHook(() => useCodeReferences(editor, undefined, scope, "python"));
    editor.handlers.cursor({ position: { lineNumber: 1, column: 6 } });
    expect(editor.setPosition).toHaveBeenCalledWith({ lineNumber: 1, column: 19 });
  });

  test("Backspace after a chip removes the reference in one undoable edit", () => {
    const editor = fakeEditor(CODE);
    editor.moveTo({ lineNumber: 1, column: 19 });
    renderHook(() => useCodeReferences(editor, undefined, scope, "python"));
    const event = keyEvent("Backspace");
    editor.handlers.key(event);
    expect(event.preventDefault).toHaveBeenCalled();
    expect(editor.executeEdits).toHaveBeenCalledWith("curio-widget-ref", [{ range: line(5, 19), text: "" }]);
    expect(editor.pushUndoStop).toHaveBeenCalledTimes(2);
  });

  test("Backspace elsewhere is left to the editor", () => {
    const editor = fakeEditor(CODE);
    editor.moveTo({ lineNumber: 1, column: 3 });
    renderHook(() => useCodeReferences(editor, undefined, scope, "python"));
    const event = keyEvent("Backspace");
    editor.handlers.key(event);
    expect(event.preventDefault).not.toHaveBeenCalled();
    expect(editor.executeEdits).not.toHaveBeenCalled();
  });
});
