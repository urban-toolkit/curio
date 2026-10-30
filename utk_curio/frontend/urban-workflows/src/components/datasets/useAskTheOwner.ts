/**
 * An invited editor's dataset of his own, asked of the dataflow's owner.
 *
 * On the owner's dataflow an editor's tab writes neither her store nor her
 * dataflow's datasets: a file he drops goes into his own Data Catalog, and
 * that file, his Add to project and a card of his catalog he drags onto her
 * canvas or a node each ask her instead (`datasetRequests.ts`). The answer
 * says when nothing needed asking: a dataset her dataflow lists already, or,
 * for a drop, one of the shared catalog, which every account's runs read.
 *
 * Null on any canvas but an invited editor's: the owner adds the dataset
 * herself, and a watcher's canvas offers none of this.
 */
import { useCallback } from "react";

import { useFlowContext } from "../../providers/FlowProvider";
import { useCollab } from "../../providers/CollaborationProvider";
import { useAgentsDataflowId } from "../../providers/agents";
import { canvasRole } from "../../providers/collab/participants";
import { useToastContext } from "../../providers/ToastProvider";
import { datasetRequestsApi, reloadDatasetRequests } from "../../services/datasetCatalog/datasetRequests";

/** A dataset as an ask names it: a catalog item's id or a drag's. */
export interface AskedDataset {
  id?: string;
  datasetId?: string;
  title: string;
}

export type AskTheOwner = (dataset: AskedDataset, how?: { add?: boolean; nodeId?: string }) => Promise<boolean>;

export function useAskTheOwner(): AskTheOwner | null {
  const { viewerMode } = useFlowContext();
  const collab = useCollab();
  const dataflowId = useAgentsDataflowId();
  const { showToast } = useToastContext();
  const editor = canvasRole(viewerMode, collab) === "editor";
  const ask = useCallback<AskTheOwner>(
    async (dataset, how = {}) => {
      const datasetId = dataset.datasetId ?? dataset.id;
      if (!dataflowId || !datasetId) return false;
      try {
        const answer = await datasetRequestsApi.ask(dataflowId, {
          datasetId,
          ...(how.nodeId ? { nodeId: how.nodeId } : {}),
          ...(how.add ? { add: true } : {}),
        });
        if (!answer.requested) return false;
        showToast(`Asked the dataflow's owner to add ${dataset.title} to it.`, "info");
        await reloadDatasetRequests();
        return true;
      } catch (err) {
        showToast((err as Error)?.message || `Could not ask the dataflow's owner for ${dataset.title}.`, "error");
        return false;
      }
    },
    [dataflowId, showToast],
  );
  return editor ? ask : null;
}
