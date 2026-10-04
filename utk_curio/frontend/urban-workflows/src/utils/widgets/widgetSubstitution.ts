/**
 * Turning a node's `[!! name !!]` references into its widgets' values (#662).
 *
 * The browser (WidgetsEditor, before a run) and the headless runner
 * (`utk_curio/backend/app/execution/widget_substitution.py`) must write the
 * same code, so both are pinned to one table of cases,
 * `widgetSubstitution.cases.json`, read by Jest and by pytest.
 *
 * A reference standing on its own becomes a literal of the editor's language:
 * quoted text, a number, a list, a boolean. A reference inside a string
 * literal becomes the value's text, escaped for that string, so
 * `"Season: [!! season !!]"` reads `"Season: winter"`. Inside a comment it is
 * the plain text.
 */

import { WIDGET_NAME_RE, effectiveValue, type WidgetDef, type WidgetValue } from "./widgetModel";

export type WidgetLanguage = "python" | "javascript" | "json";

/** A reference as written: `[!! name !!]`. Kept in sync with `REFERENCE_RE`
 * in `widget_substitution.py`. */
export const WIDGET_REFERENCE_PATTERN = String.raw`\[!!\s*(.*?)\s*!!\]`;

export interface WidgetReference {
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

type Context = { kind: "code" } | { kind: "comment" } | { kind: "string"; quote: string };

export function findWidgetReferences(code: string): WidgetReference[] {
  const re = new RegExp(WIDGET_REFERENCE_PATTERN, "g");
  const out: WidgetReference[] = [];
  let match: RegExpExecArray | null;
  while ((match = re.exec(code)) !== null) {
    out.push({ start: match.index, end: match.index + match[0].length, inner: match[1] });
  }
  return out;
}

/** Where each reference sits: in code, in a comment, or in a string literal. */
function referenceContexts(code: string, refs: WidgetReference[], language: WidgetLanguage): Context[] {
  const contexts: Context[] = [];
  let state: "code" | "comment" | "block" | "string" = "code";
  let quote = "";
  let i = 0;
  let r = 0;
  const current = (): Context =>
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
export function widgetLiteral(value: WidgetValue | undefined, language: WidgetLanguage): string {
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
  return JSON.stringify(value);
}

function textOf(value: WidgetValue | undefined, language: WidgetLanguage): string {
  return typeof value === "string" ? value : widgetLiteral(value, language);
}

function escapeFor(text: string, context: Context, language: WidgetLanguage): string {
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

/** Why *reference* cannot be resolved against *widgets*, or null. */
export function referenceProblem(reference: string, inner: string, widgets: WidgetDef[]): string | null {
  if (inner.includes("$")) {
    return `${reference} is an old widget marker. Add the widget in the node's Widgets tab and drag its tag into the code.`;
  }
  if (!WIDGET_NAME_RE.test(inner)) {
    return `${reference} does not name a widget. Widget names are letters, digits and underscores.`;
  }
  if (!widgets.some((w) => w.name === inner)) {
    return `${reference}: this node has no widget named ${inner}. Add it in the Widgets tab.`;
  }
  return null;
}

/** *code* with every reference replaced, and what could not be replaced. A
 * reference with a problem is left as written. */
export function resolveWidgetReferences(
  code: string,
  widgets: WidgetDef[],
  language: WidgetLanguage,
): { code: string; problems: ReferenceProblem[] } {
  const refs = findWidgetReferences(code);
  if (refs.length === 0) return { code, problems: [] };
  const contexts = referenceContexts(code, refs, language);
  const problems: ReferenceProblem[] = [];
  let out = "";
  let last = 0;
  refs.forEach((ref, index) => {
    out += code.slice(last, ref.start);
    const written = code.slice(ref.start, ref.end);
    const problem = referenceProblem(written, ref.inner, widgets);
    if (problem !== null) {
      problems.push({ reference: written, message: problem });
      out += written;
    } else {
      const widget = widgets.find((w) => w.name === ref.inner) as WidgetDef;
      const value = effectiveValue(widget);
      const context = contexts[index];
      out += context.kind === "code" ? widgetLiteral(value, language) : escapeFor(textOf(value, language), context, language);
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
