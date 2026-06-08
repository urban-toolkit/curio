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
import { useFlowContext } from "../FlowProvider";
import { prefetchDatasetCatalog } from "../../services/datasetCatalog";

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
  const { projectId } = useFlowContext();
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
    if (prefersReducedMotion) {
      setPresented(true);
      return;
    }
    setPresented(false);
    window.requestAnimationFrame(() => setPresented(true));
  }, [clearExitTimer, prefersReducedMotion]);

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

  useEffect(() => {
    if (!presented) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [presented]);

  useEffect(() => () => clearExitTimer(), [clearExitTimer]);

  const ctx = useMemo(
    () => ({
      openDatasetCatalogDrawer,
      closeDatasetCatalogDrawer,
      isDatasetCatalogDrawerOpen: presented,
    }),
    [closeDatasetCatalogDrawer, openDatasetCatalogDrawer, presented],
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
