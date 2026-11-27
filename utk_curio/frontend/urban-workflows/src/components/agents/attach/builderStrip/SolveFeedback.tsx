import React from "react";

import type { AgentRemedy } from "../../../../services/agents";
import { AddKeyAction } from "../../../connectionKeys/AddKeyAction";
import { useHostedGuest } from "../../../apiSettings/useHostedGuest";
import styles from "../AgentBuilderStrip.module.css";

/** The missing connection keys the live batch names, kept in view under the
 * plan line, one Add key per host (dev/116); none for a hosted guest, who
 * cannot save one. Why each node failed is on its row of the plan's card. */
export const SolveRemedies: React.FC<{
  remedies: AgentRemedy[];
}> = ({ remedies }) => {
  const hostedGuest = useHostedGuest();
  return remedies.length && !hostedGuest ? (
    <div className={styles.actions} role="group" aria-label="Missing connection keys">
      {remedies.map((r) => (
        <AddKeyAction key={`${r.kind}:${r.host}`} remedy={r} />
      ))}
    </div>
  ) : null;
};
