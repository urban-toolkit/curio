// Runs on the server. Run All, a node's play button and Ctrl+Enter save the
// dataflow, then start a run of that saved revision, which goes on with the tab
// closed (runs/routes.py). The tab follows the run's stream: each step reaches
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
import { executionResultOutput, recordExecProvenance } from "../../utils/executionResult";
import type { IOutput } from "./flowTypes";
import type { PlayAllState } from "./usePlayAll";
import {
    STOPPED_MESSAGE,
    browserWalk,
    nodeChangeFor,
    replyFromRecord,
    reportsToRun,
    reuseFor,
    settledStatus,
    stepsToRestore,
    type NodeChange,
    type TrackedStep,
} from "./serverRunSteps";

/** How often the tab follows a run again after its stream dropped while it was going. */
const MAX_REFOLLOWS = 5;
/** How often a browser node's report is sent while the server still writes the run's end. */
const MAX_REPORT_ATTEMPTS = 6;

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
    controller: AbortController;
    done: boolean;
    refollows: number;
}

type PlayNodes = (
    nodeIds: string[],
    hooks?: Pick<PlayAllState, "onNodeDone" | "onFinish">,
) => boolean;

export function useServerRun({
    reactFlow, setNodes, showToast, requestProjectSave, applyNewOutput, setOutputs,
    hydrateRestoredOutputs, markNodeErroredRef, playNodes, playAllStateRef,
    emittedForInputRef, outputsRef, workflowNameRef, nodeExecProv, flushInstallSyncRef,
}: {
    reactFlow: ReactFlowInstance;
    setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
    showToast: ReturnType<typeof useToastContext>["showToast"];
    requestProjectSave: () => Promise<any>;
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
    flushInstallSyncRef: React.MutableRefObject<() => void>;
}) {
    // True from the click until the server's part ends. UniversalNode reads
    // isRunActive, not this, so a chart draws as its data arrives.
    const [serverRunActive, setServerRunActive] = useState(false);
    const followedRef = useRef<FollowedRun | null>(null);
    // Between the click and the run's answer: the save, then the start.
    const startingRef = useRef<{ stopped: boolean } | null>(null);
    const outputSeqRef = useRef(0);

    // ── What reaches a node ──────────────────────────────────────────────

    /** Show *output* on the node, through the same setter its own run uses (UniversalNode). */
    const showOnNode = (nodeId: string, output: NodeOutput) => {
        const seq = ++outputSeqRef.current;
        setNodes((nds) => nds.map((node) =>
            node.id === nodeId ? { ...node, data: { ...node.data, serverOutput: { seq, output } } } : node,
        ));
    };

    /**
     * A step's outcome on its node: shown and passed downstream. *live* is a
     * run this tab started: it also records the provenance, with the step's
     * own times, and its outputs pass on as a run's do. Otherwise the output
     * is restored as a load restores one.
     */
    const showResult = (
        nodeId: string,
        change: Extract<NodeChange, { kind: "result" }>,
        { live }: { live: boolean },
    ) => {
        const node = reactFlow.getNode(nodeId);
        if (!node) return;
        const { shown, artifact } = executionResultOutput(change.reply);
        if (live) {
            const at = (seconds?: number) => (seconds != null ? new Date(seconds * 1000) : new Date());
            recordExecProvenance(nodeExecProv, {
                startedAt: at(change.startedAt),
                finishedAt: at(change.finishedAt),
                workflowName: workflowNameRef.current,
                nodeId,
                input: change.reply?.input ?? "",
                reply: change.reply,
                code: node.data?.code ?? "",
            });
        }
        showOnNode(nodeId, shown);
        if (!artifact) {
            // Nothing passes downstream; the nodes below read "upstream errored" (#347).
            markNodeErroredRef.current(nodeId);
            return;
        }
        if (live) {
            applyNewOutput({ nodeId, output: artifact });
            return;
        }
        // As a load restores an output: passed downstream, nothing saved.
        const restored = { nodeId, output: artifact };
        setOutputs((prev) => [...prev.filter((o) => o.nodeId !== nodeId), restored]);
        hydrateRestoredOutputs([restored]);
    };

    /** A node the run did not run because the node feeding it failed, shown as Run All shows it (#603). */
    const showSkipped = (nodeId: string, reason: string) => {
        markNodeErroredRef.current(nodeId);
        setNodes((nds) => nds.map((node) =>
            node.id === nodeId
                ? { ...node, data: { ...node.data, skipExec: (node.data.skipExec ?? 0) + 1, skipReason: reason } }
                : node,
        ));
    };

    const applyChange = (run: FollowedRun, nodeId: string, change: NodeChange | null) => {
        if (!change) return;
        if (change.kind === "running") {
            run.started.add(nodeId);
            if (!run.applied.has(nodeId)) showOnNode(nodeId, { code: "exec", content: "" });
            return;
        }
        if (run.applied.has(nodeId)) return;
        run.applied.add(nodeId);
        if (change.kind === "result") showResult(nodeId, change, { live: run.startedHere });
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
        applyChange(run, event.nodeId, nodeChangeFor(event, step, { started: run.started.has(event.nodeId) }));
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
        { startedHere, played = null }: { startedHere: boolean; played?: FollowedRun["played"] },
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
    ): boolean => {
        const walk = browserWalk(steps, reactFlow.getEdges(), played?.nodeId);
        if (!walk.length) return false;
        return playNodes(walk, {
            onNodeDone: (nodeId, outcome) => {
                // A kind whose play draws nothing of its own (a Data Export)
                // never leaves the running state the click gave it.
                if (played && nodeId === played.nodeId
                    && reactFlow.getNode(nodeId)?.data?.output?.code === "exec") {
                    showOnNode(nodeId, played.before ?? { code: "", content: "" });
                }
                if (!reportsToRun(steps.get(nodeId))) return;
                const shown = reactFlow.getNode(nodeId)?.data?.output?.content;
                report(runId, nodeId, outcome.failed
                    ? { status: "error", message: outcome.skipReason ?? String(shown ?? "") }
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
                            finishInBrowser(runId, steps);
                        }).catch((err) => showToast(err?.message || "The run could not be read.", "error"));
                    },
                },
            },
        );
    };

    const finish = (run: FollowedRun, status: RunStatus) => {
        if (run.done) return;
        run.done = true;
        run.controller.abort();
        followedRef.current = null;
        // In the same tick the flag goes down, so the Run All button never reads
        // "Run all nodes" between the server's part and the browser's.
        const browserPart = run.startedHere && finishInBrowser(run.runId, run.steps, run.played);
        if (!run.startedHere && status === "needs_canvas") offerFinish(run.runId);
        setServerRunActive(false);
        if (!browserPart) flushInstallSyncRef.current();
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

    /** Save, then run the whole dataflow or *targetNodeId* and the ancestors it needs. */
    const startRun = async (targetNodeId?: string) => {
        if (followedRef.current || startingRef.current || playAllStateRef.current != null) {
            showToast(
                "A run is already in progress. Wait for it to finish, or cancel it from the Run All button.",
                "info",
            );
            return;
        }
        const starting = { stopped: false };
        startingRef.current = starting;
        setServerRunActive(true);
        // Read before the save: what the canvas holds now is what it would reuse.
        const reuse = targetNodeId
            ? reuseFor(targetNodeId, reactFlow.getNodes(), reactFlow.getEdges(), emittedForInputRef.current, outputsRef.current)
            : undefined;
        // The played node says it runs from the click, as its own play makes it
        // say at once, rather than showing its last outcome through the save.
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
        let saved: any;
        try {
            saved = await requestProjectSave();
        } catch (err: any) {
            giveUp(`The dataflow was not run, because it could not be saved: ${err?.message || err}`);
            return;
        }
        if (starting.stopped) { giveUp(); return; }
        const projectId: string | undefined = saved?.id;
        if (!projectId) { giveUp("The dataflow was not run, because it could not be saved."); return; }
        let record: Run;
        try {
            record = await runsApi.start(projectId, {
                ...(targetNodeId ? { target: targetNodeId, reuse } : {}),
                specRevision: saved?.spec_revision ?? null,
            });
        } catch (err: any) {
            const runningId = err?.status === 409 ? err?.body?.runId : null;
            if (!runningId || starting.stopped) {
                giveUp(starting.stopped ? undefined : (err?.message || "The run could not start."));
                return;
            }
            // The dataflow already runs: follow that run. Only one of the
            // revision just saved is this click's run; one of an earlier
            // version is shown as a run opened later is, and says so.
            try {
                record = await runsApi.get(runningId);
            } catch (readErr: any) {
                giveUp(readErr?.message || "The run could not start.");
                return;
            }
            if (startingRef.current === starting) startingRef.current = null;
            unmark();
            const current = record.specRevision === (saved?.spec_revision ?? null);
            if (!current) {
                showToast(
                    "An earlier version of this dataflow is still running, and its outputs show as it goes. Run it again when it ends.",
                    "info",
                );
            }
            attach(record, { startedHere: current });
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
     * A canvas just opened *projectId*: show the outputs of its last run that
     * the saved ones did not restore, follow it if it still goes, and offer to
     * finish it if it waits for a tab.
     */
    const attachLatestRun = async (projectId: string, restored: ReadonlySet<string>) => {
        if (followedRef.current || startingRef.current) return;
        let record: Run;
        try {
            const [latest] = await runsApi.listForProject(projectId, { limit: 1 });
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
        const run: FollowedRun = {
            runId: record.id, steps: new Map(), applied: new Set(), started: new Set(), settled: new Set(),
            startedHere: false, played: null, controller: new AbortController(), done: true, refollows: 0,
        };
        for (const step of stepsToRestore(record.steps ?? [], restored)) {
            applyChange(run, step.nodeId, {
                kind: "result",
                reply: replyFromRecord(step),
                startedAt: step.startedAt ? Date.parse(step.startedAt) / 1000 : undefined,
                finishedAt: step.finishedAt ? Date.parse(step.finishedAt) / 1000 : undefined,
            });
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
