// Dashboard pins: pinning a node, which nodes a pinned tile depends on, and
// the save that follows a pin change.
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
}: {
    reactFlow: ReactFlowInstance;
    setDashboardPins: React.Dispatch<React.SetStateAction<any>>;
    setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
    markDirtyRef: React.MutableRefObject<() => void>;
    savePinChangeRef: React.MutableRefObject<() => void>;
    showToast: ReturnType<typeof useToastContext>["showToast"];
    /** The dataflow's scenarios as they are now, whose context and outcomes save too (#662). */
    scenariosNowRef?: React.MutableRefObject<() => readonly Scenario[]>;
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
        // A pin is part of the saved spec, so it is an edit. Nothing said so
        // before, which was harmless while the dashboard was a canvas mode and
        // is not now: the page renders what is on disk, so an unsaved pin would
        // be a tile the dashboard never shows.
        markDirtyRef.current();
        // Both directions: unpinning has to reach the dashboard just as promptly
        // as pinning, or the tile stays on a page the user has already removed
        // it from.
        savePinChangeRef.current();
        if (!value) return;
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
    }, [setDashboardPins, setNodes, reactFlow, showToast]);

    return { isDashboardSource, setPinForDashboard };
}

export function useDashboardPinSave({
    savePinChangeRef, dashboardOn, workflowOps, showToast,
}: {
    savePinChangeRef: React.MutableRefObject<() => void>;
    dashboardOn: boolean;
    workflowOps: ReturnType<typeof useWorkflowOperations>;
    showToast: ReturnType<typeof useToastContext>["showToast"];
}) {
    // Debounced so toggling several pins in a row is one save, and so the save
    // reads the React Flow store after the pin has landed in it rather than the
    // snapshot from the click.
    const pinSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    savePinChangeRef.current = () => {
        // The dashboard writes on its own terms (Save layout), and a visitor
        // holding a link has nothing to write to.
        if (dashboardOn) return;
        if (!workflowOps.projectId) return;
        if (workflowOps.viewerMode === "shared") return;
        if (pinSaveTimerRef.current) clearTimeout(pinSaveTimerRef.current);
        pinSaveTimerRef.current = setTimeout(() => {
            workflowOps.saveCurrentProject().catch((err: unknown) => {
                // Loud, unlike the 30 second auto-save: the user just asked for
                // something whose only visible effect is on another page, so a
                // silent failure would look like the dashboard ignoring them.
                console.error("Saving the pin failed:", err);
                showToast(
                    "Could not save the pin. The dashboard will not show this tile until the dataflow is saved.",
                    "error",
                );
            });
        }, 400);
    };
}
