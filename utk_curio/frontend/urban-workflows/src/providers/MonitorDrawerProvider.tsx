import React, { Suspense, createContext, useContext, useEffect, useMemo } from "react";
import { createPortal } from "react-dom";
import { useSlideDrawerPresentation } from "../hook/useSlideDrawerPresentation";

/** Loaded when first opened, with its charts. */
const MonitorDrawer = React.lazy(() => import("../pages/monitor/MonitorDrawer"));

type MonitorDrawerContextValue = {
  openMonitor: () => void;
  closeMonitor: () => void;
  isMonitorOpen: boolean;
};

const MonitorDrawerContext = createContext<MonitorDrawerContextValue | null>(null);

/**
 * Mounts the monitor as a drawer on the canvas and the dashboard, so checking
 * it never leaves the dataflow. Shaped like the catalog drawer providers.
 */
export function MonitorDrawerProvider({ children }: { children: React.ReactNode }) {
  const { mounted, presented, open, close, finishExit } = useSlideDrawerPresentation();

  useEffect(() => {
    if (!mounted) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [mounted]);

  const ctx = useMemo(
    () => ({ openMonitor: open, closeMonitor: close, isMonitorOpen: mounted }),
    [close, open, mounted],
  );

  const drawer = mounted
    ? createPortal(
        <Suspense fallback={null}>
          <MonitorDrawer presented={presented} onRequestClose={close} onExitComplete={finishExit} />
        </Suspense>,
        document.body,
      )
    : null;

  return (
    <MonitorDrawerContext.Provider value={ctx}>
      {children}
      {drawer}
    </MonitorDrawerContext.Provider>
  );
}

/** The drawer's controls on the canvas and the dashboard, or null on a page
 *  without one, where Monitor is the /monitor page. */
export function useMonitorDrawerOptional(): MonitorDrawerContextValue | null {
  return useContext(MonitorDrawerContext);
}
