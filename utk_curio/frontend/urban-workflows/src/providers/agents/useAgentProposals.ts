/**
 * An agent's changes and the installs a person reviews, from the client's side
 * (memo dev/142, F2: extracted from `AgentAttachmentsProvider`): an install's
 * apply and dismiss, a change's Undo, the dataset selection and the portal
 * import. An applied install and an Undo carry their mutation to the LIVE
 * canvas through the dev/48 §3.3 bridge: the server's answer is the only
 * payload source: and then refresh the transcript and the listing, which are
 * the truth. Why the server refused a card's Undo, Apply or Dismiss is kept
 * here, by chat and card (`refusals`), so the card says it across the reads
 * that draw it anew, until the user acts on it again.
 */
import type { DatasetDiscoverySourceInput } from "../../services/datasetCatalog/datasetCatalogTypes";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useFlowContext } from "../FlowProvider";
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
  /** Record a pick on the node's Dataset Finder *attachmentId*, naming the
   * card it was made on (*discoveryId*) when the card has an id. */
  recordDatasetSelection: (
    attachmentId: string,
    picks: AgentDatasetPick[],
    discoveryId?: string,
  ) => Promise<AgentDatasetSelection>;
  /** `discoverySource` is where the file came from, recorded with it. */
  importDataset: (file: File, discoverySource?: DatasetDiscoverySourceInput) => Promise<string | null>;
  /** Why the server refused the last Undo, Apply or Dismiss of a card, by
   * chat and by the card's change or proposal id: its card says it, though a
   * read of the chat draws the card anew, until the user acts on it again. */
  refusals: Record<string, Record<string, string>>;
}

export function useAgentProposals(opts: {
  effectiveProjectId: string | null;
  projectRef: React.MutableRefObject<string | null>;
  refreshAfterMutation: (attachmentId: string) => Promise<void>;
}): AgentProposalsSlice {
  const { effectiveProjectId, projectRef, refreshAfterMutation } = opts;
  // The canvas's doc as an Undo answers, which tells the others what the
  // Undo took out.
  const { dataflowDoc } = useFlowContext();
  const dataflowDocRef = useRef(dataflowDoc);
  dataflowDocRef.current = dataflowDoc;
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

  const [refusals, setRefusals] = useState<Record<string, Record<string, string>>>({});
  // Another dataflow's cards are not this one's.
  useEffect(() => setRefusals({}), [effectiveProjectId]);
  /** Act on the card *cardId* of *attachmentId*'s chat with *request*: the
   * reason the server refused its last action goes as the user acts again;
   * whatever the answer, the chat and the listing are read again after it
   * and waited for, so the card never offers its action again on its old
   * status; a refusal's reason, the server's words, is kept for the card,
   * which a read may draw anew, before the refusal reaches it. */
  const actOnCard = useCallback(
    async <T,>(attachmentId: string, cardId: string, request: () => Promise<T>): Promise<T> => {
      setRefusals((prev) => {
        if (!prev[attachmentId]?.[cardId]) return prev;
        const { [cardId]: _gone, ...rest } = prev[attachmentId];
        return { ...prev, [attachmentId]: rest };
      });
      let why: string | null = null;
      try {
        return await request();
      } catch (e) {
        why = e instanceof Error && e.message ? e.message : null;
        throw e;
      } finally {
        await refreshAfterMutation(attachmentId);
        if (why !== null) {
          const reason = why;
          setRefusals((prev) => ({ ...prev, [attachmentId]: { ...prev[attachmentId], [cardId]: reason } }));
        }
      }
    },
    [refreshAfterMutation],
  );

  const applyProposal = useCallback(
    async (attachmentId: string, proposalId: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      // Success appends the result turn + statuses; a 409 marked it stale:
      // either way the transcript and listing are the truth.
      return actOnCard(attachmentId, proposalId, async () => {
        const result = await agentsApi.applyProposal(pid, attachmentId, proposalId);
        bridgeApplyResult(proposalId, result);
        // dev/106: a reviewed project.install landed a template (and its
        // required closure) in the lockfile: the AGENTS palette repaints.
        if (result.installedCoord) notifyAgentCatalogRefresh();
        return result;
      });
    },
    [projectRef, actOnCard],
  );

  const dismissProposal = useCallback(
    async (attachmentId: string, proposalId: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      await actOnCard(attachmentId, proposalId, () => agentsApi.dismissProposal(pid, attachmentId, proposalId));
    },
    [projectRef, actOnCard],
  );

  const undoChange = useCallback(
    async (attachmentId: string, changeId: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      // Undone, the card says so; refused, nothing changed, and the card
      // says why.
      return actOnCard(attachmentId, changeId, async () => {
        const result = await agentsApi.undoChange(pid, attachmentId, changeId);
        // The nodes the Undo took out are this tab's removal: a tab that was
        // editing one says who removed it.
        const removed = (Array.isArray(result.canvas) ? result.canvas : []).flatMap((mutation) =>
          "removedNodeIds" in mutation && Array.isArray(mutation.removedNodeIds) ? mutation.removedNodeIds : [],
        );
        if (removed.length > 0) dataflowDocRef.current?.noteRemoval(removed);
        // The server put it back in the dataflow's doc; a canvas no doc
        // binds takes the same mutations here.
        notifyAgentChangesLanded(result.canvas);
        return result;
      });
    },
    [projectRef, actOnCard],
  );

  const recordDatasetSelection = useCallback(
    async (attachmentId: string, picks: AgentDatasetPick[], discoveryId?: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        return await (discoveryId
          ? agentsApi.recordDatasetSelection(pid, attachmentId, picks, discoveryId)
          : agentsApi.recordDatasetSelection(pid, attachmentId, picks));
      } finally {
        // The record lives on the attachment and the confirmation is logged
        // as a turn: refresh both, exactly as an apply does.
        await refreshAfterMutation(attachmentId);
      }
    },
    [projectRef, refreshAfterMutation],
  );

  return useMemo(
    () => ({ applyProposal, dismissProposal, undoChange, recordDatasetSelection, importDataset, refusals }),
    [applyProposal, dismissProposal, undoChange, recordDatasetSelection, importDataset, refusals],
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
