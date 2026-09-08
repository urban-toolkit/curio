import React from "react";
import type { AgentDatasetCandidateRow } from "../../../api/agentsApi";
import styles from "./AgentDatasetCandidatesCard.module.css";

type Verification = NonNullable<AgentDatasetCandidateRow["verification"]>;

/** dev/67-4 (DEC-053) → dev/114: the ONE label table for the runtime's
 * verification verdict — the candidates card and the review card's Source
 * block say the same words for the same status. Status is stated in text,
 * never by colour alone. */
export function verificationLabel(status: string | undefined): string {
  switch (status) {
    case "verified":
      return "Verified ✓";
    case "unreachable":
      return "Unreachable ✗";
    case "refused":
      return "Refused ✗";
    default:
      return "Unverified — never checked";
  }
}

export const VerificationChip: React.FC<{ verification: Verification }> = ({ verification }) => (
  <span
    className={verification.status === "verified" ? styles.installedChip : styles.notInstalledChip}
    title={
      verification.detail ??
      (verification.datasetName ? `verified: ${verification.datasetName}` : undefined)
    }
  >
    {verificationLabel(verification.status)}
  </span>
);
