import React from "react";

import { BUILDER_TEMPLATES } from "../../../../services/agents";
import styles from "../AgentBuilderStrip.module.css";

/** What a planning template does, on its tooltip. */
export const TEMPLATE_HINT = "Fills the message box. Nothing is sent until you press Send.";

/** Planning templates, in the Dataflow Builder's empty conversation: each
 *  seeds the message box through the caller's prefill rule, and nothing is
 *  sent until Send. */
export const PlanningTemplates: React.FC<{ onComposePrompt: (prompt: string) => void }> = ({ onComposePrompt }) => (
  <div className={styles.templates} role="group" aria-label="Planning templates">
    {BUILDER_TEMPLATES.map((t) => (
      <button
        key={t.id}
        type="button"
        className={styles.templateChip}
        data-tooltip={TEMPLATE_HINT}
        onClick={() => onComposePrompt(t.seed)}
      >
        {t.label}
      </button>
    ))}
  </div>
);
