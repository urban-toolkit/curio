import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useSlideDrawerPresentation } from "../hook/useSlideDrawerPresentation";
import { ProvenanceDrawer, type ProvenanceTarget } from "../components/provenance/ProvenanceDrawer";
import type { HistoryView } from "../components/provenance/ProvenanceHistory";
import { type NodeProvenanceTarget, ProvenanceDrawerContext } from "./provenanceDrawerContext";

export { useProvenanceDrawerOptional } from "./provenanceDrawerContext";

/**
 * Mounts the provenance drawer on the canvas, shaped like the catalog drawer
 * providers: the dataflow's versions from View > Provenance, or a node's runs
 * from its Provenance pill. It keeps the List or Graph the user picked last
 * while the page is open, so the drawer opens on it again.
 */
export function ProvenanceDrawerProvider({ children }: { children: React.ReactNode }) {
  const { mounted, presented, open, close, finishExit } = useSlideDrawerPresentation();
  const [target, setTarget] = useState<ProvenanceTarget>({ kind: "dataflow" });
  const [view, setView] = useState<HistoryView>("list");

  useEffect(() => {
    if (!mounted) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [mounted]);

  const openDataflowProvenance = useCallback(() => {
    setTarget({ kind: "dataflow" });
    open();
  }, [open]);

  const openNodeProvenance = useCallback(
    (node: NodeProvenanceTarget) => {
      setTarget({ kind: "node", ...node });
      open();
    },
    [open],
  );

  const ctx = useMemo(
    () => ({ openDataflowProvenance, openNodeProvenance, closeProvenance: close, isProvenanceOpen: mounted }),
    [openDataflowProvenance, openNodeProvenance, close, mounted],
  );

  const drawer = mounted
    ? createPortal(
        <ProvenanceDrawer
          presented={presented}
          onRequestClose={close}
          onExitComplete={finishExit}
          target={target}
          view={view}
          onViewChange={setView}
        />,
        document.body,
      )
    : null;

  return (
    <ProvenanceDrawerContext.Provider value={ctx}>
      {children}
      {drawer}
    </ProvenanceDrawerContext.Provider>
  );
}
