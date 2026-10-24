// A dashboard viewer's runs (#1117). A change to a control a pinned tile shows
// reruns the dataflow on the server once the changes settle (useAutoRun, with
// FlowProvider's start), with nothing saved; on open, a tile with no saved
// output runs the nodes before it with the saved values. There is no Run,
// Reset or auto-run button.
//
// The server plans the run (runs/viewer.py) and keeps each step's output for
// the next viewer who picks the same values. Each step reaches its node as a
// canvas run's does (useStepOutcomes), restored as a load restores an output,
// and its artifacts are read through the dashboard's own routes
// (dashboardRunFiles). A node a later change no longer reaches gets its saved
// output back, and so does every node when the values are the saved ones.
import React, { useEffect, useRef, useState } from "react";
import type { ReactFlowInstance } from "reactflow";
import type { useToastContext } from "../ToastProvider";
import { dashboardRunsApi, type DashboardRunEvent } from "../../services/runs/dashboardRunsApi";
import { forgetDashboardRunFiles, rememberDashboardRunFiles } from "../../services/runs/dashboardRunFiles";
import { dashboardSourceNodeIds } from "../../utils/dashboardLayout";
import { dashboardValues } from "../../utils/widgets/dashboardControls";
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
    done: boolean;
}

interface Saved {
    /** The outputs the page opened with, by node. */
    outputs: Map<string, IOutput>;
    /** The widgets each pinned node is saved with. */
    widgets: Map<string, WidgetDef[]>;
}

export function useDashboardRun({ enabled, reactFlow, outcomes, outputsRef, showToast }: {
    enabled: boolean;
    reactFlow: ReactFlowInstance;
    outcomes: StepOutcomes;
    outputsRef: React.MutableRefObject<IOutput[]>;
    showToast: ReturnType<typeof useToastContext>["showToast"];
}) {
    // From the change's start until the run's end: the tiles below wait to
    // draw (UniversalNode reads it as serverRunActive), and a change made
    // meanwhile runs once it ends (useAutoRun).
    const [active, setActive] = useState(false);
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
            // As a load restores an output: passed downstream, nothing saved.
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

    const onEvent = (run: FollowedDashboardRun, event: DashboardRunEvent) => {
        if (followedRef.current !== run) return;
        if (event.kind === "run_finished") {
            end(run);
            return;
        }
        if (event.kind !== "step_started" && event.kind !== "step_finished") return;
        const projectId = projectIdRef.current;
        if (event.kind === "step_finished" && projectId) {
            // Read on the dashboard's own routes, before the node asks for them.
            rememberDashboardRunFiles(projectId, run.token, [event.output?.path, ...(event.artifactIds ?? [])]);
        }
        apply(run, event.nodeId, nodeChangeFor(event, undefined, { started: run.started.has(event.nodeId) }));
    };

    const follow = (projectId: string, runId: string, token: string) => {
        const run: FollowedDashboardRun = {
            runId, token, controller: new AbortController(), applied: new Set(), started: new Set(), done: false,
        };
        followedRef.current = run;
        dashboardRunsApi
            .follow(projectId, runId, token, (event) => onEvent(run, event), run.controller.signal)
            .then(() => end(run), () => {
                if (!run.done) showToast("Lost track of this dashboard's run. Change a control to run it again.", "warning");
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
        let started;
        try {
            started = await dashboardRunsApi.start(projectId, dashboardValues(reactFlow.getNodes()));
        } catch (err: any) {
            setActive(false);
            showToast(err?.message || "This dashboard could not run.", err?.status === 429 ? "warning" : "error");
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
        follow(projectId, started.runId, started.token);
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
    }, []);

    return { active, start, opened, savedWidgets };
}
