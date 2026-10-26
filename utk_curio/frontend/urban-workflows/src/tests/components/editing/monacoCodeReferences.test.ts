/**
 * References inside Monaco (#662): where a dropped or clicked tag lands, what
 * each chip covers and says, and which JSON errors a reference accounts for.
 * Monaco itself is not mounted under Jest; these are the pure helpers the
 * editors wire to it.
 */
import {
  INPUT_REF_MIME,
  SCENARIO_REF_MIME,
  WIDGET_REF_MIME,
  chipClass,
  dropReference,
  insertReference,
  isReferenceDrag,
  markersOutsideReferences,
  offsetToPosition,
  referenceMarks,
} from "../../../components/editing/widgets/monacoCodeReferences";
import { referenceText, resolveReferences, type ReferenceScope } from "../../../utils/references/codeReferences";
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
const scope: ReferenceScope = { widgets, inputs: [] };
const withInputs: ReferenceScope = {
  widgets,
  inputs: [
    { slot: 0, label: "Roads", dataType: "geodataframe", columns: ["length"], dtypes: { length: "float64" } },
    { slot: 1, label: "Parcels" },
  ],
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
      dataTransfer: { types: [INPUT_REF_MIME], getData: (t: string) => (t === INPUT_REF_MIME ? "input_1.area" : "") },
    } as unknown as DragEvent;
    expect(isReferenceDrag(event)).toBe(true);
    expect(dropReference(editor, event)).toBe(true);
    expect(editor.executeEdits.mock.calls[0][1][0].text).toBe("[!! input_1.area !!]");
  });

  test("other drags are left alone", () => {
    const event = { dataTransfer: { types: ["text/plain"] } } as unknown as DragEvent;
    expect(isReferenceDrag(event)).toBe(false);
  });

  test("the reference text", () => {
    expect(referenceText("n")).toBe("[!! n !!]");
  });
});

/** The offset of a 1-based line and column in *text*. */
function offsetOf(text: string, position: { lineNumber: number; column: number }): number {
  const lines = text.split("\n");
  return lines.slice(0, position.lineNumber - 1).reduce((n, line) => n + line.length + 1, 0) + position.column - 1;
}

/** An editor over *text* whose cursor, and whose drop target, is right after *at*. */
function editorOver(text: string, at: string) {
  const position = offsetToPosition(text, text.indexOf(at) + at.length);
  return {
    ...fakeEditor(position),
    getTargetAtClientPoint: jest.fn(() => ({ position })),
    getModel: () => ({ getValue: () => text, getOffsetAt: (p: { lineNumber: number; column: number }) => offsetOf(text, p) }),
  };
}

const insertedText = (editor: { executeEdits: jest.Mock }) => editor.executeEdits.mock.calls[0][1][0].text;

/**
 * A chip that writes one text, an input's scenario color, the dataset inputs or
 * a field of it, goes in quoted where JSON wants a value, so the spec stays JSON before its
 * chips are resolved: a saved spec holds it so, and the classifiers that read
 * an Autark document's shape parse it (utils/autkSpecKind).
 */
describe("a chip that writes one text, inserted where JSON wants a value", () => {
  const MAP = '{"map": {"layers": [{"dataRef": "[!! input_1 !!]", "color": }]}}';

  test("an input's scenario color chip outside a string goes in quoted, so the spec stays JSON", () => {
    const editor = editorOver(MAP, '"color": ');
    expect(insertReference(editor, "scenario input_1")).toBe(true);
    expect(insertedText(editor)).toBe('"[!! scenario input_1 !!]"');
  });

  test("dropped there from an input's swatch, it goes in quoted too", () => {
    const editor = editorOver(MAP, '"color": ');
    const event = {
      clientX: 4,
      clientY: 8,
      dataTransfer: { types: [SCENARIO_REF_MIME], getData: (t: string) => (t === SCENARIO_REF_MIME ? "scenario input_1" : "") },
    } as unknown as DragEvent;
    expect(dropReference(editor, event)).toBe(true);
    expect(insertedText(editor)).toBe('"[!! scenario input_1 !!]"');
  });

  test("a field of inputs outside a string goes in quoted; inside one, as itself", () => {
    const spec = '{"encoding": {"y": {"field": , "title": "Mean \\"sun\\" "}}}';
    const outside = editorOver(spec, '"field": ');
    insertReference(outside, "inputs.sunlight");
    expect(insertedText(outside)).toBe('"[!! inputs.sunlight !!]"');
    const inside = editorOver(spec, '"Mean \\"sun\\" ');
    insertReference(inside, "inputs.sunlight");
    expect(insertedText(inside)).toBe("[!! inputs.sunlight !!]");
  });

  test("the dataset inputs outside a string goes in quoted; inside one, as itself", () => {
    const spec = '{"data": {"name": }, "title": "Rows of "}';
    const outside = editorOver(spec, '"name": ');
    insertReference(outside, "inputs");
    expect(insertedText(outside)).toBe('"[!! inputs !!]"');
    const inside = editorOver(spec, '"Rows of ');
    insertReference(inside, "inputs");
    expect(insertedText(inside)).toBe("[!! inputs !!]");
  });

  test("dropped there from the inputs tag, the dataset goes in quoted too", () => {
    const editor = editorOver('{"data": {"name": }}', '"name": ');
    const event = {
      clientX: 4,
      clientY: 8,
      dataTransfer: { types: [INPUT_REF_MIME], getData: (t: string) => (t === INPUT_REF_MIME ? "inputs" : "") },
    } as unknown as DragEvent;
    expect(dropReference(editor, event)).toBe(true);
    expect(insertedText(editor)).toBe('"[!! inputs !!]"');
  });

  test("a scale, a list of names and a widget's value are no text, and go in as they are", () => {
    const spec = '{"encoding": {"color": {"scale": , "sort": }}, "width": }';
    for (const [at, inner] of [['"scale": ', "scenario colors"], ['"sort": ', "scenario order"], ['"width": ', "size"]]) {
      const editor = editorOver(spec, at);
      insertReference(editor, inner);
      expect(insertedText(editor)).toBe(`[!! ${inner} !!]`);
    }
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
    const [input, column] = referenceMarks("a = [!! input_0 !!]\nb = [!! input_0.length !!]", withInputs, "python");
    expect(input.kind).toBe("input");
    expect(input.hover).toBe("input_0, from Roads (geodataframe)");
    expect(chipClass(input)).toBe("curio-input-ref");
    expect(column.hover).toBe("column length of input_0, from Roads (float64)");
  });

  test("an input chip with no edge, or for a column the input lacks, is a problem chip", () => {
    const [missing, column] = referenceMarks("[!! input_4 !!] [!! input_0.width !!]", withInputs, "python");
    expect(missing.problem).toMatch(/input_4 has no edge/);
    expect(chipClass(missing)).toBe("curio-input-ref-problem");
    expect(column.problem).toMatch(/input_0 has no column width/);
  });

  test("the dataset chip says whose rows it stacks, and is drawn as an input chip", () => {
    const [dataset] = referenceMarks('{"data": {"name": "[!! inputs !!]"}}', withInputs, "json");
    expect(dataset.kind).toBe("dataset");
    expect(dataset.problem).toBeNull();
    expect(dataset.hover).toBe("the dataset inputs: the rows of input_0 and input_1, stacked in circle order");
    expect(chipClass(dataset)).toBe("curio-input-ref");
    const one = { ...withInputs, inputs: [withInputs.inputs[0]] };
    expect(referenceMarks('{"data": {"name": [!! inputs !!]}}', one, "json")[0].hover).toBe(
      "the dataset inputs: the rows of input_0, stacked in circle order",
    );
  });

  test("the dataset chip on a node with no input, or in code, is a problem chip", () => {
    const [unwired] = referenceMarks('{"data": {"name": "[!! inputs !!]"}}', scope, "json");
    expect(unwired.problem).toBe("[!! inputs !!]: this node has no input to stack. Connect one to an input circle.");
    expect(unwired.hover).toBe(unwired.problem);
    expect(chipClass(unwired)).toBe("curio-input-ref-problem");
    const [code] = referenceMarks("rows = [!! inputs !!]", withInputs, "python");
    expect(code.problem).toBe("[!! inputs !!] is for a Vega-Lite spec, not for code.");
  });
});

describe("a scenario chip's hover", () => {
  const BASE = { scenario: "s-base", name: "Baseline", color: "#2a9d8f", rank: 0 };
  const fromNoBox: ReferenceScope = {
    widgets: [],
    inputs: [
      { slot: 0, label: "Weekday", scenario: { name: "Weekday", color: "#8a8f98" } },
      { slot: 1, label: "Weekend", scenario: { name: "Weekend", color: "#8a8f98" } },
    ],
  };
  const writes = (inner: string, over: ReferenceScope) => resolveReferences(referenceText(inner), over, "json").code;
  const hoverOf = (inner: string, over: ReferenceScope) => {
    const [mark] = referenceMarks(`{"x": ${referenceText(inner)}}`, over, "json");
    expect(mark.problem).toBeNull();
    return mark.hover;
  };

  test("on a node fed from no box, it says no input comes from a box, so it writes the names alone", () => {
    const why = "no input of this node comes from a scenario box";
    for (const chip of ["scenario colors", "scenario text_colors"]) {
      expect(hoverOf(chip, fromNoBox)).toBe(
        `${chip} = ${writes(chip, fromNoBox)}: ${why}, so it writes the names alone, in the grammar's own colors`,
      );
    }
    expect(hoverOf("scenario order", fromNoBox)).toBe(
      `scenario order = ${writes("scenario order", fromNoBox)}: ${why}, so it writes the names of the nodes its inputs come from`,
    );
    expect(hoverOf("scenario input_1", fromNoBox)).toBe(
      `scenario input_1 = ${writes("scenario input_1", fromNoBox)}: ${why}, so it writes the gray the scale gives input_1`,
    );
  });

  test("on a node fed from a box, it writes the boxes' scale, and an input from no box its grey", () => {
    const beside: ReferenceScope = { ...fromNoBox, inputs: [{ ...fromNoBox.inputs[0], scenario: BASE }, fromNoBox.inputs[1]] };
    expect(hoverOf("scenario colors", beside)).toBe(
      `scenario colors = ${writes("scenario colors", beside)}, from the boxes this node's inputs come from`,
    );
    expect(hoverOf("scenario input_0", beside)).toBe(
      `scenario input_0 = ${writes("scenario input_0", beside)}, the color of Baseline, the box input_0 comes from`,
    );
    expect(hoverOf("scenario input_1", beside)).toBe(
      `scenario input_1 = ${writes("scenario input_1", beside)}: input_1 comes from no scenario box`,
    );
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
