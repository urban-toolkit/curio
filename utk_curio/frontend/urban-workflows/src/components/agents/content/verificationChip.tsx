import React from "react";
import type { AgentDatasetCandidateRow } from "../../../services/agents";
import styles from "./AgentDatasetCandidatesCard.module.css";

type Verification = NonNullable<AgentDatasetCandidateRow["verification"]>;

/** Whether the link answered data the runtime verified: an answer of 2xx that
 * is not a web page. */
function verifiedData(verification: Verification | undefined): boolean {
  return verification?.status === "verified" && !verification.webPage;
}

/** dev/67-4 (DEC-053), dev/114: the ONE label table for the runtime's
 * verification verdict. The candidates card and the review card's Source
 * block say the same words for the same verdict. It says what the link
 * answered: data, a web page (an answer, but no data), an error status, or
 * nothing at all; *verification* is the rest of the verdict whose status is
 * *status*. Status is stated in text, never by colour alone. */
export function verificationLabel(status: string | undefined, verification?: Partial<Verification>): string {
  switch (status) {
    case "verified":
      return verification?.webPage ? "Web page" : "Verified ✓";
    case "http-error":
    case "unreachable":
      // A verdict recorded before error answers had their own status says
      // `unreachable` with the status it answered.
      return typeof verification?.httpStatus === "number"
        ? `Answered ${verification.httpStatus} ✗`
        : "Unreachable ✗";
    case "refused":
      return "Refused ✗";
    default:
      return "Unverified: never checked";
  }
}

export const VerificationChip: React.FC<{ verification: Verification }> = ({ verification }) => (
  <span
    className={verifiedData(verification) ? styles.installedChip : styles.notInstalledChip}
    data-tooltip={
      verification.detail ??
      (verification.datasetName ? `verified: ${verification.datasetName}` : undefined)
    }
  >
    {verificationLabel(verification.status, verification)}
  </span>
);
