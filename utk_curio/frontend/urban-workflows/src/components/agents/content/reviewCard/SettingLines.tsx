import React from "react";

import styles from "../AgentReviewCard.module.css";

/** A settings change's lines (`node.settings.write`), one per change, each
 * in its node's own words, where another card shows its preview. */
export const SettingLines: React.FC<{ lines: string[] }> = ({ lines }) => (
  <div className={styles.preview} data-setting-lines="true">
    {lines.map((line, index) => (
      <div key={index}>{line}</div>
    ))}
  </div>
);
