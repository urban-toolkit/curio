import React from "react";

import styles from "./CanvasSidePanels.module.css";

/**
 * The canvas's right edge, under the top bar: the collaboration panel, open by
 * default under `--collab`. The dock places it and lets it scroll within the
 * window. A dataflow's scenarios are the Scenario Catalog drawer's In project
 * tab, not a panel here. API Settings, Monitor and the catalog drawers open
 * over the dock.
 */
export function CanvasSidePanels({ children }: { children: React.ReactNode }) {
  return <div className={styles.dock}>{children}</div>;
}
