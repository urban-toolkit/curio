import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { NodeWarehouseDrawer } from "../components/packs/NodeWarehouseDrawer";

type NodeWarehouseDrawerContextValue = {
  openNodeWarehouseDrawer: () => void;
  closeNodeWarehouseDrawer: () => void;
  isNodeWarehouseDrawerOpen: boolean;
};

const NodeWarehouseDrawerContext = createContext<NodeWarehouseDrawerContextValue | null>(null);

export function NodeWarehouseDrawerProvider({ children }: { children: React.ReactNode }) {
  const [visible, setVisible] = useState(false);
  const preOpenFocusRef = useRef<HTMLElement | null>(null);

  const closeNodeWarehouseDrawer = useCallback(() => {
    setVisible(false);
    const el = preOpenFocusRef.current;
    preOpenFocusRef.current = null;
    queueMicrotask(() => el?.focus?.());
  }, []);

  const openNodeWarehouseDrawer = useCallback(() => {
    preOpenFocusRef.current = document.activeElement as HTMLElement | null;
    setVisible(true);
  }, []);

  useEffect(() => {
    if (!visible) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [visible]);

  const ctx = useMemo(
    () => ({
      openNodeWarehouseDrawer,
      closeNodeWarehouseDrawer,
      isNodeWarehouseDrawerOpen: visible,
    }),
    [closeNodeWarehouseDrawer, openNodeWarehouseDrawer, visible],
  );

  const drawer = visible
    ? createPortal(
        <NodeWarehouseDrawer onRequestClose={closeNodeWarehouseDrawer} />,
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
