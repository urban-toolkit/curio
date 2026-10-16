import React, { createContext, useContext, useMemo, useState } from "react";

/**
 * What the canvas shows of its scenarios (#662) and never saves: the scenario
 * pointed at in the Scenario Catalog drawer's In project tab, whose fixed
 * context the canvas marks. `ScenarioUiProvider` holds it in
 * `DataflowProviders`, above both the drawer, which sets it, and the canvas,
 * which reads it.
 */
export interface ScenarioUi {
  highlighted: string | null;
  setHighlighted: (id: string | null) => void;
}

export const ScenarioUiContext = createContext<ScenarioUi>({
  highlighted: null,
  setHighlighted: () => {},
});

export const useScenarioUi = () => useContext(ScenarioUiContext);

/** Holds the scenario pointed at. Its own component, so a change re-renders
 *  only what reads it, not every provider around the dataflow. */
export function ScenarioUiProvider({ children }: { children: React.ReactNode }) {
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const value = useMemo<ScenarioUi>(() => ({ highlighted, setHighlighted }), [highlighted]);
  return <ScenarioUiContext.Provider value={value}>{children}</ScenarioUiContext.Provider>;
}
