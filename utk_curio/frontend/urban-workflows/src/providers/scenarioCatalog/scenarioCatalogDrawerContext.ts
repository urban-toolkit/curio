import { createContext, useContext } from "react";

import type { DrawerTab } from "../../services/packages";

/**
 * The canvas Scenario Catalog drawer's controls, apart from the provider that
 * mounts the drawer: the scenario commands open it (`useScenarioActions`), and
 * they run inside it too, so they reach it here rather than through the
 * provider's module, which imports the drawer.
 */

export interface OpenScenarioCatalogDrawerOptions {
  /** The tab to show: "installed" for In project, this dataflow's
   *  scenarios. Browse all otherwise. */
  tab?: DrawerTab;
}

export type ScenarioCatalogDrawerContextValue = {
  openScenarioCatalogDrawer: (options?: OpenScenarioCatalogDrawerOptions) => void;
  closeScenarioCatalogDrawer: () => void;
  isScenarioCatalogDrawerOpen: boolean;
};

export const ScenarioCatalogDrawerContext = createContext<ScenarioCatalogDrawerContextValue | null>(null);

export function useScenarioCatalogDrawer(): ScenarioCatalogDrawerContextValue {
  const value = useContext(ScenarioCatalogDrawerContext);
  if (!value) {
    throw new Error("useScenarioCatalogDrawer must be used within ScenarioCatalogDrawerProvider");
  }
  return value;
}
