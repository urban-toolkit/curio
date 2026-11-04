// Auto-install: after a node's run, the debounced record of the outputs that
// installs the datasets the run produced and lists them in the open palette
// and drawers. No tab saves the dataflow: its doc keeps it.
import React, { useEffect, useRef } from "react";
import type { ReactFlowInstance } from "reactflow";
import { NodeType } from "../../constants";
import { declaresBehavior } from "../../registry/declaredNodes";
import { getUnversionedFlowNodeType } from "../../utils/flowNodeCanonicalType";
import type { useWorkflowOperations } from "../../hook/useWorkflowOperations";
import { isNonProducingNodeType, shouldSaveOutputOnRun } from "../../utils/saveOutputDataset";
import { resolveNodeDisplayLabel } from "../../utils/palettePackageFactoryDraft";
import { isDatasetPaletteNode } from "../../services/datasetCatalog/datasetApplication";

/** The Data Pool's behavior, and the built-in Data Pool for a type whose template declares none. */
const DATA_POOL_BEHAVIORS: ReadonlySet<string> = new Set(["data-pool"]);
const DATA_POOL_NODE_TYPES: ReadonlySet<string> = new Set([NodeType.DATA_POOL]);

export function useInstallSave({
    scheduleInstallSyncRef, dashboardOn, reactFlow, defaultSaveOutputDataset,
    isDashboardSource, workflowOps, flushInstallSyncRef, hostedGuest = false,
}: {
    scheduleInstallSyncRef: React.MutableRefObject<(nodeId: string) => void>;
    dashboardOn: boolean;
    reactFlow: ReactFlowInstance;
    defaultSaveOutputDataset: boolean;
    isDashboardSource: (nodeId: string) => boolean;
    workflowOps: ReturnType<typeof useWorkflowOperations>;
    flushInstallSyncRef: React.MutableRefObject<() => Promise<void> | void>;
    /** A hosted guest (`isHostedGuest`), who cannot save the dataflow. */
    hostedGuest?: boolean;
}) {
    // ── Auto-surface produced datasets without a manual disk-icon save ─────────
    // A dataset is installed when its producing node's output is recorded: for
    // tabular outputs the backend installs during execution, but for many node
    // types (raster, spatial-join, etc.) the install happens only when the
    // canvas records the output (record_node_outputs over the output refs).
    // Centralize here: applyNewOutput (reached by EVERY producing node, and only
    // on a genuine runtime output — not project load) calls scheduleInstallSyncRef
    // → this records the outputs (install + catalog refresh) so the open palette /
    // drawer refresh live. Debounced so a "play all" burst collapses into one record.
    const installSyncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const installSyncPendingIdsRef = useRef<Set<string>>(new Set());
    // The record out now, which a flush waits for too.
    const recordingRef = useRef<Promise<void> | null>(null);
    scheduleInstallSyncRef.current = (nodeId: string) => {
        // Never from a dashboard. A tile drawing itself emits an output like any
        // run: from the dashboard a record would change the owner's saved
        // outputs behind their back, and for a visitor holding a link it would
        // throw and surface as an error toast on a page they only opened to
        // look at.
        if (dashboardOn) return;
        // Nor for a hosted guest, whose saves are refused: this record is
        // Curio's own, and trying it showed "Guest users cannot save projects"
        // after a play or Run All. Before the placeholder, too, since the
        // dataset would never be added.
        if (hostedGuest) return;
        // Nor in a shared view, an invited editor's or a watcher's: the
        // dataflow's saved outputs come from its owner's runs.
        if (workflowOps.viewerMode === "shared") return;
        const node = reactFlow.getNode(nodeId);
        if (!node) return;
        const canonical = getUnversionedFlowNodeType(node);
        // Sinks / interaction surfaces pass their input through — never a NEW
        // dataset — so excluding them keeps e.g. a Data Pool's per-brush re-emit
        // from triggering saves. A Data Pool, by the behavior its template
        // declares, is a save-trigger-only extra on top of the shared sink set:
        // the backend must NOT prune data-pool refs.
        if (
            isNonProducingNodeType(canonical)
            || declaresBehavior(canonical, DATA_POOL_BEHAVIORS, DATA_POOL_NODE_TYPES)
        ) {
            return;
        }
        if (isDatasetPaletteNode(node.data)) return;
        if (!shouldSaveOutputOnRun(
            node.data, defaultSaveOutputDataset, isDashboardSource(nodeId),
        )) return;

        installSyncPendingIdsRef.current.add(nodeId);
        workflowOps.beginPendingInstall({
            key: nodeId,
            producerNodeId: nodeId,
            label: resolveNodeDisplayLabel(node.data),
        });

        // Debounce: one record covers every producer that landed in this window.
        // buildOutputRefs reads outputsRef, which setOutputs writes at once, so
        // a flush in the tick the output lands sends it too.
        if (installSyncTimerRef.current) clearTimeout(installSyncTimerRef.current);
        installSyncTimerRef.current = setTimeout(() => { void runInstallSyncNow(); }, 500);
    };

    // Run the pending record immediately. Shared by the debounce timer and by
    // flushInstallSyncRef so a forced flush takes the exact same path.
    const runInstallSyncNow = (): Promise<void> => {
        if (installSyncTimerRef.current) {
            clearTimeout(installSyncTimerRef.current);
            installSyncTimerRef.current = null;
        }
        const ids = Array.from(installSyncPendingIdsRef.current);
        if (ids.length === 0) return recordingRef.current ?? Promise.resolve();
        installSyncPendingIdsRef.current = new Set();
        // Sent in this tick. Scope the warning toast to the producers this sync
        // covers: a record re-sends refs for every toggle-enabled node, so an
        // unscoped toast names nodes the user never ran (#180).
        let sent: Promise<{ failedNodeIds?: string[] } | undefined>;
        try {
            sent = Promise.resolve(workflowOps.recordOutputs(ids));
        } catch (err) {
            sent = Promise.reject(err);
        }
        const recording = sent
            .then((outcome) => {
                // Per producer, on the record's actual result (#352). This used
                // to be a `.finally` that cleared every placeholder however it
                // went: a dataset that did not install had its "Adding…" entry
                // flash and disappear, which is #217's symptom, and nothing tied
                // the two together so no test could catch it coming back.
                // Tolerant of a resolve with no outcome: a record that reports
                // nothing is treated as "nothing failed". A crash here would
                // strand the whole canvas.
                const failed = new Set(outcome?.failedNodeIds ?? []);
                ids.forEach((id) =>
                    failed.has(id)
                        ? workflowOps.failPendingInstall(id)
                        : workflowOps.endPendingInstall(id),
                );
            })
            .catch(() => {
                // recordOutputs handles its own errors and resolves; this is
                // only here so an unexpected throw cannot strand every
                // placeholder in "Adding…" for the full 10-minute safety timeout.
                ids.forEach((id) => workflowOps.failPendingInstall(id));
            })
            .finally(() => {
                if (recordingRef.current === recording) recordingRef.current = null;
            });
        recordingRef.current = recording;
        return recording;
    };

    // Force any pending record to run now, resolving once it is done. Called
    // when Play All completes (finishPlayAll), by File > Save before its
    // version, and on unmount so the last burst's datasets are never lost to
    // the 500ms debounce window (Vector 2 in the flakiness investigation).
    flushInstallSyncRef.current = () => {
        if (installSyncTimerRef.current) return runInstallSyncNow();
        return recordingRef.current ?? undefined;
    };

    useEffect(
        () => () => {
            // Flush (not just clear) on unmount: a dataflow switch / navigation
            // inside the debounce window would otherwise drop the pending record.
            void flushInstallSyncRef.current();
        },
        [],
    );
}
