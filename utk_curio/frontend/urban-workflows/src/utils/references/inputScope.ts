/**
 * What a node's input references can name (#662): its wired circles, each with
 * the edge and the name of the node that feed it, its data type, the layer name
 * its value gives, and its columns once they have been read.
 *
 * And what a chip's hover shows of an input (`readInputPreview`, drawn by
 * components/editing/widgets/ChipPreview): the one `/get-preview` read the
 * header makes, kept as what the input holds, its first rows and its size,
 * with the state of the node that feeds it (`inputSourcesFor`). The header's
 * lists are a view of the same read (`readInputColumns`).
 */
import type { InputScope, LayerScope } from "./codeReferences";
import { isReferenceableColumn, isReferenceableLayer } from "./codeReferences";
import { inputSlotOf, isDataEdge, wiredInputSlots } from "../inputSlots";
import { readGrammarInput, type GrammarFrame, type GrammarInput } from "../grammarInput";
import { toRows } from "../rowSource";
import { fetchPreviewData } from "../../services/api";
import { outputStatus } from "../../components/scenarios/scenarioLabels";

type ScopeEdge = {
    id?: string | null;
    source?: string | null;
    target?: string | null;
    sourceHandle?: string | null;
    targetHandle?: string | null;
};
type ScopeNode = { id: string; data?: any };

export interface InputColumns {
    columns: string[];
    dtypes: Record<string, string>;
    /** The named layers it carries, when it carries several. */
    layers?: LayerScope[];
    /** How many values it holds, when it is a tuple: a bundle of values with no names. */
    tuple?: number;
}

/** What identifies an input's value, so its columns are read once per value. */
export function inputValueKey(value: unknown): string | null {
    if (value == null || value === "") return null;
    if (typeof value === "string") return value;
    if (typeof value !== "object") return null;
    const v = value as Record<string, unknown>;
    for (const key of ["path", "filename", "dataset"]) {
        if (typeof v[key] === "string" && v[key]) return `${key}:${v[key]}`;
    }
    return null;
}

/**
 * The wired inputs of *nodeId*, in circle order. *valueOf* gives what a circle
 * holds; *labelOf* names the node that feeds it; *columnsOf* gives the columns
 * already read for a value.
 */
export function inputScopeFor(
    nodeId: string,
    edges: ScopeEdge[],
    nodes: ScopeNode[],
    valueOf: (slot: number) => unknown,
    labelOf: (data: any) => string | null,
    columnsOf: (value: unknown) => InputColumns | null | undefined,
): InputScope[] {
    return wiredInputSlots(edges, nodeId).map((slot) => {
        const edge = edges.find((e) => e.target === nodeId && isDataEdge(e) && inputSlotOf(e.targetHandle) === slot);
        const source = nodes.find((n) => n.id === edge?.source);
        const value = valueOf(slot);
        const scope: InputScope = { slot };
        // The edge keeps its id when the circles renumber, the circle does not.
        if (edge?.id) scope.edge = edge.id;
        const label = source?.data ? labelOf(source.data) : null;
        if (label) scope.label = label;
        const dataType = value && typeof value === "object" ? (value as any).dataType : undefined;
        if (typeof dataType === "string" && dataType) scope.dataType = dataType;
        // A value can name the table it is read as (utils/grammarInput), as an
        // envelope's layerName does: a layer chip then names that layer.
        const layerName = value && typeof value === "object" ? (value as any).layerName : undefined;
        if (typeof layerName === "string" && isReferenceableLayer(layerName)) scope.layerName = layerName;
        const read = columnsOf(value);
        if (read) {
            scope.columns = read.columns;
            scope.dtypes = read.dtypes;
            if (read.layers) scope.layers = read.layers;
            if (read.tuple) scope.tuple = read.tuple;
        } else if (value == null || value === "") {
            // Nothing has arrived yet, so there is nothing to read.
            scope.columns = null;
        }
        return scope;
    });
}

/** A frame's columns and their dtypes. */
function frameColumns(frame: GrammarFrame): { columns: string[]; dtypes: Record<string, string> } {
    let names: string[];
    if (frame.schema) {
        names = Object.keys(frame.schema);
    } else if (frame.dataType === "geodataframe") {
        names = Object.keys(frame.payload?.features?.[0]?.properties ?? {});
    } else {
        names = Object.keys(toRows({ data: frame.payload })[0] ?? {});
    }
    const columns = names.filter(isReferenceableColumn);
    const dtypes: Record<string, string> = {};
    for (const name of columns) {
        const dtype = frame.schema?.[name];
        if (typeof dtype === "string") dtypes[name] = dtype;
    }
    return { columns, dtypes };
}

/**
 * The columns of an input's value, from its 100-row preview, as starter specs
 * read it, or the named layers it carries with theirs (an Autark node's
 * tables). A bundle of two values or more none of which is named is a tuple,
 * tables or not, whose values it counts: the frames read from it and the items
 * that are no frame (`skipped`). An input that is not a table has none. A view
 * of `readInputPreview`, so the header's lists and a chip's hover share one
 * read.
 */
export async function readInputColumns(value: unknown): Promise<InputColumns> {
    return columnsOfPreview(await readInputPreview(value));
}

/** The header's view of what *preview* holds: its columns, its layers' or how many values its tuple holds. */
export function columnsOfPreview(preview: InputPreview): InputColumns {
    if (preview.kind === "tuple") return { columns: [], dtypes: {}, layers: [], tuple: preview.size };
    if (preview.kind === "layers") {
        const layers = preview.layers.map(({ name, table }) => ({ name, columns: table.columns, dtypes: table.dtypes }));
        return { columns: [], dtypes: {}, layers };
    }
    if (preview.kind === "frame") return { columns: preview.table.columns, dtypes: preview.table.dtypes };
    return { columns: [], dtypes: {} };
}

/** The rows a preview keeps of each table it shows: its first 5. */
export const PREVIEW_ROWS = 5;
/** The most rows a preview reads of a table, inline or not: `/get-preview`'s cut. */
export const READ_ROWS = 100;
/** The longest text a preview keeps of a cell: it shows far less. */
const KEPT_TEXT = 200;

/** One column over the rows read. */
export interface ColumnSummary {
    /** How many of its cells hold nothing: null, or a number that is none. */
    empty: number;
    /** A column of numbers: its least and its greatest. */
    min?: number;
    max?: number;
    /** Any other column: its distinct values, each as text, in the order read. */
    distinct?: string[];
}

/** What a preview shows of one table. */
export interface PreviewTable {
    frameType: "dataframe" | "geodataframe";
    /** Its columns, as the header lists them. */
    columns: string[];
    /** Each column's dtype, when the input names them. */
    dtypes: Record<string, string>;
    /** Its first rows (PREVIEW_ROWS), each cell as read, a geometry as its type ("Polygon"). */
    rows: Record<string, unknown>[];
    /** How many rows it has. */
    totalRows: number;
    /** How many rows were read, which each column's summary covers: all of them, or the first READ_ROWS. */
    readRows: number;
    /** Each column over the rows read. */
    summaries: Record<string, ColumnSummary>;
    /** A GeoDataFrame's coordinate system ("EPSG:3395"), when it declares one. */
    crs?: string | null;
    /** A GeoDataFrame's geometry type ("MultiPolygon", "Point or LineString"), when it has geometries. */
    geometryType?: string | null;
}

/** One value of a tuple: a table, or any other value as itself. */
export type TuplePart = { table: PreviewTable } | { value: unknown; dataType: string | null };

/** What an input holds, as a chip's hover shows it. */
export type InputPreview =
    | { kind: "frame"; table: PreviewTable }
    /** Named layers, as an Autark node hands on its tables. */
    | { kind: "layers"; layers: Array<{ name: string; table: PreviewTable }> }
    /** A bundle of values with no names, as a Python node's `return a, b` gives:
     * how many values it holds, as the header counts them, and each one. */
    | { kind: "tuple"; size: number; parts: TuplePart[] }
    | { kind: "value"; dataType: string; value: unknown }
    /** Not read: an Autark node or a Python node loads it. */
    | { kind: "raster" }
    /** A list or a dict that holds no table: its size and first items. */
    | { kind: "json"; shape: "list" | "dict"; total: number; items: Array<{ key: string; value: unknown }> }
    | { kind: "empty" }
    /** The read failed (useInputScope). */
    | { kind: "unreadable" };

/** The state of the output of the node that feeds an input. */
export type UpstreamStatus = "done" | "not-run" | "stale" | "errored";

/** The node that feeds an input, as a preview names it. */
export interface InputSource {
    /** Its title, else the name of its type. */
    title: string;
    /** The name of its type, when its title is another. */
    type?: string;
    status: UpstreamStatus;
}

/** What a chip's hover knows of one input: its source, and what it holds once read. */
export interface InputPreviewState {
    source: InputSource;
    /** Absent until it is read. */
    preview?: InputPreview;
}

/** The data types of a value that is no table or list (`parseOutput`'s envelopes). */
const SCALAR_TYPES = new Set(["int", "float", "bool", "str"]);
const FRAME_TYPES = new Set(["dataframe", "geodataframe"]);

const isRecord = (value: unknown): value is Record<string, any> =>
    value !== null && typeof value === "object" && !Array.isArray(value);

/**
 * What *value*, an input's value, holds, from one read of it: the 100-row
 * preview of the artifact it names, or the value itself when it is inline (a
 * Data Pool hands on its rows). Its first rows, its size, and each column over
 * the rows read; a raster is not read. A failed read throws.
 */
export async function readInputPreview(value: unknown): Promise<InputPreview> {
    if (value == null || value === "") return { kind: "empty" };
    const declared = isRecord(value) && typeof value.dataType === "string" ? value.dataType : undefined;
    if (declared === "raster") return { kind: "raster" };
    const path = isRecord(value) && typeof value.path === "string" && value.path ? value.path : null;
    if (declared !== undefined && SCALAR_TYPES.has(declared)) {
        const envelope = path ? await fetchPreviewData(path) : value;
        return { kind: "value", dataType: declared, value: plainOf(envelope) };
    }
    // The grammar nodes' reader, as the header's columns were read, keeping
    // what it read: a tuple's values and a list's items are no frame.
    const reads = new Map<string, any>();
    const read = async (at: string) => {
        const envelope = await fetchPreviewData(at);
        reads.set(at, envelope);
        return envelope;
    };
    const grammar = await readGrammarInput(value, { label: "this input", preview: true, bundles: true, read });
    return previewOf(grammar, path ? reads.get(path) : value, declared, reads);
}

function previewOf(
    grammar: GrammarInput,
    envelope: unknown,
    declared: string | undefined,
    reads: Map<string, any>,
): InputPreview {
    const frames = grammar.frames;
    const size = frames.length + (grammar.skipped?.length ?? 0);
    const bundle = declared === "outputs" || frames.length > 1;
    if (bundle && size > 1 && frames.every((frame) => frame.name == null)) {
        return { kind: "tuple", size, parts: tupleParts(frames, envelope, reads) };
    }
    if (frames.length > 1) {
        const layers = frames
            .filter((frame) => typeof frame.name === "string" && isReferenceableLayer(frame.name))
            .map((frame) => ({ name: frame.name as string, table: tableOf(frame) }));
        return { kind: "layers", layers };
    }
    if (frames.length === 1) return { kind: "frame", table: tableOf(frames[0]) };
    return otherValueOf(envelope);
}

/** A value as Python reads it back from its envelope: a list's items each
 * unwrapped too, a dict's values too, and a float that is no number as NaN. */
function plainOf(item: unknown): unknown {
    if (!isRecord(item) || typeof item.dataType !== "string" || !("data" in item)) return item;
    const { dataType, data } = item;
    if (dataType === "list" && Array.isArray(data)) return data.map(plainOf);
    if (dataType === "dict" && isRecord(data)) {
        return Object.fromEntries(Object.entries(data).map(([key, cell]) => [key, plainOf(cell)]));
    }
    if (dataType === "float" && data === null) return Number.NaN;
    return data;
}

/** Each value of a tuple, in order: the table read at its place, else the value itself. */
function tupleParts(frames: GrammarFrame[], envelope: unknown, reads: Map<string, any>): TuplePart[] {
    let bundle: unknown = envelope;
    while (isRecord(bundle) && typeof bundle.dataType === "string" && bundle.dataType !== "outputs"
        && !FRAME_TYPES.has(bundle.dataType) && "data" in bundle) {
        bundle = bundle.data;
    }
    const items: unknown[] = isRecord(bundle) && bundle.dataType === "outputs" && Array.isArray(bundle.data) ? bundle.data : [];
    if (items.length === 0) return frames.map((frame) => ({ table: tableOf(frame) }));
    const parts: TuplePart[] = [];
    items.forEach((item, index) => {
        // A circle left out brings nothing, as the reader skips it.
        if (item === null) return;
        const frame = frames.find((one) => one.index === index);
        if (frame) {
            parts.push({ table: tableOf(frame) });
            return;
        }
        const held = isRecord(item) && typeof item.path === "string" && reads.has(item.path) ? reads.get(item.path) : item;
        const dataType = isRecord(held) && typeof held.dataType === "string" ? held.dataType : null;
        parts.push({ value: plainOf(held), dataType });
    });
    return parts;
}

/** What an input that carries no table holds: a list or a dict, a value, or nothing. */
function otherValueOf(envelope: unknown): InputPreview {
    const plain = plainOf(envelope);
    if (Array.isArray(plain) && plain.length > 0) {
        const items = plain.slice(0, PREVIEW_ROWS).map((value, i) => ({ key: String(i), value }));
        return { kind: "json", shape: "list", total: plain.length, items };
    }
    if (isRecord(plain) && Object.keys(plain).length > 0) {
        const entries = Object.entries(plain);
        const items = entries.slice(0, PREVIEW_ROWS).map(([key, value]) => ({ key, value }));
        return { kind: "json", shape: "dict", total: entries.length, items };
    }
    if (typeof plain === "number" || typeof plain === "string" || typeof plain === "boolean") {
        const named = isRecord(envelope) && typeof envelope.dataType === "string" ? envelope.dataType : null;
        const dataType = named ?? (typeof plain === "number" ? "float" : typeof plain === "string" ? "str" : "bool");
        return { kind: "value", dataType, value: plain };
    }
    return { kind: "empty" };
}

/** How many rows a DataFrame's columns hold, as rows read them (utils/rowSource). */
function frameLength(payload: any): number {
    if (!isRecord(payload)) return 0;
    const columns = Object.keys(payload);
    const first = columns.length ? payload[columns[0]] : null;
    if (Array.isArray(first)) return first.length;
    return isRecord(first) ? Object.keys(first).length : 0;
}

function frameCell(payload: any, column: string, index: number): unknown {
    const cells = payload?.[column];
    if (Array.isArray(cells)) return cells[index];
    return isRecord(cells) ? cells[String(index)] : null;
}

/** A cell as a preview keeps it: nothing as null, and a long text cut. */
function keptCell(cell: unknown): unknown {
    if (cell === undefined || (typeof cell === "number" && Number.isNaN(cell))) return null;
    if (typeof cell === "string" && cell.length > KEPT_TEXT) return cell.slice(0, KEPT_TEXT);
    return cell;
}

/** A coordinate system as people write it: `urn:ogc:def:crs:EPSG::3395` is EPSG:3395. */
function crsOf(name: string | null): string | null {
    if (!name) return null;
    const epsg = /EPSG:{1,2}(\d+)/i.exec(name);
    if (epsg) return `EPSG:${epsg[1]}`;
    return /CRS84$/i.test(name) ? "OGC:CRS84" : name;
}

/** *cells* as one column over the rows read. */
export function columnSummaryOf(cells: readonly unknown[]): ColumnSummary {
    let empty = 0;
    let min = Number.POSITIVE_INFINITY;
    let max = Number.NEGATIVE_INFINITY;
    let numbers = 0;
    let others = 0;
    const distinct = new Set<string>();
    for (const cell of cells) {
        if (cell === null || cell === undefined || (typeof cell === "number" && Number.isNaN(cell))) {
            empty += 1;
            continue;
        }
        if (typeof cell === "number") {
            numbers += 1;
            min = Math.min(min, cell);
            max = Math.max(max, cell);
        } else {
            others += 1;
        }
        const text = typeof cell === "string" ? cell : typeof cell === "object" ? JSON.stringify(cell) : String(cell);
        distinct.add(text.slice(0, KEPT_TEXT));
    }
    if (numbers > 0 && others === 0) return { empty, min, max };
    if (numbers === 0 && others === 0) return { empty };
    return { empty, distinct: [...distinct] };
}

/** What a preview shows of *frame*: its columns as the header lists them, its
 * first rows, its size, and each column over the rows read. */
function tableOf(frame: GrammarFrame): PreviewTable {
    const { columns, dtypes } = frameColumns(frame);
    const geo = frame.dataType === "geodataframe";
    const features: any[] = geo && Array.isArray(frame.payload?.features) ? frame.payload.features : [];
    const length = geo ? features.length : frameLength(frame.payload);
    const readRows = Math.min(length, READ_ROWS);
    const cellAt = (column: string, index: number): unknown => {
        if (!geo) return keptCell(frameCell(frame.payload, column, index));
        const feature = features[index];
        if (column === frame.geometryName) return typeof feature?.geometry?.type === "string" ? feature.geometry.type : null;
        return keptCell(feature?.properties?.[column]);
    };
    const rows = Array.from({ length: Math.min(readRows, PREVIEW_ROWS) }, (_, index) =>
        Object.fromEntries(columns.map((column) => [column, cellAt(column, index)])),
    );
    const summaries: Record<string, ColumnSummary> = {};
    for (const column of columns) {
        summaries[column] = columnSummaryOf(Array.from({ length: readRows }, (_, index) => cellAt(column, index)));
    }
    const table: PreviewTable = {
        frameType: geo ? "geodataframe" : "dataframe",
        columns,
        dtypes,
        rows,
        totalRows: Math.max(frame.totalRows ?? length, length),
        readRows,
        summaries,
    };
    if (geo) {
        const types = new Set<string>();
        for (const feature of features.slice(0, READ_ROWS)) {
            if (typeof feature?.geometry?.type === "string") types.add(feature.geometry.type);
        }
        table.crs = crsOf(frame.crsName);
        table.geometryType = types.size > 0 ? [...types].join(" or ") : null;
    }
    return table;
}

/**
 * The node that feeds each wired input of *nodeId*, by circle: its title (else
 * the name of its type, *typeOf*), the name of its type when the title is
 * another, and the state of its output, from *execStatus* (the flow's
 * `nodeExecStatus`) as a scenario's details read it (`outputStatus`). An input
 * that holds no value (*valueOf*) is not run, unless its node failed.
 */
export function inputSourcesFor(
    nodeId: string,
    edges: ScopeEdge[],
    nodes: ScopeNode[],
    valueOf: (slot: number) => unknown,
    typeOf: (data: any) => string | null,
    execStatus: Record<string, string>,
): Record<number, InputSource> {
    const sources: Record<number, InputSource> = {};
    for (const slot of wiredInputSlots(edges, nodeId)) {
        const edge = edges.find((e) => e.target === nodeId && isDataEdge(e) && inputSlotOf(e.targetHandle) === slot);
        const node = nodes.find((n) => n.id === edge?.source);
        const type = node?.data ? typeOf(node.data) : null;
        const titled = typeof node?.data?.title === "string" ? node.data.title.trim() : "";
        const title = titled || type || (edge?.source ?? "").slice(0, 8);
        const value = valueOf(slot);
        const tone = outputStatus(node, execStatus as Record<string, "stale" | "executed" | "errored">).tone;
        const status: UpstreamStatus =
            tone === "error" ? "errored" : value == null || value === "" ? "not-run" : tone === "stale" ? "stale" : "done";
        sources[slot] = { title, ...(type && type !== title ? { type } : {}), status };
    }
    return sources;
}
