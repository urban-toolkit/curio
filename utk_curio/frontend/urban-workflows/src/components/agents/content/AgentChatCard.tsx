import React from "react";
import type { AgentCardPart } from "../../../api/agentsApi";
import styles from "./AgentChatCard.module.css";

/**
 * The generic inline chat card (memo dev/39; docs/08 anatomy, docs/03 visual
 * contract). Cards are informational plain data: the fields render as text —
 * never through markdown — and there are NO action buttons (actions are
 * suggested prompts, docs/08). `kind: "result"` is the labeled kind today;
 * unknown kinds from newer servers degrade to this same generic shell.
 */
export const AgentChatCard: React.FC<{
  card: AgentCardPart;
  /** Tint class carrying the agent's category color for the accent dot. */
  tintClassName?: string;
}> = ({ card, tintClassName }) => (
  <div className={styles.card} role="group" aria-label={`${card.kind} card: ${card.title}`}>
    <div className={`${styles.header} ${tintClassName ?? ""}`}>
      <span className={styles.accentDot} aria-hidden="true" />
      <span>{card.title}</span>
      <span className={styles.kind}>{card.kind}</span>
    </div>
    {card.lines.length > 0 ? (
      <div className={styles.inner}>
        {card.lines.map((line, i) => (
          <p key={i} className={styles.line}>
            {line}
          </p>
        ))}
      </div>
    ) : null}
  </div>
);
