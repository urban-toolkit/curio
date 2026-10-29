import React, { createContext, useContext, useMemo, useState } from "react";

/**
 * What the canvas shows of its scenarios (#662) and never saves: the scenario
 * pointed at in the Scenario Catalog drawer's In project tab, whose context
 * and outcomes the canvas marks, and the scenario being defined in the define
 * panel, with the context and outcomes it holds (`preview`). `ScenarioUiProvider` holds it in
 * `DataflowProviders`, above both the drawer, which sets it, and the canvas,
 * which reads it.
 */
/**
 * A scenario being defined in the define panel: a new one from the nodes
 * selected, or an existing one edited, from its first step or from *step*
 * (Duplicate scenario opens its copy on Name & set).
 */
export type ScenarioDefine =
  | { mode: "new"; nodes?: string[] }
  | { mode: "edit"; scenarioId: string; step?: 1 | 2 | 3 };

/** The context and outcomes the define panel holds, which the canvas marks. */
export type ScenarioPreview = { context: string[]; outcomes: string[] };

export interface ScenarioUi {
  highlighted: string | null;
  setHighlighted: (id: string | null) => void;
  define: ScenarioDefine | null;
  setDefine: (define: ScenarioDefine | null) => void;
  preview: ScenarioPreview | null;
  setPreview: (preview: ScenarioPreview | null) => void;
}

export const ScenarioUiContext = createContext<ScenarioUi>({
  highlighted: null,
  setHighlighted: () => {},
  define: null,
  setDefine: () => {},
  preview: null,
  setPreview: () => {},
});

export const useScenarioUi = () => useContext(ScenarioUiContext);

/** Holds the scenario pointed at. Its own component, so a change re-renders
 *  only what reads it, not every provider around the dataflow. */
export function ScenarioUiProvider({ children }: { children: React.ReactNode }) {
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const [define, setDefine] = useState<ScenarioDefine | null>(null);
  const [preview, setPreview] = useState<ScenarioPreview | null>(null);
  const value = useMemo<ScenarioUi>(
    () => ({ highlighted, setHighlighted, define, setDefine, preview, setPreview }),
    [highlighted, define, preview],
  );
  return <ScenarioUiContext.Provider value={value}>{children}</ScenarioUiContext.Provider>;
}
