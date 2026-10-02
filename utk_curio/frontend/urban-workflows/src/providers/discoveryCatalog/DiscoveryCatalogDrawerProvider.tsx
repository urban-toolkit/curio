import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
} from "react";
import { createPortal } from "react-dom";
import { DiscoveryCatalogDrawer } from "../../components/discovery/catalog";
import { useSlideDrawerPresentation } from "../../hook/useSlideDrawerPresentation";

type DiscoveryCatalogDrawerContextValue = {
  openDiscoveryCatalogDrawer: () => void;
  closeDiscoveryCatalogDrawer: () => void;
  isDiscoveryCatalogDrawerOpen: boolean;
};

const DiscoveryCatalogDrawerContext = createContext<DiscoveryCatalogDrawerContextValue | null>(null);

/**
 * Mounts the canvas Discovery Catalog drawer and exposes open/close controls,
 * shaped like `ModelCatalogDrawerProvider`: the same two-phase slide, the same
 * scroll lock, and the drawer unmounted once its exit slide ends.
 */
export function DiscoveryCatalogDrawerProvider({ children }: { children: React.ReactNode }) {
  const {
    mounted,
    presented,
    open: openDiscoveryCatalogDrawer,
    close: closeDiscoveryCatalogDrawer,
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
      openDiscoveryCatalogDrawer,
      closeDiscoveryCatalogDrawer,
      isDiscoveryCatalogDrawerOpen: mounted,
    }),
    [closeDiscoveryCatalogDrawer, openDiscoveryCatalogDrawer, mounted],
  );

  const drawer = mounted
    ? createPortal(
        <DiscoveryCatalogDrawer
          presented={presented}
          onRequestClose={closeDiscoveryCatalogDrawer}
          onExitComplete={finishClose}
        />,
        document.body,
      )
    : null;

  return (
    <DiscoveryCatalogDrawerContext.Provider value={ctx}>
      {children}
      {drawer}
    </DiscoveryCatalogDrawerContext.Provider>
  );
}

export function useDiscoveryCatalogDrawer(): DiscoveryCatalogDrawerContextValue {
  const value = useContext(DiscoveryCatalogDrawerContext);
  if (!value) {
    throw new Error("useDiscoveryCatalogDrawer must be used within DiscoveryCatalogDrawerProvider");
  }
  return value;
}
