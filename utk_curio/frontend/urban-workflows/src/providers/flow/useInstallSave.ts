// Auto-install: after a node's run, the debounced save that installs the
// datasets the run produced and lists them in the open palette and drawers.
import React, { useEffect, useRef } from "react";
import type { ReactFlowInstance } from "reactflow";
import { NodeType } from "../../constants";
import { getUnversionedFlowNodeType } from "../../utils/flowNodeCanonicalType";
import type { useWorkflowOperations } from "../../hook/useWorkflowOperations";
import { isNonProducingNodeType, shouldSaveOutputOnRun } from "../../utils/saveOutputDataset";
import { resolveNodeDisplayLabel } from "../../utils/palettePackageFactoryDraft";
import { isDatasetPaletteNode } from "../../services/datasetCatalog/datasetApplication";

export function useInstallSave({
    scheduleInstallSyncRef, dashboardOn, reactFlow, defaultSaveOutputDataset,
    isDashboardSource, workflowOps, flushInstallSyncRef,
}: {
    scheduleInstallSyncRef: React.MutableRefObject<(nodeId: string) => void>;
    dashboardOn: boolean;
    reactFlow: ReactFlowInstance;
    defaultSaveOutputDataset: boolean;
    isDashboardSource: (nodeId: string) => boolean;
    workflowOps: ReturnType<typeof useWorkflowOperations>;
    flushInstallSyncRef: React.MutableRefObject<() => void>;
}) {
    // ── Auto-surface produced datasets without a manual disk-icon save ─────────
    // A dataset is installed when its producing node's output is persisted: for
    // tabular outputs the backend installs during execution, but for many node
    // types (raster, merge, spatial-join, etc.) the install happens only at SAVE
    // time via _auto_install_computed_outputs over the saved output refs. Only
    // CodeEditor previously triggered that, so datasets from other node types
    // stayed invisible until the user clicked Save. Centralize here: applyNewOutput
    // (reached by EVERY producing node, and only on a genuine runtime output — not
    // project load) calls scheduleInstallSyncRef → this runs the same save the disk
    // icon does (install + syncDatasetsFromSavedSpec resync) so the open palette /
    // drawer refresh live. Debounced so a "play all" burst collapses into one save.
    const installSyncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const installSyncPendingIdsRef = useRef<Set<string>>(new Set());
    scheduleInstallSyncRef.current = (nodeId: string) => {
        // Never from a dashboard. A tile drawing itself emits an output like any
        // run, and this is what turns an output into a project save: from the
        // dashboard that would rewrite the owner's dataflow behind their back,
        // and for a visitor holding a link it would throw and surface as an error
        // toast on a page they only opened to look at.
        if (dashboardOn) return;
        const node = reactFlow.getNode(nodeId);
        if (!node) return;
        const canonical = getUnversionedFlowNodeType(node);
        // Sinks / interaction surfaces pass their input through — never a NEW
        // dataset — so excluding them keeps e.g. a Data Pool's per-brush re-emit
        // from triggering saves. DATA_POOL is a save-trigger-only extra on top
        // of the shared sink set: the backend must NOT prune data-pool refs.
        if (isNonProducingNodeType(canonical) || canonical === NodeType.DATA_POOL) {
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

        // Debounce: one save covers every producer that landed in this window. The
        // save fires after outputs have committed, so buildOutputRefs sees them.
        if (installSyncTimerRef.current) clearTimeout(installSyncTimerRef.current);
        installSyncTimerRef.current = setTimeout(() => runInstallSyncNow(), 500);
    };

    // Run the pending install-save immediately. Shared by the debounce timer and
    // by flushInstallSyncRef so a forced flush takes the exact same path.
    const runInstallSyncNow = () => {
        if (installSyncTimerRef.current) {
            clearTimeout(installSyncTimerRef.current);
            installSyncTimerRef.current = null;
        }
        const ids = Array.from(installSyncPendingIdsRef.current);
        if (ids.length === 0) return;
        installSyncPendingIdsRef.current = new Set();
        void workflowOps
            // Scope the warning toast to the producers this sync covers: a save
            // re-sends refs for every toggle-enabled node, so an unscoped toast
            // names nodes the user never ran (#180).
            .persistDataflowForInstall(ids)
            .then((outcome) => {
                // Per producer, on the save's actual result (#352). This used to
                // be a `.finally` that cleared every placeholder however the save
                // went: a dataset that did not install had its "Adding…" entry
                // flash and disappear, which is #217's symptom, and nothing tied
                // the two together so no test could catch it coming back.
                // Tolerant of a resolve with no outcome: a save that reports
                // nothing is treated as "nothing failed", which is the old
                // behaviour. A crash here would strand the whole canvas.
                const failed = new Set(outcome?.failedNodeIds ?? []);
                ids.forEach((id) =>
                    failed.has(id)
                        ? workflowOps.failPendingInstall(id)
                        : workflowOps.endPendingInstall(id),
                );
            })
            .catch(() => {
                // persistDataflowForInstall handles its own errors and resolves;
                // this is only here so an unexpected throw cannot strand every
                // placeholder in "Adding…" for the full 10-minute safety timeout.
                ids.forEach((id) => workflowOps.failPendingInstall(id));
            });
    };

    // Force any pending install-save to run now. Called when Play All completes
    // (finishPlayAll) and on unmount so the last burst's datasets are never lost
    // to the 500ms debounce window (Vector 2 in the flakiness investigation).
    flushInstallSyncRef.current = () => {
        if (installSyncTimerRef.current) runInstallSyncNow();
    };

    useEffect(
        () => () => {
            // Flush (not just clear) on unmount: a dataflow switch / navigation
            // inside the debounce window would otherwise drop the pending save.
            // TMP PROOF: no flush on unmount.
        },
        [],
    );
}
