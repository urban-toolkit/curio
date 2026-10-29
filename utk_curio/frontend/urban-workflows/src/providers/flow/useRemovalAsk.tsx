/**
 * Removing a node someone else is editing asks first: "Ana is editing this
 * node. Remove it anyway?" A removal nobody else is editing goes at once.
 * Whoever removes it tells the others (`presence.noteRemoval`), so a tab that
 * was editing it says who did.
 */
import React, { useCallback, useState } from "react";

import ConfirmDialog from "../../components/ConfirmDialog";

/** "Ana", "Ana and Fabio", "Ana, Fabio and Rui". */
export function namesSaid(names: readonly string[]): string {
    const unique = Array.from(new Set(names));
    if (unique.length <= 1) return unique[0] ?? "Someone";
    return `${unique.slice(0, -1).join(", ")} and ${unique[unique.length - 1]}`;
}

/** The question asked before removing *nodeCount* nodes *names* edit. */
export function removalQuestion(names: readonly string[], nodeCount: number): string {
    const people = namesSaid(names);
    const verb = new Set(names).size > 1 ? "are" : "is";
    return nodeCount > 1
        ? `${people} ${verb} editing these nodes. Remove them anyway?`
        : `${people} ${verb} editing this node. Remove it anyway?`;
}

export function useRemovalAsk(editorsOf: (nodeId: string) => string[]): {
    /** Remove *nodeIds* with *proceed*, once asked if anyone else edits one. */
    ask: (nodeIds: readonly string[], proceed: () => void) => void;
    dialog: React.ReactNode;
} {
    const [pending, setPending] = useState<{ question: string; proceed: () => void } | null>(null);

    const ask = useCallback((nodeIds: readonly string[], proceed: () => void) => {
        const edited = nodeIds.filter((id) => editorsOf(id).length > 0);
        if (edited.length === 0) {
            proceed();
            return;
        }
        const names = edited.flatMap((id) => editorsOf(id));
        setPending({ question: removalQuestion(names, edited.length), proceed });
    }, [editorsOf]);

    const dialog = pending ? (
        <ConfirmDialog
            title="Remove while someone is editing?"
            body={pending.question}
            confirmLabel="Remove"
            cancelLabel="Keep"
            destructive
            onConfirm={() => {
                const { proceed } = pending;
                setPending(null);
                proceed();
            }}
            onCancel={() => setPending(null)}
        />
    ) : null;

    return { ask, dialog };
}
