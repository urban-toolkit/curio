import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { ModelCatalogDrawer } from "../../components/models/catalog";
import { useSlideDrawerPresentation } from "../../hook/useSlideDrawerPresentation";
import type { PackageAddRequest } from "../../services/packages/packageAddRequests";

type OpenModelCatalogDrawerOptions = {
  /** The Add of a model the dataflow lacks, from a drop with the drawer
   *  closed (a row of the Tools panel's Models dropdown): the drawer runs it
   *  once open, as it runs a drop of its own cards. */
  addRequest?: PackageAddRequest;
};

type ModelCatalogDrawerContextValue = {
  openModelCatalogDrawer: (options?: OpenModelCatalogDrawerOptions) => void;
  closeModelCatalogDrawer: () => void;
  isModelCatalogDrawerOpen: boolean;
};

const ModelCatalogDrawerContext = createContext<ModelCatalogDrawerContextValue | null>(null);

/**
 * Mounts the canvas Model Catalog drawer and exposes open/close controls,
 * shaped like `DatasetCatalogDrawerProvider`: the same two-phase slide, the
 * same scroll lock, and the drawer unmounted once its exit slide ends. A drop
 * that opens it hands it its Add, as `NodeCatalogDrawerProvider` hands its
 * drawer a search.
 */
export function ModelCatalogDrawerProvider({ children }: { children: React.ReactNode }) {
  const {
    mounted,
    presented,
    open: present,
    close: closeModelCatalogDrawer,
    finishExit,
  } = useSlideDrawerPresentation();

  // The drop's Add is this drawer's own payload, so it stays here, and it
  // goes with the drawer: a drawer opened later runs no Add it was not given.
  const [addRequest, setAddRequest] = useState<PackageAddRequest | null>(null);

  const openModelCatalogDrawer = useCallback(
    (options?: OpenModelCatalogDrawerOptions) => {
      setAddRequest(options?.addRequest ?? null);
      present();
    },
    [present],
  );

  const finishClose = useCallback(() => {
    setAddRequest(null);
    finishExit();
  }, [finishExit]);

  // Gated on `mounted`, like its peers: `presented` goes false a frame into
  // the exit slide, and releasing the lock then let the page jump behind it.
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
      openModelCatalogDrawer,
      closeModelCatalogDrawer,
      isModelCatalogDrawerOpen: mounted,
    }),
    [closeModelCatalogDrawer, openModelCatalogDrawer, mounted],
  );

  const drawer = mounted
    ? createPortal(
        <ModelCatalogDrawer
          presented={presented}
          addRequest={addRequest}
          onRequestClose={closeModelCatalogDrawer}
          onExitComplete={finishClose}
        />,
        document.body,
      )
    : null;

  return (
    <ModelCatalogDrawerContext.Provider value={ctx}>
      {children}
      {drawer}
    </ModelCatalogDrawerContext.Provider>
  );
}

export function useModelCatalogDrawer(): ModelCatalogDrawerContextValue {
  const value = useContext(ModelCatalogDrawerContext);
  if (!value) {
    throw new Error("useModelCatalogDrawer must be used within ModelCatalogDrawerProvider");
  }
  return value;
}
