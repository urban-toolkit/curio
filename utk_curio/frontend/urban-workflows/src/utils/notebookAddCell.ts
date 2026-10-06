// A cell added from the notebook view's (+) reads the output of the cell above
// it: the new node's first input takes that cell's output, when the one has an
// output, the other an input, and their kinds connect. Otherwise it is added
// with no connection. Pure, so its tests need no flow.
import type { Connection } from "reactflow";

export interface CellEnd {
    id: string;
    nodeType: string;
    handles: readonly { id: string; type: string }[];
}

export function addedCellConnection(
    above: CellEnd,
    added: CellEnd,
    compatible: (outType: string, inType: string) => boolean,
): Connection | null {
    const out = above.handles.find((h) => h.type === "source" && h.id === "out");
    const input = added.handles.find((h) => h.type === "target" && h.id.startsWith("in") && h.id !== "in/out");
    if (!out || !input) return null;
    if (!compatible(above.nodeType, added.nodeType)) return null;
    return { source: above.id, sourceHandle: out.id, target: added.id, targetHandle: input.id };
}
