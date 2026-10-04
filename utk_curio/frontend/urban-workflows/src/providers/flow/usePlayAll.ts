// Run All and run up to a node: the level-by-level runner, its stall
// watchdog, and the signal a node sends when its run ends. FlowProvider holds
// the run's state (playAllStateRef, isRunActive) and passes it in.
import React, { useCallback, useRef } from "react";
import type { Edge, Node, ReactFlowInstance } from "reactflow";
import type { useToastContext } from "../ToastProvider";
import { resolveNodeDisplayLabel } from "../../utils/palettePackageFactoryDraft";
import { upstreamErroredMessage } from "../../utils/nodeEmptyState";
import type { NodeExecOutcome } from "./flowTypes";
import { computeTopologicalLevels, directedEdgesOf, nodesToRunUpTo } from "./runLevels";

export interface PlayAllState {
    levels: string[][];
    currentLevel: number;
    pending: Set<string>;
    /** The directed edges the run was planned on. */
    edges: Array<{ source: string; target: string }>;
    /** Nodes whose run failed in this run. */
    failed: Set<string>;
    /** Nodes this run did not run, because a node feeding them failed or was not run. */
    skipped: Set<string>;
    /** Told how each node ended: run, failed, or not run because of the node above it. */
    onNodeDone?: (nodeId: string, outcome: { failed: boolean; skipReason?: string }) => void;
    /** Told when the run ends on its own; a cancelled run ends without it. */
    onFinish?: () => void;
}


// Play All advances level-by-level only once every node in the active level
// reports it finished. If a node never does — the backend never returns, its
// output never reaches success/error, or a node type forgets to signal — the run
// would wedge forever and every downstream level (and the datasets those nodes
// produce) would never run. This watchdog bounds that: if NO node in the active
// level makes progress for this long, the run force-advances past the stuck
// node(s) with a warning. The timer resets on every completion, so a level full
// of legitimately-slow nodes is fine as long as they keep finishing. Sized to
// the client execution ceiling so a single genuinely-running node isn't cut off.
const PLAY_ALL_STALL_TIMEOUT_MS = 600_000;

export function usePlayAll({
    playAllStateRef, setIsRunActive, flushInstallSyncRef, showToast, reactFlow,
    markNodeErroredRef, setNodes, emittedForInputRef,
}: {
    playAllStateRef: React.MutableRefObject<PlayAllState | null>;
    setIsRunActive: React.Dispatch<React.SetStateAction<boolean>>;
    flushInstallSyncRef: React.MutableRefObject<() => void>;
    showToast: ReturnType<typeof useToastContext>["showToast"];
    reactFlow: ReactFlowInstance;
    markNodeErroredRef: React.MutableRefObject<(nodeId: string) => void>;
    setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
    emittedForInputRef: React.MutableRefObject<Map<string, unknown>>;
}) {
    const playAllStallTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const clearPlayAllStallTimer = () => {
        if (playAllStallTimerRef.current) {
            clearTimeout(playAllStallTimerRef.current);
            playAllStallTimerRef.current = null;
        }
    };

    // End the run: stop the watchdog, drop the state, and persist the final burst
    // immediately so the last level's datasets can't be lost to the install-save
    // debounce window (see flushInstallSyncRef / scheduleInstallSyncRef).
    function finishPlayAll() {
        const onFinish = playAllStateRef.current?.onFinish;
        clearPlayAllStallTimer();
        playAllStateRef.current = null;
        setIsRunActive(false);
        flushInstallSyncRef.current();
        onFinish?.();
    }

    // Abandon the run without the finishing save: a cancelled run has nothing
    // new worth persisting, and on "New workflow" the user has just agreed to
    // discard changes. Nodes already executing still settle on their own;
    // their signals then find no run and are ignored (#271).
    function cancelRun() {
        clearPlayAllStallTimer();
        playAllStateRef.current = null;
        setIsRunActive(false);
    }

    function advancePlayAll(state: PlayAllState) {
        const next = state.currentLevel + 1;
        if (next < state.levels.length) triggerLevel(next);
        else finishPlayAll();
    }

    // (Re)arm the stall watchdog for the active level. Armed when a level is
    // triggered and reset on every node completion, so it fires only after a
    // genuine no-progress stall — never while nodes are still finishing.
    function armPlayAllStallTimer() {
        clearPlayAllStallTimer();
        playAllStallTimerRef.current = setTimeout(() => {
            playAllStallTimerRef.current = null;
            const state = playAllStateRef.current;
            if (!state) return;
            const stuck = state.pending.size;
            if (stuck > 0) {
                const ids = [...state.pending].join(", ");
                showToast(
                    `${stuck} node(s) didn't finish in time (${ids}); continuing with the rest ` +
                    "of the run. Use the Run All button to cancel a run that is stuck.",
                    "warning",
                );
            }
            state.pending = new Set();
            advancePlayAll(state);
        }, PLAY_ALL_STALL_TIMEOUT_MS);
    }

    // The reason a node this run does not run shows instead of an outcome: the
    // node feeding it, by name, failed or was not run either (#603).
    function skipReason(sourceId: string): string {
        const source = reactFlow.getNode(sourceId);
        let name: string | null = null;
        try {
            name = source?.data ? resolveNodeDisplayLabel(source.data) : null;
        } catch {
            name = null;
        }
        return upstreamErroredMessage(name);
    }

    function triggerLevel(levelIndex: number) {
        const state = playAllStateRef.current;
        if (!state) return;
        const levelNodeIds = state.levels[levelIndex];
        if (!levelNodeIds?.length) { finishPlayAll(); return; }
        state.currentLevel = levelIndex;
        // A node fed by one that failed in this run, or by one this run did not
        // run, is not run either, as the agent runner stops at the first failure
        // (#603). It still counts as done for its level, so the run moves on.
        const skipped = new Map<string, string>();
        for (const id of levelNodeIds) {
            const stoppedBy = state.edges.find(
                e => e.target === id && (state.failed.has(e.source) || state.skipped.has(e.source)),
            );
            if (stoppedBy) skipped.set(id, skipReason(stoppedBy.source));
        }
        const toRun = levelNodeIds.filter(id => !skipped.has(id));
        state.pending = new Set(toRun);
        for (const [id, reason] of skipped) {
            state.skipped.add(id);
            // Errored, so the nodes it feeds read "upstream-errored" by the rule
            // charts and the Data Pool already use.
            markNodeErroredRef.current(id);
            state.onNodeDone?.(id, { failed: true, skipReason: reason });
        }
        setNodes((nds: Node[]) =>
            nds.map((node: Node) => {
                if (toRun.includes(node.id)) {
                    return { ...node, data: { ...node.data, triggerExec: (node.data.triggerExec ?? 0) + 1 } };
                }
                if (skipped.has(node.id)) {
                    return {
                        ...node,
                        data: {
                            ...node.data,
                            skipExec: (node.data.skipExec ?? 0) + 1,
                            skipReason: skipped.get(node.id),
                        },
                    };
                }
                return node;
            })
        );
        if (toRun.length === 0) {
            advancePlayAll(state);
            return;
        }
        armPlayAllStallTimer();
    }

    const signalNodeExecDone = useCallback((nodeId: string, outcome?: NodeExecOutcome) => {
        const state = playAllStateRef.current;
        if (!state) return;
        // Ignore signals from nodes that aren't part of the active level (e.g. a
        // straggler/duplicate from an earlier level) — they must not drain the
        // pending set or reset the watchdog.
        if (!state.pending.delete(nodeId)) return;
        // The signal that completes a node says whether it failed; a later one
        // for the same node is ignored above. Carried here rather than read from
        // the node's exec status, which may not have committed yet (#603).
        if (outcome?.failed) state.failed.add(nodeId);
        state.onNodeDone?.(nodeId, { failed: !!outcome?.failed });
        if (state.pending.size === 0) {
            advancePlayAll(state);
        } else {
            // Progress made — reset the watchdog so slow-but-alive levels survive.
            armPlayAllStallTimer();
        }
    }, [setNodes]);

    function playAllNodes() {
        if (playAllStateRef.current != null) {
            // Say so. A silent no-op here is indistinguishable from a dead
            // button, which is how #271 was reported.
            showToast(
                "A run is already in progress. Wait for it to finish, or cancel it from the Run All button.",
                "info",
            );
            return;
        }
        const allNodes = reactFlow.getNodes();
        const allEdges = reactFlow.getEdges();
        const levels = computeTopologicalLevels(allNodes, allEdges);
        if (!levels.length) return;
        const visitedIds = new Set(levels.flat());
        const cyclic = allNodes.filter(n => !visitedIds.has(n.id));
        if (cyclic.length > 0) {
            showToast(`${cyclic.length} node(s) skipped due to cycles in the graph`, "warning");
        }
        playAllStateRef.current = newRunState(levels, allEdges);
        setIsRunActive(true);
        triggerLevel(0);
    }

    function newRunState(levels: string[][], edges: Edge[]): PlayAllState {
        return {
            levels,
            currentLevel: 0,
            pending: new Set(),
            edges: directedEdgesOf(edges).map(e => ({ source: e.source, target: e.target })),
            failed: new Set(),
            skipped: new Set(),
        };
    }

    // *target* is one node, or a list that all run: a scenario's levers
    // (#662), with only those of its context that cannot be reused.
    function playNodesUpTo(target: string | readonly string[]) {
        // Same guard playAllNodes has. Without it a second play click - which
        // the e2e helper issues on its own, retrying up to three times when a
        // node has not visibly acknowledged - overwrites playAllStateRef and
        // orphans the level already in flight.
        if (playAllStateRef.current != null) {
            showToast(
                "A run is already in progress. Wait for it to finish, or cancel it from the Run All button.",
                "info",
            );
            return;
        }

        const currentNodes = reactFlow.getNodes();
        const currentEdges = reactFlow.getEdges();
        const { willRun } = nodesToRunUpTo(
            target, currentNodes, currentEdges, emittedForInputRef.current,
        );
        playNodes([...willRun]);
    }

    /**
     * Run the given nodes in the order Run All would, each level once the one
     * above it has reported. The browser half of a run on the server goes
     * through here, with *hooks* reporting each node to that run.
     */
    function playNodes(
        nodeIds: string[],
        hooks: Pick<PlayAllState, "onNodeDone" | "onFinish"> = {},
    ): boolean {
        if (playAllStateRef.current != null) {
            showToast(
                "A run is already in progress. Wait for it to finish, or cancel it from the Run All button.",
                "info",
            );
            return false;
        }
        const wanted = new Set(nodeIds);
        const subgraphNodes = reactFlow.getNodes().filter(n => wanted.has(n.id));
        const subgraphEdges = reactFlow.getEdges().filter(
            e => wanted.has(e.source) && wanted.has(e.target)
        );

        const levels = computeTopologicalLevels(subgraphNodes, subgraphEdges);
        if (!levels.length) return false;

        playAllStateRef.current = { ...newRunState(levels, subgraphEdges), ...hooks };
        setIsRunActive(true);
        triggerLevel(0);
        return true;
    }

    return { cancelRun, signalNodeExecDone, playAllNodes, playNodesUpTo, playNodes };
}
