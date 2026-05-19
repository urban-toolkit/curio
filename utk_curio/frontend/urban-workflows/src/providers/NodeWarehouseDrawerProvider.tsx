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
import { NodeWarehouseDrawer } from "../components/packs/NodeWarehouseDrawer";

/** Panel slide duration — keep in sync with `.drawer` in NodeWarehouseDrawer.module.css */
const DRAWER_MOTION_MS = 300;

type NodeWarehouseDrawerContextValue = {
  openNodeWarehouseDrawer: () => void;
  closeNodeWarehouseDrawer: () => void;
  isNodeWarehouseDrawerOpen: boolean;
};

const NodeWarehouseDrawerContext = createContext<NodeWarehouseDrawerContextValue | null>(null);

function subscribeReducedMotion(onStoreChange: () => void): () => void {
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  mq.addEventListener("change", onStoreChange);
  return () => mq.removeEventListener("change", onStoreChange);
}

function getReducedMotionSnapshot(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function NodeWarehouseDrawerProvider({ children }: { children: React.ReactNode }) {
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

  const closeNodeWarehouseDrawer = useCallback(() => {
    clearExitTimer();
    setPresented(false);
    exitTimerRef.current = window.setTimeout(
      finishClose,
      prefersReducedMotion ? 0 : DRAWER_MOTION_MS + 80,
    );
  }, [clearExitTimer, finishClose, prefersReducedMotion]);

  const openNodeWarehouseDrawer = useCallback(() => {
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
      openNodeWarehouseDrawer,
      closeNodeWarehouseDrawer,
      isNodeWarehouseDrawerOpen: mounted,
    }),
    [closeNodeWarehouseDrawer, mounted, openNodeWarehouseDrawer],
  );

  const drawer = mounted
    ? createPortal(
        <NodeWarehouseDrawer
          presented={presented}
          onRequestClose={closeNodeWarehouseDrawer}
          onExitComplete={finishClose}
        />,
        document.body,
      )
    : null;

  return (
    <NodeWarehouseDrawerContext.Provider value={ctx}>
      {children}
      {drawer}
    </NodeWarehouseDrawerContext.Provider>
  );
}

export function useNodeWarehouseDrawer(): NodeWarehouseDrawerContextValue {
  const v = useContext(NodeWarehouseDrawerContext);
  if (!v) {
    throw new Error("useNodeWarehouseDrawer must be used within NodeWarehouseDrawerProvider");
  }
  return v;
}
