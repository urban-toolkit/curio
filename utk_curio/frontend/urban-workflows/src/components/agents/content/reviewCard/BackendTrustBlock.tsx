import React from "react";

import type { AgentProposalPart } from "../../../../services/agents";
import { describePackagePermission } from "../../../../utils/packagePermissions";
import styles from "../AgentReviewCard.module.css";

type Backend = NonNullable<AgentProposalPart["backend"]>;

/** dev/91 §5: the trust edge is stated ON the card, before Apply —
 * server-side handlers + declared permissions, impossible to miss. */
export const BackendTrustBlock: React.FC<{ backend: Backend }> = ({ backend }) => (
  <div className={styles.removals} role="group" aria-label="Server-side code this package runs">
    <div className={styles.removalsTitle}>
      Runs server-side code in the package sandbox
      {backend.network ? " (may reach the network, server-network declared)" : " (no network access)"}
    </div>
    <ul className={styles.removalsList}>
      {backend.handlers.map((h) => (
        <li key={`handler:${h.name}`}>
          handler {h.name}
          {h.timeoutClass ? ` · ${h.timeoutClass} limits` : ""}
        </li>
      ))}
      {backend.permissions.map((perm) => {
        const meaning = describePackagePermission(perm);
        return (
          <li key={`perm:${perm}`}>
            permission {perm}
            {meaning ? `: ${meaning}` : ""}
          </li>
        );
      })}
    </ul>
  </div>
);
