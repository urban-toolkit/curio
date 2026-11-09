/**
 * A click on a function under the header's Functions: its call at the cursor,
 * and, for a function of a module the code does not import yet, its import
 * line after the imports the code starts with, in one edit, so one undo takes
 * both back. Curio's own functions need no import. The groups the header
 * shows: each module that offers a function, then Curio's.
 */
import {
  functionCallEdits,
  functionGroups,
  importLineNumber,
  importsName,
  insertFunctionCall,
} from "../../../components/editing/widgets/functionCalls";
import type { NodeFunctionsPayload } from "../../../services/packages/types";

const SEASON = { name: "season_factor", call: "season_factor(season)", insert: "season_factor(season)" };
const CALCULATE = {
  name: "raster_calculate",
  call: "raster_calculate(operation, rasters, codes=None, *, absolute=False, output_file=None)",
  insert: "raster_calculate(operation, rasters)",
};
const LOAD = { name: "curio_load_model", call: "curio_load_model(model_id)", insert: "curio_load_model(model_id)" };

/** Accumulated Shadow's starter, as its package ships it. */
const SHADOW_STARTER =
  "from deep_umbra import accumulated_shadow\n" +
  'model = curio_load_model("model.scout.deep-umbra")\n' +
  "return accumulated_shadow(input_0, season=[!! season !!], model=model, output_file=curio_output_file)\n";

/** *code* with *edits* made, as Monaco makes them: each at its place in the code as it was. */
function applied(code: string, edits: Array<{ at: { lineNumber: number; column: number }; text: string }>): string {
  const offsetOf = ({ lineNumber, column }: { lineNumber: number; column: number }) => {
    const lines = code.split("\n");
    return lines.slice(0, lineNumber - 1).reduce((sum, line) => sum + line.length + 1, 0) + column - 1;
  };
  return [...edits]
    .map((edit) => ({ offset: offsetOf(edit.at), text: edit.text }))
    .sort((a, b) => b.offset - a.offset)
    .reduce((text, edit) => text.slice(0, edit.offset) + edit.text + text.slice(edit.offset), code);
}

describe("the groups the header shows", () => {
  test("each module that offers a function, in the list's order, then Curio's", () => {
    const list: NodeFunctionsPayload = {
      engine: "python",
      modules: [
        { package: "model.scout.deep-umbra@1", module: "deep_umbra", problem: null, functions: [{ ...SEASON, doc: "" }] },
        { package: "curio.rasterization@1", module: "scout_rasters.convert_to_raster", problem: null, functions: [] },
        { package: "curio.rasterization@1", module: "scout_rasters.broken", problem: "does not parse", functions: [] },
        { package: "curio.rasterization@1", module: "scout_rasters.raster_algebra", problem: null, functions: [{ ...CALCULATE, doc: "" }] },
      ],
      curio: [{ ...LOAD, doc: "" }],
    };
    expect(functionGroups(list).map((group) => [group.module, group.functions.map((fn) => fn.name)])).toEqual([
      ["deep_umbra", ["season_factor"]],
      ["scout_rasters.raster_algebra", ["raster_calculate"]],
      [null, ["curio_load_model"]],
    ]);
    expect(functionGroups({ engine: null, modules: [], curio: [] })).toEqual([]);
    expect(functionGroups(null)).toEqual([]);
  });
});

describe("whether the code imports a function already", () => {
  test.each([
    ["from deep_umbra import season_factor\n", true],
    ["from deep_umbra import accumulated_shadow, season_factor  # both\n", true],
    ["from deep_umbra import (\n    accumulated_shadow,\n    season_factor,\n)\n", true],
    ["from deep_umbra import accumulated_shadow, \\\n    season_factor\n", true],
    ["from deep_umbra import *\n", true],
    ["    from deep_umbra import season_factor\n", true],
    ["from deep_umbra import accumulated_shadow\n", false],
    ["from deep_umbra import season_factor as factor\n", false],
    ["from deep_umbra.deep_umbra import season_factor\n", false],
    ["import deep_umbra\n", false],
    ["# from deep_umbra import season_factor\nx = 1\n", false],
  ])("%j: %s", (code, imported) => {
    expect(importsName(code, "deep_umbra", "season_factor")).toBe(imported);
  });
});

describe("where a new import line goes", () => {
  test.each([
    ["the line after the code's first imports", SHADOW_STARTER, 2],
    ["after the comments and imports the code starts with", "# Settings\n#\nimport numpy as np\nfrom a import b\n\nreturn b(np)\n", 5],
    ["the first line of code that imports nothing", "return input_0\n", 1],
    ["the first line, before comments, when nothing is imported", "# A note\nreturn input_0\n", 1],
    ["after an import in parentheses", "from a import (\n    b,\n    c,\n)\nx = 1\n", 5],
    ["after an import over backslashed lines", "from a import b, \\\n    c\nx = 1\n", 3],
    ["not after an import further down", "x = 1\nimport numpy\n", 1],
    ["after the last line, when the code is its imports", "from a import b", 2],
  ])("%s", (_what, code, line) => {
    expect(importLineNumber(code)).toBe(line);
  });
});

describe("the edits a click makes", () => {
  test("a function of a module the code does not import: its import after the first imports, its call at the cursor", () => {
    const end = { lineNumber: 4, column: 1 };
    const edits = functionCallEdits(SHADOW_STARTER, end, SEASON, "deep_umbra");
    expect(edits).toEqual([
      { at: { lineNumber: 2, column: 1 }, text: "from deep_umbra import season_factor\n" },
      { at: end, text: "season_factor(season)" },
    ]);
    expect(applied(SHADOW_STARTER, edits)).toBe(
      "from deep_umbra import accumulated_shadow\n" +
        "from deep_umbra import season_factor\n" +
        'model = curio_load_model("model.scout.deep-umbra")\n' +
        "return accumulated_shadow(input_0, season=[!! season !!], model=model, output_file=curio_output_file)\n" +
        "season_factor(season)",
    );
  });

  test("the call a click writes gives the arguments a call must give", () => {
    const code = "from scout_rasters.raster_algebra import raster_statistics\n\nresult = \n";
    const cursor = { lineNumber: 3, column: 10 };
    expect(applied(code, functionCallEdits(code, cursor, CALCULATE, "scout_rasters.raster_algebra"))).toBe(
      "from scout_rasters.raster_algebra import raster_statistics\n" +
        "from scout_rasters.raster_algebra import raster_calculate\n" +
        "\nresult = raster_calculate(operation, rasters)\n",
    );
  });

  test("a function the code imports, or one of Curio's, is its call alone", () => {
    const code = "from deep_umbra import season_factor\nminutes = \n";
    const cursor = { lineNumber: 2, column: 11 };
    expect(functionCallEdits(code, cursor, SEASON, "deep_umbra")).toEqual([{ at: cursor, text: "season_factor(season)" }]);
    expect(functionCallEdits(code, cursor, LOAD, null)).toEqual([{ at: cursor, text: "curio_load_model(model_id)" }]);
  });

  test("where the import and the call go at one place, one edit writes both, the import first", () => {
    expect(functionCallEdits("", { lineNumber: 1, column: 1 }, SEASON, "deep_umbra")).toEqual([
      { at: { lineNumber: 1, column: 1 }, text: "from deep_umbra import season_factor\nseason_factor(season)" },
    ]);
    // Code that is its imports, the cursor at its end: the import, then the call, each on its own line.
    const code = "from deep_umbra import accumulated_shadow";
    const edits = functionCallEdits(code, { lineNumber: 1, column: code.length + 1 }, SEASON, "deep_umbra");
    expect(applied(code, edits)).toBe(
      "from deep_umbra import accumulated_shadow\nfrom deep_umbra import season_factor\nseason_factor(season)",
    );
  });

  test("insertFunctionCall makes them in one edit at the editor's cursor, then gives it the focus", () => {
    const executeEdits = jest.fn();
    const focus = jest.fn();
    const editor = {
      getPosition: () => ({ lineNumber: 4, column: 1 }),
      getModel: () => ({ getValue: () => SHADOW_STARTER }),
      executeEdits,
      focus,
    };
    expect(insertFunctionCall(editor, SEASON, "deep_umbra")).toBe(true);
    expect(executeEdits).toHaveBeenCalledTimes(1);
    const [source, edits] = executeEdits.mock.calls[0];
    expect(source).toBe("curio-function-tag");
    expect(edits).toEqual([
      {
        range: { startLineNumber: 2, startColumn: 1, endLineNumber: 2, endColumn: 1 },
        text: "from deep_umbra import season_factor\n",
        forceMoveMarkers: true,
      },
      {
        range: { startLineNumber: 4, startColumn: 1, endLineNumber: 4, endColumn: 1 },
        text: "season_factor(season)",
        forceMoveMarkers: true,
      },
    ]);
    expect(focus).toHaveBeenCalled();
    // No editor mounted yet: nothing to write in.
    expect(insertFunctionCall(null, SEASON, "deep_umbra")).toBe(false);
  });
});
