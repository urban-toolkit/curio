import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { createPortal } from "react-dom";
import { DatasetCatalogDrawer } from "../../components/datasets/catalog";
import { useAgentsDataflowId } from "../agents/useAgentsDataflowId";
import { useCollab } from "../CollaborationProvider";
import { canvasRole } from "../collab/participants";
import { useFlowContext } from "../FlowProvider";
import { useToastContext } from "../ToastProvider";
import { prefetchDatasetCatalog } from "../../services/datasetCatalog";
import {
  EDITOR_REQUESTS_CHANGED_EVENT,
  loadEditorRequests,
  openRequestsReview,
  requestCatalog,
  requestsToldText,
  type EditorRequest,
} from "../../services/editorRequests";
import { isStandaloneDashboard } from "../../standalone/dashboardPayload";
import { useSlideDrawerPresentation } from "../../hook/useSlideDrawerPresentation";

type DatasetCatalogDrawerContextValue = {
  openDatasetCatalogDrawer: () => void;
  closeDatasetCatalogDrawer: () => void;
  isDatasetCatalogDrawerOpen: boolean;
};

const DatasetCatalogDrawerContext = createContext<DatasetCatalogDrawerContextValue | null>(null);

export function DatasetCatalogDrawerProvider({ children }: { children: React.ReactNode }) {
  // The dataflow both surfaces list (`useAgentsDataflowId`).
  const dataflowId = useAgentsDataflowId();
  const {
    mounted,
    presented,
    open: openDatasetCatalogDrawer,
    close: closeDatasetCatalogDrawer,
    finishExit: finishClose,
  } = useSlideDrawerPresentation();

  // Warm the catalog cache at startup so both surfaces are ready before the
  // user interacts with them: the drawer default query (includeHub) and the
  // dataset palette query (no hub) that drives the trigger counter.
  useEffect(() => {
    if (!dataflowId) return;
    // A standalone dashboard shows neither surface: there is no drawer to open
    // and no palette to count. Warming a cache nothing reads would be two
    // requests from a page whose whole claim is that it makes none.
    if (isStandaloneDashboard()) return;
    prefetchDatasetCatalog({
      dataflowId,
      includeHub: true,
      sort: "recent",
    });
    prefetchDatasetCatalog({
      dataflowId,
      includeHub: false,
      sort: "recent",
    });
  }, [dataflowId]);

  // What the dataflow's editors asked its owner to add (`editorRequests.ts`),
  // datasets and packages, which each catalog drawer shows and a node a
  // request names marks: read for the owner's canvas and an editor's, and
  // again each time the room says they changed. The owner is told of each
  // request she was not told of yet, with a way to review it in the drawer
  // of its kind: this one for a dataset, the Node or Model Catalog's for a
  // package (`openRequestsReview`).
  const { viewerMode } = useFlowContext();
  const collab = useCollab();
  const role = canvasRole(viewerMode, collab);
  const viewer = role === "watcher" ? null : role;
  const { onRemote } = collab;
  const { showToast } = useToastContext();
  const tell = useRef({ showToast, open: openDatasetCatalogDrawer });
  tell.current = { showToast, open: openDatasetCatalogDrawer };
  const told = useRef<{ dataflowId: string | null; ids: Set<string> }>({ dataflowId: null, ids: new Set() });
  useEffect(() => {
    if (isStandaloneDashboard()) return;
    const tellTheOwner = (requests: EditorRequest[]) => {
      if (viewer !== "owner" || !dataflowId) return;
      if (told.current.dataflowId !== dataflowId) told.current = { dataflowId, ids: new Set() };
      const fresh = requests.filter((request) => !told.current.ids.has(request.proposalId));
      for (const request of requests) told.current.ids.add(request.proposalId);
      if (fresh.length === 0) return;
      const catalog = requestCatalog(fresh[0]);
      tell.current.showToast(requestsToldText(fresh), "info", {
        action: {
          label: "Review",
          onClick: () => (catalog === "datasets" ? tell.current.open() : openRequestsReview(catalog)),
        },
      });
    };
    const load = () => void loadEditorRequests(dataflowId, viewer).then(tellTheOwner);
    load();
    if (!dataflowId || !viewer || typeof onRemote !== "function") return;
    return onRemote(EDITOR_REQUESTS_CHANGED_EVENT, load);
  }, [dataflowId, viewer, onRemote]);

  // Gated on `mounted`, like its two peers: `presented` goes false a frame
  // into the exit slide, which released the lock while the drawer was still
  // visibly on screen and let the page jump behind it.
  useEffect(() => {
    if (!mounted) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [mounted]);

  const ctx = useMemo(
    () => ({
      openDatasetCatalogDrawer,
      closeDatasetCatalogDrawer,
      isDatasetCatalogDrawerOpen: mounted,
    }),
    [closeDatasetCatalogDrawer, openDatasetCatalogDrawer, mounted],
  );

  const drawer = mounted
    ? createPortal(
        <DatasetCatalogDrawer
          presented={presented}
          onRequestClose={closeDatasetCatalogDrawer}
          onExitComplete={finishClose}
        />,
        document.body,
      )
    : null;

  return (
    <DatasetCatalogDrawerContext.Provider value={ctx}>
      {children}
      {drawer}
    </DatasetCatalogDrawerContext.Provider>
  );
}

export function useDatasetCatalogDrawer(): DatasetCatalogDrawerContextValue {
  const value = useContext(DatasetCatalogDrawerContext);
  if (!value) {
    throw new Error("useDatasetCatalogDrawer must be used within DatasetCatalogDrawerProvider");
  }
  return value;
}
