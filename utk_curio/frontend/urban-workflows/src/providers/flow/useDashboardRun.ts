// A dashboard viewer's runs (#1117). A change to a control a pinned tile shows
// reruns the dataflow on the server once the changes settle (useAutoRun, with
// FlowProvider's start), which never changes the dataflow; on open, a tile with no saved
// output runs the nodes before it with the saved values. There is no Run,
// Reset or auto-run button.
//
// The server plans the run (runs/viewer.py) and keeps each step's output for
// the next viewer who picks the same values. Each step reaches its node as a
// canvas run's does (useStepOutcomes), restored as a load restores an output,
// and its artifacts are read through the dashboard's own routes
// (dashboardRunFiles). A node a later change no longer reaches gets its saved
// output back, and so does every node when the values are the saved ones.
//
// A step only a browser runs (an Autark compute node, a Spatial Join) is the
// page's. The run ends asking for it (`needs_canvas`); the page runs the node
// as a canvas's run on the server walks its browser part
// (usePlayAll.playNodes), sends what it made to the run (dashboardRunSteps),
// and starts the run again with the same values and token, which runs the
// steps below on that. A node that cannot run here, as without WebGPU, shows
// why, and the nodes and tiles below say which step could not run (`stopped`).
import React, { useEffect, useRef, useState } from "react";
import type { ReactFlowInstance } from "reactflow";
import type { useToastContext } from "../ToastProvider";
import { dashboardRunsApi, type DashboardRunEvent } from "../../services/runs/dashboardRunsApi";
import { forgetDashboardRunFiles, rememberDashboardRunFiles } from "../../services/runs/dashboardRunFiles";
import { askPage, forgetPageSteps, keepPageResult } from "../../services/runs/dashboardRunSteps";
import { dashboardSourceNodeIds } from "../../utils/dashboardLayout";
import { resolveNodeDisplayLabel } from "../../utils/palettePackageFactoryDraft";
import { dashboardValues, type DashboardValues } from "../../utils/widgets/dashboardControls";
import type { WidgetDef } from "../../utils/widgets/widgetModel";
import type { IOutput } from "./flowTypes";
import { STOPPED_MESSAGE, nodeChangeFor, type NodeChange } from "./serverRunSteps";
import type { StepOutcomes } from "./useStepOutcomes";

interface FollowedDashboardRun {
    runId: string;
    token: string;
    controller: AbortController;
    /** Nodes whose finished step reached them, so a replayed event is not applied twice. */
    applied: Set<string>;
    /** Nodes this run showed as running. */
    started: Set<string>;
    /** The values the run was started with: the page's part runs on them too. */
    values: DashboardValues;
    /** What the page made of the steps earlier runs of these values left to it. */
    pageOutputs: Record<string, string>;
    /** The steps only a browser runs, which this run left to the page. */
    browserSteps: string[];
    /** The steps below them, which wait for what the page makes. */
    waiting: string[];
    /** The run ended asking for the page's part, which carries it on. */
    handedToPage: boolean;
    done: boolean;
}

interface Saved {
    /** The outputs the page opened with, by node. */
    outputs: Map<string, IOutput>;
    /** The widgets each pinned node is saved with. */
    widgets: Map<string, WidgetDef[]>;
}

/** usePlayAll's playNodes: run nodes as Run All would, each reported when done. */
type PlayNodes = (
    nodeIds: string[],
    hooks?: {
        onNodeDone?: (nodeId: string, outcome: { failed: boolean; skipReason?: string; message?: string }) => void;
        onFinish?: () => void;
    },
) => boolean;

export function useDashboardRun({ enabled, reactFlow, outcomes, outputsRef, showToast, playNodes }: {
    enabled: boolean;
    reactFlow: ReactFlowInstance;
    outcomes: StepOutcomes;
    outputsRef: React.MutableRefObject<IOutput[]>;
    showToast: ReturnType<typeof useToastContext>["showToast"];
    playNodes: PlayNodes;
}) {
    // From the change's start until the run's end: the tiles below wait to
    // draw (UniversalNode reads it as serverRunActive) and say they are
    // computing (useGrammarInputState), and a change made meanwhile runs once
    // it ends (useAutoRun).
    const [active, setActive] = useState(false);
    // Why the last run stopped before the tiles: at a step this browser could
    // not run, or a run refused, lost or left unfinished. It is what a tile
    // left with nothing says (useGrammarInputState), where "Computing..."
    // would wait for nothing. The next start clears it.
    const [stopped, setStopped] = useState<string | null>(null);
    const projectIdRef = useRef<string | null>(null);
    // Between a start and its answer.
    const startingRef = useRef(false);
    const followedRef = useRef<FollowedDashboardRun | null>(null);
    const savedRef = useRef<Saved | null>(null);
    // The nodes showing an output a viewer's run made.
    const changedRef = useRef(new Set<string>());

    /** Put each node's saved output back, as the page opened with it. */
    const restoreSaved = (nodeIds: Iterable<string>) => {
        for (const nodeId of nodeIds) {
            const saved = savedRef.current?.outputs.get(nodeId);
            changedRef.current.delete(nodeId);
            if (!saved) continue;
            outcomes.showResult(nodeId, {
                kind: "result",
                reply: { stdout: [], stderr: "", output: saved.output },
            }, { live: false });
        }
    };

    const apply = (run: FollowedDashboardRun, nodeId: string, change: NodeChange | null) => {
        if (!change) return;
        if (change.kind === "running") {
            run.started.add(nodeId);
            if (!run.applied.has(nodeId)) outcomes.showOnNode(nodeId, { code: "exec", content: "" });
            return;
        }
        if (run.applied.has(nodeId)) return;
        run.applied.add(nodeId);
        if (change.kind === "result") {
            // As a load restores an output: passed downstream, the dataflow unchanged.
            outcomes.showResult(nodeId, change, { live: false });
            changedRef.current.add(nodeId);
        } else if (change.kind === "skipped") {
            outcomes.showSkipped(nodeId, change.reason);
        } else {
            outcomes.showOnNode(nodeId, { code: "error", content: STOPPED_MESSAGE });
        }
    };

    const end = (run: FollowedDashboardRun) => {
        if (run.done) return;
        run.done = true;
        run.controller.abort();
        if (followedRef.current === run) followedRef.current = null;
        setActive(false);
    };

    /**
     * What the page made of *nodeId*, which it just ran for a run: the output
     * the node sent the run itself (an Autark node does), or its output held
     * on the page, sent to the run now (a Spatial Join's rows).
     */
    const pageResultOf = async (nodeId: string): Promise<string | null> => {
        const output: any = outputsRef.current.find((o) => o.nodeId === nodeId)?.output;
        if (!output || typeof output !== "object") return null;
        if (typeof output.path === "string" && output.path) return output.path;
        if (output.data == null) return null;
        return (await keepPageResult(nodeId, output)).path;
    };

    /** The nodes below a step the page could not run say so, as a run says it of a failed node. */
    const showWaitingSkipped = (run: FollowedDashboardRun, failed: string[]) => {
        // As its header names it, and as Run All names a failed node (usePlayAll).
        const name = (nodeId: string) => {
            const data = reactFlow.getNode(nodeId)?.data;
            return (data && resolveNodeDisplayLabel(data)) || nodeId;
        };
        const why = `"${name(failed[0])}" could not run in this browser.`;
        for (const nodeId of run.waiting) outcomes.showSkipped(nodeId, `No data yet: ${why}`);
        setStopped(why);
    };

    /**
     * Run the steps *run* left to the page, send what they made, and start
     * the run again on that, with the same values and token.
     */
    const finishInPage = async (run: FollowedDashboardRun) => {
        const projectId = projectIdRef.current;
        if (!projectId) {
            end(run);
            return;
        }
        askPage(projectId, run.runId, run.token, run.browserSteps);
        try {
            // The results before these steps reach them a tick after they land,
            // as a load's do (useApplyOutput's hydrateRestoredOutputs), and a
            // run's whole stream can land at once: the steps run once their
            // inputs are in, not on the inputs they held before.
            await new Promise<void>((resolve) => setTimeout(resolve, 0));
            if (followedRef.current !== run) return;
            const made = new Map<string, Promise<string | null>>();
            const failed: string[] = [];
            await new Promise<void>((resolve) => {
                const playing = playNodes([...run.browserSteps], {
                    onNodeDone: (nodeId, outcome) => {
                        if (outcome.failed) failed.push(nodeId);
                        else made.set(nodeId, pageResultOf(nodeId));
                    },
                    onFinish: () => resolve(),
                });
                if (!playing) resolve();
            });
            const pageOutputs = { ...run.pageOutputs };
            for (const [nodeId, result] of made) {
                const path = await result.catch(() => null);
                if (path) pageOutputs[nodeId] = path;
                else failed.push(nodeId);
            }
            if (followedRef.current !== run) return;
            if (failed.length > 0 || run.browserSteps.some((nodeId) => !pageOutputs[nodeId])) {
                showWaitingSkipped(run, failed.length > 0 ? failed : run.browserSteps);
                end(run);
                return;
            }
            const next = await dashboardRunsApi.start(projectId, run.values, {
                token: run.token, browserOutputs: pageOutputs,
            });
            if (followedRef.current !== run) return;
            if (!next.runId || !next.token) {
                end(run);
                return;
            }
            // The run carries on as the next one: the tiles keep waiting.
            run.done = true;
            run.controller.abort();
            follow(projectId, next.runId, next.token, run.values, pageOutputs);
        } catch (err: any) {
            const unfinished = err?.message || "This dashboard could not finish its run.";
            showToast(unfinished, "error");
            setStopped(unfinished);
            end(run);
        } finally {
            forgetPageSteps();
        }
    };

    const onEvent = (run: FollowedDashboardRun, event: DashboardRunEvent) => {
        if (followedRef.current !== run) return;
        if (event.kind === "run_finished") {
            if (event.status === "needs_canvas" && run.browserSteps.length > 0) {
                run.handedToPage = true;
                void finishInPage(run);
            } else {
                end(run);
            }
            return;
        }
        if (event.kind !== "step_started" && event.kind !== "step_finished") return;
        if (event.kind === "step_finished" && event.status === "browser") {
            run.browserSteps.push(event.nodeId);
            return;
        }
        if (event.kind === "step_finished" && event.status === "waiting") {
            run.waiting.push(event.nodeId);
            return;
        }
        const projectId = projectIdRef.current;
        if (event.kind === "step_finished" && projectId) {
            // Read on the dashboard's own routes, before the node asks for them.
            rememberDashboardRunFiles(projectId, run.token, [event.output?.path, ...(event.artifactIds ?? [])]);
        }
        apply(run, event.nodeId, nodeChangeFor(event, undefined, { started: run.started.has(event.nodeId) }));
    };

    const follow = (
        projectId: string, runId: string, token: string,
        values: DashboardValues, pageOutputs: Record<string, string> = {},
    ) => {
        const run: FollowedDashboardRun = {
            runId, token, controller: new AbortController(), applied: new Set(), started: new Set(),
            values, pageOutputs, browserSteps: [], waiting: [], handedToPage: false, done: false,
        };
        followedRef.current = run;
        dashboardRunsApi
            .follow(projectId, runId, token, (event) => onEvent(run, event), run.controller.signal)
            .then(() => { if (!run.handedToPage) end(run); }, () => {
                if (run.handedToPage) return;
                if (!run.done) {
                    const lost = "Lost track of this dashboard's run. Change a control to run it again.";
                    showToast(lost, "warning");
                    setStopped(lost);
                }
                end(run);
            });
    };

    /**
     * Run the dashboard with its controls' values as they stand, or join the
     * run of those values already going. Nothing to run (the values are the
     * saved ones): every node shows its saved output again.
     */
    const start = async () => {
        const projectId = projectIdRef.current;
        if (!enabled || !projectId || followedRef.current || startingRef.current) return;
        startingRef.current = true;
        setActive(true);
        setStopped(null);
        const values = dashboardValues(reactFlow.getNodes());
        let started;
        try {
            started = await dashboardRunsApi.start(projectId, values);
        } catch (err: any) {
            const refused = err?.message || "This dashboard could not run.";
            setActive(false);
            setStopped(refused);
            showToast(refused, err?.status === 429 ? "warning" : "error");
            return;
        } finally {
            startingRef.current = false;
        }
        // A node this change does not reach shows its saved output again.
        const planned = new Set(started.nodeIds ?? []);
        restoreSaved([...changedRef.current].filter((nodeId) => !planned.has(nodeId)));
        if (!started.runId || !started.token) {
            setActive(false);
            return;
        }
        follow(projectId, started.runId, started.token, values);
    };

    /**
     * The dashboard of *projectId* opened: what its nodes are saved with is
     * kept, and a tile with no saved output runs the nodes before it.
     */
    const opened = (projectId: string) => {
        if (!enabled) return;
        projectIdRef.current = projectId;
        const nodes = reactFlow.getNodes();
        savedRef.current = {
            outputs: new Map(outputsRef.current.map((output) => [output.nodeId, output])),
            widgets: new Map(
                nodes
                    .filter((node) => node.data?.dashboardPinned && Array.isArray(node.data.widgets))
                    .map((node) => [node.id, JSON.parse(JSON.stringify(node.data.widgets)) as WidgetDef[]]),
            ),
        };
        const sources = dashboardSourceNodeIds(nodes, reactFlow.getEdges());
        if ([...sources].some((nodeId) => !savedRef.current?.outputs.has(nodeId))) void start();
    };

    /** The widgets each pinned node is saved with: Save layout writes these, never a tried value. */
    const savedWidgets = () => savedRef.current?.widgets;

    // Leaving the page stops following; what the runs made is not read again.
    useEffect(() => () => {
        const run = followedRef.current;
        if (run) { run.done = true; run.controller.abort(); }
        forgetDashboardRunFiles();
        forgetPageSteps();
    }, []);

    return { active, stopped, start, opened, savedWidgets };
}
