/**
 * An agent's changes and the installs a person reviews, from the client's side
 * (memo dev/142, F2: extracted from `AgentAttachmentsProvider`): an install's
 * apply and dismiss, a change's Undo, the dataset selection and the portal
 * import. An applied install and an Undo carry their mutation to the LIVE
 * canvas through the dev/48 §3.3 bridge: the server's answer is the only
 * payload source: and then refresh the transcript and the listing, which are
 * the truth.
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
  notifyAgentChangesLanded,
} from "../../services/agents";
import type {
  AgentApplyResult,
  AgentDatasetPick,
  AgentDatasetSelection,
  AgentUndoResult,
} from "../../services/agents/types";

export interface AgentProposalsSlice {
  applyProposal: (attachmentId: string, proposalId: string) => Promise<AgentApplyResult>;
  dismissProposal: (attachmentId: string, proposalId: string) => Promise<void>;
  /** Undo a change the attachment's agent made; rejects with the refusal
   * (who changed it after) when nothing was undone. */
  undoChange: (attachmentId: string, changeId: string) => Promise<AgentUndoResult>;
  recordDatasetSelection: (attachmentId: string, picks: AgentDatasetPick[]) => Promise<AgentDatasetSelection>;
  /** `discoverySource` is where the file came from, recorded with it. */
  importDataset: (file: File, discoverySource?: DatasetDiscoverySourceInput) => Promise<string | null>;
}

export function useAgentProposals(opts: {
  effectiveProjectId: string | null;
  projectRef: React.MutableRefObject<string | null>;
  refreshAfterMutation: (attachmentId: string) => Promise<void>;
}): AgentProposalsSlice {
  const { effectiveProjectId, projectRef, refreshAfterMutation } = opts;
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
        return result;
      } finally {
        // Success appends the result turn + statuses; a 409 marked it stale —
        // either way the transcript and listing are the truth.
        await refreshAfterMutation(attachmentId);
      }
    },
    [projectRef, refreshAfterMutation],
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

  const undoChange = useCallback(
    async (attachmentId: string, changeId: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        const result = await agentsApi.undoChange(pid, attachmentId, changeId);
        // The server put it back in the dataflow's doc; a canvas no doc
        // binds takes the same mutations here.
        notifyAgentChangesLanded(result.canvas);
        return result;
      } finally {
        // Undone, the card says so; refused, nothing changed.
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
    () => ({ applyProposal, dismissProposal, undoChange, recordDatasetSelection, importDataset }),
    [applyProposal, dismissProposal, undoChange, recordDatasetSelection, importDataset],
  );
}

/** The apply→canvas bridge (dev/48 §3.3): the saved spec was mutated; carry
 * the same mutation to the LIVE canvas in this user action so the next save
 * can't clobber it. An applied package (dev/89), or a package's install that
 * placed notes, refreshes the package registry BEFORE painting its nodes. */
function bridgeApplyResult(proposalId: string, result: AgentApplyResult): void {
  if (result.requiresRegistryRefresh && result.installedPackage) {
    notifyAgentCanvasMutation({
      kind: "package-nodes-created",
      artifactDigest: proposalId,
      packageDir: result.installedPackage.dirName,
      nodes: result.createdNodes ?? [],
    });
  }
}
