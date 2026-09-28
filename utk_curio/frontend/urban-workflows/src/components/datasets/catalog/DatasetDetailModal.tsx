import React, { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import ModalShell from "../../ModalShell";
import { LEAVE_DATAFLOW, useLeaveGuard } from "../../../hook/useLeaveGuard";
import { DatasetCatalogItem, datasetCatalogApi, type DatasetCatalogQuery } from "../../../services/datasetCatalog";
import { DatasetDetailPanel } from "./DatasetDetailPanel";

export interface DatasetDetailModalProps {
  datasetId: string;
  dataflowId?: string | null;
  liveOutputs?: DatasetCatalogQuery["liveOutputs"];
  fallbackDataset?: DatasetCatalogItem | null;
  initialTab?: "Overview" | "Schema" | "Table Preview" | "Lineage";
  /** Set only by the in-canvas drawer; see DatasetDetailPanel. */
  canvasAvailable?: boolean;
  /** The dataflow behind the modal has changes not yet saved, so a link that
   *  leaves it asks first. Set only by the in-canvas drawer. */
  unsavedChanges?: boolean;
  /** In the account's "all projects" list. Left out, the modal reads the
   *  list itself. */
  inAllProjects?: boolean;
  onClose: () => void;
}

function samePath(a: string, b: string): boolean {
  const decode = (p: string) => {
    try {
      return decodeURIComponent(p);
    } catch {
      return p;
    }
  };
  return decode(a) === decode(b);
}

export const DatasetDetailModal: React.FC<DatasetDetailModalProps> = ({
  datasetId,
  dataflowId = null,
  liveOutputs,
  fallbackDataset = null,
  initialTab = "Overview",
  canvasAvailable = false,
  unsavedChanges = false,
  inAllProjects,
  onClose,
}) => {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { leave, dialog: leaveDialog } = useLeaveGuard(unsavedChanges, LEAVE_DATAFLOW, {
    layer: "overlay",
  });
  const [dataset, setDataset] = useState<DatasetCatalogItem | null>(fallbackDataset);
  const [loading, setLoading] = useState(!fallbackDataset);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(!fallbackDataset);
    setError(null);
    if (fallbackDataset) setDataset(fallbackDataset);
    void datasetCatalogApi
      .getDataset(datasetId, { dataflowId, liveOutputs })
      .then((item) => {
        if (!cancelled) setDataset(item);
      })
      .catch((err) => {
        if (cancelled) return;
        // An id nothing answers to, typically a stale link: the panel's own
        // "Dataset not found." says that better than the server's 404 text.
        if ((err as { status?: number } | null)?.status === 404 && !fallbackDataset) {
          setDataset(null);
          return;
        }
        setError((err as Error)?.message || "Could not load dataset.");
        if (fallbackDataset) setDataset(fallbackDataset);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dataflowId, datasetId, liveOutputs, reloadToken]);

  // The Data Catalog page holds the account's "all projects" list and passes
  // it; everywhere else the modal asks, as the Node details modal does.
  const [fetchedInAllProjects, setFetchedInAllProjects] = useState<boolean | undefined>();
  useEffect(() => {
    if (inAllProjects !== undefined) return;
    let cancelled = false;
    void datasetCatalogApi
      .listDatasetDefaults()
      .then((resp) => {
        if (!cancelled) setFetchedInAllProjects(resp.datasets.includes(datasetId));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [inAllProjects, datasetId]);

  // A link in the details (the portal a download came from, a dataflow that
  // uses the dataset) opens a page, so the modal closes on the way. A plain
  // `<Link>` left it open: on that portal's own page it stayed over the
  // results and the navigation cleared their search. A link to the page
  // already open now only closes. Leaving a dataflow with unsaved changes asks
  // first, as the top menu's exits do, because `beforeunload` does not fire on
  // an in-app navigation.
  const followLink = (to: string) => {
    if (samePath(to, pathname)) {
      onClose();
      return;
    }
    leave(() => {
      onClose();
      navigate(to);
    });
  };

  return (
    <ModalShell onClose={onClose} size="xlarge" layer="overlay" label="Dataset details">
      <DatasetDetailPanel
        dataset={dataset}
        loading={loading}
        error={error}
        canvasAvailable={canvasAvailable}
        dataflowId={dataflowId}
        liveOutputs={liveOutputs}
        initialTab={initialTab}
        onMutated={() => setReloadToken((token) => token + 1)}
        onFollowLink={followLink}
        inAllProjects={inAllProjects ?? fetchedInAllProjects}
      />
      {leaveDialog}
    </ModalShell>
  );
};
