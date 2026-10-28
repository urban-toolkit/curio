/**
 * A dataflow's Trill and its Yjs doc, each made from the other: the canvas's
 * side of the server's mapping (`collaboration/doc_mapping.py`), read from the
 * same layout (`src/contracts/dataflowDoc.json`). The server and every tab so
 * build the same doc from the same Trill, and the same Trill from the same doc.
 *
 * **Keys and values.** A map's keys, and the items of the order arrays
 * (`nodeOrder`, `edgeOrder`, `scenarioOrder`, a node's `widgetOrder`), are
 * plain strings: node and edge ids, scenario ids, widget names. Every other
 * value that is not a shared type is the JSON text of its value, plain strings
 * included. A node's `place`, `size` and `pin` are one value each; its
 * `content` is a `Y.Text`; its `metadata` is a map with each setting as its own
 * key; its `widgets` (a map by name of `definition` and `value`) and
 * `widgetOrder` hold `metadata.widgets`.
 *
 * A list whose entries cannot each be keyed is kept whole, as one value under
 * its Trill name. Trill comes out in the layout's order, then the fields the
 * layout does not name, sorted.
 *
 * Where the two sides differ, by necessity:
 * - places in a text are UTF-16 code units here, as in Yjs; pycrdt counts
 *   UTF-8 bytes;
 * - JavaScript has one kind of number, so `5` and `5.0` read alike here, and
 *   two values are the same when they decode to equal values, whatever the
 *   order of their keys.
 */
import * as Y from "yjs";

import layoutJson from "../../contracts/dataflowDoc.json";
import { changedStretch } from "../../utils/textStretch";

type Json = unknown;
type Fields = Record<string, Json>;

interface Layout {
    layout: number;
    event: string;
    roots: Record<string, string>;
    meta: string[];
    outsideTheDoc: string[];
    dataflow: Record<string, string>;
    node: Record<string, string>;
    metadata: Record<string, string>;
    widget: Record<string, string>;
    edge: Record<string, string>;
    scenario: Record<string, string>;
}

/** The doc's layout, shared with the server. */
export const LAYOUT: Layout = layoutJson as Layout;
/** The Socket.IO event the doc's messages travel in. */
export const DOC_EVENT: string = LAYOUT.event;
/** The `dataflow` sections the server keeps beside the doc, never in it. */
export const OUTSIDE_THE_DOC: ReadonlySet<string> = new Set(LAYOUT.outsideTheDoc);
/** The origin of the transaction that builds a doc from Trill. */
export const TRILL_ORIGIN = "trill";

const KEY = "@key";
const TEXT = "@text";
const METADATA = "@metadata";
const WIDGETS = "@widgets";
const NODES = "@nodes";
const EDGES = "@edges";
const SCENARIOS = "@scenarios";

/** A node's keys for its widgets, and a widget's keys. */
export const WIDGETS_KEY = "widgets";
export const WIDGET_ORDER_KEY = "widgetOrder";
const DEFINITION_KEY = "definition";
const VALUE_KEY = "value";

function fieldOf(table: Record<string, string>, target: string): string {
    const names = Object.keys(table).filter((name) => table[name] === target);
    if (names.length !== 1) throw new Error(`the layout names ${names.length} fields at ${target}`);
    return names[0];
}

const NODE_TABLE = LAYOUT.node;
const METADATA_TABLE = LAYOUT.metadata;
const WIDGET_TABLE = LAYOUT.widget;
const SCENARIO_TABLE = LAYOUT.scenario;

/** The Trill fields that name an entry. */
export const NODE_ID = fieldOf(NODE_TABLE, KEY);
export const EDGE_ID = fieldOf(LAYOUT.edge, KEY);
const SCENARIO_ID = fieldOf(SCENARIO_TABLE, KEY);
const WIDGET_NAME = fieldOf(WIDGET_TABLE, KEY);
/** The node fields that hold its code and its settings. */
export const CONTENT = fieldOf(NODE_TABLE, TEXT);
const NODE_METADATA = fieldOf(NODE_TABLE, METADATA);
const WIDGET_VALUE = fieldOf(WIDGET_TABLE, VALUE_KEY);

/** A node's grouped values: group -> {member: Trill field}. */
const GROUPS: Record<string, Record<string, string>> = {};
for (const [name, place] of Object.entries(NODE_TABLE)) {
    if (place.includes(".")) {
        const [group, member] = place.split(".", 2);
        (GROUPS[group] ??= {})[member] = name;
    }
}

/** Every key the layout gives a node's map. */
export const NODE_DOC_KEYS: ReadonlySet<string> = new Set([
    ...Object.values(NODE_TABLE).filter((place) => !place.startsWith("@") && !place.includes(".")),
    ...Object.keys(GROUPS),
    CONTENT, NODE_METADATA, WIDGETS_KEY, WIDGET_ORDER_KEY,
]);

/** A Trill the layout has no place for. */
export class DocMappingError extends Error {}

// ---------------------------------------------------------------------------
// Values
// ---------------------------------------------------------------------------

/** *value* as the JSON text the doc holds; a number that is not finite is null. */
export function encode(value: Json): string {
    return JSON.stringify(value === undefined ? null : value);
}

/** The value a doc holds as JSON text. A text that is not JSON is kept as it is. */
export function decode(value: unknown): Json {
    if (typeof value === "string") {
        try {
            return JSON.parse(value);
        } catch {
            return value;
        }
    }
    if (value instanceof Y.Text) return value.toString();
    if (value instanceof Y.Map || value instanceof Y.Array) return value.toJSON();
    return value;
}

/** A field a Trill object does not hold. */
export const MISSING: unique symbol = Symbol("missing");
type Maybe = Json | typeof MISSING;

function canonical(value: Json): Json {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === "object") {
        const out: Fields = {};
        for (const key of Object.keys(value as Fields).sort()) {
            const item = (value as Fields)[key];
            if (item !== undefined) out[key] = canonical(item);
        }
        return out;
    }
    return value;
}

/** Whether two decoded values are one value, whatever the order of their
 *  keys; two missing fields are one. */
export function same(a: Maybe, b: Maybe): boolean {
    if (a === MISSING || b === MISSING) return a === b;
    if (a === b) return true;
    return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
}

function isObject(value: unknown): value is Fields {
    return !!value && typeof value === "object" && !Array.isArray(value);
}

function field(source: unknown, name: string): Maybe {
    return isObject(source) && Object.prototype.hasOwnProperty.call(source, name) && source[name] !== undefined
        ? source[name]
        : MISSING;
}

function keysOf(value: unknown): Set<string> {
    return value instanceof Y.Map ? new Set(Array.from(value.keys())) : new Set();
}

// ---------------------------------------------------------------------------
// Trill to doc
// ---------------------------------------------------------------------------

/** The part of a Trill `dataflow` the doc holds. */
export function owned(dataflow: Fields): Fields {
    const out: Fields = {};
    for (const [name, value] of Object.entries(dataflow)) {
        if (!OUTSIDE_THE_DOC.has(name) && value !== undefined) out[name] = value;
    }
    return out;
}

/** *entries* by their *key*, or null when they cannot each be keyed. */
function keyed(entries: unknown, key: string): Array<[string, Fields]> | null {
    if (!Array.isArray(entries)) return null;
    const out: Array<[string, Fields]> = [];
    const seen = new Set<string>();
    for (const entry of entries) {
        if (!isObject(entry)) return null;
        const name = entry[key];
        if (typeof name !== "string" || seen.has(name)) return null;
        seen.add(name);
        out.push([name, entry]);
    }
    return out;
}

/** Write the Trill *dataflow* into the empty *doc*, which is then named *docId*. */
export function dataflowToDoc(dataflow: Fields, doc: Y.Doc, docId: string): void {
    if (!isObject(dataflow)) throw new DocMappingError("a dataflow is an object");
    doc.transact(() => {
        const meta = doc.getMap("meta");
        const fields = doc.getMap("dataflow");
        meta.set("id", encode(docId));
        meta.set("layout", encode(LAYOUT.layout));
        for (const [name, value] of Object.entries(dataflow)) {
            if (OUTSIDE_THE_DOC.has(name) || value === undefined) continue;
            const place = LAYOUT.dataflow[name];
            if (place === NODES) {
                const entries = keyed(value, NODE_ID);
                if (entries === null) {
                    fields.set(name, encode(value));
                    continue;
                }
                const nodes = doc.getMap("nodes");
                for (const [id, node] of entries) nodes.set(id, nodeMap(node));
                doc.getArray<string>("nodeOrder").push(entries.map(([id]) => id));
            } else if (place === EDGES) {
                const entries = keyed(value, EDGE_ID);
                if (entries === null) {
                    fields.set(name, encode(value));
                    continue;
                }
                const edges = doc.getMap("edges");
                for (const [id, edge] of entries) edges.set(id, encode(edge));
                doc.getArray<string>("edgeOrder").push(entries.map(([id]) => id));
            } else if (place === SCENARIOS) {
                const entries = keyed(value, SCENARIO_ID);
                if (entries === null) {
                    fields.set(name, encode(value));
                    continue;
                }
                meta.set("scenariosListed", encode(true));
                const scenarios = doc.getMap("scenarios");
                for (const [id, scenario] of entries) scenarios.set(id, scenarioMap(scenario));
                doc.getArray<string>("scenarioOrder").push(entries.map(([id]) => id));
            } else {
                fields.set(name, encode(value));
            }
        }
    }, TRILL_ORIGIN);
}

/** A node's map, made whole: its metadata, widgets and widget order with it,
 *  so two tabs never each make one. */
export function nodeMap(node: Fields): Y.Map<unknown> {
    const entries: Array<[string, unknown]> = [];
    const groups: Record<string, Fields> = {};
    let metadata: Json = {};
    for (const [name, value] of Object.entries(node)) {
        if (value === undefined) continue;
        const place = NODE_TABLE[name];
        if (place === KEY) continue;
        if (place === undefined) {
            if (NODE_DOC_KEYS.has(name)) {
                throw new DocMappingError(
                    `node ${JSON.stringify(node[NODE_ID])} has a field ${JSON.stringify(name)}, which is a key `
                    + "the doc's layout gives a node for something else",
                );
            }
            entries.push([name, encode(value)]);
        } else if (place === TEXT) {
            entries.push([name, typeof value === "string" ? new Y.Text(value) : encode(value)]);
        } else if (place === METADATA) {
            metadata = value;
        } else if (place.includes(".")) {
            const [group, member] = place.split(".", 2);
            (groups[group] ??= {})[member] = value;
        } else {
            entries.push([place, encode(value)]);
        }
    }
    for (const [group, members] of Object.entries(groups)) entries.push([group, encode(members)]);
    const [settings, widgets, order] = metadataParts(metadata);
    entries.push([NODE_METADATA, settings]);
    entries.push([WIDGETS_KEY, new Y.Map<unknown>(widgets)]);
    entries.push([WIDGET_ORDER_KEY, Y.Array.from(order)]);
    return new Y.Map<unknown>(entries);
}

function metadataParts(metadata: Json): [unknown, Array<[string, Y.Map<unknown>]>, string[]] {
    const widgets: Array<[string, Y.Map<unknown>]> = [];
    let order: string[] = [];
    if (!isObject(metadata)) return [encode(metadata), widgets, order];
    const settings: Array<[string, unknown]> = [];
    for (const [name, value] of Object.entries(metadata)) {
        if (value === undefined) continue;
        if (METADATA_TABLE[name] === WIDGETS) {
            const entries = keyed(value, WIDGET_NAME);
            if (entries === null) {
                settings.push([name, encode(value)]);
                continue;
            }
            for (const [widgetName, widget] of entries) widgets.push([widgetName, widgetMap(widget)]);
            order = entries.map(([widgetName]) => widgetName);
        } else {
            settings.push([name, encode(value)]);
        }
    }
    return [new Y.Map<unknown>(settings), widgets, order];
}

function definitionOf(widget: Fields): Fields {
    const out: Fields = {};
    for (const [name, value] of Object.entries(widget)) {
        if (name !== WIDGET_NAME && name !== WIDGET_VALUE && value !== undefined) out[name] = value;
    }
    return out;
}

function widgetMap(widget: Fields): Y.Map<unknown> {
    const entries: Array<[string, unknown]> = [[DEFINITION_KEY, encode(definitionOf(widget))]];
    const value = field(widget, WIDGET_VALUE);
    if (value !== MISSING) entries.push([VALUE_KEY, encode(value)]);
    return new Y.Map<unknown>(entries);
}

function scenarioMap(scenario: Fields): Y.Map<unknown> {
    return new Y.Map<unknown>(
        Object.entries(scenario)
            .filter(([name, value]) => name !== SCENARIO_ID && value !== undefined)
            .map(([name, value]) => [name, encode(value)] as [string, unknown]),
    );
}

// ---------------------------------------------------------------------------
// Doc to Trill
// ---------------------------------------------------------------------------

/** The keys of *entries* in the order *order* lists them, each once; any it
 *  does not list come after, sorted. */
function ordered(order: unknown, entries: unknown): string[] {
    const present = keysOf(entries);
    const seen = new Set<string>();
    const out: string[] = [];
    if (order instanceof Y.Array) {
        for (const item of order.toArray()) {
            if (typeof item === "string" && present.has(item) && !seen.has(item)) {
                seen.add(item);
                out.push(item);
            }
        }
    }
    const rest = Array.from(present).filter((key) => !seen.has(key)).sort();
    return out.concat(rest);
}

/** The id *doc* was built with, if it holds one. */
export function docId(doc: Y.Doc): string | null {
    const meta = doc.getMap("meta");
    if (!meta.has("id")) return null;
    const value = decode(meta.get("id"));
    return typeof value === "string" && value ? value : null;
}

/** The ids of *doc*'s nodes, in order. */
export function nodeIds(doc: Y.Doc): string[] {
    return ordered(doc.getArray("nodeOrder"), doc.getMap("nodes"));
}

/** The ids of *doc*'s edges, in order. */
export function edgeIds(doc: Y.Doc): string[] {
    return ordered(doc.getArray("edgeOrder"), doc.getMap("edges"));
}

/** The Trill `dataflow` *doc* holds, without the sections kept outside it. */
export function docToDataflow(doc: Y.Doc): Fields {
    const meta = doc.getMap("meta");
    const fields = doc.getMap("dataflow");
    const present = keysOf(fields);
    const out: Fields = {};
    for (const [name, place] of Object.entries(LAYOUT.dataflow)) {
        if (present.has(name)) {
            out[name] = decode(fields.get(name));
        } else if (place === NODES) {
            const nodes = doc.getMap("nodes");
            out[name] = nodeIds(doc).map((id) => nodeOut(id, nodes.get(id)));
        } else if (place === EDGES) {
            const edges = doc.getMap("edges");
            out[name] = edgeIds(doc).map((id) => edgeOut(id, edges.get(id)));
        } else if (place === SCENARIOS) {
            const listed = scenarioIds(doc).map((id) => scenarioOut(id, doc.getMap("scenarios").get(id)));
            if (listed.length > 0 || (meta.has("scenariosListed") && decode(meta.get("scenariosListed")) === true)) {
                out[name] = listed;
            }
        }
    }
    for (const name of Array.from(present).filter((n) => !(n in LAYOUT.dataflow)).sort()) {
        out[name] = decode(fields.get(name));
    }
    return out;
}

/** The ids of *doc*'s scenarios, in order. */
export function scenarioIds(doc: Y.Doc): string[] {
    return ordered(doc.getArray("scenarioOrder"), doc.getMap("scenarios"));
}

/** An entry kept whole, its *name* field the *key* its map names it by. */
function withKey(name: string, key: string, value: unknown): Json {
    const decoded = decode(value);
    if (isObject(decoded)) {
        if (name in decoded) {
            decoded[name] = key;
            return decoded;
        }
        return { [name]: key, ...decoded };
    }
    return decoded;
}

/** The Trill of one node of the doc. */
export function nodeOut(id: string, node: unknown): Json {
    if (!(node instanceof Y.Map)) return withKey(NODE_ID, id, node);
    const keys = keysOf(node);
    const groups: Record<string, Json> = {};
    for (const group of Object.keys(GROUPS)) if (keys.has(group)) groups[group] = decode(node.get(group));
    const out: Fields = {};
    for (const [name, place] of Object.entries(NODE_TABLE)) {
        if (place === KEY) {
            out[name] = id;
        } else if (place === TEXT) {
            if (keys.has(name)) {
                const value = node.get(name);
                out[name] = value instanceof Y.Text ? value.toString() : decode(value);
            }
        } else if (place === METADATA) {
            const metadata = metadataOut(node, keys);
            if (metadata !== MISSING) out[name] = metadata;
        } else if (place.includes(".")) {
            const [group, member] = place.split(".", 2);
            const members = groups[group];
            if (isObject(members) && member in members) out[name] = members[member];
        } else if (keys.has(place)) {
            out[name] = decode(node.get(place));
        }
    }
    for (const name of Array.from(keys).filter((k) => !NODE_DOC_KEYS.has(k)).sort()) {
        out[name] = decode(node.get(name));
    }
    return out;
}

function metadataOut(node: Y.Map<unknown>, keys: Set<string>): Maybe {
    const settings = keys.has(NODE_METADATA) ? node.get(NODE_METADATA) : null;
    if (settings !== null && settings !== undefined && !(settings instanceof Y.Map)) return decode(settings);
    const present = keysOf(settings);
    const out: Fields = {};
    for (const [name, place] of Object.entries(METADATA_TABLE)) {
        if (present.has(name)) {
            out[name] = decode((settings as Y.Map<unknown>).get(name));
        } else if (place === WIDGETS) {
            const widgets = widgetsOut(node, keys);
            if (widgets.length > 0) out[name] = widgets;
        }
    }
    for (const name of Array.from(present).filter((n) => !(n in METADATA_TABLE)).sort()) {
        out[name] = decode((settings as Y.Map<unknown>).get(name));
    }
    return Object.keys(out).length > 0 ? out : MISSING;
}

function widgetsOut(node: Y.Map<unknown>, keys: Set<string>): Json[] {
    const widgets = keys.has(WIDGETS_KEY) ? node.get(WIDGETS_KEY) : null;
    if (!(widgets instanceof Y.Map)) return [];
    const order = keys.has(WIDGET_ORDER_KEY) ? node.get(WIDGET_ORDER_KEY) : null;
    return ordered(order, widgets).map((name) => widgetOut(name, widgets.get(name)));
}

function widgetOut(name: string, widget: unknown): Json {
    if (!(widget instanceof Y.Map)) return withKey(WIDGET_NAME, name, widget);
    const keys = keysOf(widget);
    const out: Fields = { [WIDGET_NAME]: name };
    const definition = keys.has(DEFINITION_KEY) ? decode(widget.get(DEFINITION_KEY)) : {};
    if (isObject(definition)) {
        for (const [fieldName, value] of Object.entries(definition)) {
            if (fieldName !== WIDGET_NAME && fieldName !== WIDGET_VALUE) out[fieldName] = value;
        }
    }
    if (keys.has(VALUE_KEY)) out[WIDGET_VALUE] = decode(widget.get(VALUE_KEY));
    return out;
}

/** The Trill of one edge of the doc. */
export function edgeOut(id: string, edge: unknown): Json {
    return withKey(EDGE_ID, id, edge);
}

/** The Trill of one scenario of the doc. */
export function scenarioOut(id: string, scenario: unknown): Json {
    if (!(scenario instanceof Y.Map)) return withKey(SCENARIO_ID, id, scenario);
    const keys = keysOf(scenario);
    const out: Fields = {};
    for (const [name, place] of Object.entries(SCENARIO_TABLE)) {
        if (place === KEY) out[name] = id;
        else if (keys.has(place)) out[name] = decode(scenario.get(place));
    }
    const named = new Set(Object.values(SCENARIO_TABLE));
    for (const name of Array.from(keys).filter((k) => !named.has(k)).sort()) {
        out[name] = decode(scenario.get(name));
    }
    return out;
}

// ---------------------------------------------------------------------------
// A change between two Trills, made on a doc
// ---------------------------------------------------------------------------

/** Hold *value* at *key* (MISSING: hold nothing there), writing nothing when
 *  the doc holds it already. */
function setValue(entries: Y.Map<unknown>, key: string, value: Maybe): void {
    if (value === MISSING) {
        if (entries.has(key)) entries.delete(key);
        return;
    }
    if (entries.has(key)) {
        const held = entries.get(key);
        if (!(held instanceof Y.AbstractType) && same(decode(held), value)) return;
    }
    entries.set(key, encode(value));
}

/** *target* at *key* when it differs from *base*: what the doc changed since
 *  *base* stays where the change leaves it alone. */
function merge(entries: Y.Map<unknown>, key: string, base: Maybe, target: Maybe): void {
    if (!same(base, target)) setValue(entries, key, target);
}

/** Make *text* read *next*, changing only the stretch where the two differ
 *  (`changedStretch`), so typing elsewhere in it, merged after, stays. */
export function replaceText(text: Y.Text, next: string): void {
    const old = text.toString();
    if (old === next) return;
    const { start, endOld, endNew } = changedStretch(old, next);
    if (endOld > start) text.delete(start, endOld - start);
    if (endNew > start) text.insert(start, next.slice(start, endNew));
}

/**
 * Make *doc* carry what changed from *base* to *target*, two Trill `dataflow`
 * objects (their parts outside the doc are left alone), in the transaction
 * the caller holds or in one of its own. What the doc changed since *base*
 * stays wherever the change leaves it alone, and nothing is written where the
 * doc holds the value already. A node's code changes only where the doc still
 * holds *base*'s code; the ids of the nodes whose code the doc changed too,
 * and keeps, are returned.
 */
export function applyDataflow(doc: Y.Doc, base: Fields, target: Fields): string[] {
    const refused: string[] = [];
    doc.transact(() => {
        const meta = doc.getMap("meta");
        const fields = doc.getMap("dataflow");
        const names = Array.from(new Set([...Object.keys(base), ...Object.keys(target)]))
            .filter((name) => !OUTSIDE_THE_DOC.has(name));
        for (const name of names) {
            const old = field(base, name);
            const now = field(target, name);
            if (old === now || same(old, now)) continue;
            const place = LAYOUT.dataflow[name];
            if (place === NODES) {
                applyEntries(fields, name, doc.getMap("nodes"), doc.getArray<string>("nodeOrder"), old, now, {
                    key: NODE_ID,
                    build: (node) => nodeMap(node),
                    change: (entries, id, was, entry) => changeNode(entries.get(id), id, was, entry, refused),
                });
            } else if (place === EDGES) {
                applyEntries(fields, name, doc.getMap("edges"), doc.getArray<string>("edgeOrder"), old, now, {
                    key: EDGE_ID,
                    build: (edge) => encode(edge),
                    change: (entries, id, _was, entry) => setValue(entries, id, entry),
                });
            } else if (place === SCENARIOS) {
                applyEntries(fields, name, doc.getMap("scenarios"), doc.getArray<string>("scenarioOrder"), old, now, {
                    key: SCENARIO_ID,
                    build: (scenario) => scenarioMap(scenario),
                    change: changeScenario,
                });
                setValue(meta, "scenariosListed", Array.isArray(now) ? true : MISSING);
            } else {
                setValue(fields, name, now);
            }
        }
    });
    return refused;
}

interface EntryRules {
    key: string;
    build: (entry: Fields) => unknown;
    change: (entries: Y.Map<unknown>, id: string, was: Fields, entry: Fields) => void;
}

/** Carry a list's change into the map that holds its entries by key and the
 *  array that orders them. A list kept whole, in *parent* under *name*, is
 *  held whole as *target* says. */
function applyEntries(
    parent: Y.Map<unknown>,
    name: string,
    entries: Y.Map<unknown>,
    order: Y.Array<string>,
    base: Maybe,
    target: Maybe,
    rules: EntryRules,
): void {
    const old = base === MISSING ? [] : keyed(base, rules.key);
    const next = target === MISSING ? [] : keyed(target, rules.key);
    if (old === null || next === null || parent.has(name)) {
        for (const id of Array.from(entries.keys())) entries.delete(id);
        if (order.length) order.delete(0, order.length);
        if (next === null) {
            setValue(parent, name, target);
            return;
        }
        setValue(parent, name, MISSING);
        for (const [id, entry] of next) entries.set(id, rules.build(entry));
        order.push(next.map(([id]) => id));
        return;
    }
    const was = new Map(old);
    const now = new Map(next);
    const before = ordered(order, entries);
    for (const [id, entry] of next) {
        if (!entries.has(id)) {
            // An entry the doc took out since base stays out.
            if (!was.has(id)) entries.set(id, rules.build(entry));
        } else {
            const prior = was.get(id);
            if (prior !== entry && !same(prior === undefined ? MISSING : prior, entry)) {
                rules.change(entries, id, prior ?? {}, entry);
            }
        }
    }
    for (const id of Array.from(was.keys())) {
        if (!now.has(id) && entries.has(id)) entries.delete(id);
    }
    const present = keysOf(entries);
    const oldIds = old.map(([id]) => id);
    const newIds = next.map(([id]) => id);
    let wanted: string[];
    if (before.length === oldIds.length && before.every((id, i) => id === oldIds[i])) {
        wanted = newIds.filter((id) => present.has(id));
    } else {
        wanted = before.filter((id) => present.has(id));
        for (const id of newIds) if (present.has(id) && !wanted.includes(id)) wanted.push(id);
    }
    for (const id of Array.from(present).sort()) if (!wanted.includes(id)) wanted.push(id);
    const current = order.toArray();
    if (current.length !== wanted.length || current.some((id, i) => id !== wanted[i])) {
        if (order.length) order.delete(0, order.length);
        order.push(wanted);
    }
}

function changeScenario(entries: Y.Map<unknown>, id: string, was: Fields, now: Fields): void {
    const scenario = entries.get(id);
    if (!(scenario instanceof Y.Map)) {
        entries.set(id, scenarioMap(now));
        return;
    }
    for (const name of new Set([...Object.keys(was), ...Object.keys(now)])) {
        if (name !== SCENARIO_ID) merge(scenario, SCENARIO_TABLE[name] ?? name, field(was, name), field(now, name));
    }
}

function changeWidget(entries: Y.Map<unknown>, name: string, was: Fields, now: Fields): void {
    const widget = entries.get(name);
    if (!(widget instanceof Y.Map)) {
        entries.set(name, widgetMap(now));
        return;
    }
    merge(widget, DEFINITION_KEY, definitionOf(was), definitionOf(now));
    merge(widget, VALUE_KEY, field(was, WIDGET_VALUE), field(now, WIDGET_VALUE));
}

function changeNode(node: unknown, id: string, was: Fields, now: Fields, refused: string[]): void {
    if (!(node instanceof Y.Map)) return;
    for (const name of new Set([...Object.keys(was), ...Object.keys(now)])) {
        const place = NODE_TABLE[name];
        if (place === KEY || place === TEXT || place === METADATA || (place !== undefined && place.includes("."))) continue;
        if (place === undefined && NODE_DOC_KEYS.has(name)) {
            throw new DocMappingError(
                `node ${JSON.stringify(id)} has a field ${JSON.stringify(name)}, which is a key the doc's `
                + "layout gives a node for something else",
            );
        }
        merge(node, place ?? name, field(was, name), field(now, name));
    }
    for (const [group, members] of Object.entries(GROUPS)) {
        const old: Fields = {};
        const next: Fields = {};
        for (const [member, name] of Object.entries(members)) {
            const before = field(was, name);
            const after = field(now, name);
            if (before !== MISSING) old[member] = before;
            if (after !== MISSING) next[member] = after;
        }
        if (!same(old, next)) setValue(node, group, Object.keys(next).length > 0 ? next : MISSING);
    }
    changeCode(node, id, field(was, CONTENT), field(now, CONTENT), refused);
    changeMetadata(node, field(was, NODE_METADATA), field(now, NODE_METADATA));
}

function changeCode(node: Y.Map<unknown>, id: string, was: Maybe, now: Maybe, refused: string[]): void {
    if (same(was, now)) return;
    const held = node.has(CONTENT) ? node.get(CONTENT) : MISSING;
    const holds: Maybe = held instanceof Y.Text ? held.toString() : held === MISSING ? MISSING : decode(held);
    if (!same(holds, was)) {
        if (!same(holds, now)) refused.push(id); // the doc changed this code too, and keeps it
        return;
    }
    if (now === MISSING) {
        node.delete(CONTENT);
    } else if (typeof now === "string" && held instanceof Y.Text) {
        replaceText(held, now);
    } else if (typeof now === "string") {
        node.set(CONTENT, new Y.Text(now));
    } else {
        node.set(CONTENT, encode(now));
    }
}

function changeMetadata(node: Y.Map<unknown>, was: Maybe, now: Maybe): void {
    if (same(was, now)) return;
    const old = was === MISSING ? {} : was;
    const next = now === MISSING ? {} : now;
    const settings = node.has(NODE_METADATA) ? node.get(NODE_METADATA) : null;
    if (!isObject(old) || !isObject(next) || !(settings instanceof Y.Map)) {
        // A metadata that is no object, here or in the doc, is held whole.
        const [parts, widgets, order] = metadataParts(next);
        node.set(NODE_METADATA, parts);
        node.set(WIDGETS_KEY, new Y.Map<unknown>(widgets));
        node.set(WIDGET_ORDER_KEY, Y.Array.from(order));
        return;
    }
    if (!node.has(WIDGETS_KEY)) node.set(WIDGETS_KEY, new Y.Map<unknown>());
    if (!node.has(WIDGET_ORDER_KEY)) node.set(WIDGET_ORDER_KEY, new Y.Array<string>());
    for (const name of new Set([...Object.keys(old), ...Object.keys(next)])) {
        const before = field(old, name);
        const after = field(next, name);
        if (same(before, after)) continue;
        if (METADATA_TABLE[name] === WIDGETS) {
            applyEntries(
                settings, name, node.get(WIDGETS_KEY) as Y.Map<unknown>, node.get(WIDGET_ORDER_KEY) as Y.Array<string>,
                before, after, { key: WIDGET_NAME, build: widgetMap, change: changeWidget },
            );
        } else {
            setValue(settings, name, after);
        }
    }
}
