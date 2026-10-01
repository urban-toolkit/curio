import React from "react";

import type { AgentProposalSource } from "../../../../services/agents";
import styles from "../AgentReviewCard.module.css";
import { VerificationChip } from "../verificationChip";
import { SOURCE_KIND_LABEL, sourceRefText } from "./reviewCardText";

/** dev/114 (DEC-072): what the code opens/fetches and how the RUNTIME
 * grounded it — a catalog dataset by id, a probed URL with its verdict, a path
 * the user typed, or declared synthetic data. Above the preview so it cannot
 * be missed; plain text, never markup. */
export const SourceBlock: React.FC<{ source: AgentProposalSource }> = ({ source }) => (
  <div className={styles.sourceBlock} role="group" aria-label="Data source">
    <div className={styles.sourceTitle}>Source · {SOURCE_KIND_LABEL[source.kind] ?? source.kind}</div>
    <ul className={styles.sourceList}>
      {source.refs.map((ref, i) => (
        <li key={i}>
          {sourceRefText(ref)}
          {ref.kind === "external" && ref.verification ? (
            <>
              {" "}
              <VerificationChip verification={ref.verification} />
            </>
          ) : null}
        </li>
      ))}
    </ul>
  </div>
);
