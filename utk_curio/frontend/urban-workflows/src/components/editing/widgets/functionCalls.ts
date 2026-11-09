/**
 * The functions a node's code can call, as the header above its code lists
 * them under Functions: grouped by the module they are imported from, the
 * node's own package's first, then Curio's, which need no import. A click on
 * one writes its call at the cursor, and first its import line when the code
 * lacks it, in one edit, so one undo takes both back.
 *
 * Pure but for `insertFunctionCall`, which edits a mounted editor.
 */
import type { NodeFunctionsPayload, OfferedFunctionPayload } from "../../../services/packages/types";

/** One line of Functions: a module and what it offers, or Curio's own. */
export interface FunctionGroup {
  /** The module its functions are imported from; null for Curio's, which need no import. */
  module: string | null;
  functions: OfferedFunctionPayload[];
}

/** What the line of Curio's own functions is called. */
export const CURIO_FUNCTIONS = "Curio";

/** The line a function's hover ends with, and its tag's text tooltip. */
export const FUNCTION_HOW = "Click to insert the call at the cursor";
export const FUNCTION_HOW_IMPORT = "Click to insert the call at the cursor, with its import when the code lacks it";

/** The groups a node's list makes: each module that offers a function, in
 * the list's order, then Curio's. */
export function functionGroups(payload: NodeFunctionsPayload | null | undefined): FunctionGroup[] {
  if (!payload) return [];
  const groups: FunctionGroup[] = payload.modules
    .filter((row) => row.functions.length > 0)
    .map((row) => ({ module: row.module, functions: row.functions }));
  if (payload.curio.length > 0) groups.push({ module: null, functions: payload.curio });
  return groups;
}

/** The line that imports *name* from *module*. */
export function importLine(module: string, name: string): string {
  return `from ${module} import ${name}`;
}

/** A `from <module> import <names>`: on one line, in parentheses, or over backslashed lines. */
const FROM_IMPORTS = /^[ \t]*from[ \t]+([A-Za-z_][\w.]*)[ \t]+import[ \t]+(\([^)]*\)|(?:[^\n\\]|\\\n)*)/gm;

/** Whether *code* already imports *name* from *module*: a `from <module>
 * import` that names it, unaliased, or `*`. */
export function importsName(code: string, module: string, name: string): boolean {
  for (const match of code.matchAll(FROM_IMPORTS)) {
    if (match[1] !== module) continue;
    const names = match[2]
      .replace(/#[^\n]*/g, "")
      .replace(/[()\\]/g, " ")
      .split(",")
      .map((item) => item.trim().split(/\s+/));
    if (names.some((words) => words[0] === "*" || (words.length === 1 && words[0] === name))) return true;
  }
  return false;
}

/** The 1-based line a new import line goes before: the line after the last
 * import among the imports, comments and blank lines the code starts with,
 * else the first line. */
export function importLineNumber(code: string): number {
  const lines = code.split("\n");
  let last = 0;
  // Whether the import before goes on: inside its parentheses, or after a backslash.
  let parens = false;
  let backslash = false;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const text = line.replace(/#.*$/, "").trim();
    if (parens || backslash) {
      if (parens && text.includes(")")) parens = false;
      backslash = text.endsWith("\\");
    } else if (text === "") {
      continue;
    } else if (/^[ \t]/.test(line) || !/^(from\s+[\w.]+\s+import\b|import\s+[\w.])/.test(text)) {
      break;
    } else {
      parens = text.includes("(") && !text.includes(")");
      backslash = text.endsWith("\\");
    }
    if (!parens && !backslash) last = index + 1;
  }
  return last + 1;
}

/** A position in an editor's model, 1-based. */
export interface CodePosition {
  lineNumber: number;
  column: number;
}

/** The edits a click on *fn* makes in *code* with the cursor at *cursor*:
 * its call there, and, for a function of *module* the code does not import
 * yet, its import line on a line of its own after the code's first imports.
 * Where both go at one place, one edit writes the import, then the call. */
export function functionCallEdits(
  code: string,
  cursor: CodePosition,
  fn: Pick<OfferedFunctionPayload, "name" | "call" | "insert">,
  module: string | null,
): Array<{ at: CodePosition; text: string }> {
  const call = fn.insert || fn.call;
  if (!module || importsName(code, module, fn.name)) return [{ at: cursor, text: call }];
  const lines = code.split("\n");
  const imported = importLine(module, fn.name);
  const before = importLineNumber(code);
  // The code ends with its imports: the import goes after its last line.
  const atEnd = before > lines.length;
  const at = atEnd
    ? { lineNumber: lines.length, column: lines[lines.length - 1].length + 1 }
    : { lineNumber: before, column: 1 };
  const text = atEnd ? `\n${imported}` : `${imported}\n`;
  if (at.lineNumber === cursor.lineNumber && at.column === cursor.column) {
    return [{ at, text: atEnd ? `${text}\n${call}` : `${text}${call}` }];
  }
  return [{ at, text }, { at: cursor, text: call }];
}

/** Writes the call of *fn* at the editor's cursor, with its import line when
 * the code lacks it (`functionCallEdits`), as one edit. */
export function insertFunctionCall(
  editor: any,
  fn: Pick<OfferedFunctionPayload, "name" | "call" | "insert">,
  module: string | null,
): boolean {
  const cursor = editor?.getPosition?.();
  const code = editor?.getModel?.()?.getValue?.();
  if (!editor || !cursor || typeof code !== "string") return false;
  const edits = functionCallEdits(code, { lineNumber: cursor.lineNumber, column: cursor.column }, fn, module);
  editor.executeEdits(
    "curio-function-tag",
    edits.map(({ at, text }) => ({
      range: { startLineNumber: at.lineNumber, startColumn: at.column, endLineNumber: at.lineNumber, endColumn: at.column },
      text,
      forceMoveMarkers: true,
    })),
  );
  editor.focus?.();
  return true;
}
