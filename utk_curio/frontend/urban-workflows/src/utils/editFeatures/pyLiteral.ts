/**
 * Python literals, written and read, for the code a node writes for itself
 * and reads back (the Map Edits node's `curio_edit_features` call,
 * `editFeatures.ts`): texts in single or double quotes with Python's escapes,
 * numbers, True, False, None, lists and dicts.
 *
 * The writer writes what the reader takes back exactly: a line break JSON
 * leaves in a text is escaped, so Python's `splitlines` never splits one, and
 * `[!!` is written `[\x21!`, so no text reads as a reference. The reader says
 * where it stopped and why (`Unreadable`), so the node can tell a person why
 * it cannot read a hand edit.
 */
import { widgetLiteral } from "../references/codeReferences";

/** A value a literal holds: anything JSON holds. */
export type JsonValue = null | boolean | number | string | JsonValue[] | { [name: string]: JsonValue };

/** A literal as the reader found it: a dict keeps its keys' types, a bare name its name. */
export type Literal =
  | { kind: "value"; value: null | boolean | number | string }
  | { kind: "list"; items: Literal[] }
  | { kind: "dict"; entries: Array<[Literal, Literal]> }
  | { kind: "name"; name: string };

/** Why code cannot be read: its message is what the node says. */
export class Unreadable extends Error {}

/**
 * U+0085, U+2028 and U+2029: line breaks to Python's `splitlines`, which JSON
 * leaves in a text. The headless runner indents a node's code with
 * `textwrap.indent`, which splits lines there.
 */
const UNICODE_BREAKS = String.fromCharCode(0x85, 0x2028, 0x2029);
const LINE_BREAKS = new RegExp(`[${UNICODE_BREAKS}]`, "g");
/** Half of a character, which Python reads apart from its other half. */
const LONE_SURROGATE = /\p{Cs}/gu;

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** *value* as a Python literal: a dict, a list, a text, a number, True, False or None. */
export function pyLiteral(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (Array.isArray(value)) return `[${value.map(pyLiteral).join(", ")}]`;
  if (isObject(value)) {
    return `{${Object.entries(value).filter(([, item]) => item !== undefined).map(([name, item]) => `${pyLiteral(name)}: ${pyLiteral(item)}`).join(", ")}}`;
  }
  if (typeof value !== "string") return widgetLiteral(value as number | boolean, "python");
  return widgetLiteral(value.replace(LONE_SURROGATE, "�"), "python")
    .replace(LINE_BREAKS, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`)
    .split("[!!").join("[\\x21!");
}

const ESCAPES: Record<string, string> = {
  "\\": "\\", "'": "'", '"': '"', a: "\x07", b: "\b", f: "\f", n: "\n", r: "\r", t: "\t", v: "\v",
};

/** The arguments of a call: its positional ones in order, then its keywords. */
export interface CallArgs {
  positional: Literal[];
  keywords: Map<string, Literal>;
}

/**
 * The arguments of the call whose `(` ends just before *start* in *text*, and
 * nothing after it. Values are literals; a bare name is read only in the
 * positional places *names* takes (the call's input). Whitespace and line
 * breaks may stand between any two tokens, a list, a dict or the call may end
 * in a comma, and a comment inside the call is refused: it would be lost when
 * the node writes its code again.
 */
export function readCallArgs(text: string, start: number, call: string, names: (position: number) => boolean): CallArgs {
  let pos = start;
  const fail = (what: string): never => {
    throw new Unreadable(`Line ${text.slice(0, pos).split(/\r\n|\r|\n/).length}: ${what}.`);
  };
  /** Fails with *what*, or with the call not closed when the code ends first. */
  const missing = (what: string): never => fail(pos >= text.length ? "the call is not closed" : what);
  const skip = () => {
    while (pos < text.length) {
      const c = text[pos];
      if (c === "#") throw new Unreadable(`The call holds a comment, which would be lost when the node writes its code.`);
      if (c !== " " && c !== "\t" && c !== "\f" && c !== "\n" && c !== "\r") return;
      pos++;
    }
  };
  const word = (): string | null => {
    const match = /[A-Za-z_][A-Za-z0-9_]*/y;
    match.lastIndex = pos;
    const found = match.exec(text);
    if (!found) return null;
    pos += found[0].length;
    return found[0];
  };
  const hex = (digits: number): number => {
    const found = text.slice(pos, pos + digits);
    if (!new RegExp(`^[0-9a-fA-F]{${digits}}$`).test(found)) fail("a text has an escape cut short");
    pos += digits;
    return parseInt(found, 16);
  };
  const escape = (): string => {
    const c = text[pos + 1];
    pos += 2;
    if (c !== undefined && Object.prototype.hasOwnProperty.call(ESCAPES, c)) return ESCAPES[c];
    if (c === "x") return String.fromCharCode(hex(2));
    if (c === "u" || c === "U") {
      const code = hex(c === "u" ? 4 : 8);
      if (code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) fail("a text escapes a character Unicode has not");
      return String.fromCodePoint(code);
    }
    if (c !== undefined && c >= "0" && c <= "7") {
      const octal = /[0-7]{1,3}/y;
      octal.lastIndex = pos - 1;
      const digits = (octal.exec(text) as RegExpExecArray)[0];
      pos += digits.length - 1;
      return String.fromCharCode(parseInt(digits, 8));
    }
    pos -= 2;
    return fail(c === "\n" || c === "\r" ? "a text goes on past its line" : `\\${c ?? ""} is not an escape the node reads`);
  };
  const string = (): string => {
    const quote = text[pos];
    if (text.startsWith(quote.repeat(3), pos)) fail("the node reads texts in single or double quotes, not in triple quotes");
    pos++;
    let out = "";
    for (;;) {
      const c = text[pos];
      if (c === undefined || c === "\n" || c === "\r") fail("a text is not closed on its line");
      if (c === quote) {
        pos++;
        return out;
      }
      if (c === "\\") out += escape();
      else {
        out += c;
        pos++;
      }
    }
  };
  const number = (): number => {
    const sign = text[pos] === "-" ? -1 : 1;
    if (text[pos] === "-" || text[pos] === "+") {
      pos++;
      skip();
    }
    const match = /(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?/y;
    match.lastIndex = pos;
    const found = match.exec(text);
    if (!found) return fail("a sign stands before no number");
    pos += found[0].length;
    if (/[A-Za-z0-9_.]/.test(text[pos] ?? "")) fail(`${found[0]}${text[pos]} is not a number the node reads`);
    const whole = /^\d+$/.test(found[0]);
    if (whole && /^0+[1-9]/.test(found[0])) fail(`${found[0]} starts with a zero, which Python refuses`);
    const value = sign * Number(found[0]);
    if (!Number.isFinite(value) || (whole && !Number.isSafeInteger(value))) fail(`${found[0]} is too large to read exactly`);
    return value;
  };
  const value = (named: boolean): Literal => {
    skip();
    const c = text[pos];
    if (c === "[") {
      pos++;
      const items: Literal[] = [];
      for (;;) {
        skip();
        if (text[pos] === "]") break;
        items.push(value(named));
        skip();
        if (text[pos] === ",") pos++;
        else if (text[pos] !== "]") missing("an item of a list has no , or ] after it");
      }
      pos++;
      return { kind: "list", items };
    }
    if (c === "{") {
      pos++;
      const entries: Array<[Literal, Literal]> = [];
      for (;;) {
        skip();
        if (text[pos] === "}") break;
        const key = value(false);
        skip();
        if (text[pos] !== ":") missing("a key of a dict has no : after it");
        pos++;
        entries.push([key, value(false)]);
        skip();
        if (text[pos] === ",") pos++;
        else if (text[pos] !== "}") missing("a value of a dict has no , or } after it");
      }
      pos++;
      return { kind: "dict", entries };
    }
    if (c === '"' || c === "'") return { kind: "value", value: string() };
    if (c !== undefined && /[-+.0-9]/.test(c)) return { kind: "value", value: number() };
    const name = word();
    if (name === "True" || name === "False") return { kind: "value", value: name === "True" };
    if (name === "None") return { kind: "value", value: null };
    if (name !== null && named) return { kind: "name", name };
    if (name !== null) return fail(`${name} is not a value written out`);
    return fail(c === undefined ? "the call is not closed" : `${c} does not start a value the node reads`);
  };

  const args: CallArgs = { positional: [], keywords: new Map() };
  skip();
  while (text[pos] !== ")") {
    if (pos >= text.length) fail("the call is not closed");
    // A keyword: a name and one =, not ==.
    const at = pos;
    const name = word();
    skip();
    if (name !== null && text[pos] === "=" && text[pos + 1] !== "=") {
      if (args.keywords.has(name)) throw new Unreadable(`The call gives ${name} twice.`);
      pos++;
      args.keywords.set(name, value(false));
    } else {
      pos = at;
      if (args.keywords.size > 0) throw new Unreadable(`The call gives a value without its name after one with a name.`);
      args.positional.push(value(names(args.positional.length)));
    }
    skip();
    if (text[pos] === ",") {
      pos++;
      skip();
    } else if (text[pos] !== ")") missing("an argument has no , or ) after it");
  }
  pos++;
  if (!/^[ \t\f\r\n]*$/.test(text.slice(pos))) throw new Unreadable(`The code goes on after the ${call} call.`);
  return args;
}

/** *literal* as Python's `repr` would show it, in a reason. */
export function shown(literal: Literal): string {
  if (literal.kind === "list") return "a list";
  if (literal.kind === "dict") return "a dict";
  if (literal.kind === "name") return literal.name;
  if (literal.value === null) return "None";
  if (typeof literal.value === "boolean") return literal.value ? "True" : "False";
  return typeof literal.value === "string" ? JSON.stringify(literal.value) : String(literal.value);
}

/** *literal* as JSON: a dict's keys must be texts, each once; *where* names it in a reason. */
export function jsonOf(literal: Literal, where: string): JsonValue {
  if (literal.kind === "value") return literal.value;
  if (literal.kind === "name") throw new Unreadable(`${where} holds ${literal.name}, which is not a value written out.`);
  if (literal.kind === "list") return literal.items.map((item) => jsonOf(item, where));
  const out: Record<string, JsonValue> = {};
  for (const [name, item] of literal.entries) {
    if (name.kind !== "value" || typeof name.value !== "string") {
      throw new Unreadable(`A dict in ${where} has the key ${shown(name)}, which is not a text.`);
    }
    if (Object.prototype.hasOwnProperty.call(out, name.value)) throw new Unreadable(`A dict in ${where} gives ${name.value} twice.`);
    out[name.value] = jsonOf(item, where);
  }
  return out;
}
