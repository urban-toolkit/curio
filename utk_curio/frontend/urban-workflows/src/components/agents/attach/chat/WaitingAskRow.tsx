import React, { useState } from "react";

import { writtenBySomeoneElse } from "../../../../services/agents";
import type { WaitingAsk } from "../../../../providers/agents/turnAsks";
import styles from "../AgentChatPanel.module.css";

/** A message asked of the agent while a turn of it runs: it waits its turn
 * on the server, after the transcript, and starts when the turn before it
 * ends. A message someone else wrote names its writer above it; the viewer's
 * own has **Withdraw** while it waits. A message just sent, whose turn starts
 * now, shows without the waiting line. */
export const WaitingAskRow: React.FC<{
  ask: WaitingAsk;
  viewerAccount?: string | null;
  onWithdraw?: (askId: string) => Promise<void>;
}> = ({ ask, viewerAccount = null, onWithdraw }) => {
  const [withdrawing, setWithdrawing] = useState(false);
  const someoneElse = writtenBySomeoneElse(ask.by, viewerAccount);
  const withdraw = () => {
    if (!onWithdraw || withdrawing) return;
    setWithdrawing(true);
    onWithdraw(ask.askId).catch(() => setWithdrawing(false));
  };
  return (
    <div
      className={styles.userTurn}
      data-agent-ask={ask.askId}
      data-agent-ask-status={ask.status}
      {...(someoneElse ? { "data-curio-writer": ask.by?.name } : {})}
    >
      {someoneElse ? <div className={styles.msgWriter}>{ask.by?.name}</div> : null}
      <div className={styles.msgUser}>{ask.message}</div>
      {ask.status === "waiting" ? (
        <div className={styles.msgWriter}>
          Waiting its turn
          {!someoneElse && onWithdraw ? (
            <button type="button" className={styles.retry} onClick={withdraw} disabled={withdrawing}>
              Withdraw
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};
