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
import { useFlowContext } from "./FlowProvider";
import { AgentsCatalogDrawer } from "../components/agents/catalog/AgentsCatalogDrawer";

/**
 * Mounts the Agents Catalog drawer and exposes open/close controls, mirroring
 * ``NodeCatalogDrawerProvider``'s two-phase presentation (memo dev/43): the
 * drawer mounts closed and slides in on the next frames; closing keeps it
 * mounted through the exit slide and unmounts on `onExitComplete` (with a
 * timer fallback), so open/close animate exactly like the Nodes and Datasets
 * drawers. Must sit INSIDE ``FlowProvider`` — the drawer reads
 * ``useFlowContext().projectId`` to scope Install/Uninstall to the open
 * project. Rendered via a portal so it overlays the canvas.
 */

/** Panel slide duration — keep in sync with `.panel` in AgentsCatalogDrawer.module.css */
const DRAWER_MOTION_MS = 300;

type AgentsCatalogDrawerContextValue = {
  openAgentsCatalogDrawer: () => void;
  closeAgentsCatalogDrawer: () => void;
  isAgentsCatalogDrawerOpen: boolean;
};

const AgentsCatalogDrawerContext = createContext<AgentsCatalogDrawerContextValue | null>(null);

// jsdom (tests) has no matchMedia — degrade to "no reduced motion".
function subscribeReducedMotion(onStoreChange: () => void): () => void {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  mq.addEventListener("change", onStoreChange);
  return () => mq.removeEventListener("change", onStoreChange);
}

function getReducedMotionSnapshot(): boolean {
  return typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;
}

export function AgentsCatalogDrawerProvider({ children }: { children: React.ReactNode }) {
  const prefersReducedMotion = useSyncExternalStore(
    subscribeReducedMotion,
    getReducedMotionSnapshot,
    () => false,
  );

  const [mounted, setMounted] = useState(false);
  const [presented, setPresented] = useState(false);
  // DEC-042: the roster header carries the Pin only — pinned blocks the
  // backdrop/Escape dismissals (programmatic close still works).
  const [pinned, setPinned] = useState(false);
  const { projectId } = useFlowContext();
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

  const closeAgentsCatalogDrawer = useCallback(() => {
    clearExitTimer();
    setPresented(false);
    exitTimerRef.current = window.setTimeout(
      finishClose,
      prefersReducedMotion ? 0 : DRAWER_MOTION_MS + 80,
    );
  }, [clearExitTimer, finishClose, prefersReducedMotion]);

  const openAgentsCatalogDrawer = useCallback(() => {
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
    if (!presented) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !pinned) closeAgentsCatalogDrawer();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [presented, pinned, closeAgentsCatalogDrawer]);

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
      openAgentsCatalogDrawer,
      closeAgentsCatalogDrawer,
      isAgentsCatalogDrawerOpen: mounted,
    }),
    [openAgentsCatalogDrawer, closeAgentsCatalogDrawer, mounted],
  );

  const drawer = mounted
    ? createPortal(
        <AgentsCatalogDrawer
          presented={presented}
          projectId={projectId ?? null}
          pinned={pinned}
          onPinToggle={() => setPinned((v) => !v)}
          onRequestClose={closeAgentsCatalogDrawer}
          onExitComplete={finishClose}
        />,
        document.body,
      )
    : null;

  return (
    <AgentsCatalogDrawerContext.Provider value={ctx}>
      {children}
      {drawer}
    </AgentsCatalogDrawerContext.Provider>
  );
}

export function useAgentsCatalogDrawerControls(): AgentsCatalogDrawerContextValue {
  const v = useContext(AgentsCatalogDrawerContext);
  if (!v) {
    throw new Error(
      "useAgentsCatalogDrawerControls must be used within AgentsCatalogDrawerProvider",
    );
  }
  return v;
}
