/**
 * The Map Edits node (its type id is still `curio.builtin/edit-features`): the
 * features picked on its map removed, put back or given new values. The
 * node's code is its only state, one call of the sandbox's `curio_map_edits`
 * (`utk_curio/sandbox/util/map_edits.py`), which this module writes
 * (`mapEditsCode`) and reads back (`readMapEdits`):
 *
 *     return curio_map_edits(
 *         input_0,
 *         key="building_id",
 *         remove=[8, 10],
 *         change={34: {"height": 60}},
 *     )
 *
 * - `key`, the column that identifies a feature: `osm_id`, or `building_id`,
 *   which every part of a building repeats;
 * - `layer`, the layer the edits apply to, when the input names several;
 * - `remove`, the ids of the features taken out;
 * - `change`, per id, the values written into its features' properties.
 *
 * Features are matched by their key's value, never by their place. Code of
 * another shape is never rewritten: the reader says why it cannot read it, and
 * the run still runs it. `changeFromField` turns an Apply in the node's
 * properties panel into the change for one id, and `applyMapEdits` applies the
 * edits in the browser, for the node's map, as a run applies them.
 */
import { REFERENCE_PATTERN, widgetLiteral } from "../references/codeReferences";

/** What the node's code calls (`utk_curio/sandbox/util/map_edits.py`). */
export const MAP_EDITS_HELPER = "curio_map_edits";

/** A value of the column that identifies a feature. */
export type FeatureId = string | number;

/** A value a change writes: anything the properties panel's JSON holds. */
export type JsonValue = null | boolean | number | string | JsonValue[] | { [name: string]: JsonValue };

/** The values a change writes, by property name. */
export type ChangeValues = Record<string, JsonValue>;

/** The values written into the features of one id. */
export interface FeatureChange {
  id: FeatureId;
  values: ChangeValues;
}

/**
 * What the node's code holds. `change` is a list in the order the ids were
 * first changed, so a number id stays a number.
 */
export interface MapEdits {
  key?: string;
  layer?: string;
  remove: FeatureId[];
  change: FeatureChange[];
}

/** What `readMapEdits` makes of a node's code. */
export type MapEditsRead =
  /** The edits, and the comment lines above the call; none for a new node. */
  | { edits: MapEdits; comments?: string[] }
  /** Why the code is not one the node writes. */
  | { problem: string };

/** A feature's properties, as the map drew them or as the input has them. */
export type Properties = Record<string, unknown>;

/** A GeoJSON feature, as the node's map draws it. */
export interface MapFeature {
  properties?: Properties | null;
  [member: string]: unknown;
}

/** The property a feature's geometry would clash with once it is a table's row. */
const GEOMETRY = "geometry";

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const has = (object: Record<string, unknown>, name: string): boolean =>
  Object.prototype.hasOwnProperty.call(object, name) && object[name] !== undefined;

/** Whether *value* can name a feature: a text, or a finite number. */
export function isFeatureId(value: unknown): value is FeatureId {
  return typeof value === "string" || (typeof value === "number" && Number.isFinite(value));
}

/** An id as the sandbox compares it (`_id_key`): a number by its value, a text as it is. */
const idKey = (id: FeatureId): string => `${typeof id}:${id}`;

/** Whether *a* and *b* are one id: 12 and 12.0 are, "12" and 12 are not. */
export function sameId(a: FeatureId, b: FeatureId): boolean {
  return typeof a === typeof b && a === b;
}

/** Whether two JSON values are equal, objects whatever the order of their keys. */
function sameJson(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((item, i) => sameJson(item, b[i]));
  }
  if (!isObject(a) || !isObject(b)) return false;
  const names = Object.keys(a).filter((name) => has(a, name));
  return names.length === Object.keys(b).filter((name) => has(b, name)).length
    && names.every((name) => has(b, name) && sameJson(a[name], b[name]));
}

/**
 * U+0085, U+2028 and U+2029: line breaks to Python's `splitlines`, which JSON
 * leaves in a text. The headless runner indents a node's code with
 * `textwrap.indent`, which splits lines there.
 */
const UNICODE_BREAKS = String.fromCharCode(0x85, 0x2028, 0x2029);
const LINE_BREAKS = new RegExp(`[${UNICODE_BREAKS}]`, "g");
/** Every line break `splitlines` knows. */
const ANY_BREAK = new RegExp(`[\\n\\r\\v\\f\\x1c-\\x1e${UNICODE_BREAKS}]`, "g");

/** The node's own comment lines above its call, naming its key. */
export function mapEditsComment(key?: string): string[] {
  // A line break in a column's name would end the comment.
  const by = key ? key.replace(ANY_BREAK, " ") : "the Id column";
  return [
    "# Map Edits writes this code from its map: the features it removes and the",
    `# values it changes, matched by ${by}. Comment lines above the return stay.`,
  ];
}

const OWN_SECOND_LINE = /^# values it changes, matched by .*\. Comment lines above the return stay\.$/;

/** Whether *comments* open with the node's own lines, for any key. */
const opensWithOwnLines = (comments: readonly string[]): boolean =>
  comments[0] === mapEditsComment()[0] && OWN_SECOND_LINE.test(comments[1] ?? "");

/**
 * *value* as a Python literal, its texts as `widgetLiteral` writes them, with
 * two escapes more: the line breaks JSON leaves in a text (`UNICODE_BREAKS`),
 * and `[!!` as `[\x21!`, so no text reads as a reference.
 */
function pyLiteral(value: JsonValue): string {
  if (Array.isArray(value)) return `[${value.map(pyLiteral).join(", ")}]`;
  if (isObject(value)) {
    return `{${Object.entries(value).map(([name, item]) => `${pyLiteral(name)}: ${pyLiteral(item)}`).join(", ")}}`;
  }
  const literal = widgetLiteral(value, "python");
  if (typeof value !== "string") return literal;
  return literal
    .replace(LINE_BREAKS, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`)
    .split("[!!").join("[\\x21!");
}

/**
 * The node's code for *edits*. *comments* are the lines the reader found above
 * the call, kept as they are; without them (a new node), the node's own. Where
 * the node's own lines open *comments*, they are written for the current key.
 */
export function mapEditsCode(edits: MapEdits, comments?: readonly string[]): string {
  const own = mapEditsComment(edits.key);
  const lines = comments === undefined ? own : opensWithOwnLines(comments) ? [...own, ...comments.slice(2)] : [...comments];
  const entry = (c: FeatureChange) => `${pyLiteral(c.id)}: ${pyLiteral(c.values)}`;
  const change = edits.change.filter((c) => isFeatureId(c.id));
  const args = [
    "    input_0,",
    ...(edits.key ? [`    key=${pyLiteral(edits.key)},`] : []),
    ...(edits.layer ? [`    layer=${pyLiteral(edits.layer)},`] : []),
    `    remove=[${edits.remove.filter(isFeatureId).map(pyLiteral).join(", ")}],`,
    // One change on the call's line, several one per line.
    ...(change.length <= 1
      ? [`    change={${change.map(entry).join("")}},`]
      : ["    change={", ...change.map((c) => `        ${entry(c)},`), "    },"]),
  ];
  return [...lines, `return ${MAP_EDITS_HELPER}(`, ...args, ")", ""].join("\n");
}

/** Why the code cannot be read; caught by `readMapEdits`. */
class Unreadable extends Error {}

/** A Python literal as the reader found it: a dict keeps its keys' types. */
type Literal =
  | { kind: "value"; value: null | boolean | number | string }
  | { kind: "list"; items: Literal[] }
  | { kind: "dict"; entries: Array<[Literal, Literal]> };

const KEYWORDS = ["key", "layer", "remove", "change"];
const NOT_THE_CALL = "Map Edits reads one call, return curio_map_edits(input_0, ...), and this code holds something else.";
const ESCAPES: Record<string, string> = {
  "\\": "\\", "'": "'", '"': '"', a: "\x07", b: "\b", f: "\f", n: "\n", r: "\r", t: "\t", v: "\v",
};

/**
 * The call's arguments by keyword, read from *text* at *start*, just after
 * `curio_map_edits(`. Values are Python literals: texts in single or double
 * quotes with Python's escapes, numbers, True, False, None, lists and dicts.
 * Whitespace and line breaks may stand between any two tokens, and a list, a
 * dict or the call may end in a comma.
 */
function readCall(text: string, start: number): Map<string, Literal> {
  let pos = start;
  const fail = (what: string): never => {
    throw new Unreadable(`Line ${text.slice(0, pos).split(/\r\n|\r|\n/).length}: ${what}.`);
  };
  /** Fails with *what*, or with the call not closed when the code ends first. */
  const missing = (what: string): never => fail(pos >= text.length ? "the call is not closed" : what);
  const skip = () => {
    while (pos < text.length) {
      const c = text[pos];
      if (c === "#") throw new Unreadable("The call holds a comment, which Map Edits would lose when it writes its code.");
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
    return fail(c === "\n" || c === "\r" ? "a text goes on past its line" : `\\${c ?? ""} is not an escape Map Edits reads`);
  };
  const string = (): string => {
    const quote = text[pos];
    if (text.startsWith(quote.repeat(3), pos)) fail("Map Edits reads texts in single or double quotes, not in triple quotes");
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
    if (/[A-Za-z0-9_.]/.test(text[pos] ?? "")) fail(`${found[0]}${text[pos]} is not a number Map Edits reads`);
    const whole = /^\d+$/.test(found[0]);
    if (whole && /^0+[1-9]/.test(found[0])) fail(`${found[0]} starts with a zero, which Python refuses`);
    const value = sign * Number(found[0]);
    if (!Number.isFinite(value) || (whole && !Number.isSafeInteger(value))) fail(`${found[0]} is too large to read exactly`);
    return value;
  };
  const value = (): Literal => {
    skip();
    const c = text[pos];
    if (c === "[") {
      pos++;
      const items: Literal[] = [];
      for (;;) {
        skip();
        if (text[pos] === "]") break;
        items.push(value());
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
        const key = value();
        skip();
        if (text[pos] !== ":") missing("a key of a dict has no : after it");
        pos++;
        entries.push([key, value()]);
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
    if (name !== null) return fail(`${name} is not a value written out`);
    return fail(c === undefined ? "the call is not closed" : `${c} does not start a value Map Edits reads`);
  };

  const args = new Map<string, Literal>();
  skip();
  const input = word();
  skip();
  if (input !== "input_0") throw new Unreadable("The call's first argument is not input_0.");
  if (text[pos] !== "," && text[pos] !== ")") missing("input_0 has no , or ) after it");
  while (text[pos] !== ")") {
    pos++;
    skip();
    if (text[pos] === ")") break;
    const name = word();
    skip();
    if (name === null || text[pos] !== "=" || text[pos + 1] === "=") {
      if (pos >= text.length) fail("the call is not closed");
      throw new Unreadable("After input_0, the call takes key, layer, remove and change, by name.");
    }
    if (!KEYWORDS.includes(name)) throw new Unreadable(`curio_map_edits takes key, layer, remove and change, not ${name}.`);
    if (args.has(name)) throw new Unreadable(`The call gives ${name} twice.`);
    pos++;
    args.set(name, value());
    skip();
    if (text[pos] !== "," && text[pos] !== ")") missing("an argument has no , or ) after it");
  }
  pos++;
  if (!/^[ \t\f\r\n]*$/.test(text.slice(pos))) throw new Unreadable("The code goes on after the curio_map_edits call.");
  return args;
}

/** *literal* as Python's `repr` would show it, in a reason. */
function shown(literal: Literal): string {
  if (literal.kind === "list") return "a list";
  if (literal.kind === "dict") return "a dict";
  if (literal.value === null) return "None";
  if (typeof literal.value === "boolean") return literal.value ? "True" : "False";
  return typeof literal.value === "string" ? JSON.stringify(literal.value) : String(literal.value);
}

function idOf(literal: Literal): FeatureId {
  if (literal.kind === "value" && isFeatureId(literal.value)) return literal.value;
  throw new Unreadable(`${shown(literal)} is not an id: an id is a number or a text.`);
}

function textOf(literal: Literal | undefined, name: string): string | undefined {
  if (literal === undefined || (literal.kind === "value" && (literal.value === null || literal.value === ""))) return undefined;
  if (literal.kind === "value" && typeof literal.value === "string") return literal.value;
  throw new Unreadable(`${name} is not a text.`);
}

/** *literal* as JSON: a dict's keys must be texts, each once. */
function jsonOf(literal: Literal): JsonValue {
  if (literal.kind === "value") return literal.value;
  if (literal.kind === "list") return literal.items.map(jsonOf);
  return Object.fromEntries(namedEntries(literal.entries));
}

function namedEntries(entries: Array<[Literal, Literal]>): Array<[string, JsonValue]> {
  const seen = new Set<string>();
  return entries.map(([name, item]) => {
    if (name.kind !== "value" || typeof name.value !== "string") {
      throw new Unreadable(`A dict in change has the key ${shown(name)}, which is not a text.`);
    }
    if (seen.has(name.value)) throw new Unreadable(`A dict in change gives ${name.value} twice.`);
    seen.add(name.value);
    return [name.value, jsonOf(item)];
  });
}

/** The edits the call's arguments hold. */
function editsOf(args: Map<string, Literal>): MapEdits {
  const key = textOf(args.get("key"), "key");
  const layer = textOf(args.get("layer"), "layer");
  const edits: MapEdits = { ...(key ? { key } : {}), ...(layer ? { layer } : {}), remove: [], change: [] };
  const remove = args.get("remove");
  if (remove !== undefined && !(remove.kind === "value" && remove.value === null)) {
    if (remove.kind !== "list") throw new Unreadable("remove is not a list of ids.");
    edits.remove = withRemoved(edits, remove.items.map(idOf)).remove;
  }
  const change = args.get("change");
  if (change !== undefined && !(change.kind === "value" && change.value === null)) {
    if (change.kind !== "dict") throw new Unreadable("change is not a dict of ids and the values they write.");
    for (const [name, values] of change.entries) {
      const id = idOf(name);
      // Python makes one key of 1 and 1.0, and keeps the last value.
      if (edits.change.some((c) => sameId(c.id, id))) throw new Unreadable(`change gives ${id} twice.`);
      if (values.kind !== "dict") throw new Unreadable(`change gives ${id} ${shown(values)}, not a dict of values.`);
      const written = namedEntries(values.entries);
      if (key && written.some(([column]) => column === key)) {
        throw new Unreadable(`change writes ${key} on ${id}, and ${key} identifies the features.`);
      }
      if (written.some(([column]) => column === GEOMETRY)) {
        throw new Unreadable(`change writes geometry on ${id}, which is the features' shape.`);
      }
      edits.change.push({ id, values: Object.fromEntries(written) });
    }
    // An id with nothing to write is no change.
    edits.change = edits.change.filter((c) => Object.keys(c.values).length > 0);
  }
  return edits;
}

/**
 * The edits *code* holds, and the comment lines above its call, or why the
 * node cannot read it. Blank code is a new node: no edits. Otherwise the code
 * is comment and blank lines, then `return curio_map_edits(input_0, ...)` from
 * the start of its line, its keywords `key`, `layer`, `remove` and `change` in
 * any order, each at most once, each a literal (`readCall`). Anything else is
 * refused: another statement, a comment inside the call, a reference.
 */
export function readMapEdits(code: string | null | undefined): MapEditsRead {
  const text = code ?? "";
  if (text.trim() === "") return { edits: { remove: [], change: [] } };
  const head = (/^(?:[ \t\f]*(?:#[^\r\n]*)?(?:\r\n|\r|\n))*/.exec(text) as RegExpExecArray)[0];
  const comments = head.split(/\r\n|\r|\n/).slice(0, -1);
  const call = text.slice(head.length);
  const opening = /^return[ \t\f]+curio_map_edits[ \t\f]*\(/.exec(call);
  if (!opening) {
    return { problem: /^[ \t\f]+return\b/.test(call) ? "The return line starts with spaces; Map Edits writes it from the line's start." : NOT_THE_CALL };
  }
  if (new RegExp(REFERENCE_PATTERN).test(call)) {
    return { problem: "The call holds a [!! !!] reference, whose value Map Edits cannot know before a run." };
  }
  try {
    return { edits: editsOf(readCall(text, head.length + opening[0].length)), comments };
  } catch (error) {
    if (error instanceof Unreadable) return { problem: error.message };
    throw error;
  }
}

/** *edits* with *ids* removed, each once and after the ones already removed, and without their changes. */
export function withRemoved(edits: MapEdits, ids: readonly FeatureId[]): MapEdits {
  const remove = [...edits.remove];
  const removed = new Set(remove.map(idKey));
  const now = new Set<string>();
  for (const id of ids) {
    if (!isFeatureId(id)) continue;
    now.add(idKey(id));
    if (removed.has(idKey(id))) continue;
    removed.add(idKey(id));
    remove.push(id);
  }
  return { ...edits, remove, change: edits.change.filter((c) => !now.has(idKey(c.id))) };
}

/** *edits* with *id*'s features put back. */
export function withPutBack(edits: MapEdits, id: FeatureId): MapEdits {
  return { ...edits, remove: edits.remove.filter((r) => !sameId(r, id)) };
}

/** *edits* with *values* as *id*'s change, in its place; no values drop it. */
export function withChange(edits: MapEdits, id: FeatureId, values: ChangeValues): MapEdits {
  const empty = Object.keys(values).length === 0;
  const at = edits.change.findIndex((c) => sameId(c.id, id));
  const change = [...edits.change];
  if (at >= 0 && empty) change.splice(at, 1);
  else if (at >= 0) change[at] = { id: change[at].id, values: { ...values } };
  else if (!empty) change.push({ id, values: { ...values } });
  return { ...edits, change };
}

/** The values *edits* write into *id*'s features, if any. */
export function changeFor(edits: MapEdits, id: FeatureId): ChangeValues | undefined {
  return edits.change.find((c) => sameId(c.id, id))?.values;
}

/** Whether *edits* remove *id*'s features. */
export function isRemoved(edits: MapEdits, id: FeatureId): boolean {
  return edits.remove.some((r) => sameId(r, id));
}

/** What an Apply in the properties panel works from, for one feature. */
export interface FieldEdit {
  /** The feature as the map drew it before this Apply: its input properties with the node's change for its id written in. */
  shown: Properties | null | undefined;
  /** The same feature as the input has it. */
  original: Properties | null | undefined;
  /** What the field holds, parsed. */
  edited: unknown;
  /** The column that identifies a feature. */
  key: string | undefined;
  /** The values the node's change for the feature's id writes now. */
  current?: ChangeValues;
}

/** What an Apply makes: *id*'s new change, and what this Apply wrote, for its label. */
export type FieldChange =
  | { values: ChangeValues; written: ChangeValues }
  | { noChange: true }
  | { problem: string };

/**
 * The change an Apply makes of *field*: the current change, with each value
 * that differs from the feature as shown written, and a key the field no
 * longer holds written as null; then a value equal to the input's is dropped,
 * so a value typed back to the input's leaves the edits (a null for a key the
 * input lacks is equal). Untouched values are never written, a derived height
 * included. An Apply that writes nothing new is no change. The key's value
 * and the geometry cannot change.
 */
export function changeFromField({ shown, original, edited, key, current = {} }: FieldEdit): FieldChange {
  if (!key) return { problem: "Pick the column that identifies a feature first." };
  if (!isObject(edited)) return { problem: "The field holds the feature's properties as one JSON object, such as {\"height\": 60}." };
  const before = shown ?? {};
  const input = original ?? {};
  const written: Array<[string, JsonValue]> = [];
  for (const [name, value] of Object.entries(edited)) {
    if (!has(before, name) || !sameJson(before[name], value)) written.push([name, value as JsonValue]);
  }
  for (const name of Object.keys(before)) {
    if (has(before, name) && before[name] !== null && !has(edited, name)) written.push([name, null]);
  }
  if (written.length === 0) return { noChange: true };
  if (written.some(([name]) => name === key)) return { problem: `${key} identifies the feature, so its value cannot change.` };
  if (written.some(([name]) => name === GEOMETRY)) return { problem: "geometry is the feature's shape, which Map Edits cannot set." };
  const merged = new Map<string, JsonValue>(Object.entries(current));
  for (const [name, value] of written) merged.set(name, value);
  const asInput = (name: string, value: JsonValue) => (has(input, name) ? sameJson(input[name], value) : value === null);
  const values = Object.fromEntries([...merged].filter(([name, value]) => !asInput(name, value)));
  if (sameJson(values, current)) return { noChange: true };
  return { values, written: Object.fromEntries(written) };
}

const LABEL_VALUE_CHARS = 24;
const LABEL_ITEMS = 5;

const by = (key: string | undefined) => (key ? `${key} ` : "");

function shortValue(value: JsonValue): string {
  if (value === null) return "cleared";
  const text = JSON.stringify(value);
  return text.length > LABEL_VALUE_CHARS ? text.slice(0, LABEL_VALUE_CHARS - 1) + "…" : text;
}

function listed(items: readonly string[]): string {
  const more = items.length - LABEL_ITEMS;
  return items.slice(0, LABEL_ITEMS).join(", ") + (more > 0 ? ` and ${more} more` : "");
}

/** A Remove's entry in the node's Provenance drawer: "remove building_id 12". */
export function removeLabel(key: string | undefined, ids: readonly FeatureId[]): string {
  return `remove ${by(key)}${listed(ids.map(String))}`;
}

/** A put back's entry: "put back building_id 12". */
export function putBackLabel(key: string | undefined, id: FeatureId): string {
  return `put back ${by(key)}${id}`;
}

/** An Apply's entry, from what it wrote: "height 60, name cleared on building_id 34". */
export function changeLabel(key: string | undefined, id: FeatureId, written: ChangeValues): string {
  const parts = Object.entries(written).map(([name, value]) => `${name} ${shortValue(value)}`);
  return `${listed(parts)} on ${by(key)}${id}`;
}

/**
 * *features* as the node's edits leave them, for its map: those whose key's
 * value is removed dropped, and copies of those a change names with its values
 * written into their properties. Every other feature is handed on as it is,
 * and *features* is never changed. With no key, nothing applies.
 */
export function applyMapEdits<F extends MapFeature>(features: readonly F[], edits: MapEdits): F[] {
  const key = edits.key;
  if (!key || (edits.remove.length === 0 && edits.change.length === 0)) return [...features];
  const gone = new Set(edits.remove.filter(isFeatureId).map(idKey));
  const written = new Map<string, ChangeValues>();
  for (const { id, values } of edits.change) {
    if (isFeatureId(id)) written.set(idKey(id), { ...(written.get(idKey(id)) ?? {}), ...values });
  }
  const out: F[] = [];
  for (const feature of features) {
    const value = feature?.properties?.[key];
    const id = isFeatureId(value) ? idKey(value) : null;
    if (id !== null && gone.has(id)) continue;
    const values = id === null ? undefined : written.get(id);
    out.push(values ? { ...feature, properties: { ...(feature.properties ?? {}), ...values } } : feature);
  }
  return out;
}
