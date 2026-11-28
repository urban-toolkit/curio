import React from "react";

import type { AgentProposalSource } from "../../../../services/agents";
import styles from "../AgentReviewCard.module.css";
import { VerificationChip } from "../verificationChip";
import { sourceLine, sourceRefText } from "./reviewCardText";

/** dev/114 (DEC-072), on one line: what a change's code opens or fetches, as
 * the runtime grounded it: "Source: Chicago Neighborhoods, Data Catalog". The
 * rest of each source (a format, a dataset's id, a key's host, a saved key's
 * hint, a path Curio did not check) is the line's tooltip. An external source
 * the runtime found unreachable, refused or never checked keeps its chip: one
 * that works needs none. Plain text, never markup. */
export const SourceLine: React.FC<{ source: AgentProposalSource }> = ({ source }) => {
  const warned = source.refs.filter(
    (ref) => ref.kind === "external" && ref.verification && ref.verification.status !== "verified",
  );
  return (
    <div
      className={styles.sourceLine}
      role="group"
      aria-label="Data source"
      data-tooltip={source.refs.map(sourceRefText).join("\n") || undefined}
    >
      <span>{sourceLine(source)}</span>
      {warned.map((ref, i) => (
        <React.Fragment key={i}>
          {" "}
          <VerificationChip verification={ref.verification!} />
        </React.Fragment>
      ))}
    </div>
  );
};
