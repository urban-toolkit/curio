import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { ScenarioCatalogDrawer } from "../../components/scenarios/catalog";
import { ScenarioDefinePanel } from "../../components/scenarios/define/ScenarioDefinePanel";
import { useScenarioUi } from "../../components/scenarios/scenarioUi";
import { useSlideDrawerPresentation } from "../../hook/useSlideDrawerPresentation";
import type { DrawerTab } from "../../services/packages";
import {
  ScenarioCatalogDrawerContext,
  type OpenScenarioCatalogDrawerOptions,
} from "./scenarioCatalogDrawerContext";

/**
 * Mounts the canvas Scenario Catalog drawer and exposes open/close controls,
 * shaped like `ModelCatalogDrawerProvider`: the same two-phase slide, the same
 * scroll lock, and the drawer unmounted once its exit slide ends. It holds the
 * drawer's tab, so a scenario command can open the drawer on In project, or
 * turn it to In project when it is open already.
 */
export function ScenarioCatalogDrawerProvider({ children }: { children: React.ReactNode }) {
  const {
    mounted,
    presented,
    open: present,
    close: closeScenarioCatalogDrawer,
    finishExit: finishClose,
  } = useSlideDrawerPresentation();
  const [tab, setTab] = useState<DrawerTab>("browse");
  // The define panel, beside the canvas rather than over it: a scenario
  // being made, or one whose context and outcomes are edited.
  const { define } = useScenarioUi();

  const openScenarioCatalogDrawer = useCallback(
    (options?: OpenScenarioCatalogDrawerOptions) => {
      setTab(options?.tab === "installed" ? "installed" : "browse");
      // Open already, it only turns to the tab: opening it again would slide
      // it out of view and in again.
      if (!presented) present();
    },
    [present, presented],
  );

  // Gated on `mounted`, like its peers: `presented` goes false a frame into
  // the exit slide, and releasing the lock then let the page jump behind it.
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
      openScenarioCatalogDrawer,
      closeScenarioCatalogDrawer,
      isScenarioCatalogDrawerOpen: mounted,
    }),
    [closeScenarioCatalogDrawer, openScenarioCatalogDrawer, mounted],
  );

  const drawer = mounted
    ? createPortal(
        <ScenarioCatalogDrawer
          presented={presented}
          tab={tab}
          onTabChange={setTab}
          onRequestClose={closeScenarioCatalogDrawer}
          onExitComplete={finishClose}
        />,
        document.body,
      )
    : null;

  return (
    <ScenarioCatalogDrawerContext.Provider value={ctx}>
      {children}
      {drawer}
      {define &&
        createPortal(
          <ScenarioDefinePanel
            key={define.mode === "edit" ? `edit-${define.scenarioId}` : `new-${define.nodes.join(",")}`}
            define={define}
          />,
          document.body,
        )}
    </ScenarioCatalogDrawerContext.Provider>
  );
}
