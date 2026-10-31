// Runs on the server. Run All, a node's play button, Ctrl+Enter and an
// automatic run (useAutoRun, #845) start a run of the dataflow as its doc holds
// it, once the server has this tab's last change, and the run goes on with the
// tab closed (runs/routes.py). A dataflow not saved yet is made first. The tab
// follows the run's stream: each step reaches
// its node by the rules a run in the browser follows (executionResultOutput,
// applyNewOutput, the provenance), and the nodes only a browser can run go
// through usePlayAll once the server's part has ended, each reported to the run.
//
// A canvas opened later shows the outputs of the dataflow's last run, follows
// it if it is still going, and offers to finish it when it waits for a tab.
import React, { useEffect, useRef, useState } from "react";
import type { Node, ReactFlowInstance } from "reactflow";
import type { useToastContext } from "../ToastProvider";
import { ACTIVE_RUN_STATUSES, runsApi } from "../../services/runs/runsApi";
import type { Run, RunEvent, RunStatus } from "../../services/runs/runsApi";
import type { NodeOutput } from "../../hook/useNodeState";
import type { DatasetInstallWarning } from "../../api/projectsApi";
import type { IOutput } from "./flowTypes";
import type { PlayAllState } from "./usePlayAll";
import { useStepOutcomes, type StepOutcomes } from "./useStepOutcomes";
import { runKeysOf } from "../../utils/references/runKeys";
import {
    STOPPED_MESSAGE,
    browserWalk,
    nodeChangeFor,
    replyFromRecord,
    reportsToRun,
    reuseFor,
    settledStatus,
    type NodeChange,
    type TrackedStep,
} from "./serverRunSteps";

/** How often the tab follows a run again after its stream dropped while it was going. */
const MAX_REFOLLOWS = 5;
/** How often a browser node's report is sent while the server still writes the run's end. */
const MAX_REPORT_ATTEMPTS = 6;
/** How often a start is tried while the server still writes the end of the run this tab saw end. */
const MAX_START_ATTEMPTS = 3;
/** How long, in reads a quarter second apart, a start waits for the server to write that end. */
const END_WAIT_READS = 40;

interface FollowedRun {
    runId: string;
    steps: Map<string, TrackedStep>;
    /** Nodes whose finished step reached them, so a replayed event is not applied twice. */
    applied: Set<string>;
    /** Nodes this run showed as running. */
    started: Set<string>;
    /** Nodes whose step finished, by the stream's own events. */
    settled: Set<string>;
    /**
     * Started here (or asked for here and already going): outputs pass on as a
     * run's do, and this tab runs the nodes only a browser can. A run the tab
     * found going when it opened only shows its outputs, as a load does.
     */
    startedHere: boolean;
    /** The node a play ran up to, and what it showed before the click; null for Run All. */
    played: { nodeId: string; before: NodeOutput | undefined } | null;
    /** The nodes an automatic run ran (#845); null for any other run. */
    targets: readonly string[] | null;
    /**
     * Each node's run key when the server had this tab's last change and the
     * run started; a result is stamped with its node's. Null for a run this
     * tab did not start, whose results take the key their node holds when they
     * land.
     */
    runKeys: Map<string, string> | null;
    controller: AbortController;
    done: boolean;
    refollows: number;
}

type PlayNodes = (
    nodeIds: string[],
    hooks?: Pick<PlayAllState, "onNodeDone" | "onFinish">,
) => boolean;

export function useServerRun({
    reactFlow, setNodes, showToast, keepDataflow, applyNewOutput, setOutputs,
    hydrateRestoredOutputs, markNodeErroredRef, playNodes, playAllStateRef,
    emittedForInputRef, outputsRef, workflowNameRef, nodeExecProv, flushInstallSyncRef,
    surfaceInstallWarnings, outcomes, onRunEnded,
}: {
    reactFlow: ReactFlowInstance;
    setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
    showToast: ReturnType<typeof useToastContext>["showToast"];
    /** The dataflow's id once the server has this tab's every change, a
     *  dataflow not saved yet made first (`ensureProjectId`); null when there
     *  is none to run, with the reason said. */
    keepDataflow: () => Promise<string | null>;
    applyNewOutput: (output: IOutput) => void;
    setOutputs: (fnOrValue: ((prev: IOutput[]) => IOutput[]) | IOutput[]) => void;
    hydrateRestoredOutputs: (restored: IOutput[], edges?: readonly any[]) => void;
    markNodeErroredRef: React.MutableRefObject<(nodeId: string) => void>;
    playNodes: PlayNodes;
    playAllStateRef: React.MutableRefObject<PlayAllState | null>;
    emittedForInputRef: React.MutableRefObject<Map<string, unknown>>;
    outputsRef: React.MutableRefObject<IOutput[]>;
    workflowNameRef: React.MutableRefObject<string>;
    nodeExecProv: (...args: any[]) => void;
    flushInstallSyncRef: React.MutableRefObject<() => Promise<void> | void>;
    /** The warning a save's `dataset_install_warnings` raises, for an output a run could not install. */
    surfaceInstallWarnings?: (
        detail: { dataset_install_warnings?: DatasetInstallWarning[] } | undefined,
        scopeNodeIds?: readonly string[],
    ) => void;
    /** What a step does to its node, shared with a dashboard's runs (useStepOutcomes). */
    outcomes?: StepOutcomes;
    /** A run this tab followed ended: the canvas title asks for the dataflow's
     *  categories as it is now (useCategoriesRefresh). */
    onRunEnded?: () => void;
}) {
    // True from the click until the server's part ends. UniversalNode reads it
    // with isRunActive: a map or chart draws in the run's browser part, or from
    // its input once the run ends, never twice.
    const [serverRunActive, setServerRunActive] = useState(false);
    const followedRef = useRef<FollowedRun | null>(null);
    // The run this tab last saw end. It ends here as its last step lands, a
    // moment before the server writes its end, and a start in that moment is
    // refused naming it.
    const endedRunRef = useRef<string | null>(null);
    // Between the click and the run's answer: the wait for the server to hold
    // this tab's changes, then the start.
    const startingRef = useRef<{ stopped: boolean } | null>(null);

    // ── What reaches a node ──────────────────────────────────────────────

    // FlowProvider shares one set with a dashboard's runs; a caller that
    // passes none (a test) gets this hook's own.
    const own = useStepOutcomes({
        reactFlow, setNodes, applyNewOutput, setOutputs, hydrateRestoredOutputs,
        markNodeErroredRef, workflowNameRef, nodeExecProv,
    });
    const { showOnNode, showResult, showSkipped } = outcomes ?? own;

    const applyChange = (run: FollowedRun, nodeId: string, change: NodeChange | null) => {
        if (!change) return;
        if (change.kind === "running") {
            run.started.add(nodeId);
            if (!run.applied.has(nodeId)) showOnNode(nodeId, { code: "exec", content: "" });
            return;
        }
        if (run.applied.has(nodeId)) return;
        run.applied.add(nodeId);
        if (change.kind === "result") {
            showResult(nodeId, change, { live: run.startedHere, runKey: run.runKeys?.get(nodeId) });
        }
        else if (change.kind === "skipped") showSkipped(nodeId, change.reason);
        else showOnNode(nodeId, { code: "error", content: STOPPED_MESSAGE });
    };

    // ── Following a run ──────────────────────────────────────────────────

    const onEvent = (run: FollowedRun, event: RunEvent) => {
        if (followedRef.current !== run) return;
        if (event.kind === "run") {
            for (const step of event.run.steps ?? []) {
                run.steps.set(step.nodeId, { role: step.role, status: step.status });
            }
            return;
        }
        if (event.kind === "run_finished") {
            finish(run, event.status);
            return;
        }
        if (event.kind !== "step_started" && event.kind !== "step_finished") return;
        const step = run.steps.get(event.nodeId);
        if (step) step.status = event.kind === "step_started" ? "running" : event.status;
        const firstOutcome = event.kind === "step_finished" && !run.applied.has(event.nodeId);
        applyChange(run, event.nodeId, nodeChangeFor(event, step, { started: run.started.has(event.nodeId) }));
        // An output the run could not install warns as it does after a save.
        if (firstOutcome && run.startedHere && event.kind === "step_finished" && event.installWarnings?.length) {
            surfaceInstallWarnings?.({ dataset_install_warnings: event.installWarnings }, [event.nodeId]);
        }
        if (event.kind !== "step_finished" || !step) return;
        run.settled.add(event.nodeId);
        // Every step has an outcome: the run is over, whatever its record
        // still says. Ending here, as the last node's own outcome lands, is
        // what a run in the browser does; the record's `run_finished` comes
        // after the server has written the run's outcome.
        if (run.settled.size >= run.steps.size) finish(run, settledStatus(run.steps));
    };

    const follow = (run: FollowedRun) => {
        runsApi
            .follow(run.runId, (event) => onEvent(run, event), run.controller.signal)
            .then(() => streamEnded(run), () => streamEnded(run));
    };

    // The stream ended before the run did: a dropped connection, or a backend
    // that restarted. Follow it again while it goes; otherwise its record says
    // how it ended.
    const streamEnded = async (run: FollowedRun) => {
        if (followedRef.current !== run || run.done) return;
        try {
            const record = await runsApi.get(run.runId);
            if (followedRef.current !== run || run.done) return;
            if (ACTIVE_RUN_STATUSES.has(record.status) && run.refollows < MAX_REFOLLOWS) {
                run.refollows += 1;
                window.setTimeout(() => {
                    if (followedRef.current === run && !run.done) follow(run);
                }, 1000 * run.refollows);
                return;
            }
            for (const step of record.steps ?? []) {
                run.steps.set(step.nodeId, { role: step.role, status: step.status });
                const change = nodeChangeFor(
                    { kind: "step_finished", nodeId: step.nodeId, status: step.status, skipReason: step.skipReason ?? undefined, reply: replyFromRecord(step) },
                    run.steps.get(step.nodeId),
                    { started: run.started.has(step.nodeId) },
                );
                applyChange(run, step.nodeId, change);
            }
            finish(run, record.status);
        } catch {
            stopFollowing(run, { stopped: false });
            showToast("Lost track of the run on the server. Open the dataflow again to see how it ended.", "warning");
        }
    };

    const attach = (
        record: Run,
        { startedHere, played = null, runKeys = null }: {
            startedHere: boolean; played?: FollowedRun["played"]; runKeys?: FollowedRun["runKeys"];
        },
    ) => {
        const run: FollowedRun = {
            runId: record.id,
            steps: new Map((record.steps ?? []).map((s) => [s.nodeId, { role: s.role, status: s.status }])),
            applied: new Set(),
            // The played node shows as running from the click on.
            started: new Set(played ? [played.nodeId] : []),
            settled: new Set(),
            startedHere,
            played,
            targets: record.targetNodeIds?.length ? record.targetNodeIds : null,
            runKeys,
            controller: new AbortController(),
            done: false,
            refollows: 0,
        };
        followedRef.current = run;
        setServerRunActive(true);
        follow(run);
    };

    /** Run the nodes only a browser can run, reporting each to *runId*. */
    const finishInBrowser = (
        runId: string,
        steps: Map<string, TrackedStep>,
        played: FollowedRun["played"] = null,
        targets: FollowedRun["targets"] = null,
    ): boolean => {
        const walk = browserWalk(steps, reactFlow.getEdges(), played?.nodeId ?? targets);
        if (!walk.length) return false;
        return playNodes(walk, {
            onNodeDone: (nodeId, outcome) => {
                // A kind whose play draws nothing of its own (a Data Export)
                // never leaves the running state the click gave it. The node
                // decides: an Autark node reports done in the tick it shows
                // its result, before `data.output` follows.
                if (played && nodeId === played.nodeId) {
                    showOnNode(nodeId, played.before ?? { code: "", content: "" }, { onlyIfRunning: true });
                }
                if (!reportsToRun(steps.get(nodeId))) return;
                const shown = reactFlow.getNode(nodeId)?.data?.output?.content;
                report(runId, nodeId, outcome.failed
                    ? { status: "error", message: outcome.skipReason ?? outcome.message ?? String(shown ?? "") }
                    : { status: "ok" });
            },
        });
    };

    // The tab can end a run as its last step lands, a moment before the server
    // has written the run's outcome, and the server takes no report until it
    // has (409): such a report is sent again shortly.
    const report = (
        runId: string, nodeId: string, body: { status: "ok" | "error"; message?: string }, attempt = 1,
    ) => {
        runsApi.reportStep(runId, nodeId, body).catch((err) => {
            if (err?.status !== 409 || attempt >= MAX_REPORT_ATTEMPTS) return;
            window.setTimeout(() => report(runId, nodeId, body, attempt + 1), 500 * attempt);
        });
    };

    const offerFinish = (runId: string) => {
        showToast(
            "This dataflow's last run is waiting for the canvas: some of its nodes run only in the browser.",
            "info",
            {
                action: {
                    label: "Finish run",
                    onClick: () => {
                        void runsApi.get(runId).then((record) => {
                            const steps = new Map((record.steps ?? []).map((s) => [s.nodeId, { role: s.role, status: s.status }]));
                            finishInBrowser(runId, steps, null, record.targetNodeIds?.length ? record.targetNodeIds : null);
                        }).catch((err) => showToast(err?.message || "The run could not be read.", "error"));
                    },
                },
            },
        );
    };

    const finish = (run: FollowedRun, status: RunStatus) => {
        if (run.done) return;
        run.done = true;
        endedRunRef.current = run.runId;
        run.controller.abort();
        followedRef.current = null;
        // In the same tick the flag goes down, so the Run All button never reads
        // "Run all nodes" between the server's part and the browser's.
        const browserPart = run.startedHere && finishInBrowser(run.runId, run.steps, run.played, run.targets);
        if (!run.startedHere && status === "needs_canvas") offerFinish(run.runId);
        setServerRunActive(false);
        if (!browserPart) void flushInstallSyncRef.current();
        onRunEnded?.();
    };

    /** Stop following without ending the run; with *stopped*, a node it left running says so. */
    const stopFollowing = (run: FollowedRun, { stopped }: { stopped: boolean }) => {
        run.done = true;
        run.controller.abort();
        if (followedRef.current === run) followedRef.current = null;
        if (stopped) {
            for (const nodeId of run.started) {
                if (!run.applied.has(nodeId)) showOnNode(nodeId, { code: "error", content: STOPPED_MESSAGE });
            }
        }
        setServerRunActive(false);
    };

    // ── What the canvas calls ────────────────────────────────────────────

    /** Wait until the server has written *runId*'s end; false when it has not in time. */
    const serverWroteEnd = async (runId: string): Promise<boolean> => {
        for (let read = 0; read < END_WAIT_READS; read++) {
            try {
                const record = await runsApi.get(runId);
                if (!ACTIVE_RUN_STATUSES.has(record.status)) return true;
            } catch {
                return false;
            }
            await new Promise((resolve) => window.setTimeout(resolve, 250));
        }
        return false;
    };

    /**
     * Run the whole dataflow, or *target* and the ancestors it needs: one node
     * (a play), or several (an automatic run, #845), once the server has this
     * tab's last change.
     */
    const startRun = async (target?: string | readonly string[]) => {
        const targetNodeId = typeof target === "string" ? target : undefined;
        const targets = typeof target === "string" || !target?.length ? undefined : [...target];
        if (followedRef.current || startingRef.current || playAllStateRef.current != null) {
            showToast(
                "A run is already in progress. Wait for it to finish, or cancel it with the stop button.",
                "info",
            );
            return;
        }
        const starting = { stopped: false };
        startingRef.current = starting;
        setServerRunActive(true);
        // Read at the click: what the canvas holds now is what it would reuse.
        const reuseTarget = targetNodeId ?? targets;
        const reuse = reuseTarget
            ? reuseFor(reuseTarget, reactFlow.getNodes(), reactFlow.getEdges(), emittedForInputRef.current, outputsRef.current)
            : undefined;
        // The played node says it runs from the click, as its own play makes it
        // say at once, rather than showing its last outcome through the wait.
        const shownBefore: NodeOutput | undefined = targetNodeId
            ? reactFlow.getNode(targetNodeId)?.data?.output
            : undefined;
        if (targetNodeId) showOnNode(targetNodeId, { code: "exec", content: "" });
        const unmark = () => {
            if (targetNodeId) showOnNode(targetNodeId, shownBefore ?? { code: "", content: "" });
        };
        const giveUp = (message?: string) => {
            if (startingRef.current === starting) startingRef.current = null;
            if (!starting.stopped) setServerRunActive(false);
            unmark();
            if (message) showToast(message, "error");
        };
        // The server runs the dataflow as its doc holds it once it has this
        // tab's last change (a dataflow not saved yet is made first).
        let projectId: string | null = null;
        try {
            projectId = await keepDataflow();
        } catch (err: any) {
            giveUp(`The dataflow was not run: ${err?.message || err}`);
            return;
        }
        if (starting.stopped) { giveUp(); return; }
        if (!projectId) { giveUp(); return; }
        // Each node's key now is the one its result is stamped with, so a
        // selection, widget value or code changed while the run goes leaves
        // the node stale.
        const runKeys = runKeysOf(reactFlow.getNodes());
        let record: Run | null = null;
        let refused: any = null;
        for (let attempt = 1; attempt <= MAX_START_ATTEMPTS && !record; attempt++) {
            try {
                record = await runsApi.start(projectId, {
                    ...(targetNodeId ? { target: targetNodeId, reuse } : {}),
                    ...(targets ? { targets, reuse } : {}),
                });
            } catch (err: any) {
                refused = err;
                // Refused naming the run this tab just saw end: the server is
                // still writing its end. Start again once it has.
                const endingId = err?.status === 409 ? err?.body?.runId : null;
                if (!endingId || endingId !== endedRunRef.current || starting.stopped) break;
                if (!(await serverWroteEnd(endingId))) break;
            }
        }
        if (!record) {
            const err = refused;
            const runningId = err?.status === 409 ? err?.body?.runId : null;
            if (!runningId || starting.stopped) {
                giveUp(starting.stopped ? undefined : (err?.message || "The run could not start."));
                return;
            }
            // The dataflow already runs, started by another tab or before this
            // one opened: follow that run, as a run opened later is shown, and
            // say so. The tab that started it runs its browser part.
            try {
                record = await runsApi.get(runningId);
            } catch (readErr: any) {
                giveUp(readErr?.message || "The run could not start.");
                return;
            }
            if (startingRef.current === starting) startingRef.current = null;
            unmark();
            showToast(
                "This dataflow is already running, and its outputs show as it goes. Run it again when it ends.",
                "info",
            );
            attach(record, { startedHere: false });
            return;
        }
        if (startingRef.current === starting) startingRef.current = null;
        if (starting.stopped) {
            unmark();
            void runsApi.cancel(record.id).catch(() => {});
            return;
        }
        attach(record, {
            startedHere: true,
            played: targetNodeId ? { nodeId: targetNodeId, before: shownBefore } : null,
            runKeys,
        });
    };

    /** Stop: the run ends before its next node starts, and the button comes back now. */
    const stopRun = () => {
        if (startingRef.current) {
            startingRef.current.stopped = true;
            setServerRunActive(false);
            return;
        }
        const run = followedRef.current;
        if (!run) return;
        stopFollowing(run, { stopped: true });
        void runsApi.cancel(run.runId).catch(() => { /* it had already ended */ });
    };

    /** Leave the run going and stop following it: another dataflow is opening. */
    const detachRun = () => {
        if (startingRef.current) startingRef.current.stopped = true;
        startingRef.current = null;
        const run = followedRef.current;
        if (run) stopFollowing(run, { stopped: false });
        else setServerRunActive(false);
    };

    /**
     * A canvas just opened *projectId*: follow its last run if it still goes,
     * and offer to finish it if it waits for a tab. What a finished run made
     * came with the load, which shows each node's newest kept result
     * (`GET /api/projects/<id>?results=last`). The run is this account's
     * own: the owner lists her editors' runs too, whose outputs are theirs.
     */
    const attachLatestRun = async (projectId: string) => {
        if (followedRef.current || startingRef.current) return;
        let record: Run;
        try {
            const [latest] = await runsApi.listForProject(projectId, { limit: 1, mine: true });
            if (!latest) return;
            record = await runsApi.get(latest.id);
        } catch {
            return; // nothing to show is the same as no run
        }
        if (followedRef.current || startingRef.current) return;
        if (ACTIVE_RUN_STATUSES.has(record.status)) {
            attach(record, { startedHere: false });
            return;
        }
        if (record.status === "needs_canvas") offerFinish(record.id);
    };

    // Leaving the canvas stops following; the run goes on.
    useEffect(() => () => {
        const run = followedRef.current;
        if (run) { run.done = true; run.controller.abort(); }
    }, []);

    return { serverRunActive, startRun, stopRun, detachRun, attachLatestRun };
}
