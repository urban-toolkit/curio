/**
 * An invited editor's item of his own, asked of the dataflow's owner.
 *
 * On the owner's dataflow an editor's tab writes neither her store nor her
 * dataflow's lists of datasets and packages: each item of his own he brings
 * asks her instead (`editorRequests.ts`).
 *
 * - A dataset (`useAskTheOwner`): a file he drops goes into his own Data
 *   Catalog, and that file, his Add to project and a card of his catalog he
 *   drags onto her canvas or a node each ask her.
 * - A package or a model (`useAskForPackage`): his Add to project, a card he
 *   drops on her canvas, which makes its node at once, and a model he drops on
 *   a node of hers each ask her.
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

/** A dataset as an ask names it: a catalog item's id or a drag's. */
export interface AskedDataset {
  id?: string;
  datasetId?: string;
  title: string;
}

/** A package or a model as an ask names it: its `<packageId>@<major>` and name. */
export interface AskedPackage {
  dirName: string;
  name: string;
}

export type AskTheOwner = (dataset: AskedDataset, how?: { add?: boolean; nodeId?: string }) => Promise<boolean>;
export type AskForPackage = (pkg: AskedPackage, how?: { add?: boolean; nodeId?: string }) => Promise<boolean>;

/** The ask of an item of *kind* (*body* names it), or null off an editor's canvas. */
function useAsk(kind: RequestKind) {
  const { viewerMode } = useFlowContext();
  const collab = useCollab();
  const dataflowId = useAgentsDataflowId();
  const { showToast } = useToastContext();
  const editor = canvasRole(viewerMode, collab) === "editor";
  const ask = useCallback(
    async (body: { datasetId?: string; dirName?: string }, name: string, how: { add?: boolean; nodeId?: string } = {}) => {
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

export function useAskTheOwner(): AskTheOwner | null {
  const ask = useAsk("datasets");
  const askForDataset = useCallback<AskTheOwner>(
    (dataset, how) => ask!({ datasetId: dataset.datasetId ?? dataset.id }, dataset.title, how),
    [ask],
  );
  return ask ? askForDataset : null;
}

export function useAskForPackage(): AskForPackage | null {
  const ask = useAsk("packages");
  const askForPackage = useCallback<AskForPackage>(
    (pkg, how) => ask!({ dirName: pkg.dirName }, pkg.name, how),
    [ask],
  );
  return ask ? askForPackage : null;
}
