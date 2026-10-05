// Selection tags (#662): a node's code reads a view's selection as
// `[!! selection name !!]`, the ids of the rows it picks. The node holds the
// ids (data.selections, saved at metadata.selections), so every run reads the
// same ones. A new selection in the view writes new ids into every tag on it,
// and the nodes holding them go stale: their run key covers the ids.
import React, { useEffect, useRef } from "react";
import type { Node, ReactFlowInstance } from "reactflow";
import type { IInteraction } from "./flowTypes";
import {
    changesSelection,
    normalizeSelections,
    sameState,
    withState,
    type SelectionState,
    type SelectionTag,
} from "../../utils/references/selectionTags";
import {
    recordViewSelection,
    selectionStateOf,
    type ViewDetails,
} from "../../utils/references/viewSelections";

type NodeLike = { id: string; data?: any };

/** The columns the tags among *nodes* read the view *viewId* by. */
export function tagColumnsOn(nodes: readonly NodeLike[], viewId: string): string[] {
    const columns = new Set<string>();
    for (const node of nodes) {
        for (const tag of normalizeSelections(node.data?.selections)) {
            if (tag.node === viewId) columns.add(tag.column);
        }
    }
    return [...columns];
}

/**
 * *selections* (one node's `data.selections`) with each tag on the view
 * *viewId* holding what *states* says for its column, or null when no tag
 * holds anything new.
 */
export function withViewStates(
    selections: unknown,
    viewId: string,
    states: ReadonlyMap<string, SelectionState>,
): SelectionTag[] | null {
    const tags = normalizeSelections(selections);
    let changed = false;
    const next = tags.map((tag) => {
        const state = tag.node === viewId ? states.get(tag.column) : undefined;
        if (state === undefined) return tag;
        const updated = withState(tag, state);
        if (sameState(tag, updated)) return tag;
        changed = true;
        return updated;
    });
    return changed ? next : null;
}

/** What the selection *details* of the view *viewId* hold for each column
 * the tags among *nodes* read it by. A view that holds no rows yet gives none. */
export async function viewStates(
    nodes: readonly NodeLike[],
    viewId: string,
    details: ViewDetails,
): Promise<Map<string, SelectionState>> {
    const states = new Map<string, SelectionState>();
    for (const column of tagColumnsOn(nodes, viewId)) {
        const state = await selectionStateOf(viewId, column, details);
        if (state !== null) states.set(column, state);
    }
    return states;
}

export function useSelectionTags({
    interactions, reactFlow, setNodes, markNodeStaleRef, markDirtyRef,
}: {
    interactions: IInteraction[];
    reactFlow: ReactFlowInstance;
    setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
    markNodeStaleRef: React.MutableRefObject<(nodeId: string) => void>;
    markDirtyRef: React.MutableRefObject<() => void>;
}) {
    // The selection last read for each view, and how many were asked for: a
    // brush reports at every move, and only the last one's ids are kept.
    const seen = useRef(new Map<string, unknown>());
    const asked = useRef(new Map<string, number>());

    useEffect(() => {
        for (const { nodeId: viewId, details } of interactions) {
            const previous = seen.current.get(viewId);
            if (previous === details) continue;
            seen.current.set(viewId, details);
            recordViewSelection(viewId, details);
            // Only a selection the user made, or cleared: a chart declaring its
            // selects as it compiles, or reporting them empty as it first
            // draws, changes nothing, and a reload keeps the saved ids.
            if (!changesSelection(previous, details)) continue;
            const nodes = reactFlow.getNodes?.() ?? [];
            if (tagColumnsOn(nodes, viewId).length === 0) continue;
            const turn = (asked.current.get(viewId) ?? 0) + 1;
            asked.current.set(viewId, turn);
            void viewStates(nodes, viewId, details as ViewDetails).then((states) => {
                if (asked.current.get(viewId) !== turn || states.size === 0) return;
                const changed = (reactFlow.getNodes?.() ?? [])
                    .filter((node) => withViewStates(node.data?.selections, viewId, states) !== null)
                    .map((node) => node.id);
                if (changed.length === 0) return;
                setNodes((nds) =>
                    nds.map((node) => {
                        const next = withViewStates(node.data?.selections, viewId, states);
                        return next === null ? node : { ...node, data: { ...node.data, selections: next } };
                    }),
                );
                changed.forEach((id) => markNodeStaleRef.current(id));
                markDirtyRef.current();
            });
        }
    }, [interactions]);
}
