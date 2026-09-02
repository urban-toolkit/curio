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
import { NodeCatalogDrawer } from "../components/packages/publishing";

/** Panel slide duration — keep in sync with `.drawer` in NodeCatalogDrawer.module.css */
const DRAWER_MOTION_MS = 300;

type OpenNodeCatalogDrawerOptions = {
  /** Seed the drawer's search box, so a caller can land the user on one
   *  package instead of the whole catalog. Used by the missing-package node
   *  card, which knows exactly which package it needs (#233). */
  search?: string;
};

type NodeCatalogDrawerContextValue = {
  openNodeCatalogDrawer: (options?: OpenNodeCatalogDrawerOptions) => void;
  closeNodeCatalogDrawer: () => void;
  isNodeCatalogDrawerOpen: boolean;
};

const NodeCatalogDrawerContext = createContext<NodeCatalogDrawerContextValue | null>(null);

function subscribeReducedMotion(onStoreChange: () => void): () => void {
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  mq.addEventListener("change", onStoreChange);
  return () => mq.removeEventListener("change", onStoreChange);
}

function getReducedMotionSnapshot(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function NodeCatalogDrawerProvider({ children }: { children: React.ReactNode }) {
  const prefersReducedMotion = useSyncExternalStore(
    subscribeReducedMotion,
    getReducedMotionSnapshot,
    () => false,
  );

  const [mounted, setMounted] = useState(false);
  const [presented, setPresented] = useState(false);
  const [initialSearch, setInitialSearch] = useState("");
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

  const closeNodeCatalogDrawer = useCallback(() => {
    clearExitTimer();
    setPresented(false);
    exitTimerRef.current = window.setTimeout(
      finishClose,
      prefersReducedMotion ? 0 : DRAWER_MOTION_MS + 80,
    );
  }, [clearExitTimer, finishClose, prefersReducedMotion]);

  const openNodeCatalogDrawer = useCallback((options?: OpenNodeCatalogDrawerOptions) => {
    clearExitTimer();
    exitSettledRef.current = false;
    setInitialSearch(options?.search ?? "");
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
      openNodeCatalogDrawer,
      closeNodeCatalogDrawer,
      isNodeCatalogDrawerOpen: mounted,
    }),
    [closeNodeCatalogDrawer, mounted, openNodeCatalogDrawer],
  );

  const drawer = mounted
    ? createPortal(
        <NodeCatalogDrawer
          initialSearch={initialSearch}
          presented={presented}
          onRequestClose={closeNodeCatalogDrawer}
          onExitComplete={finishClose}
        />,
        document.body,
      )
    : null;

  return (
    <NodeCatalogDrawerContext.Provider value={ctx}>
      {children}
      {drawer}
    </NodeCatalogDrawerContext.Provider>
  );
}

export function useNodeCatalogDrawer(): NodeCatalogDrawerContextValue {
  const v = useContext(NodeCatalogDrawerContext);
  if (!v) {
    throw new Error("useNodeCatalogDrawer must be used within NodeCatalogDrawerProvider");
  }
  return v;
}
