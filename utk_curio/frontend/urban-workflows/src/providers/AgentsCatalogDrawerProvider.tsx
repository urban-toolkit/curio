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
import { AgentsCatalogDrawer } from "../components/agents/catalog/AgentsCatalogDrawer";
import styles from "./AgentsCatalogDrawerProvider.module.css";

/**
 * Mounts the Agents Catalog drawer and exposes open/close controls, mirroring
 * ``NodeCatalogDrawerProvider``. Must sit INSIDE ``FlowProvider`` — the drawer
 * reads ``useFlowContext().projectId`` to scope Install/Uninstall to the open
 * project. Rendered via a portal so it overlays the canvas.
 */

type AgentsCatalogDrawerContextValue = {
  openAgentsCatalogDrawer: () => void;
  closeAgentsCatalogDrawer: () => void;
  isAgentsCatalogDrawerOpen: boolean;
};

const AgentsCatalogDrawerContext = createContext<AgentsCatalogDrawerContextValue | null>(null);

export function AgentsCatalogDrawerProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const { projectId } = useFlowContext();

  const closeAgentsCatalogDrawer = useCallback(() => setOpen(false), []);
  const openAgentsCatalogDrawer = useCallback(() => setOpen(true), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const ctx = useMemo(
    () => ({ openAgentsCatalogDrawer, closeAgentsCatalogDrawer, isAgentsCatalogDrawerOpen: open }),
    [openAgentsCatalogDrawer, closeAgentsCatalogDrawer, open],
  );

  return (
    <AgentsCatalogDrawerContext.Provider value={ctx}>
      {children}
      {open
        ? createPortal(
            <div className={styles.backdrop} onClick={closeAgentsCatalogDrawer}>
              <div className={styles.panel} onClick={(e) => e.stopPropagation()}>
                <AgentsCatalogDrawer
                  presented
                  projectId={projectId ?? null}
                  onClose={closeAgentsCatalogDrawer}
                />
              </div>
            </div>,
            document.body,
          )
        : null}
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
