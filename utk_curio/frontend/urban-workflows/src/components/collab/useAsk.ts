/**
 * An invited editor's item of his own, asked of the dataflow's owner.
 *
 * On the owner's dataflow an editor's tab writes neither her store nor her
 * dataflow's lists of datasets and packages: each item of his own he brings
 * asks her instead (`editorRequests.ts`), through the ask of its kind: a
 * dataset's or a collection's (`datasets/useAskTheOwner`), a package's or a
 * model's (`packages/useAskForPackage`).
 *
 * The answer says when nothing needed asking: an item her dataflow has
 * already, or, for a dataset dropped, one of the shared Data Catalog, which
 * every account's runs read.
 *
 * Null on any canvas but an invited editor's: the owner adds the item
 * herself, and a watcher's canvas offers none of this.
 */
import { useCallback } from "react";

import { useFlowContext } from "../../providers/FlowProvider";
import { useCollab } from "../../providers/CollaborationProvider";
import { useAgentsDataflowId } from "../../providers/agents";
import { canvasRole } from "../../providers/collab/participants";
import { useToastContext } from "../../providers/ToastProvider";
import { editorRequestsApi, reloadEditorRequests, type RequestKind } from "../../services/editorRequests";

/** How an item was brought: an Add to project (*add*), or a drop that made the node *nodeId*. */
export interface AskHow {
  add?: boolean;
  nodeId?: string;
}

/** The ask of an item of *kind*, which *body* names and the toasts call
 *  *name*, or null off an invited editor's canvas. */
export function useAsk(kind: RequestKind) {
  const { viewerMode } = useFlowContext();
  const collab = useCollab();
  const dataflowId = useAgentsDataflowId();
  const { showToast } = useToastContext();
  const editor = canvasRole(viewerMode, collab) === "editor";
  const ask = useCallback(
    async (body: { datasetId?: string; dirName?: string }, name: string, how: AskHow = {}) => {
      if (!dataflowId || !(body.datasetId || body.dirName)) return false;
      try {
        const answer = await editorRequestsApi.ask(dataflowId, kind, {
          ...body,
          ...(how.nodeId ? { nodeId: how.nodeId } : {}),
          ...(how.add ? { add: true } : {}),
        });
        if (!answer.requested) return false;
        showToast(`Asked the dataflow's owner to add ${name} to it.`, "info");
        await reloadEditorRequests();
        return true;
      } catch (err) {
        showToast((err as Error)?.message || `Could not ask the dataflow's owner for ${name}.`, "error");
        return false;
      }
    },
    [dataflowId, kind, showToast],
  );
  return editor ? ask : null;
}
