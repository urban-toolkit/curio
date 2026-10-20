import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useSlideDrawerPresentation } from "../hook/useSlideDrawerPresentation";
import { ProvenanceDrawer, type ProvenanceTarget } from "../components/provenance/ProvenanceDrawer";
import { ProvenanceDrawerContext } from "./provenanceDrawerContext";

export { useProvenanceDrawerOptional } from "./provenanceDrawerContext";

/**
 * Mounts the provenance drawer on the canvas, shaped like the catalog drawer
 * providers.
 */
export function ProvenanceDrawerProvider({ children }: { children: React.ReactNode }) {
  const { mounted, presented, open, close, finishExit } = useSlideDrawerPresentation();
  const [target, setTarget] = useState<ProvenanceTarget>({ kind: "dataflow" });

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

  const ctx = useMemo(
    () => ({ openDataflowProvenance, closeProvenance: close, isProvenanceOpen: mounted }),
    [openDataflowProvenance, close, mounted],
  );

  const drawer = mounted
    ? createPortal(
        <ProvenanceDrawer
          presented={presented}
          onRequestClose={close}
          onExitComplete={finishExit}
          target={target}
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
