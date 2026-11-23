import React, { Suspense, createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useSlideDrawerPresentation } from "../hook/useSlideDrawerPresentation";
import type { MonitorTab } from "../pages/monitor/monitorTabs";

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
 * it never leaves the dataflow. Shaped like the catalog drawer providers, and
 * like API Settings' drawer it keeps its tab in its state, opening on Status.
 */
export function MonitorDrawerProvider({ children }: { children: React.ReactNode }) {
  const { mounted, presented, open, close, finishExit } = useSlideDrawerPresentation();
  const [tab, setTab] = useState<MonitorTab>("status");

  useEffect(() => {
    if (!mounted) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [mounted]);

  const openMonitor = useCallback(() => {
    setTab("status");
    open();
  }, [open]);

  const ctx = useMemo(
    () => ({ openMonitor, closeMonitor: close, isMonitorOpen: mounted }),
    [close, openMonitor, mounted],
  );

  const drawer = mounted
    ? createPortal(
        <Suspense fallback={null}>
          <MonitorDrawer
            presented={presented}
            tab={tab}
            onTabChange={setTab}
            onRequestClose={close}
            onExitComplete={finishExit}
          />
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
