import React from "react";

import type { AgentProposalPart } from "../../../../services/agents";
import styles from "../AgentReviewCard.module.css";

/** Why a package draft adds node types: the closest existing templates the
 * agent considered and why each is inadequate. It is what the user judges,
 * so the card renders it verbatim before the draft's details. */
export const JustificationBlock: React.FC<{ part: AgentProposalPart }> = ({ part }) => {
  if (!part.justification) return null;
  return (
    <div className={styles.justification} aria-label="Why a new node type is needed">
      {part.justification}
    </div>
  );
};
