import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
} from "react";
import { createPortal } from "react-dom";
import { DatasetCatalogDrawer } from "../../components/datasets/catalog";
import { useFlowContext } from "../FlowProvider";
import { prefetchDatasetCatalog } from "../../services/datasetCatalog";
import { useSlideDrawerPresentation } from "../../hook/useSlideDrawerPresentation";

type DatasetCatalogDrawerContextValue = {
  openDatasetCatalogDrawer: () => void;
  closeDatasetCatalogDrawer: () => void;
  isDatasetCatalogDrawerOpen: boolean;
};

const DatasetCatalogDrawerContext = createContext<DatasetCatalogDrawerContextValue | null>(null);

export function DatasetCatalogDrawerProvider({ children }: { children: React.ReactNode }) {
  const { projectId } = useFlowContext();
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
    if (!projectId) return;
    prefetchDatasetCatalog({
      dataflowId: projectId,
      includeHub: true,
      sort: "recent",
    });
    prefetchDatasetCatalog({
      dataflowId: projectId,
      includeHub: false,
      sort: "recent",
    });
  }, [projectId]);

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
