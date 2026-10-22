// A node's wired inputs, for its input chips and tags (#662): which circles
// have an edge, the node feeding each, what each holds, the columns read for
// it on request, and the scenario label its rows carry, which the scenario
// chips write (utils/scenarios/inputScenarios). And what a chip's hover shows
// of each input: the node feeding it and the state of its output, and its
// preview once read, from the same read as its columns.
import { useCallback, useMemo, useRef, useState } from "react";
import { useFlowContext } from "../providers/FlowProvider";
import { emptyWiredSlots } from "../utils/inputSlots";
import type { InputScope } from "../utils/references/codeReferences";
import {
    columnsOfPreview,
    inputScopeFor,
    inputSourcesFor,
    inputValueKey,
    isScalarInput,
    readInputPreview,
    type InputColumns,
    type InputPreview,
    type InputPreviewState,
} from "../utils/references/inputScope";
import { resolveNodeDisplayLabel } from "../utils/palettePackageFactoryDraft";
import { inputScenarios } from "../utils/scenarios/inputScenarios";
import type { Scenario } from "../utils/scenarios/scenarioModel";

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
    /** Each wired input's preview, by circle: the node that feeds it and the
     * state of its output, and what the input holds once it is read. */
    previews: Record<number, InputPreviewState>;
    /** Read input *slot*, once per value: a chip's hover asks as it shows, as
     * the header asks for the columns, which this same read gives. */
    loadPreview: (slot: number) => void;
} {
    const flow = useFlowContext() as {
        nodes?: any[];
        edges?: any[];
        scenarios?: Scenario[];
        nodeExecStatus?: Record<string, string>;
    };
    const nodes = flow?.nodes ?? [];
    const edges = flow?.edges ?? [];
    const scenarios = flow?.scenarios ?? [];
    const [readCount, setReadCount] = useState(0);
    const keyed = useRef(new Map<string, InputPreview>());
    const inline = useRef(new WeakMap<object, InputPreview>());
    const reading = useRef(new Set<unknown>());
    // An inline value has no key, so it is known by a number of its own.
    const inlineIds = useRef(new WeakMap<object, number>());
    const inlineCount = useRef(0);

    // A growing node holds a value per circle; any other node holds one.
    const valueOf = useCallback(
        (slot: number): unknown =>
            Array.isArray(data.inputSlots) ? data.inputSlots[slot] : slot === 0 ? data.input : undefined,
        [data.inputSlots, data.input],
    );
    const previewOf = (value: unknown): InputPreview | undefined => {
        const key = inputValueKey(value);
        if (key) return keyed.current.get(key);
        return value && typeof value === "object" ? inline.current.get(value as object) : undefined;
    };
    const columnsOf = (value: unknown): InputColumns | undefined => {
        // A value is no table: it has no columns, with nothing to read.
        if (isScalarInput(value)) return { columns: [], dtypes: {} };
        const preview = previewOf(value);
        return preview ? columnsOfPreview(preview) : undefined;
    };
    const identityOf = (value: unknown): string => {
        const key = inputValueKey(value);
        if (key || !value || typeof value !== "object") return key ?? String(value);
        let id = inlineIds.current.get(value as object);
        if (id === undefined) {
            inlineCount.current += 1;
            id = inlineCount.current;
            inlineIds.current.set(value as object, id);
        }
        return `inline ${id}`;
    };

    const labels = new Map(inputScenarios(data.nodeId, nodes, edges, scenarios).map((input) => [input.slot, input.label]));
    const computed = inputScopeFor(data.nodeId, edges, nodes, valueOf, labelOf, columnsOf).map((input) =>
        labels.has(input.slot) ? { ...input, scenario: labels.get(input.slot) } : input,
    );
    // The same list keeps its identity, so editors do not redraw their chips
    // whenever an unrelated node moves; a box renamed or recolored is a new one.
    const signature = JSON.stringify(computed);
    const inputs = useMemo(() => computed, [signature, readCount]);

    const sources = inputSourcesFor(data.nodeId, edges, nodes, valueOf, labelOf, flow?.nodeExecStatus ?? {});
    const computedPreviews: Record<number, InputPreviewState> = {};
    for (const [slot, source] of Object.entries(sources)) {
        const preview = previewOf(valueOf(Number(slot)));
        computedPreviews[Number(slot)] = preview ? { source, preview } : { source };
    }
    // The same, while no source changes state and no input changes value.
    const previewsSignature = JSON.stringify(
        Object.entries(sources).map(([slot, source]) => [slot, source, identityOf(valueOf(Number(slot)))]),
    );
    const previews = useMemo(() => computedPreviews, [previewsSignature, readCount]);

    const loadPreview = useCallback(
        (slot: number) => {
            const value = valueOf(slot);
            if (value == null || value === "" || previewOf(value) !== undefined) return;
            const marker = inputValueKey(value) ?? value;
            if (reading.current.has(marker)) return;
            reading.current.add(marker);
            readInputPreview(value)
                .catch((): InputPreview => ({ kind: "unreadable" }))
                .then((preview) => {
                    const key = inputValueKey(value);
                    if (key) keyed.current.set(key, preview);
                    else if (typeof value === "object") inline.current.set(value as object, preview);
                    reading.current.delete(marker);
                    setReadCount((n) => n + 1);
                });
        },
        [valueOf],
    );

    // The header reads an input for its columns, which a value has none of: a
    // value is read only for its preview, as its tooltip shows.
    const loadColumns = useCallback(
        (slot: number) => {
            if (!isScalarInput(valueOf(slot))) loadPreview(slot);
        },
        [valueOf, loadPreview],
    );

    // Only a node holding a value per circle waits for all of them; a node with
    // one input runs as it always has.
    const growing = Array.isArray(data.inputSlots) || inputs.length > 1;
    const emptyInputs = growing
        ? emptyWiredSlots(Array.isArray(data.inputSlots) ? data.inputSlots : [], inputs.map((i) => i.slot))
        : [];
    return { inputs, emptyInputs, loadColumns, previews, loadPreview };
}
