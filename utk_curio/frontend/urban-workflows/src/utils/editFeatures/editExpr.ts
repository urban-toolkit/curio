/**
 * The Interaction node's expressions: the conditions its edits pick features
 * by (`where`) and the formulas an `expr` edit writes, over one feature's
 * properties. The twin of `utk_curio/sandbox/util/edit_expr.py`; both read
 * `applyEdits.cases.json`, so the map's preview and the node's run agree.
 *
 * - a column: a name (`height`, `building:levels`), or any name in backticks;
 * - a number, a text in quotes, `true`, `false`, `null`;
 * - `+ - * / %`, a leading `-`, `== != < <= > >=`, `and`, `or`, `not`, parentheses;
 * - `abs`, `min`, `max`, `round`.
 *
 * A column a feature lacks is null; arithmetic with null or a text is null; a
 * comparison with null is false.
 */

export type ExprValue = number | string | boolean | null;

type Node =
  | { k: "lit"; v: ExprValue }
  | { k: "col"; name: string }
  | { k: "not"; a: Node }
  | { k: "and" | "or"; a: Node; b: Node }
  | { k: "neg"; a: Node }
  | { k: "bin"; op: string; a: Node; b: Node }
  | { k: "cmp"; op: string; a: Node; b: Node }
  | { k: "call"; name: string; args: Node[] };

export type Expr = Node;

export class ExprError extends Error {}

const TOKEN = new RegExp(
  "\\s*(?:"
  + "(?<num>\\d+(?:\\.\\d*)?(?:[eE][+-]?\\d+)?|\\.\\d+(?:[eE][+-]?\\d+)?)"
  + "|(?<str>'(?:[^'\\\\]|\\\\.)*'|\"(?:[^\"\\\\]|\\\\.)*\")"
  + "|(?<tick>`[^`]*`)"
  + "|(?<name>[A-Za-z_][A-Za-z0-9_:.]*)"
  + "|(?<op>==|!=|<=|>=|[-+*/%<>(),])"
  + ")",
  "y",
);
const KEYWORDS = new Set(["and", "or", "not", "true", "false", "null"]);
const FUNCTIONS = new Set(["abs", "min", "max", "round"]);

type Token = ["num", number] | ["str", string] | ["col", string] | ["kw", string] | ["name", string] | ["op", string];

function tokens(text: string): Token[] {
  const out: Token[] = [];
  let pos = 0;
  while (pos < text.length) {
    if (text.slice(pos).trim() === "") break;
    TOKEN.lastIndex = pos;
    const m = TOKEN.exec(text);
    if (!m || m.index !== pos || TOKEN.lastIndex === pos) {
      throw new ExprError(`cannot read '${text.slice(pos).trim().slice(0, 20)}' in '${text}'`);
    }
    pos = TOKEN.lastIndex;
    const g = m.groups ?? {};
    if (g.num !== undefined) out.push(["num", Number(g.num)]);
    else if (g.str !== undefined) out.push(["str", g.str.slice(1, -1).replace(/\\(.)/g, "$1")]);
    else if (g.tick !== undefined) out.push(["col", g.tick.slice(1, -1)]);
    else if (g.name !== undefined) out.push(KEYWORDS.has(g.name) ? ["kw", g.name] : ["name", g.name]);
    else out.push(["op", g.op]);
  }
  return out;
}

class Parser {
  private at = 0;
  private readonly toks: Token[];
  constructor(private readonly text: string) {
    this.toks = tokens(text);
  }
  private peek(kind?: string, value?: unknown): Token | null {
    const t = this.toks[this.at];
    if (!t) return null;
    if (kind !== undefined && t[0] !== kind) return null;
    if (value !== undefined && t[1] !== value) return null;
    return t;
  }
  private take(kind?: string, value?: unknown): Token {
    const t = this.peek(kind, value);
    if (!t) throw new ExprError(`expected ${String(value ?? kind ?? "more")} in '${this.text}'`);
    this.at += 1;
    return t;
  }
  parse(): Node {
    if (this.toks.length === 0) throw new ExprError("the expression is empty");
    const node = this.or();
    if (this.at !== this.toks.length) throw new ExprError(`unexpected '${String(this.toks[this.at][1])}' in '${this.text}'`);
    return node;
  }
  private or(): Node {
    let node = this.and();
    while (this.peek("kw", "or")) { this.take(); node = { k: "or", a: node, b: this.and() }; }
    return node;
  }
  private and(): Node {
    let node = this.not();
    while (this.peek("kw", "and")) { this.take(); node = { k: "and", a: node, b: this.not() }; }
    return node;
  }
  private not(): Node {
    if (this.peek("kw", "not")) { this.take(); return { k: "not", a: this.not() }; }
    return this.compare();
  }
  private compare(): Node {
    const node = this.sum();
    for (const op of ["==", "!=", "<=", ">=", "<", ">"]) {
      if (this.peek("op", op)) { this.take(); return { k: "cmp", op, a: node, b: this.sum() }; }
    }
    return node;
  }
  private sum(): Node {
    let node = this.product();
    while (this.peek("op", "+") || this.peek("op", "-")) {
      const op = String(this.take()[1]);
      node = { k: "bin", op, a: node, b: this.product() };
    }
    return node;
  }
  private product(): Node {
    let node = this.unary();
    while (this.peek("op", "*") || this.peek("op", "/") || this.peek("op", "%")) {
      const op = String(this.take()[1]);
      node = { k: "bin", op, a: node, b: this.unary() };
    }
    return node;
  }
  private unary(): Node {
    if (this.peek("op", "-")) { this.take(); return { k: "neg", a: this.unary() }; }
    return this.atom();
  }
  private atom(): Node {
    const t = this.peek();
    if (!t) throw new ExprError(`the expression '${this.text}' ends too soon`);
    const [kind, value] = t;
    if (kind === "num" || kind === "str") { this.take(); return { k: "lit", v: value }; }
    if (kind === "kw" && (value === "true" || value === "false" || value === "null")) {
      this.take();
      return { k: "lit", v: value === "true" ? true : value === "false" ? false : null };
    }
    if (kind === "col") { this.take(); return { k: "col", name: value }; }
    if (kind === "name") {
      this.take();
      if (this.peek("op", "(")) {
        if (!FUNCTIONS.has(value)) throw new ExprError(`${value} is not a function here: use abs, min, max or round`);
        this.take();
        const args = [this.or()];
        while (this.peek("op", ",")) { this.take(); args.push(this.or()); }
        this.take("op", ")");
        return { k: "call", name: value, args };
      }
      return { k: "col", name: value };
    }
    if (kind === "op" && value === "(") {
      this.take();
      const node = this.or();
      this.take("op", ")");
      return node;
    }
    throw new ExprError(`unexpected '${String(value)}' in '${this.text}'`);
  }
}

/** The expression *text*, parsed; ExprError when it is not one. */
export function parseExpr(text: string): Expr {
  return new Parser(text ?? "").parse();
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

const asNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const plain = (value: unknown): ExprValue => {
  if (value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" || typeof value === "boolean" || value === null) return value;
  return null;
};

/** Round half away from zero (as the sandbox does). */
function roundAway(value: number, digits: number): number {
  const scale = 10 ** digits;
  const rounded = Math.floor(Math.abs(value) * scale + 0.5) / scale;
  return value < 0 ? -rounded : rounded;
}

/** Keep floating-point noise out of a result, as the sandbox's floats print. */
const tidy = (value: number): number => Number(value.toPrecision(15));

export function truthy(value: ExprValue): boolean {
  return value !== null && value !== false && value !== 0 && value !== "";
}

/** *node* over one feature's properties *row*. */
export function evaluate(node: Expr, row: Record<string, unknown>): ExprValue {
  switch (node.k) {
    case "lit": return node.v;
    case "col": return plain(row[node.name]);
    case "not": return !truthy(evaluate(node.a, row));
    case "and": return truthy(evaluate(node.a, row)) && truthy(evaluate(node.b, row));
    case "or": return truthy(evaluate(node.a, row)) || truthy(evaluate(node.b, row));
    case "neg": {
      const v = asNumber(evaluate(node.a, row));
      return v === null ? null : tidy(-v);
    }
    case "bin": {
      const a = evaluate(node.a, row);
      const b = evaluate(node.b, row);
      const x = asNumber(a);
      const y = asNumber(b);
      if (x === null || y === null) return node.op === "+" && typeof a === "string" && typeof b === "string" ? a + b : null;
      if (node.op === "+") return tidy(x + y);
      if (node.op === "-") return tidy(x - y);
      if (node.op === "*") return tidy(x * y);
      if (y === 0) return null;
      return node.op === "/" ? tidy(x / y) : tidy(x % y);
    }
    case "cmp": {
      let a: ExprValue = evaluate(node.a, row);
      let b: ExprValue = evaluate(node.b, row);
      if (a === null || b === null) return false;
      const x = asNumber(a);
      const y = asNumber(b);
      if (x !== null && y !== null) { a = x; b = y; } else if (typeof a !== typeof b) return node.op === "!=";
      switch (node.op) {
        case "==": return a === b;
        case "!=": return a !== b;
        case "<": return (a as any) < (b as any);
        case "<=": return (a as any) <= (b as any);
        case ">": return (a as any) > (b as any);
        default: return (a as any) >= (b as any);
      }
    }
    case "call": {
      const numbers = node.args.map((arg) => asNumber(evaluate(arg, row)));
      if (numbers.some((n) => n === null)) return null;
      const ns = numbers as number[];
      if (node.name === "abs" && ns.length === 1) return Math.abs(ns[0]);
      if (node.name === "round") return tidy(roundAway(ns[0], ns.length > 1 ? Math.trunc(ns[1]) : 0));
      if (node.name === "min" && ns.length) return Math.min(...ns);
      if (node.name === "max" && ns.length) return Math.max(...ns);
      throw new ExprError(`${node.name} takes ${node.name === "abs" ? "one argument" : "numbers"}`);
    }
  }
}
