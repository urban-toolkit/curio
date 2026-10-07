/**
 * What a node's input references can name (#662): its wired circles, each with
 * the name of the node that feeds it, its data type, the layer name its value
 * gives, and its columns once they have been read.
 */
import type { InputScope, LayerScope } from "./codeReferences";
import { isReferenceableColumn, isReferenceableLayer } from "./codeReferences";
import { inputSlotOf, isDataEdge, wiredInputSlots } from "../inputSlots";
import { readGrammarInput, type GrammarFrame } from "../grammarInput";
import { toRows } from "../rowSource";

type ScopeEdge = {
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
 * tables). An input that is not a table has none.
 */
export async function readInputColumns(value: unknown): Promise<InputColumns> {
    const read = await readGrammarInput(value, { label: "this input", preview: true, bundles: true });
    if (read.frames.length > 1) {
        const layers = read.frames
            .filter((frame) => typeof frame.name === "string" && isReferenceableLayer(frame.name))
            .map((frame) => ({ name: frame.name as string, ...frameColumns(frame) }));
        return { columns: [], dtypes: {}, layers };
    }
    const frame = read.frames[0];
    return frame ? frameColumns(frame) : { columns: [], dtypes: {} };
}
