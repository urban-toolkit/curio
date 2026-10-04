import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
} from "react";
import { createPortal } from "react-dom";
import { ScenarioCatalogDrawer } from "../../components/scenarios/catalog";
import { useSlideDrawerPresentation } from "../../hook/useSlideDrawerPresentation";

type ScenarioCatalogDrawerContextValue = {
  openScenarioCatalogDrawer: () => void;
  closeScenarioCatalogDrawer: () => void;
  isScenarioCatalogDrawerOpen: boolean;
};

const ScenarioCatalogDrawerContext = createContext<ScenarioCatalogDrawerContextValue | null>(null);

/**
 * Mounts the canvas Scenario Catalog drawer and exposes open/close controls,
 * shaped like `ModelCatalogDrawerProvider`: the same two-phase slide, the same
 * scroll lock, and the drawer unmounted once its exit slide ends.
 */
export function ScenarioCatalogDrawerProvider({ children }: { children: React.ReactNode }) {
  const {
    mounted,
    presented,
    open: openScenarioCatalogDrawer,
    close: closeScenarioCatalogDrawer,
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
      openScenarioCatalogDrawer,
      closeScenarioCatalogDrawer,
      isScenarioCatalogDrawerOpen: mounted,
    }),
    [closeScenarioCatalogDrawer, openScenarioCatalogDrawer, mounted],
  );

  const drawer = mounted
    ? createPortal(
        <ScenarioCatalogDrawer
          presented={presented}
          onRequestClose={closeScenarioCatalogDrawer}
          onExitComplete={finishClose}
        />,
        document.body,
      )
    : null;

  return (
    <ScenarioCatalogDrawerContext.Provider value={ctx}>
      {children}
      {drawer}
    </ScenarioCatalogDrawerContext.Provider>
  );
}

export function useScenarioCatalogDrawer(): ScenarioCatalogDrawerContextValue {
  const value = useContext(ScenarioCatalogDrawerContext);
  if (!value) {
    throw new Error("useScenarioCatalogDrawer must be used within ScenarioCatalogDrawerProvider");
  }
  return value;
}
