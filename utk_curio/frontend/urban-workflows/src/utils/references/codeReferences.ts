/**
 * A node's references in its code (#662): chips dragged in from the strip
 * above its editor and stored as plain `[!! ... !!]` text.
 *
 * - `[!! season !!]` names one of the node's widgets;
 * - `[!! input 1 !!]` names one of its inputs, by circle, counted from 0;
 * - `[!! input 1.height !!]` names a column of that input;
 * - `[!! input 1:roads !!]` names a layer an input carries (an Autark node's
 *   tables), and `[!! input 1:roads.height !!]` a column of that layer.
 *
 * The browser (NodeEditor, before a run) and the headless runner
 * (`utk_curio/backend/app/execution/code_references.py`) must write the same
 * code, so both are pinned to one table of cases, `codeReferences.cases.json`,
 * read by Jest and by pytest.
 *
 * A widget reference standing on its own becomes a literal of the editor's
 * language: quoted text, a number, a list, a boolean. Inside a string literal
 * it becomes the value's text, escaped for that string, so
 * `"Season: [!! season !!]"` reads `"Season: winter"`. Inside a comment it is
 * the plain text. A column or layer reference is written the same way as a text
 * value: its name. In Python and JavaScript an input reference becomes `arg`
 * when the node has one input and `arg[i]` when it has several, `i` being the
 * input's place in circle order. In a Vega-Lite or Autark spec it is the name
 * that input is read by, `input_<i>`, written like a text value too.
 */

import { WIDGET_NAME_RE, effectiveValue, type WidgetDef, type WidgetValue } from "../widgets/widgetModel";
import { inputTableName } from "../../generated/autkGrammar";

export type CodeLanguage = "python" | "javascript" | "json";

/** A reference as written: `[!! ... !!]`. Kept in sync with `REFERENCE_RE`
 * in `code_references.py`. */
export const REFERENCE_PATTERN = String.raw`\[!!\s*(.*?)\s*!!\]`;

/** What stands inside an input, layer or column reference: `input 1`,
 * `input 1.height`, `input 1:roads`, `input 1:roads.height`, or `input ?`
 * once its edge was deleted. A layer name holds no dot; a column name is all
 * the text after the first one. Kept in sync with `INPUT_REFERENCE_RE` in
 * `code_references.py`. */
export const INPUT_REFERENCE_PATTERN = String.raw`^input\s+(\d+|\?)(?::([^.]+))?(?:\.(.+))?$`;
const INPUT_REFERENCE_RE = new RegExp(INPUT_REFERENCE_PATTERN);

export interface CodeReference {
  /** Offsets of the whole `[!! ... !!]` in the code. */
  start: number;
  end: number;
  /** What stands between the brackets, trimmed. */
  inner: string;
}

export interface ReferenceProblem {
  reference: string;
  message: string;
}

/** One of the node's wired inputs. */
export interface InputScope {
  /** Its circle, counted from 0. */
  slot: number;
  /** The node that feeds it, shown on its tag and in its chips' hover. */
  label?: string;
  /** Its data type, once it has arrived. */
  dataType?: string;
  /** Its column names, once known. Absent or null before: a column chip is
   * then not checked against them. */
  columns?: string[] | null;
  /** Each column's dtype, when the input names them. */
  dtypes?: Record<string, string>;
  /** The layers it carries, once known, when it carries several (an Autark
   * node's tables). */
  layers?: LayerScope[] | null;
}

/** One layer an input carries. */
export interface LayerScope {
  name: string;
  columns?: string[] | null;
  dtypes?: Record<string, string>;
}

/** What a node's references can name: its widgets and its wired inputs. */
export interface ReferenceScope {
  widgets: WidgetDef[];
  /** In circle order. */
  inputs: InputScope[];
}

export type ParsedReference =
  | { kind: "widget"; name: string }
  /** `slot` is null for `input ?`, the input whose edge was deleted. */
  | { kind: "input"; slot: number | null; layer?: string; column?: string };

export type ReferenceContext = { kind: "code" } | { kind: "comment" } | { kind: "string"; quote: string };

export function parseReference(inner: string): ParsedReference {
  const m = INPUT_REFERENCE_RE.exec(inner);
  if (!m) return { kind: "widget", name: inner };
  const parsed: ParsedReference = { kind: "input", slot: m[1] === "?" ? null : Number(m[1]) };
  if (m[2] !== undefined) parsed.layer = m[2];
  if (m[3] !== undefined) parsed.column = m[3];
  return parsed;
}

/** The text of a reference to *inner*. */
export function referenceText(inner: string): string {
  return `[!! ${inner} !!]`;
}

/** What stands inside a reference to input *slot*, to one of its layers, or to
 * a column of either. */
export function inputReferenceInner(slot: number | null, column?: string, layer?: string): string {
  return (
    `input ${slot === null ? "?" : slot}`
    + (layer !== undefined ? `:${layer}` : "")
    + (column !== undefined ? `.${column}` : "")
  );
}

/** Whether *name* can ride a layer reference and read back as itself. */
export function isReferenceableLayer(name: string): boolean {
  return isReferenceableColumn(name) && !name.includes(".");
}

/** Whether *name* can ride a column reference and read back as itself. */
export function isReferenceableColumn(name: string): boolean {
  return name !== "" && name.trim() === name && !/[\r\n]/.test(name) && !name.includes("!!]");
}

export function findReferences(code: string): CodeReference[] {
  const re = new RegExp(REFERENCE_PATTERN, "g");
  const out: CodeReference[] = [];
  let match: RegExpExecArray | null;
  while ((match = re.exec(code)) !== null) {
    out.push({ start: match.index, end: match.index + match[0].length, inner: match[1] });
  }
  return out;
}

/** Where each reference sits: in code, in a comment, or in a string literal. */
export function referenceContexts(code: string, refs: CodeReference[], language: CodeLanguage): ReferenceContext[] {
  const contexts: ReferenceContext[] = [];
  let state: "code" | "comment" | "block" | "string" = "code";
  let quote = "";
  let i = 0;
  let r = 0;
  const current = (): ReferenceContext =>
    state === "string" ? { kind: "string", quote } : state === "code" ? { kind: "code" } : { kind: "comment" };

  while (i < code.length || r < refs.length) {
    if (r < refs.length && i >= refs[r].start) {
      contexts.push(current());
      i = Math.max(i, refs[r].end);
      r += 1;
      continue;
    }
    if (i >= code.length) break;
    const ch = code[i];
    if (state === "code") {
      if (language === "python" && ch === "#") {
        state = "comment";
      } else if (language === "javascript" && code.startsWith("//", i)) {
        state = "comment";
        i += 2;
        continue;
      } else if (language === "javascript" && code.startsWith("/*", i)) {
        state = "block";
        i += 2;
        continue;
      } else if (ch === '"' || (language !== "json" && (ch === "'" || (language === "javascript" && ch === "`")))) {
        if (language === "python" && code.startsWith(ch.repeat(3), i)) {
          quote = ch.repeat(3);
          state = "string";
          i += 3;
          continue;
        }
        quote = ch;
        state = "string";
      }
    } else if (state === "comment") {
      if (ch === "\n") state = "code";
    } else if (state === "block") {
      if (code.startsWith("*/", i)) {
        state = "code";
        i += 2;
        continue;
      }
    } else {
      if (ch === "\\") {
        i += 2;
        continue;
      }
      if (quote.length === 3) {
        if (code.startsWith(quote, i)) {
          state = "code";
          i += 3;
          continue;
        }
      } else if (ch === quote) {
        state = "code";
      } else if (ch === "\n" && quote !== "`") {
        // An unterminated one-line string ends with its line.
        state = "code";
      }
    }
    i += 1;
  }
  return contexts;
}

/** *value* as a literal of *language*. */
export function widgetLiteral(value: WidgetValue | undefined, language: CodeLanguage): string {
  if (value === null || value === undefined) return language === "python" ? "None" : "null";
  if (typeof value === "boolean") {
    if (language === "python") return value ? "True" : "False";
    return value ? "true" : "false";
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return language === "python" ? "None" : "null";
    return String(value);
  }
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return "[" + (value as WidgetValue[]).map((v) => widgetLiteral(v, language)).join(", ") + "]";
  }
  if (typeof value === "object") {
    // A location's {"lat": ..., "lon": ...}: a dict in Python, an object in
    // JavaScript and JSON.
    return (
      "{" +
      Object.entries(value as unknown as Record<string, WidgetValue>)
        .map(([k, v]) => JSON.stringify(k) + ": " + widgetLiteral(v, language))
        .join(", ") +
      "}"
    );
  }
  return JSON.stringify(value);
}

function textOf(value: WidgetValue | undefined, language: CodeLanguage): string {
  return typeof value === "string" ? value : widgetLiteral(value, language);
}

function escapeFor(text: string, context: ReferenceContext, language: CodeLanguage): string {
  if (context.kind === "comment") return text.split("\r\n").join(" ").split("\n").join(" ");
  if (context.kind === "code") return text;
  if (language === "json") return JSON.stringify(text).slice(1, -1);
  const quote = context.quote;
  let out = text.split("\\").join("\\\\");
  if (quote === "`") return out.split("`").join("\\`").split("${").join("\\${");
  if (quote.length === 3) return out.split(quote[0]).join("\\" + quote[0]);
  out = out.split(quote).join("\\" + quote);
  return out.split("\n").join("\\n").split("\r").join("\\r");
}

/** *text* as a reference standing in *context* writes it. */
function writeText(text: string, context: ReferenceContext, language: CodeLanguage): string {
  return context.kind === "code" ? widgetLiteral(text, language) : escapeFor(text, context, language);
}

/** Why *reference* cannot be resolved in *scope*, standing in *context*, or null. */
export function referenceProblem(
  reference: string,
  inner: string,
  scope: ReferenceScope,
  context: ReferenceContext,
  language: CodeLanguage,
): string | null {
  const parsed = parseReference(inner);
  if (parsed.kind === "input") {
    if (parsed.slot === null) {
      return `${reference}: the edge for this input was deleted. Drag one of this node's input chips here.`;
    }
    const input = scope.inputs.find((i) => i.slot === parsed.slot);
    if (input === undefined) {
      return `${reference}: input ${parsed.slot} has no edge. Connect one to that circle, or drag one of this node's input chips here.`;
    }
    if (parsed.layer !== undefined) {
      if (language !== "json") return `${reference}: a layer chip works in Vega-Lite and Autark specs.`;
      const layers = Array.isArray(input.layers) ? input.layers : null;
      const layer = layers?.find((l) => l.name === parsed.layer);
      if (layers !== null && layer === undefined) {
        return `${reference}: input ${parsed.slot} has no layer ${parsed.layer}.`;
      }
      if (parsed.column !== undefined && Array.isArray(layer?.columns) && !layer!.columns!.includes(parsed.column)) {
        return `${reference}: layer ${parsed.layer} of input ${parsed.slot} has no column ${parsed.column}.`;
      }
      return null;
    }
    if (parsed.column === undefined) {
      if (language === "json") {
        if (Array.isArray(input.layers) && input.layers.length > 1) {
          const names = input.layers.map((l) => l.name).join(", ");
          return `${reference}: input ${parsed.slot} carries several layers (${names}). Drag one of its layer chips here.`;
        }
        return null;
      }
      if (context.kind !== "code") {
        return `${reference} is an input, not text. Use it outside quotes and comments.`;
      }
      return null;
    }
    if (Array.isArray(input.columns) && !input.columns.includes(parsed.column)) {
      return `${reference}: input ${parsed.slot} has no column ${parsed.column}.`;
    }
    return null;
  }
  if (inner.includes("$")) {
    return `${reference} is an old widget marker. Add the widget in the node's Widgets tab and drag its tag into the code.`;
  }
  if (!WIDGET_NAME_RE.test(inner)) {
    return `${reference} does not name a widget. Widget names are letters, digits and underscores.`;
  }
  if (!scope.widgets.some((w) => w.name === inner)) {
    return `${reference}: this node has no widget named ${inner}. Add it in the Widgets tab.`;
  }
  return null;
}

/** What a reference without a problem writes, standing in *context*. */
function resolvedText(inner: string, scope: ReferenceScope, context: ReferenceContext, language: CodeLanguage): string {
  const parsed = parseReference(inner);
  if (parsed.kind === "input") {
    if (parsed.column !== undefined) return writeText(parsed.column, context, language);
    if (parsed.layer !== undefined) return writeText(parsed.layer, context, language);
    const position = scope.inputs.findIndex((i) => i.slot === parsed.slot);
    if (language === "json") return writeText(inputTableName(position), context, language);
    if (scope.inputs.length === 1) return "arg";
    return `arg[${position}]`;
  }
  const widget = scope.widgets.find((w) => w.name === inner) as WidgetDef;
  const value = effectiveValue(widget);
  return context.kind === "code" ? widgetLiteral(value, language) : escapeFor(textOf(value, language), context, language);
}

/** *code* with every reference replaced, and what could not be replaced. A
 * reference with a problem is left as written. */
export function resolveReferences(
  code: string,
  scope: ReferenceScope,
  language: CodeLanguage,
): { code: string; problems: ReferenceProblem[] } {
  const refs = findReferences(code);
  if (refs.length === 0) return { code, problems: [] };
  const ordered: ReferenceScope = { ...scope, inputs: [...scope.inputs].sort((a, b) => a.slot - b.slot) };
  const contexts = referenceContexts(code, refs, language);
  const problems: ReferenceProblem[] = [];
  let out = "";
  let last = 0;
  refs.forEach((ref, index) => {
    out += code.slice(last, ref.start);
    const written = code.slice(ref.start, ref.end);
    const problem = referenceProblem(written, ref.inner, ordered, contexts[index], language);
    if (problem !== null) {
      problems.push({ reference: written, message: problem });
      out += written;
    } else {
      out += resolvedText(ref.inner, ordered, contexts[index], language);
    }
    last = ref.end;
  });
  out += code.slice(last);
  return { code: out, problems };
}

/** One message for a failed run, one line per problem. */
export function describeReferenceProblems(problems: ReferenceProblem[]): string {
  return problems.map((p) => p.message).join("\n");
}

/** Why a node with several inputs cannot run yet: the circles in *slots* hold
 * nothing. One line per input. */
export function describeEmptyInputs(slots: number[], inputs: InputScope[]): string {
  return slots
    .map((slot) => {
      const label = inputs.find((i) => i.slot === slot)?.label;
      return `Input ${slot}${label ? ` (from ${label})` : ""} has no value yet. Run the node that feeds it.`;
    })
    .join("\n");
}

/**
 * *code* after circle *removedSlot* lost its edge and the circles below it
 * moved up one: references to later inputs count one less, and references to
 * the removed input become `[!! input ? !!]`, which reports itself. Other
 * references, and the text around them, are kept as written.
 */
export function renumberInputReferences(code: string, removedSlot: number): string {
  const refs = findReferences(code);
  let out = "";
  let last = 0;
  for (const ref of refs) {
    const parsed = parseReference(ref.inner);
    if (parsed.kind !== "input" || parsed.slot === null || parsed.slot < removedSlot) continue;
    const slot = parsed.slot === removedSlot ? null : parsed.slot - 1;
    out += code.slice(last, ref.start) + referenceText(inputReferenceInner(slot, parsed.column, parsed.layer));
    last = ref.end;
  }
  return last === 0 ? code : out + code.slice(last);
}
