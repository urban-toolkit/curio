import { createContext, useContext } from "react";

/**
 * What the canvas shows of its scenarios (#662) and never saves: whether the
 * Scenarios panel is open, and which scenario it highlights, whose fixed
 * context the canvas marks. MainCanvas holds it; the top bar's Scenarios menu,
 * the panel and the canvas view read it.
 */
export interface ScenarioUi {
  panelOpen: boolean;
  setPanelOpen: (open: boolean) => void;
  highlighted: string | null;
  setHighlighted: (id: string | null) => void;
}

export const ScenarioUiContext = createContext<ScenarioUi>({
  panelOpen: false,
  setPanelOpen: () => {},
  highlighted: null,
  setHighlighted: () => {},
});

export const useScenarioUi = () => useContext(ScenarioUiContext);
