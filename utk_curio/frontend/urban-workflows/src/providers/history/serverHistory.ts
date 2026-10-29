/**
 * Whose history this tab's canvas has: the server's, while the canvas is
 * bound to the dataflow's doc (`useDataflowDoc`), or the browser's own, while
 * it is not (a dataflow never saved, a hosted guest's own canvas, the
 * dashboard).
 *
 * The one check the browser's recorders make (`ProvenanceProvider`'s entries,
 * `TrillGenerator`'s versions): a canvas bound to the doc records nothing
 * here, since the server records its versions (`collaboration/history.py`)
 * and the entries the tab sends it, and the drawers read them from there. A
 * canvas that binds hands the history it carries to the server: a save
 * carries it, or `ProvenanceProvider` sends the runs no save carried.
 */
import { useSyncExternalStore } from "react";

import { historyApi, type SavedVersion } from "../../api/historyApi";

/** What the server tells the owner's and the editors' tabs when the history
 *  changed (`history.py`'s `CHANGED_EVENT`): the drawers read it again. */
export const HISTORY_CHANGED_EVENT = "history_changed";

export interface ServerHistory {
    readonly projectId: string;
    /** Whether this tab reads and adds to the history: an owner's and an
     *  invited editor's do; a watcher's never does. */
    reads(): boolean;
    /** Resolves once the server holds every change this tab made to the doc,
     *  so what it sends next comes after them. */
    whenKept(): Promise<boolean>;
    /** The code the doc holds in *nodeId* now, as its editor shows it;
     *  undefined when the doc has no such node. */
    codeOf(nodeId: string): string | undefined;
}

let held: ServerHistory | null = null;
const listeners = new Set<() => void>();

/** The history the server keeps for this tab's canvas, or null. */
export function serverHistory(): ServerHistory | null {
    return held;
}

/** The canvas bound to a dataflow's doc (*next*), or to none (null). */
export function setServerHistory(next: ServerHistory | null): void {
    if (held === next) return;
    held = next;
    listeners.forEach((listener) => listener());
}

export function subscribeServerHistory(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

/** {@link serverHistory}, for a component that renders by it. */
export function useServerHistory(): ServerHistory | null {
    return useSyncExternalStore(subscribeServerHistory, serverHistory, serverHistory);
}

/** Once React has drawn what was just changed, and the doc's writer has
 *  taken it. */
export function afterCommit(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

/** File > Save of a dataflow the canvas is bound to: a version named Saved,
 *  after every change this tab made. Its answer, with the dataflow's
 *  categories as it is now; null when no version was recorded. */
export async function noteSaved(): Promise<SavedVersion | null> {
    const server = serverHistory();
    if (!server || !server.reads()) return null;
    await server.whenKept();
    try {
        return await historyApi.saved(server.projectId);
    } catch (error) {
        console.warn("[history] File > Save's version was not recorded:", error);
        return null;
    }
}
