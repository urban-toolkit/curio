import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
} from "react";
import { createPortal } from "react-dom";
import { ModelCatalogDrawer } from "../../components/models/catalog";
import { useSlideDrawerPresentation } from "../../hook/useSlideDrawerPresentation";

type ModelCatalogDrawerContextValue = {
  openModelCatalogDrawer: () => void;
  closeModelCatalogDrawer: () => void;
  isModelCatalogDrawerOpen: boolean;
};

const ModelCatalogDrawerContext = createContext<ModelCatalogDrawerContextValue | null>(null);

/**
 * Mounts the canvas Model Catalog drawer and exposes open/close controls,
 * shaped like `DatasetCatalogDrawerProvider`: the same two-phase slide, the
 * same scroll lock, and the drawer unmounted once its exit slide ends.
 */
export function ModelCatalogDrawerProvider({ children }: { children: React.ReactNode }) {
  const {
    mounted,
    presented,
    open: openModelCatalogDrawer,
    close: closeModelCatalogDrawer,
    finishExit: finishClose,
  } = useSlideDrawerPresentation();

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
