// The categories the canvas title shows (`serverCategories`), asked of the
// server again as the dataflow changes (`GET /api/projects/<id>/categories`).
// Only the server derives them from the dataflow, and no tab saves it any
// more, whose answer carried them.
//
// Every tab bound to the dataflow's doc asks, a watcher's among them: after a
// change to the doc, this tab's or one the server relays, once changes have
// been quiet for CATEGORIES_QUIET_MS and the server has this tab's own; and at
// once when a server run ends. One request at a time, so a burst of changes
// costs one.
import { useCallback, useEffect, useRef } from "react";
import { projectsApi } from "../../api/projectsApi";
import type { DataflowCategories } from "../../utils/dataflowCategories";
import type { DataflowDocProvider } from "../collab/docProvider";

/** How long the dataflow's doc stays quiet before its categories are asked again. */
export const CATEGORIES_QUIET_MS = 3000;

export interface CategoriesRefreshDeps {
    /** The doc the canvas is bound to; null while it is bound to none. */
    provider: DataflowDocProvider | null;
    /** How many answers with the categories the canvas has taken so far. */
    taken: () => number;
    /** Show *categories* on the canvas title. */
    take: (categories: DataflowCategories) => void;
}

export function useCategoriesRefresh({ provider, taken, take }: CategoriesRefreshDeps): { now: () => void } {
    const latest = useRef({ provider, taken, take });
    latest.current = { provider, taken, take };
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const askingRef = useRef(false);
    const againRef = useRef(false);
    const askRef = useRef<() => Promise<void>>(async () => {});

    const stopWaiting = useCallback(() => {
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = null;
    }, []);

    /** Ask once the doc has been quiet for CATEGORIES_QUIET_MS. */
    const askSoon = useCallback(() => {
        stopWaiting();
        timerRef.current = setTimeout(() => {
            timerRef.current = null;
            void askRef.current();
        }, CATEGORIES_QUIET_MS);
    }, [stopWaiting]);

    /** Ask now, or once the request out is answered. */
    const ask = useCallback(async (): Promise<void> => {
        stopWaiting();
        const held = latest.current.provider;
        if (!held) return;
        if (askingRef.current) {
            againRef.current = true;
            return;
        }
        askingRef.current = true;
        try {
            // Once the server has this tab's own changes (a watcher's has
            // none); asked again later while it does not.
            const kept = await held.whenKept();
            if (latest.current.provider !== held) return;
            if (!kept) {
                askSoon();
                return;
            }
            const before = latest.current.taken();
            const answer = await projectsApi.categories(held.projectId);
            // Another dataflow's by now, or overtaken by a newer answer (a
            // record's, File > Save's).
            if (latest.current.provider !== held || latest.current.taken() !== before) return;
            if (answer?.categories) latest.current.take(answer.categories);
        } catch {
            // The title keeps the categories it shows; the next change asks again.
        } finally {
            askingRef.current = false;
            if (againRef.current) {
                againRef.current = false;
                void askRef.current();
            }
        }
    }, [askSoon, stopWaiting]);
    askRef.current = ask;

    useEffect(() => {
        if (!provider) return;
        provider.doc.on("update", askSoon);
        return () => {
            provider.doc.off("update", askSoon);
            stopWaiting();
            againRef.current = false;
        };
    }, [provider, askSoon, stopWaiting]);

    const now = useCallback(() => {
        void askRef.current();
    }, []);
    return { now };
}
