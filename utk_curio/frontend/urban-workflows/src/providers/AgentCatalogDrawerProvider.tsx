import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useFlowContext } from "./FlowProvider";
import { AgentCatalogDrawer } from "../components/agents/catalog/AgentCatalogDrawer";
import { modalStackDepth } from "../components/ModalShell";
import { useSlideDrawerPresentation } from "../hook/useSlideDrawerPresentation";

/**
 * Mounts the Agent Catalog drawer and exposes open/close controls, mirroring
 * ``NodeCatalogDrawerProvider``'s two-phase presentation (memo dev/43): the
 * drawer mounts closed and slides in on the next frames; closing keeps it
 * mounted through the exit slide and unmounts on `onExitComplete` (with a
 * timer fallback), so open/close animate exactly like the Nodes and Datasets
 * drawers. Must sit INSIDE ``FlowProvider`` — the drawer reads
 * ``useFlowContext().projectId`` to scope Install/Uninstall to the open
 * project. Rendered via a portal so it overlays the canvas.
 */

type AgentCatalogDrawerContextValue = {
  openAgentCatalogDrawer: () => void;
  closeAgentCatalogDrawer: () => void;
  isAgentCatalogDrawerOpen: boolean;
};

const AgentCatalogDrawerContext = createContext<AgentCatalogDrawerContextValue | null>(null);

export function AgentCatalogDrawerProvider({ children }: { children: React.ReactNode }) {
  const {
    mounted,
    presented,
    open: openAgentCatalogDrawer,
    close: closeAgentCatalogDrawer,
    finishExit: finishClose,
  } = useSlideDrawerPresentation();

  // DEC-042: the roster header carries the Pin only — pinned blocks the
  // backdrop/Escape dismissals (programmatic close still works).
  const [pinned, setPinned] = useState(false);
  const { projectId, ensureProjectId } = useFlowContext();

  useEffect(() => {
    if (!presented) return;
    const onKey = (e: KeyboardEvent) => {
      // A modal rendered inside this drawer (AI Settings, agent import) owns
      // Escape while it is open. This listener was registered first, so the
      // modal cannot stop it from firing - it has to stand down itself.
      if (modalStackDepth() > 0) return;
      if (e.key === "Escape" && !pinned) closeAgentCatalogDrawer();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [presented, pinned, closeAgentCatalogDrawer]);

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
      openAgentCatalogDrawer,
      closeAgentCatalogDrawer,
      isAgentCatalogDrawerOpen: mounted,
    }),
    [openAgentCatalogDrawer, closeAgentCatalogDrawer, mounted],
  );

  const drawer = mounted
    ? createPortal(
        <AgentCatalogDrawer
          presented={presented}
          projectId={projectId ?? null}
          onEnsureProject={ensureProjectId}
          pinned={pinned}
          onPinToggle={() => setPinned((v) => !v)}
          onRequestClose={closeAgentCatalogDrawer}
          onExitComplete={finishClose}
        />,
        document.body,
      )
    : null;

  return (
    <AgentCatalogDrawerContext.Provider value={ctx}>
      {children}
      {drawer}
    </AgentCatalogDrawerContext.Provider>
  );
}

export function useAgentCatalogDrawerControls(): AgentCatalogDrawerContextValue {
  const v = useContext(AgentCatalogDrawerContext);
  if (!v) {
    throw new Error(
      "useAgentCatalogDrawerControls must be used within AgentCatalogDrawerProvider",
    );
  }
  return v;
}
