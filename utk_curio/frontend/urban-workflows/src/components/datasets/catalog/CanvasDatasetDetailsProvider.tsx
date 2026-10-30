import React, { useMemo } from "react";

import { useFlowContext } from "../../../providers/FlowProvider";
import { useAgentsDataflowId } from "../../../providers/agents/useAgentsDataflowId";
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
  const { projectDirty, whenChangesKept, outputs, nodes, defaultSaveOutputDataset } = useFlowContext();
  // The dataflow the details read, as the palette and the drawer list it
  // (`useAgentsDataflowId`): on an invited editor's canvas, the one its route
  // opened, so one of its datasets opens and previews.
  const dataflowId = useAgentsDataflowId();
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
      whenChangesKept={whenChangesKept}
      datasetId={request.datasetId}
      dataflowId={dataflowId}
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
