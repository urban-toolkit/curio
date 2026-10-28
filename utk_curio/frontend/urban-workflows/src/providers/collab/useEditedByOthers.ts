/**
 * The nodes someone else is editing the code of now, from the doc's
 * awareness (`presence.ts`): removing one asks first.
 */
import { useEffect, useState } from "react";

import { useDocBinding } from "./docContext";
import { othersOf } from "./presence";

const NONE: ReadonlySet<string> = new Set();

function editedNodes(states: ReturnType<typeof othersOf>): ReadonlySet<string> {
    const ids = new Set<string>();
    for (const [, state] of states) if (typeof state.editing === "string") ids.add(state.editing);
    return ids.size ? ids : NONE;
}

function sameSet(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
    if (a.size !== b.size) return false;
    for (const id of a) if (!b.has(id)) return false;
    return true;
}

export function useEditedByOthers(): ReadonlySet<string> {
    const binding = useDocBinding();
    const awareness = binding?.provider.awareness ?? null;
    const [edited, setEdited] = useState<ReadonlySet<string>>(NONE);
    useEffect(() => {
        if (!awareness) {
            setEdited(NONE);
            return;
        }
        const read = () => {
            const next = editedNodes(othersOf(awareness));
            setEdited((prev) => (sameSet(prev, next) ? prev : next));
        };
        read();
        awareness.on("change", read);
        return () => awareness.off("change", read);
    }, [awareness]);
    return edited;
}
