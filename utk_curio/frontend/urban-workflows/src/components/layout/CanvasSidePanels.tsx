import React from "react";

import styles from "./CanvasSidePanels.module.css";

/**
 * The canvas's right edge, under the top bar: the collaboration panel, open by
 * default under `--collab`, and under it the Scenarios panel, opened from View.
 * One column places both, so neither covers the other, and each scrolls within
 * its share of the height. Alone, either sits at the top. API Settings, Monitor
 * and the catalog drawers open over the column.
 */
export function CanvasSidePanels({ children }: { children: React.ReactNode }) {
  return <div className={styles.dock}>{children}</div>;
}
