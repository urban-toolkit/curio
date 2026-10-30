import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { AgentReviewCard } from "../agents/content/AgentReviewCard";
import { holdModalStack } from "../ModalShell";
import { InstallPermissionsDialog } from "../packages/publishing/InstallPermissionsDialog";
import { installsIntoAccount } from "../../services/agents/agentEditors";
import { notifyDatasetCatalogRefresh } from "../../services/datasetCatalog/datasetCatalogApi";
import { notifyPackageCatalogRefresh } from "../../services/packages/modelPackages";
import {
  editorRequestsApi,
  isPackageRequest,
  reloadEditorRequests,
  requestCatalog,
  requestEffect,
  requestedName,
  requestPart,
  useHeldEditorRequests,
  type EditorRequest,
  type PackageRequestReview,
  type RequestCatalog,
} from "../../services/editorRequests";
import { useToastContext } from "../../providers/ToastProvider";
import styles from "./EditorRequestsSection.module.css";

/** A package request's review, open while the owner decides. */
interface Reviewing {
  request: EditorRequest;
  review: PackageRequestReview;
  settle: (error?: unknown) => void;
}

/** The attributes a catalog's section is found by. */
const SECTION_ATTRIBUTE: Record<RequestCatalog, Record<string, string>> = {
  datasets: { "data-curio-dataset-requests": "true" },
  node: { "data-curio-package-requests": "node" },
  model: { "data-curio-package-requests": "model" },
};

/**
 * What the dataflow's invited editors asked its owner to add, at the top of
 * the catalog drawer of its kind (*catalog*: the Data, Node or Model
 * Catalog's; `editorRequests.ts`). Each is the review card an install an agent
 * asks for has (`AgentReviewCard`), under the name of who asked: the owner
 * applies or dismisses it, and on an editor's canvas the card says it waits
 * for her, as an install does in an editor's chat. In place of the line an
 * agent's install has, the card says what her Apply does (`requestEffect`).
 *
 * A package's Apply first opens the review her own Add opens
 * (`InstallPermissionsDialog`: its permissions, libraries and conflicts with
 * her packages, read by the server from the copy it would install); its
 * confirm applies the request, and Cancel leaves it waiting. An Apply the
 * server refuses says why on the card, which stays in her review. Nothing
 * renders while no request waits.
 */
export const EditorRequestsSection: React.FC<{ catalog: RequestCatalog }> = ({ catalog }) => {
  const { dataflowId, viewer, requests: held } = useHeldEditorRequests();
  const requests = useMemo(() => held.filter((request) => requestCatalog(request) === catalog), [held, catalog]);
  const { showToast } = useToastContext();
  const owner = viewer === "owner";
  const [reviewing, setReviewing] = useState<Reviewing | null>(null);
  const [busy, setBusy] = useState(false);

  // One more layer over the drawer while the review is open, so its Escape
  // leaves the drawer open.
  useEffect(() => {
    if (!reviewing) return;
    const release = holdModalStack();
    return () => {
      window.setTimeout(release, 0);
    };
  }, [reviewing]);

  /** Post the Apply and say what it added; a refusal rejects, which the card shows. */
  const applyNow = useCallback(
    async (request: EditorRequest) => {
      if (!dataflowId) return;
      try {
        await editorRequestsApi.apply(dataflowId, request);
      } catch (err) {
        const requests = await reloadEditorRequests();
        // A request that left her review (its asker no longer edits) has no
        // card left to say why.
        if (!requests.some((r) => r.proposalId === request.proposalId)) {
          showToast((err as Error)?.message || `Could not add ${requestedName(request)}.`, "error");
        }
        throw err;
      }
      showToast(`Added ${requestedName(request)} to this dataflow.`, "success");
      // A package reaches every tab's registry with the dataflow's lockfile
      // (`takeDataflowFields`); the drawers list it again.
      if (isPackageRequest(request)) notifyPackageCatalogRefresh();
      else notifyDatasetCatalogRefresh();
      await reloadEditorRequests();
    },
    [dataflowId, showToast],
  );

  const apply = useCallback(
    async (request: EditorRequest) => {
      if (!dataflowId) return;
      if (!isPackageRequest(request)) {
        await applyNow(request);
        return;
      }
      const review = await editorRequestsApi.review(dataflowId, request);
      await new Promise<void>((resolve, reject) => {
        setReviewing({ request, review, settle: (error) => (error === undefined ? resolve() : reject(error)) });
      });
    },
    [dataflowId, applyNow],
  );

  const confirm = useCallback(async () => {
    if (!reviewing || busy) return;
    setBusy(true);
    try {
      await applyNow(reviewing.request);
      reviewing.settle();
    } catch (err) {
      reviewing.settle(err);
    } finally {
      setBusy(false);
      setReviewing(null);
    }
  }, [reviewing, busy, applyNow]);

  const cancel = useCallback(() => {
    if (!reviewing || busy) return;
    reviewing.settle();
    setReviewing(null);
  }, [reviewing, busy]);

  const dismiss = useCallback(
    async (request: EditorRequest) => {
      if (!dataflowId) return;
      try {
        await editorRequestsApi.dismiss(dataflowId, request);
        showToast(`Dismissed ${request.by.name}'s request for ${requestedName(request)}.`, "success");
      } finally {
        await reloadEditorRequests();
      }
    },
    [dataflowId, showToast],
  );

  const dialog = reviewing ? (
    <InstallPermissionsDialog
      pkg={reviewing.review.package}
      conflicts={reviewing.review.conflicts}
      busy={busy}
      onCancel={cancel}
      onConfirm={() => void confirm()}
    />
  ) : null;

  if (!dataflowId || requests.length === 0) return dialog ? createPortal(dialog, document.body) : null;
  return (
    <section className={styles.requests} aria-label="Waiting for review" {...SECTION_ATTRIBUTE[catalog]}>
      <div className={styles.requestsTitle}>Waiting for review</div>
      {requests.map((request) => (
        <div
          key={request.proposalId}
          {...(isPackageRequest(request)
            ? { "data-curio-package-request": request.dirName }
            : { "data-curio-dataset-request": request.datasetId })}
        >
          <div className={styles.requestBy}>Asked by {request.by.name}</div>
          <AgentReviewCard
            part={requestPart(request)}
            waitsForOwner={!owner && installsIntoAccount(request.tool)}
            effect={requestEffect(request, viewer)}
            onApply={owner ? () => apply(request) : undefined}
            onDismiss={owner ? () => dismiss(request) : undefined}
          />
        </div>
      ))}
      {dialog ? createPortal(dialog, document.body) : null}
    </section>
  );
};
