import React from "react";

import { BUILDER_TEMPLATES } from "../../../../services/agents";
import styles from "../AgentBuilderStrip.module.css";

/** Planning templates seed the goal prompt through the caller's prefill rule. */
export const PlanningTemplates: React.FC<{ onComposePrompt: (prompt: string) => void }> = ({ onComposePrompt }) => (
  <div className={styles.templates} role="group" aria-label="Planning templates">
    {BUILDER_TEMPLATES.map((t) => (
      <button key={t.id} type="button" className={styles.templateChip} onClick={() => onComposePrompt(t.seed)}>
        {t.label}
      </button>
    ))}
  </div>
);
