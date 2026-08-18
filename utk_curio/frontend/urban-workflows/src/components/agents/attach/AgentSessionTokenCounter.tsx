import React from "react";
import type { AgentUsage } from "../../../api/agentsApi";
import { formatTokenCount } from "./agentRunStatus";
import styles from "./AgentSessionTokenCounter.module.css";

/**
 * Cumulative session token usage (memo dev/80) — the right side of the chat
 * status strip, beside the composer. Provider-reported Actuals only (memo
 * dev/37): renders nothing when no usage was ever reported, never a
 * fabricated 0. While a run is in flight (`live`) the figure includes the
 * stream's interim sums and pulses gently to signal it may still grow.
 */
export const AgentSessionTokenCounter: React.FC<{
  totals: AgentUsage | null;
  /** True while this attachment's run is in flight. */
  live?: boolean;
}> = ({ totals, live = false }) => {
  if (!totals) return null;
  const total = (totals.inputTokens ?? 0) + (totals.outputTokens ?? 0);
  if (total <= 0) return null;
  const breakdown = `${totals.inputTokens.toLocaleString()} in / ${totals.outputTokens.toLocaleString()} out — provider-reported`;
  return (
    <span
      className={`${styles.counter} ${live ? styles.live : ""}`}
      title={breakdown}
      aria-label={`Session token usage: ${breakdown}`}
    >
      {formatTokenCount(total)} tokens
    </span>
  );
};
