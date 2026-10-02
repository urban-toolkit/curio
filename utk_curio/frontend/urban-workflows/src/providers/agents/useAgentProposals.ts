/**
 * Review-before-apply from the client's side (memo dev/142, F2 — extracted
 * from `AgentAttachmentsProvider`): apply, the per-node and per-edge plan
 * applies, a plan goal edit, dismiss, the dataset selection and the portal
 * import. Every apply carries its mutation to the LIVE canvas through the
 * dev/48 §3.3 bridge — the apply response is the only payload source — and
 * then refreshes the transcript and the listing, which are the truth.
 */
import type { DatasetDiscoverySourceInput } from "../../services/datasetCatalog/datasetCatalogTypes";
import { useCallback, useMemo } from "react";

import { useOptionalToastContext } from "../ToastProvider";
import { useDatasetCatalog } from "../../services/datasetCatalog/datasetCatalogHooks";
import { useDatasetImport } from "../../services/datasetCatalog/useDatasetImport";
import {
  agentsApi,
  notifyAgentCanvasMutation,
  notifyAgentCatalogRefresh,
} from "../../services/agents";
import type {
  AgentApplyResult,
  AgentDatasetPick,
  AgentDatasetSelection,
  AgentPlanEdgesResult,
} from "../../services/agents/types";

export interface AgentProposalsSlice {
  applyProposal: (attachmentId: string, proposalId: string) => Promise<AgentApplyResult>;
  applyPlanNode: (attachmentId: string, proposalId: string, ref: string) => Promise<void>;
  applyPlanEdges: (attachmentId: string, proposalId: string, indices?: number[]) => Promise<AgentPlanEdgesResult>;
  savePlanGoal: (attachmentId: string, proposalId: string, ref: string, goal: string) => Promise<void>;
  dismissProposal: (attachmentId: string, proposalId: string) => Promise<void>;
  recordDatasetSelection: (attachmentId: string, picks: AgentDatasetPick[]) => Promise<AgentDatasetSelection>;
  /** `discoverySource` is where the file came from, recorded with it. */
  importDataset: (file: File, discoverySource?: DatasetDiscoverySourceInput) => Promise<string | null>;
}

export function useAgentProposals(opts: {
  effectiveProjectId: string | null;
  projectRef: React.MutableRefObject<string | null>;
  reload: () => Promise<void>;
  refreshAfterMutation: (attachmentId: string) => Promise<void>;
}): AgentProposalsSlice {
  const { effectiveProjectId, projectRef, reload, refreshAfterMutation } = opts;
  // dev/132: the toast is how the shared import reports itself; the provider
  // must still render where none is mounted (a test, an embedded surface).
  const toast = useOptionalToastContext();
  const showToast = useCallback(
    (message: string, kind: "success" | "error") => {
      if (toast) toast.showToast(message, kind);
    },
    [toast],
  );
  // dev/132: the catalog hook is used for its import ONLY — `enabled: false`
  // fetches no listing here (the drawer and the catalog page own that).
  const datasetCatalog = useDatasetCatalog({ dataflowId: effectiveProjectId ?? undefined, enabled: false });
  const { importFile: importDatasetFile } = useDatasetImport({
    importDataset: datasetCatalog.importDataset,
    showToast,
  });
  const importDataset = useCallback(
    async (file: File, discoverySource?: DatasetDiscoverySourceInput) => {
      const imported = await importDatasetFile(file, discoverySource ? { discoverySource } : undefined);
      const id = (imported as { id?: string } | null | undefined)?.id;
      return typeof id === "string" && id ? id : null;
    },
    [importDatasetFile],
  );

  const applyProposal = useCallback(
    async (attachmentId: string, proposalId: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        const result = await agentsApi.applyProposal(pid, attachmentId, proposalId);
        bridgeApplyResult(proposalId, result);
        // dev/106: a reviewed project.install landed a template (and its
        // required closure) in the lockfile — the AGENTS palette repaints.
        if (result.installedCoord) notifyAgentCatalogRefresh();
        // dev/105 A3: callers that queue follow-ups (the package install
        // review) read the result to walk them one at a time.
        return result;
      } finally {
        // Success appends the result turn + statuses; a 409 marked it stale —
        // either way the transcript and listing are the truth.
        await refreshAfterMutation(attachmentId);
      }
    },
    [projectRef, refreshAfterMutation],
  );

  const applyPlanNode = useCallback(
    async (attachmentId: string, proposalId: string, ref: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        const result = await agentsApi.applyPlanNode(pid, attachmentId, proposalId, ref);
        // The created node reaches the LIVE canvas through the same bridge
        // path as node.create applies (dev/48 §3.3).
        if (result.createdNode) {
          notifyAgentCanvasMutation({ kind: "node-created", node: result.createdNode });
        }
        // dev/71: the progressive sweep's edges draw immediately too.
        if (result.createdEdges?.length) {
          notifyAgentCanvasMutation({
            kind: "edges-created",
            batchId: `${proposalId}:${ref}:${result.createdEdges.map((e) => e.id).join(",")}`,
            edges: result.createdEdges,
          });
        }
      } finally {
        await refreshAfterMutation(attachmentId); // the result turn + the per-node ledger
      }
    },
    [projectRef, refreshAfterMutation],
  );

  const applyPlanEdges = useCallback(
    async (attachmentId: string, proposalId: string, indices?: number[]) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        const result = await agentsApi.applyPlanEdges(pid, attachmentId, proposalId, indices);
        if (result.createdEdges.length) {
          notifyAgentCanvasMutation({
            kind: "edges-created",
            batchId: `${proposalId}:${result.createdEdges.map((e) => e.id).join(",")}`,
            edges: result.createdEdges,
          });
        }
        return result;
      } finally {
        await refreshAfterMutation(attachmentId);
      }
    },
    [projectRef, refreshAfterMutation],
  );

  const savePlanGoal = useCallback(
    async (attachmentId: string, proposalId: string, ref: string, goal: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      await agentsApi.savePlanGoal(pid, attachmentId, proposalId, ref, goal);
      await reload(); // the mirror carries editedGoals
    },
    [projectRef, reload],
  );

  const dismissProposal = useCallback(
    async (attachmentId: string, proposalId: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        await agentsApi.dismissProposal(pid, attachmentId, proposalId);
      } finally {
        await refreshAfterMutation(attachmentId);
      }
    },
    [projectRef, refreshAfterMutation],
  );

  const recordDatasetSelection = useCallback(
    async (attachmentId: string, picks: AgentDatasetPick[]) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        return await agentsApi.recordDatasetSelection(pid, attachmentId, picks);
      } finally {
        // The record lives on the attachment and the confirmation is logged
        // as a turn: refresh both, exactly as an apply does.
        await refreshAfterMutation(attachmentId);
      }
    },
    [projectRef, refreshAfterMutation],
  );

  return useMemo(
    () => ({ applyProposal, applyPlanNode, applyPlanEdges, savePlanGoal, dismissProposal, recordDatasetSelection, importDataset }),
    [applyProposal, applyPlanNode, applyPlanEdges, savePlanGoal, dismissProposal, recordDatasetSelection, importDataset],
  );
}

/** The apply→canvas bridge (dev/48 §3.3): the saved spec was mutated; carry
 * the same mutation to the LIVE canvas in this user action so the next save
 * can't clobber it. */
function bridgeApplyResult(proposalId: string, result: AgentApplyResult): void {
  if (result.requiresRegistryRefresh && result.installedPackage) {
    // dev/89: an applied package draft — the bridge refreshes the package
    // registry BEFORE painting the created nodes.
    notifyAgentCanvasMutation({
      kind: "package-nodes-created",
      artifactDigest: proposalId,
      packageDir: result.installedPackage.dirName,
      nodes: result.createdNodes ?? [],
    });
  } else if (result.createdNode) {
    notifyAgentCanvasMutation({
      kind: "node-created",
      node: result.createdNode,
      createdPackageDir: result.createdTemplate?.packageDir,
    });
  } else if (result.appliedContent) {
    notifyAgentCanvasMutation({
      kind: "node-content-applied",
      nodeId: result.appliedContent.nodeId,
      content: result.appliedContent.content,
    });
  } else if (result.appliedGraph) {
    // dev/52: a whole applied plan — bulk insert + edges + fit; dev/59:
    // removals ride the same event, applied first.
    notifyAgentCanvasMutation({
      kind: "graph-created",
      planId: proposalId,
      nodes: result.appliedGraph.nodes,
      edges: result.appliedGraph.edges,
      removedNodeIds: result.appliedGraph.removedNodeIds,
      removedEdgeIds: result.appliedGraph.removedEdgeIds,
    });
  }
}
