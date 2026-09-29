import React from "react";

import type { AgentProposalPart } from "../../../../services/agents";
import styles from "../AgentReviewCard.module.css";

/** A node.template.create proposal's two blocks: the adequacy gate's
 * reasoning (dev/48 §3.2b — the model's justification is what the user
 * judges, rendered verbatim FIRST) and the template's label/engine line. */
export const TemplateCreateBlocks: React.FC<{ part: AgentProposalPart }> = ({ part }) => {
  if (part.tool !== "node.template.create") return null;
  return (
    <>
      {part.justification ? (
        <div className={styles.justification} aria-label="Why a new node type is needed">
          {part.justification}
        </div>
      ) : null}
      {part.template ? (
        <div className={styles.meta}>
          {part.template.label} · {part.template.engine}
          {part.template.description ? ` — ${part.template.description}` : ""}
        </div>
      ) : null}
    </>
  );
};
