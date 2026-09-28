import React, { useMemo } from "react";

import { useFlowContext } from "../../../providers/FlowProvider";
import { buildSaveableLiveOutputs } from "../../../utils/saveOutputDataset";
import { DatasetDetailModal } from "./DatasetDetailModal";
import { DatasetDetailsProvider, type DatasetDetailsRequest } from "./DatasetDetailsProvider";

/**
 * The dataset details modal with a dataflow behind it.
 *
 * Mounted only while open, so the live outputs are gathered when someone is
 * looking rather than on every change to the canvas.
 */
const CanvasDatasetDetailModal: React.FC<{
  request: DatasetDetailsRequest;
  onClose: () => void;
}> = ({ request, onClose }) => {
  const { projectId, projectDirty, outputs, nodes, defaultSaveOutputDataset } = useFlowContext();
  const liveOutputs = useMemo(
    () => buildSaveableLiveOutputs(outputs, nodes, defaultSaveOutputDataset),
    // Captured once per opening: a new array each render would refetch the
    // dataset on every canvas update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [request.datasetId],
  );
  return (
    <DatasetDetailModal
      canvasAvailable
      unsavedChanges={projectDirty}
      datasetId={request.datasetId}
      dataflowId={projectId}
      liveOutputs={liveOutputs}
      fallbackDataset={request.fallbackDataset ?? null}
      inAllProjects={request.inAllProjects}
      onClose={onClose}
    />
  );
};

/** `DatasetDetailsProvider` for the canvas: lineage read from the live graph,
 *  unsaved outputs included, and a link out of the dataflow asks first. */
export const CanvasDatasetDetailsProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => (
  <DatasetDetailsProvider
    renderModal={(request, close) => (
      <CanvasDatasetDetailModal key={request.datasetId} request={request} onClose={close} />
    )}
  >
    {children}
  </DatasetDetailsProvider>
);

export default CanvasDatasetDetailsProvider;
