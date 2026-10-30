import React, { useCallback } from "react";

import { AgentReviewCard } from "../../agents/content/AgentReviewCard";
import { installsIntoAccount } from "../../../services/agents/agentEditors";
import { notifyDatasetCatalogRefresh } from "../../../services/datasetCatalog/datasetCatalogApi";
import {
  datasetRequestPart,
  datasetRequestsApi,
  reloadDatasetRequests,
  useHeldDatasetRequests,
  type DatasetRequest,
} from "../../../services/datasetCatalog/datasetRequests";
import { useToastContext } from "../../../providers/ToastProvider";
import styles from "./DatasetCatalogDrawer.module.css";

/**
 * The datasets the dataflow's invited editors asked its owner to add, at the
 * top of the Data Catalog drawer (`datasetRequests.ts`). Each is the review
 * card an install an agent asks for has (`AgentReviewCard`), under the name of
 * who asked: the owner applies or dismisses it, and on an editor's canvas the
 * card says it waits for her, as an install does in an editor's chat. Nothing
 * renders while no request waits.
 */
export const DatasetRequestsSection: React.FC = () => {
  const { dataflowId, viewer, requests } = useHeldDatasetRequests();
  const { showToast } = useToastContext();
  const owner = viewer === "owner";

  const settle = useCallback(
    async (request: DatasetRequest, act: () => Promise<unknown>, done: string) => {
      try {
        await act();
        showToast(done, "success");
        notifyDatasetCatalogRefresh();
      } catch (err) {
        showToast((err as Error)?.message || `Could not review ${request.datasetName}.`, "error");
      } finally {
        await reloadDatasetRequests();
      }
    },
    [showToast],
  );

  if (!dataflowId || requests.length === 0) return null;
  return (
    <section className={styles.requests} aria-label="Waiting for review" data-curio-dataset-requests="true">
      <div className={styles.requestsTitle}>Waiting for review</div>
      {requests.map((request) => {
        const waits = !owner && installsIntoAccount(request.tool);
        return (
          <div key={request.proposalId} data-curio-dataset-request={request.datasetId}>
            <div className={styles.requestBy}>Asked by {request.by.name}</div>
            <AgentReviewCard
              part={datasetRequestPart(request)}
              waitsForOwner={waits}
              onApply={
                owner
                  ? () =>
                      settle(
                        request,
                        () => datasetRequestsApi.apply(dataflowId, request.proposalId),
                        `Added ${request.datasetName} to this dataflow.`,
                      )
                  : undefined
              }
              onDismiss={
                owner
                  ? () =>
                      settle(
                        request,
                        () => datasetRequestsApi.dismiss(dataflowId, request.proposalId),
                        `Dismissed ${request.by.name}'s request for ${request.datasetName}.`,
                      )
                  : undefined
              }
            />
          </div>
        );
      })}
    </section>
  );
};
