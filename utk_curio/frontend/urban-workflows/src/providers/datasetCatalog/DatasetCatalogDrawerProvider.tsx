import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { createPortal } from "react-dom";
import { DatasetCatalogDrawer } from "../../components/datasets/catalog";

const DRAWER_MOTION_MS = 300;

type DatasetCatalogDrawerContextValue = {
  openDatasetCatalogDrawer: () => void;
  closeDatasetCatalogDrawer: () => void;
  isDatasetCatalogDrawerOpen: boolean;
};

const DatasetCatalogDrawerContext = createContext<DatasetCatalogDrawerContextValue | null>(null);

function subscribeReducedMotion(onStoreChange: () => void): () => void {
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  mq.addEventListener("change", onStoreChange);
  return () => mq.removeEventListener("change", onStoreChange);
}

function getReducedMotionSnapshot(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function DatasetCatalogDrawerProvider({ children }: { children: React.ReactNode }) {
  const prefersReducedMotion = useSyncExternalStore(
    subscribeReducedMotion,
    getReducedMotionSnapshot,
    () => false,
  );
  const [mounted, setMounted] = useState(false);
  const [presented, setPresented] = useState(false);
  const preOpenFocusRef = useRef<HTMLElement | null>(null);
  const exitTimerRef = useRef<number | null>(null);
  const exitSettledRef = useRef(false);

  const clearExitTimer = useCallback(() => {
    if (exitTimerRef.current != null) {
      window.clearTimeout(exitTimerRef.current);
      exitTimerRef.current = null;
    }
  }, []);

  const finishClose = useCallback(() => {
    if (exitSettledRef.current) return;
    exitSettledRef.current = true;
    clearExitTimer();
    setMounted(false);
    setPresented(false);
    const el = preOpenFocusRef.current;
    preOpenFocusRef.current = null;
    queueMicrotask(() => el?.focus?.());
  }, [clearExitTimer]);

  const closeDatasetCatalogDrawer = useCallback(() => {
    clearExitTimer();
    setPresented(false);
    exitTimerRef.current = window.setTimeout(
      finishClose,
      prefersReducedMotion ? 0 : DRAWER_MOTION_MS + 80,
    );
  }, [clearExitTimer, finishClose, prefersReducedMotion]);

  const openDatasetCatalogDrawer = useCallback(() => {
    clearExitTimer();
    exitSettledRef.current = false;
    preOpenFocusRef.current = document.activeElement as HTMLElement | null;
    setMounted(true);
    setPresented(false);
    if (prefersReducedMotion) {
      setPresented(true);
      return;
    }
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => setPresented(true));
    });
  }, [clearExitTimer, prefersReducedMotion]);

  useEffect(() => {
    if (!mounted) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [mounted]);

  useEffect(() => () => clearExitTimer(), [clearExitTimer]);

  const ctx = useMemo(
    () => ({
      openDatasetCatalogDrawer,
      closeDatasetCatalogDrawer,
      isDatasetCatalogDrawerOpen: mounted,
    }),
    [closeDatasetCatalogDrawer, mounted, openDatasetCatalogDrawer],
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
