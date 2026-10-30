// Dashboard pins: pinning a node, which nodes a pinned tile depends on, and
// the record of the outputs a pinned tile or a scenario reads, which follows
// a pin or scenario change.
import React, { useCallback, useRef } from "react";
import type { Node, ReactFlowInstance } from "reactflow";
import { dashboardSourceNodeIds } from "../../utils/dashboardLayout";
import { savedSourceNodeIds } from "../../utils/scenarios/scenarioParts";
import type { Scenario } from "../../utils/scenarios/scenarioModel";
import type { useWorkflowOperations } from "../../hook/useWorkflowOperations";
import type { useToastContext } from "../ToastProvider";
import { resolveNodeDisplayLabel } from "../../utils/palettePackageFactoryDraft";

export function useDashboardPins({
    reactFlow, setDashboardPins, setNodes, markDirtyRef, savePinChangeRef, showToast, scenariosNowRef,
    hostedGuest = false,
}: {
    reactFlow: ReactFlowInstance;
    setDashboardPins: React.Dispatch<React.SetStateAction<any>>;
    setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
    markDirtyRef: React.MutableRefObject<() => void>;
    savePinChangeRef: React.MutableRefObject<() => void>;
    showToast: ReturnType<typeof useToastContext>["showToast"];
    /** The dataflow's scenarios as they are now, whose context and outcomes save too (#662). */
    scenariosNowRef?: React.MutableRefObject<() => readonly Scenario[]>;
    /** A hosted guest (`isHostedGuest`), who cannot save the dataflow. */
    hostedGuest?: boolean;
}) {
    // Which nodes a pinned tile or a scenario (#662) depends on. Derived from
    // the live graph rather than stored: pins and wiring both change, and a
    // stale set would either save the wrong node's output or none at all.
    const isDashboardSource = useCallback((nodeId: string) => {
        try {
            return savedSourceNodeIds(
                reactFlow.getNodes() as any, reactFlow.getEdges() as any,
                scenariosNowRef?.current() ?? [],
            ).has(nodeId);
        } catch {
            // The graph is the source of truth, not a requirement. If it cannot
            // be read, fall back to the explicit toggle alone.
            return false;
        }
    }, [reactFlow, scenariosNowRef]);

    const setPinForDashboard = useCallback((nodeId: string, value: boolean) => {
        setDashboardPins((prev: any) => ({ ...prev, [nodeId]: value }));
        setNodes((nds: Node[]) =>
            nds.map(n => n.id === nodeId ? { ...n, data: { ...n.data, dashboardPinned: value } } : n)
        );
        // A pin is part of the dataflow, so it is an edit: the doc keeps it on
        // a saved dataflow, and a dataflow not saved yet is Unsaved.
        markDirtyRef.current();
        // Both directions: the outputs a newly pinned tile reads are recorded
        // for the dashboard to draw, and an unpinned tile's sources are no
        // longer kept on its account.
        savePinChangeRef.current();
        // A hosted guest's pin is not saved, nor the outputs behind it, so
        // there is nothing to announce.
        if (!value || hostedGuest) return;
        // Say what pinning does beyond hiding the other nodes: the tile has to
        // be able to draw without a run, which means the outputs behind it get
        // saved to the Data Catalog.
        const sources = dashboardSourceNodeIds(
            reactFlow.getNodes().map((n) =>
                n.id === nodeId
                    ? { ...n, data: { ...n.data, dashboardPinned: true } }
                    : n,
            ) as any,
            reactFlow.getEdges() as any,
        );
        if (sources.size === 0) return;
        const labels = reactFlow.getNodes()
            .filter((n) => sources.has(n.id))
            .map((n) => resolveNodeDisplayLabel(n.data))
            .filter(Boolean);
        if (labels.length === 0) return;
        showToast(
            `Pinned. The output of ${labels.join(", ")} will be saved to the `
            + `Data Catalog so this tile can render without running the dataflow.`,
            "info",
        );
    }, [setDashboardPins, setNodes, reactFlow, showToast, hostedGuest]);

    return { isDashboardSource, setPinForDashboard };
}

export function useDashboardPinSave({
    savePinChangeRef, dashboardOn, workflowOps, showToast, hostedGuest = false,
}: {
    savePinChangeRef: React.MutableRefObject<() => void>;
    dashboardOn: boolean;
    workflowOps: ReturnType<typeof useWorkflowOperations>;
    showToast: ReturnType<typeof useToastContext>["showToast"];
    /** A hosted guest (`isHostedGuest`), who cannot save the dataflow. */
    hostedGuest?: boolean;
}) {
    // Debounced so toggling several pins in a row is one record, and so the
    // record reads the React Flow store after the pin has landed in it rather
    // than the snapshot from the click.
    const pinSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    savePinChangeRef.current = () => {
        // The dashboard writes on its own terms (Save layout), and a visitor
        // holding a link has nothing to write to.
        if (dashboardOn) return;
        if (!workflowOps.projectId) return;
        if (workflowOps.viewerMode === "shared") return;
        // A hosted guest's saves are refused. This record is Curio's own, so
        // it is skipped rather than tried and reported.
        if (hostedGuest) return;
        if (pinSaveTimerRef.current) clearTimeout(pinSaveTimerRef.current);
        pinSaveTimerRef.current = setTimeout(() => {
            // recordOutputs says itself when the record fails.
            void workflowOps.recordOutputs().catch((err: unknown) => {
                console.error("Recording the outputs a tile or a scenario reads failed:", err);
                showToast("Could not save the outputs this dataflow's tiles and scenarios read.", "error");
            });
        }, 400);
    };
}
