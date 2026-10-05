import React from "react";

import type { AgentRemedy } from "../../../../services/agents";
import { AddKeyAction } from "../../../connectionKeys/AddKeyAction";
import { useHostedGuest } from "../../../apiSettings/useHostedGuest";
import { OpenDatasetFinderAction } from "../OpenDatasetFinderAction";
import styles from "../AgentBuilderStrip.module.css";

/** What the live batch said about its nodes, de-duplicated: the failure
 * reasons (dev/106), the notices that are not errors (dev/118), the missing
 * connection keys by host (dev/116; none for a hosted guest, who cannot save
 * one) and the nodes awaiting a dataset selection (dev/126). */
export const SolveFeedback: React.FC<{
  reasons: string[];
  notices: string[];
  remedies: AgentRemedy[];
  selectionRemedies: Array<[string, AgentRemedy]>;
  onOpenChat?: (attachmentId: string) => void;
}> = ({ reasons, notices, remedies, selectionRemedies, onOpenChat }) => {
  const hostedGuest = useHostedGuest();
  return (
    <>
      {reasons.length ? (
        <div className={styles.error} aria-live="polite">
          {reasons.map((r) => (
            <div key={r}>{r}</div>
          ))}
        </div>
      ) : null}
      {notices.length ? (
        <div className={styles.hint} role="note" aria-label="Solve notices">
          {notices.map((n) => (
            <div key={n}>{n}</div>
          ))}
        </div>
      ) : null}
      {remedies.length && !hostedGuest ? (
        <div className={styles.actions} role="group" aria-label="Missing connection keys">
          {remedies.map((r) => (
            <AddKeyAction key={`${r.kind}:${r.host}`} remedy={r} />
          ))}
        </div>
      ) : null}
      {selectionRemedies.length && onOpenChat ? (
        <div className={styles.actions} role="group" aria-label="Nodes awaiting a dataset selection">
          {selectionRemedies.map(([nodeId, r]) => (
            <OpenDatasetFinderAction
              key={r.attachmentId}
              remedy={r}
              onOpenChat={onOpenChat}
              // One awaiting node needs no disambiguation; several do.
              nodeLabel={selectionRemedies.length > 1 ? nodeId.slice(0, 8) : undefined}
            />
          ))}
        </div>
      ) : null}
    </>
  );
};
