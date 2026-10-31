import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { NodeCatalogDrawer } from "../../components/packages/publishing";
import { useSlideDrawerPresentation } from "../../hook/useSlideDrawerPresentation";
import { useOpensForRequests } from "../../services/editorRequests";

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

export function NodeCatalogDrawerProvider({ children }: { children: React.ReactNode }) {
  const {
    mounted,
    presented,
    open: present,
    close: closeNodeCatalogDrawer,
    finishExit: finishClose,
  } = useSlideDrawerPresentation();

  const [initialSearch, setInitialSearch] = useState("");

  // The search seed is this drawer's own payload, so it stays here: the
  // presentation hook knows about sliding and nothing else.
  const openNodeCatalogDrawer = useCallback(
    (options?: OpenNodeCatalogDrawerOptions) => {
      setInitialSearch(options?.search ?? "");
      present();
    },
    [present],
  );
  // The review of the packages the dataflow's editors asked its owner to add
  // waits in this drawer (`openRequestsReview`).
  const openForRequests = useCallback(() => openNodeCatalogDrawer(), [openNodeCatalogDrawer]);
  useOpensForRequests("node", openForRequests);

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
