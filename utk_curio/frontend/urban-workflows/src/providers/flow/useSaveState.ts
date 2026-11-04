/**
 * What the top bar says of the open dataflow, and whether closing the tab
 * asks first.
 *
 * A canvas bound to the dataflow's doc saves nothing itself: the doc keeps
 * each change as it is made. It reads Saved once the server has every change
 * this tab made, Saving... while some are on their way, and Offline while the
 * tab cannot reach the server and changes wait in it. Saving... and Offline
 * show only once a change has waited a moment, so typing does not make the
 * bar flicker. A canvas bound to no doc (a dataflow not saved yet, a hosted
 * guest's own canvas, the dashboard) reads Unsaved while it holds changes no
 * one keeps.
 *
 * Closing or reloading the tab asks while changes wait: nothing is kept in the
 * browser across a reload.
 */
import { useEffect, useRef, useState } from "react";

import type { DataflowDocProvider } from "../collab/docProvider";

export type SaveState = "saved" | "saving" | "offline" | "unsaved";

type KeptState = Exclude<SaveState, "unsaved">;

/** How long a change waits before the bar says Saving... or Offline. */
export const SAVING_SHOWN_AFTER_MS = 800;

export interface SaveStateDeps {
    /** The doc the canvas is bound to, or null. */
    provider: DataflowDocProvider | null;
    /** Whether the tab's socket reaches the server. */
    connected: boolean;
    /** A canvas bound to no doc holds changes no one keeps. */
    projectDirty: boolean;
    /** When the dataflow was last saved, as its load or File > Save says. */
    projectSavedAt: Date | null;
}

export function useSaveState({ provider, connected, projectDirty, projectSavedAt }: SaveStateDeps): {
    /** What the bar shows. */
    state: SaveState;
    /** When the server last had every change, or the dataflow was last saved. */
    savedAt: Date | null;
    /** Whether changes of this tab's wait for the server now, shown or not. */
    pending: boolean;
} {
    const [shown, setShown] = useState<KeptState>("saved");
    const [pending, setPending] = useState(false);
    const [keptAt, setKeptAt] = useState<Date | null>(null);
    const shownRef = useRef<KeptState>("saved");
    const pendingRef = useRef(false);

    useEffect(() => {
        if (!provider) return;
        let alive = true;
        let waiting = false;
        let timer: ReturnType<typeof setTimeout> | null = null;
        const show = (next: KeptState) => {
            if (shownRef.current === next) return;
            shownRef.current = next;
            setShown(next);
        };
        const note = (next: boolean) => {
            if (pendingRef.current === next) return;
            pendingRef.current = next;
            if (!next) setKeptAt(new Date());
            setPending(next);
        };
        const check = () => {
            if (!alive) return;
            if (provider.isKept()) {
                if (timer) clearTimeout(timer);
                timer = null;
                note(false);
                show("saved");
                return;
            }
            note(true);
            const waitingAs: KeptState = connected ? "saving" : "offline";
            if (shownRef.current !== "saved") show(waitingAs);
            else if (!timer) {
                timer = setTimeout(() => {
                    timer = null;
                    if (alive && !provider.isKept()) show(connected ? "saving" : "offline");
                }, SAVING_SHOWN_AFTER_MS);
            }
            if (waiting || !connected) return;
            waiting = true;
            void provider.whenKept().then(() => {
                waiting = false;
                check();
            });
        };
        // This tab's own changes: the provider has sent them by now, as it
        // listens first.
        const onUpdate = (_update: Uint8Array, origin: unknown) => {
            if (origin !== provider) check();
        };
        provider.doc.on("update", onUpdate);
        check();
        return () => {
            alive = false;
            if (timer) clearTimeout(timer);
            provider.doc.off("update", onUpdate);
        };
    }, [provider, connected]);

    if (!provider) {
        return {
            state: projectDirty || !projectSavedAt ? "unsaved" : "saved",
            savedAt: projectSavedAt,
            pending: projectDirty,
        };
    }
    return { state: shown, savedAt: keptAt ?? projectSavedAt, pending };
}

/**
 * Closing or reloading the tab asks while changes wait: a bound canvas's that
 * the server does not have yet (read as the tab closes), or a canvas bound to
 * no doc that holds changes no one keeps.
 */
export function useLeavePageGuard(provider: DataflowDocProvider | null, projectDirty: boolean): void {
    useEffect(() => {
        if (!provider && !projectDirty) return;
        const handler = (e: BeforeUnloadEvent) => {
            if (provider ? provider.isKept() : !projectDirty) return;
            e.preventDefault();
            e.returnValue = "";
        };
        window.addEventListener("beforeunload", handler);
        return () => window.removeEventListener("beforeunload", handler);
    }, [provider, projectDirty]);
}
