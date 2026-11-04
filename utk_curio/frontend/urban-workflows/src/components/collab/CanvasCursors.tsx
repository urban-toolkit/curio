/**
 * Everyone's pointer on the canvas (`providers/collab/cursors.ts`).
 *
 * - This tab's goes into the doc's awareness as `pointer` while it is over the
 *   canvas, nodes included, and becomes null when it leaves the canvas (onto
 *   the top bar, the tool rail, a menu) or the tab is hidden.
 * - Everyone else's is drawn over the canvas on the scenario layers' plane
 *   (`ParticipantCursors`), watchers' included; this tab's own never is.
 * - An agent's drag is drawn with the cursor that carries it (`AgentDrags`),
 *   so a state that carries one has no cursor of its own (`cursors.ts`).
 *
 * A canvas bound to no doc (never saved, a hosted guest's example) sends and
 * draws nothing. A child of React Flow, which it reads the view from.
 */
import React, { useEffect, useState } from "react";
import { useStore, useStoreApi, type ReactFlowState } from "reactflow";
import type { Awareness } from "y-protocols/awareness";

import { useDocBinding } from "../../providers/collab/docContext";
import { othersOf } from "../../providers/collab/presence";
import {
    CursorSender,
    CursorTracker,
    flowPointOf,
    sameCursors,
    type DrawnCursor,
    type Point,
} from "../../providers/collab/cursors";
import { ParticipantCursors } from "../scenarios/ScenarioLayers";
import { AgentDrags } from "./AgentDrags";

const NONE: DrawnCursor[] = [];
const canvasOf = (s: ReactFlowState) => s.domNode;

/** Puts this tab's pointer into *awareness* while it is on the canvas. */
function useCursorSending(awareness: Awareness | null): void {
    const store = useStoreApi();
    const canvas = useStore(canvasOf);
    useEffect(() => {
        if (!awareness || !canvas) return;
        // Where the pointer is, in window coordinates, while it is on the canvas.
        let pointer: Point | null = null;
        const sender = new CursorSender(awareness, () => {
            if (!pointer) return null;
            const box = canvas.getBoundingClientRect();
            return flowPointOf(pointer, { x: box.left, y: box.top }, store.getState().transform);
        });
        const onMove = (event: PointerEvent) => {
            pointer = { x: event.clientX, y: event.clientY };
            sender.moved();
        };
        const onLeave = () => {
            pointer = null;
            sender.left();
        };
        const onVisibility = () => {
            if (document.visibilityState === "hidden") onLeave();
        };
        // A view that moves under a resting pointer (a zoom button, a fit)
        // moves it on the dataflow.
        const unsubscribe = store.subscribe((state, prev) => {
            if (pointer && state.transform !== prev.transform) sender.moved();
        });
        // Capturing: a node's editor that keeps its moves to itself still
        // has the pointer on the canvas.
        canvas.addEventListener("pointermove", onMove, { capture: true, passive: true });
        canvas.addEventListener("pointerleave", onLeave);
        document.addEventListener("visibilitychange", onVisibility);
        return () => {
            unsubscribe();
            canvas.removeEventListener("pointermove", onMove, { capture: true });
            canvas.removeEventListener("pointerleave", onLeave);
            document.removeEventListener("visibilitychange", onVisibility);
            sender.stop();
        };
    }, [awareness, canvas, store]);
}

/** Everyone else's cursors in *awareness*, each faded once it rests. */
function useOthersCursors(awareness: Awareness | null): DrawnCursor[] {
    const [cursors, setCursors] = useState<DrawnCursor[]>(NONE);
    useEffect(() => {
        if (!awareness) {
            setCursors(NONE);
            return;
        }
        const tracker = new CursorTracker();
        let fade: ReturnType<typeof setTimeout> | null = null;
        const read = () => {
            if (fade) clearTimeout(fade);
            fade = null;
            const now = Date.now();
            const next = tracker.read(othersOf(awareness), now);
            setCursors((prev) => (sameCursors(prev, next) ? prev : next.length ? next : NONE));
            const at = tracker.nextFadeAt(now);
            if (at !== null) fade = setTimeout(read, at - now);
        };
        read();
        awareness.on("change", read);
        return () => {
            awareness.off("change", read);
            if (fade) clearTimeout(fade);
        };
    }, [awareness]);
    return cursors;
}

export const CanvasCursors = React.memo(function CanvasCursors() {
    const awareness = useDocBinding()?.provider.awareness ?? null;
    useCursorSending(awareness);
    const cursors = useOthersCursors(awareness);
    return (
        <>
            {cursors.length > 0 ? <ParticipantCursors cursors={cursors} /> : null}
            <AgentDrags awareness={awareness} />
        </>
    );
});
