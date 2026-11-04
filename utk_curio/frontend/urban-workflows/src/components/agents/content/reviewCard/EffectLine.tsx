import React from "react";

import type { AgentProposalPart } from "../../../../services/agents";
import styles from "../AgentReviewCard.module.css";
import { EFFECT_LINE } from "./reviewCardText";

/** What one Apply click of an install does, per kind: stated on its card.
 * *text*, when given, says it in place of the kind's line. */
export const EffectLine: React.FC<{ part: AgentProposalPart; text?: string }> = ({ part, text }) => {
  const line = text ?? EFFECT_LINE[part.tool];
  return line ? <div className={styles.meta}>{line}</div> : null;
};
