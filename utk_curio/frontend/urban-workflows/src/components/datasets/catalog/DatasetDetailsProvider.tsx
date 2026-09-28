import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import { DatasetDetailModal } from "./DatasetDetailModal";
import {
  DatasetDetailsContext,
  type DatasetDetailsRequest,
  type OpenDatasetDetailsOptions,
} from "./datasetDetailsContext";

export type { DatasetDetailsRequest, OpenDatasetDetailsOptions } from "./datasetDetailsContext";

/**
 * The one place a dataset's details open from, whatever asked.
 *
 * A card, a drawer, a lake row, a palette row, a Dataset Finder row and a toast
 * all open the same `DatasetDetailModal`, and most of them have no natural
 * owner for it: a toast outlives the call that raised it, and a palette row is
 * one of hundreds. So the modal lives here, once per context. The app root
 * mounts this for the catalog pages; the canvas mounts
 * `CanvasDatasetDetailsProvider`, which renders the same modal with the
 * dataflow behind it.
 */
/** Closes the open modal when the page under it changes. Its own component so
 *  only the provider that asks for it needs a router. */
const CloseOnNavigate: React.FC<{ onNavigate: () => void }> = ({ onNavigate }) => {
  const { pathname } = useLocation();
  const first = useRef(pathname);
  useEffect(() => {
    if (pathname !== first.current) onNavigate();
  }, [pathname, onNavigate]);
  return null;
};

export const DatasetDetailsProvider: React.FC<{
  children: React.ReactNode;
  /** How to render the open modal; the canvas adds its dataflow context. */
  renderModal?: (request: DatasetDetailsRequest, close: () => void) => React.ReactNode;
  /** Close when the route changes. The app root sits above every page, so a
   *  modal opened from one page must not survive onto the next the way it
   *  would not have when each page owned its own. */
  closeOnNavigate?: boolean;
}> = ({ children, renderModal, closeOnNavigate = false }) => {
  const [request, setRequest] = useState<DatasetDetailsRequest | null>(null);
  const requestRef = useRef(request);
  requestRef.current = request;

  const openDatasetDetails = useCallback(
    (datasetId: string, options: OpenDatasetDetailsOptions = {}) => {
      setRequest({ datasetId, ...options });
    },
    [],
  );

  const close = useCallback(() => {
    const onClose = requestRef.current?.onClose;
    setRequest(null);
    onClose?.();
  }, []);

  const value = useMemo(() => ({ openDatasetDetails }), [openDatasetDetails]);

  return (
    <DatasetDetailsContext.Provider value={value}>
      {children}
      {request && closeOnNavigate ? <CloseOnNavigate onNavigate={close} /> : null}
      {request
        ? renderModal
          ? renderModal(request, close)
          : (
            <DatasetDetailModal
              key={request.datasetId}
              datasetId={request.datasetId}
              fallbackDataset={request.fallbackDataset ?? null}
              inAllProjects={request.inAllProjects}
              onClose={close}
            />
          )
        : null}
    </DatasetDetailsContext.Provider>
  );
};

export default DatasetDetailsProvider;
