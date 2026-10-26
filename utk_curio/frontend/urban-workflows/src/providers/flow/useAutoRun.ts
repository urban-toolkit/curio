// Auto-run (#845): with the dataflow's "Run stale nodes automatically" on, a
// widget value change runs the nodes it touched and every node below them,
// once the changes settle, through the run Run All starts. On a
// dashboard it is always on and starts a viewer's run (useDashboardRun, #1117).
// Only those value changes ask for it: code typed into a node, a new edge, and
// a brush that rewrites a selection tag mark nodes stale and run nothing.
import { useCallback, useEffect, useRef } from "react";
import type { Edge, ReactFlowInstance } from "reactflow";
import { directedEdgesOf } from "./runLevels";

/** How long the changes have to settle, a slider's steps say, before the run starts. */
export const AUTO_RUN_SETTLE_MS = 500;

/**
 * The nodes a change to *touched* runs: those of them still on the canvas,
 * and every node below them by a data edge, in canvas order.
 */
export function autoRunTargets(
    touched: Iterable<string>,
    nodes: readonly { id: string }[],
    edges: readonly Edge[],
): string[] {
    const onCanvas = new Set(nodes.map((n) => n.id));
    const successors = new Map<string, string[]>();
    for (const edge of directedEdgesOf([...edges])) {
        const list = successors.get(edge.source) ?? [];
        list.push(edge.target);
        successors.set(edge.source, list);
    }
    const reached = new Set([...touched].filter((id) => onCanvas.has(id)));
    const queue = [...reached];
    while (queue.length) {
        const nodeId = queue.pop()!;
        for (const next of successors.get(nodeId) ?? []) {
            if (onCanvas.has(next) && !reached.has(next)) {
                reached.add(next);
                queue.push(next);
            }
        }
    }
    return nodes.map((n) => n.id).filter((id) => reached.has(id));
}

/**
 * *enabled*: the toggle is on where auto-run is offered. *runActive*: a run
 * goes, in the browser or on the server. *start* runs the targets.
 */
export function useAutoRun({ enabled, runActive, reactFlow, start }: {
    enabled: boolean;
    runActive: boolean;
    reactFlow: Pick<ReactFlowInstance, "getNodes" | "getEdges">;
    start: (targets: string[]) => void;
}) {
    const touched = useRef(new Set<string>());
    const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
    // The changes settled while a run went: they run once it ends.
    const waiting = useRef(false);
    const enabledRef = useRef(enabled);
    enabledRef.current = enabled;
    const runActiveRef = useRef(runActive);
    runActiveRef.current = runActive;
    const startRef = useRef(start);
    startRef.current = start;

    const clearTimer = () => {
        if (timer.current) clearTimeout(timer.current);
        timer.current = null;
    };

    /** Forget the changes that have not run yet. */
    const dropWaiting = useCallback(() => {
        clearTimer();
        touched.current = new Set();
        waiting.current = false;
    }, []);

    const fire = useCallback(() => {
        if (!enabledRef.current) {
            dropWaiting();
            return;
        }
        if (runActiveRef.current) {
            waiting.current = true;
            return;
        }
        waiting.current = false;
        const targets = autoRunTargets(touched.current, reactFlow.getNodes(), reactFlow.getEdges());
        touched.current = new Set();
        if (targets.length) startRef.current(targets);
    }, [reactFlow, dropWaiting]);

    /** A widget value changed what *nodeIds* compute. */
    const requestAutoRun = useCallback((nodeIds: readonly string[]) => {
        if (!enabledRef.current || nodeIds.length === 0) return;
        nodeIds.forEach((id) => touched.current.add(id));
        clearTimer();
        timer.current = setTimeout(() => {
            timer.current = null;
            fire();
        }, AUTO_RUN_SETTLE_MS);
    }, [fire]);

    // Turned off: the changes that have not run yet never do.
    useEffect(() => {
        if (!enabled) dropWaiting();
    }, [enabled, dropWaiting]);

    // A run ended: the changes that settled while it went run now, once.
    useEffect(() => {
        if (!runActive && waiting.current && !timer.current) fire();
    }, [runActive, fire]);

    useEffect(() => clearTimer, []);

    return { requestAutoRun, dropWaiting };
}
