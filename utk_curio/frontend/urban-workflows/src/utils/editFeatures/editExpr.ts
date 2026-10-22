/**
 * The Map Edits node's expressions: the conditions its edits pick features
 * by (`where`) and the formulas an `expr` edit computes, over one feature's
 * properties. Read by its own parser, never by `eval`.
 *
 * The twin of `utk_curio/sandbox/util/edit_expr.py`: both read the cases in
 * `editExpr.cases.json`, so the node's table here and a run agree on every
 * value. The language, and what a value is, are described there.
 */

export type ExprValue = number | string | boolean | null;

export type Expr =
  | { k: "lit"; v: ExprValue }
  | { k: "col"; name: string }
  | { k: "not"; a: Expr }
  | { k: "and" | "or"; a: Expr; b: Expr }
  | { k: "neg"; a: Expr }
  | { k: "bin"; op: string; a: Expr; b: Expr }
  | { k: "cmp"; op: string; a: Expr; b: Expr }
  | { k: "call"; name: string; args: Expr[] };

/** The text is not an expression, or a function was given the wrong number of arguments. */
export class ExprError extends Error {}

/** Deeper than this, an expression is refused, as the sandbox refuses it. */
export const MAX_DEPTH = 50;

// Whitespace and digits spelled out, as the sandbox spells them.
const SPACE = /[ \t\r\n]*/y;
const TOKEN = new RegExp(
  "(?<num>[0-9]+(?:\\.[0-9]*)?(?:[eE][+-]?[0-9]+)?|\\.[0-9]+(?:[eE][+-]?[0-9]+)?)"
    + "|(?<str>'(?:[^'\\\\]|\\\\[\\s\\S])*'|\"(?:[^\"\\\\]|\\\\[\\s\\S])*\")"
    + "|(?<tick>`[^`]+`)"
    + "|(?<name>[A-Za-z_][A-Za-z0-9_:.]*)"
    + "|(?<op>==|!=|<=|>=|[-+*/%<>(),])",
  "y",
);
const ESCAPE = /\\([\s\S])/g;
const KEYWORDS = new Set(["and", "or", "not", "true", "false", "null"]);
/** Each function and how many arguments it takes, at least and at most. */
const FUNCTIONS = new Map<string, [number, number | null]>([["abs", [1, 1]], ["round", [1, 2]], ["min", [1, null]], ["max", [1, null]]]);
const COMPARISONS = ["==", "!=", "<=", ">=", "<", ">"];
/** Powers of ten written out, so a scale is the same number in both languages. */
const TENS = [1, 10, 100, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9, 1e10, 1e11, 1e12, 1e13, 1e14, 1e15];

type Token = ["lit", ExprValue] | ["col", string] | ["kw", string] | ["name", string] | ["op", string];

function tokens(text: string): Token[] {
  const out: Token[] = [];
  let pos = 0;
  for (;;) {
    SPACE.lastIndex = pos;
    SPACE.exec(text);
    pos = SPACE.lastIndex;
    if (pos >= text.length) return out;
    TOKEN.lastIndex = pos;
    const match = TOKEN.exec(text);
    if (!match) throw new ExprError(`cannot read '${text.slice(pos, pos + 20)}' in '${text}'`);
    pos = TOKEN.lastIndex;
    const g = match.groups ?? {};
    if (g.num !== undefined) {
      const literal = Number(g.num);
      if (!Number.isFinite(literal)) throw new ExprError(`${g.num} is too large a number`);
      out.push(["lit", literal]);
    } else if (g.str !== undefined) {
      out.push(["lit", g.str.slice(1, -1).replace(ESCAPE, "$1")]);
    } else if (g.tick !== undefined) {
      out.push(["col", g.tick.slice(1, -1)]);
    } else if (g.name !== undefined) {
      out.push(KEYWORDS.has(g.name) ? ["kw", g.name] : ["name", g.name]);
    } else {
      out.push(["op", g.op]);
    }
  }
}

function arity(name: string): string {
  const [least, most] = FUNCTIONS.get(name)!;
  if (most === least) return "one argument";
  if (most === null) return "one argument or more";
  return `${least} or ${most} arguments`;
}

class Parser {
  private at = 0;
  private depth = 0;
  private readonly toks: Token[];

  constructor(private readonly text: string) {
    this.toks = tokens(text);
  }

  private peek(kind?: string, value?: unknown): Token | null {
    const token = this.toks[this.at];
    if (!token) return null;
    if ((kind !== undefined && token[0] !== kind) || (value !== undefined && token[1] !== value)) return null;
    return token;
  }

  private take(kind?: string, value?: unknown): Token {
    const token = this.peek(kind, value);
    if (!token) throw new ExprError(`expected ${String(value ?? kind ?? "more")} in '${this.text}'`);
    this.at += 1;
    return token;
  }

  private deeper(): void {
    this.depth += 1;
    if (this.depth > MAX_DEPTH) throw new ExprError(`the expression nests deeper than ${MAX_DEPTH} levels`);
  }

  parse(): Expr {
    if (this.toks.length === 0) throw new ExprError("the expression is empty");
    const node = this.or();
    if (this.at !== this.toks.length) throw new ExprError(`unexpected '${String(this.toks[this.at][1])}' in '${this.text}'`);
    return node;
  }

  private or(): Expr {
    let node = this.and();
    while (this.peek("kw", "or")) {
      this.take();
      node = { k: "or", a: node, b: this.and() };
    }
    return node;
  }

  private and(): Expr {
    let node = this.not();
    while (this.peek("kw", "and")) {
      this.take();
      node = { k: "and", a: node, b: this.not() };
    }
    return node;
  }

  private not(): Expr {
    if (this.peek("kw", "not")) {
      this.take();
      this.deeper();
      const node: Expr = { k: "not", a: this.not() };
      this.depth -= 1;
      return node;
    }
    return this.compare();
  }

  private compare(): Expr {
    const node = this.sum();
    for (const op of COMPARISONS) {
      if (this.peek("op", op)) {
        this.take();
        return { k: "cmp", op, a: node, b: this.sum() };
      }
    }
    return node;
  }

  private sum(): Expr {
    let node = this.product();
    while (this.peek("op", "+") || this.peek("op", "-")) {
      const op = String(this.take()[1]);
      node = { k: "bin", op, a: node, b: this.product() };
    }
    return node;
  }

  private product(): Expr {
    let node = this.unary();
    while (this.peek("op", "*") || this.peek("op", "/") || this.peek("op", "%")) {
      const op = String(this.take()[1]);
      node = { k: "bin", op, a: node, b: this.unary() };
    }
    return node;
  }

  private unary(): Expr {
    if (this.peek("op", "-")) {
      this.take();
      this.deeper();
      const node: Expr = { k: "neg", a: this.unary() };
      this.depth -= 1;
      return node;
    }
    return this.atom();
  }

  private atom(): Expr {
    const token = this.peek();
    if (!token) throw new ExprError(`the expression '${this.text}' ends too soon`);
    if (token[0] === "lit") {
      this.take();
      return { k: "lit", v: token[1] };
    }
    if (token[0] === "col") {
      this.take();
      return { k: "col", name: token[1] };
    }
    if (token[0] === "kw" && (token[1] === "true" || token[1] === "false" || token[1] === "null")) {
      this.take();
      return { k: "lit", v: token[1] === "true" ? true : token[1] === "false" ? false : null };
    }
    if (token[0] === "name") {
      const name = token[1];
      this.take();
      if (!this.peek("op", "(")) return { k: "col", name };
      const counts = FUNCTIONS.get(name);
      if (!counts) throw new ExprError(`${name} is not a function: use abs, round, min or max`);
      this.take();
      this.deeper();
      const args = [this.or()];
      while (this.peek("op", ",")) {
        this.take();
        args.push(this.or());
      }
      this.take("op", ")");
      this.depth -= 1;
      const [least, most] = counts;
      if (args.length < least || (most !== null && args.length > most)) {
        throw new ExprError(`${name} takes ${arity(name)}, not ${args.length}`);
      }
      return { k: "call", name, args };
    }
    if (token[0] === "op" && token[1] === "(") {
      this.take();
      this.deeper();
      const node = this.or();
      this.take("op", ")");
      this.depth -= 1;
      return node;
    }
    throw new ExprError(`unexpected '${String(token[1])}' in '${this.text}'`);
  }
}

/** The expression *text*, parsed. ExprError when it is not one. */
export function parseExpr(text: string): Expr {
  if (typeof text !== "string") throw new ExprError("an expression is a text");
  return new Parser(text).parse();
}

/** Why *text* is not an expression, or null when it is one. */
export function exprProblem(text: string): string | null {
  try {
    parseExpr(text);
    return null;
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  }
}

/** A value as the language sees it: a number, a text, true, false or null. */
function scalar(value: unknown): ExprValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  return null;
}

/** *value* as a finite number, or null when it is not one (true and false are not numbers). */
export function exprNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** A number an expression makes: null when it is not finite, else kept to 15 significant digits. Zero has no sign. */
export function exprResult(value: number): number | null {
  if (!Number.isFinite(value)) return null;
  if (value === 0) return 0;
  return Number(value.toPrecision(15));
}

/** Whether a value counts as true: anything but null, false, 0 and ''. */
export function truthy(value: ExprValue): boolean {
  return !(value === null || value === false || value === "" || value === 0);
}

function roundHalfAway(value: number, digits: number): number {
  const places = Math.max(-15, Math.min(15, Math.trunc(digits)));
  const scaled = places >= 0 ? Math.abs(value) * TENS[places] + 0.5 : Math.abs(value) / TENS[-places] + 0.5;
  if (!Number.isFinite(scaled)) return value;
  const floor = Math.floor(scaled);
  const rounded = places >= 0 ? floor / TENS[places] : floor * TENS[-places];
  return value < 0 ? -rounded : rounded;
}

function arithmetic(op: string, a: ExprValue, b: ExprValue): ExprValue {
  const x = exprNumber(a);
  const y = exprNumber(b);
  if (x === null || y === null) return op === "+" && typeof a === "string" && typeof b === "string" ? a + b : null;
  if (op === "+") return exprResult(x + y);
  if (op === "-") return exprResult(x - y);
  if (op === "*") return exprResult(x * y);
  if (y === 0) return null;
  return op === "/" ? exprResult(x / y) : exprResult(x % y);
}

function compare(op: string, left: ExprValue, right: ExprValue): boolean {
  if (left === null || right === null) return false;
  let a: number | string;
  let b: number | string;
  if (typeof left === "number" && typeof right === "number") {
    [a, b] = [left, right];
  } else if (typeof left === "boolean" && typeof right === "boolean") {
    [a, b] = [Number(left), Number(right)];
  } else if (typeof left === "string" && typeof right === "string") {
    [a, b] = [left, right];
  } else {
    return op === "!=";
  }
  switch (op) {
    case "==": return a === b;
    case "!=": return a !== b;
    case "<": return a < b;
    case "<=": return a <= b;
    case ">": return a > b;
    default: return a >= b;
  }
}

function call(name: string, args: ExprValue[]): ExprValue {
  const numbers = args.map(exprNumber);
  if (numbers.some((n) => n === null)) return null;
  const ns = numbers as number[];
  if (name === "abs") return exprResult(Math.abs(ns[0]));
  if (name === "round") return exprResult(roundHalfAway(ns[0], ns.length > 1 ? ns[1] : 0));
  if (name === "min") return exprResult(Math.min(...ns));
  return exprResult(Math.max(...ns));
}

/** What the parsed expression *node* makes of one feature's properties *row*. */
export function evaluate(node: Expr, row: Record<string, unknown>): ExprValue {
  switch (node.k) {
    case "lit": return node.v;
    case "col": return row != null && Object.prototype.hasOwnProperty.call(row, node.name) ? scalar(row[node.name]) : null;
    case "not": return !truthy(evaluate(node.a, row));
    case "and": return truthy(evaluate(node.a, row)) && truthy(evaluate(node.b, row));
    case "or": return truthy(evaluate(node.a, row)) || truthy(evaluate(node.b, row));
    case "neg": {
      const value = exprNumber(evaluate(node.a, row));
      return value === null ? null : exprResult(-value);
    }
    case "bin": return arithmetic(node.op, evaluate(node.a, row), evaluate(node.b, row));
    case "cmp": return compare(node.op, evaluate(node.a, row), evaluate(node.b, row));
    case "call": return call(node.name, node.args.map((arg) => evaluate(arg, row)));
  }
}
