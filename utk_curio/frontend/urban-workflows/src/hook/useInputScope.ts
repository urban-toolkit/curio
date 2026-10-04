// A node's wired inputs, for its input chips and tags (#662): which circles
// have an edge, the node feeding each, what each holds, and the columns read
// for it on request.
import { useCallback, useMemo, useRef, useState } from "react";
import { useFlowContext } from "../providers/FlowProvider";
import { emptyWiredSlots } from "../utils/inputSlots";
import type { InputScope } from "../utils/references/codeReferences";
import {
    inputScopeFor,
    inputValueKey,
    readInputColumns,
    type InputColumns,
} from "../utils/references/inputScope";
import { resolveNodeDisplayLabel } from "../utils/palettePackageFactoryDraft";

function labelOf(data: any): string | null {
    try {
        return resolveNodeDisplayLabel(data) || null;
    } catch {
        return null;
    }
}

export function useInputScope(data: any): {
    inputs: InputScope[];
    /** Wired circles that hold no value yet. */
    emptyInputs: number[];
    loadColumns: (slot: number) => void;
} {
    const flow = useFlowContext() as { nodes?: any[]; edges?: any[] };
    const nodes = flow?.nodes ?? [];
    const edges = flow?.edges ?? [];
    const [readCount, setReadCount] = useState(0);
    const keyed = useRef(new Map<string, InputColumns>());
    const inline = useRef(new WeakMap<object, InputColumns>());
    const reading = useRef(new Set<unknown>());

    // A growing node holds a value per circle; any other node holds one.
    const valueOf = useCallback(
        (slot: number): unknown =>
            Array.isArray(data.inputSlots) ? data.inputSlots[slot] : slot === 0 ? data.input : undefined,
        [data.inputSlots, data.input],
    );
    const columnsOf = (value: unknown): InputColumns | undefined => {
        const key = inputValueKey(value);
        if (key) return keyed.current.get(key);
        return value && typeof value === "object" ? inline.current.get(value as object) : undefined;
    };

    const computed = inputScopeFor(data.nodeId, edges, nodes, valueOf, labelOf, columnsOf);
    // The same list keeps its identity, so editors do not redraw their chips
    // whenever an unrelated node moves.
    const signature = JSON.stringify(computed);
    const inputs = useMemo(() => computed, [signature, readCount]);

    const loadColumns = useCallback(
        (slot: number) => {
            const value = valueOf(slot);
            if (value == null || value === "" || columnsOf(value) !== undefined) return;
            const marker = inputValueKey(value) ?? value;
            if (reading.current.has(marker)) return;
            reading.current.add(marker);
            readInputColumns(value)
                .catch(() => ({ columns: [], dtypes: {} }))
                .then((read) => {
                    const key = inputValueKey(value);
                    if (key) keyed.current.set(key, read);
                    else if (typeof value === "object") inline.current.set(value as object, read);
                    reading.current.delete(marker);
                    setReadCount((n) => n + 1);
                });
        },
        [valueOf],
    );

    // Only a node holding a value per circle waits for all of them; a node with
    // one input runs as it always has.
    const growing = Array.isArray(data.inputSlots) || inputs.length > 1;
    const emptyInputs = growing
        ? emptyWiredSlots(Array.isArray(data.inputSlots) ? data.inputSlots : [], inputs.map((i) => i.slot))
        : [];
    return { inputs, emptyInputs, loadColumns };
}
