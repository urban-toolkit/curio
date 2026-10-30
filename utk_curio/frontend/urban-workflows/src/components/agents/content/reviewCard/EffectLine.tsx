import React from "react";

import type { AgentProposalPart } from "../../../../services/agents";
import styles from "../AgentReviewCard.module.css";
import { EFFECT_LINE } from "./reviewCardText";

/** What one Apply click of an install does, per kind: stated on its card. */
export const EffectLine: React.FC<{ part: AgentProposalPart }> = ({ part }) =>
  EFFECT_LINE[part.tool] ? <div className={styles.meta}>{EFFECT_LINE[part.tool]}</div> : null;
