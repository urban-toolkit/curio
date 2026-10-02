import { useCallback, useState } from "react";

import type { ToastVariant } from "../../../providers/ToastProvider";
import { permanentDeletionNotice } from "../../../services/retentionCopy";
import {
  isDeletableModel,
  modelCatalogApi,
  notifyModelCatalogRefresh,
  type ModelRow,
} from "../../../services/modelCatalog";

/** A pending confirmation. The hook cannot render, so it holds the question
 *  and the surface paints it with `ConfirmDialog`, as the dataset drawer does. */
export interface ModelConfirmAction {
  title: string;
  body: string;
  confirmLabel: string;
  destructive: boolean;
  /** Returns the action's promise so callers (and tests) can await it. */
  run: () => Promise<void>;
}

type ShowToast = (message: string, variant?: ToastVariant) => void;

/**
 * Deleting a downloaded model, asked first, for the browse page and the canvas
 * drawer alike: one question, one request, one refresh, so the two surfaces
 * cannot word or do it differently.
 */
export function useModelDelete(showToast: ShowToast) {
  const [confirmAction, setConfirmAction] = useState<ModelConfirmAction | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const performDelete = useCallback(
    async (model: ModelRow) => {
      setBusyId(model.id);
      try {
        await modelCatalogApi.deleteModel(model.id);
        // One refresh event: every mounted listing reloads from it.
        notifyModelCatalogRefresh();
        showToast(`Deleted ${model.name} from your Model Catalog.`, "success");
      } catch (err) {
        showToast((err as Error)?.message || "Could not delete the model.", "error");
      } finally {
        setBusyId(null);
      }
    },
    [showToast],
  );

  const requestDelete = useCallback(
    (model: ModelRow) => {
      // Shipped models are never offered Delete; this is the backstop.
      if (!isDeletableModel(model)) return;
      const title = model.name;
      setConfirmAction({
        // The question the Data Catalog and the projects page ask for the same
        // act: the permanence in the title, qualified in the body.
        title: `Permanently delete "${title}"?`,
        body:
          `Delete ${title} from your Model Catalog?\n\n` +
          `Nodes that name it in their code fail the next time they run.` +
          `\n\n${permanentDeletionNotice()}`,
        confirmLabel: "Delete",
        destructive: true,
        run: () => performDelete(model),
      });
    },
    [performDelete],
  );

  const dismissConfirm = useCallback(() => setConfirmAction(null), []);

  return { confirmAction, requestDelete, dismissConfirm, busyId };
}
