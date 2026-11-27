import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCheck, faXmark } from "@fortawesome/free-solid-svg-icons";

import type { AgentChangePart } from "../../../../services/agents";
import { AddKeyAction } from "../../../connectionKeys/AddKeyAction";
import styles from "../AgentReviewCard.module.css";
import { outputWords } from "./reviewCardText";

type Validation = NonNullable<AgentChangePart["validation"]>;
type Attempt = NonNullable<Validation["attempts"]>[number];

/** A chart's or a map's document: the sandbox does not run one, so its
 * grammar's schema validates it, and a document that validated failed
 * nothing. */
const documentValidated = (validation: Validation): boolean =>
  validation.verdict === "not-executable" && Boolean(validation.evidence?.documentValidated);

/** A round whose document its grammar validated: it reads as a check that
 * passed, with no reason the sandbox ran nothing and its document under
 * plain words. A round whose document failed its check keeps its error. */
const validatedRound = (validation: Validation, attempt: Attempt): boolean =>
  documentValidated(validation) && attempt.verdict === "not-executable";

/** The check of the code that landed, in one line: "Ran in the sandbox: a
 * GeoDataFrame", "Valid: checked against its grammar", or why it failed. */
function checkWords(validation: Validation): string {
  const rounds = validation.rounds > 1 && !validation.attempts?.length ? ` (${validation.rounds} rounds)` : "";
  if (validation.verdict === "pass") {
    const type = validation.evidence?.outputDataType;
    return `Ran in the sandbox${type ? `: ${outputWords(type)}` : ""}${rounds}`;
  }
  if (documentValidated(validation)) return `Valid: checked against its grammar${rounds}`;
  if (validation.evidence?.kind === "upstream-blocker") {
    return `Upstream node ${validation.evidence?.blockerLabel ?? "?"} failed before this node ran${rounds}`;
  }
  if (validation.evidence?.detail) return `${validation.evidence.detail}${rounds}`;
  return `Validation failed after ${validation.rounds} round${validation.rounds === 1 ? "" : "s"}`;
}

/** The Verification disclosure's words: how many rounds, and that each
 * carries its code when every round that did not pass does. */
function verificationWords(attempts: Attempt[]): string {
  const rounds = `${attempts.length} round${attempts.length === 1 ? "" : "s"}`;
  const withCode = attempts.every((attempt) => attempt.verdict === "pass" || Boolean(attempt.code));
  return `Verification: ${rounds}${withCode && attempts.some((attempt) => attempt.code) ? ", each with its code" : ""}`;
}

/** dev/67-7: the check of code that landed, on one line, from real runtime
 * evidence, rendered inert: it ran in the sandbox and what it put out, its
 * document validated against its grammar, or why it failed, with the error
 * output. dev/115, dev/127: under Verification, collapsed, every round the
 * runtime ran (or refused before running), how it failed, that a fix
 * followed, and the code each round ran. A document its grammar validated
 * reads as a check that passed. */
export const ValidationBlock: React.FC<{ validation: Validation }> = ({ validation }) => {
  const passed = validation.verdict === "pass" || documentValidated(validation);
  const attempts = validation.attempts ?? [];
  return (
    <div
      className={`${styles.check} ${passed ? styles.checkPass : styles.checkFail}`}
      role="status"
      aria-label={documentValidated(validation) ? "Validated against its grammar" : `Validation ${validation.verdict}`}
    >
      <div className={styles.checkLine}>
        <FontAwesomeIcon icon={passed ? faCheck : faXmark} className={styles.checkIcon} aria-hidden="true" />
        <span>{checkWords(validation)}</span>
      </div>
      {validation.evidence?.stderrTail ? (
        <details className={styles.validationDetails}>
          <summary>Error output</summary>
          <pre>{validation.evidence.stderrTail}</pre>
        </details>
      ) : null}
      {attempts.length > 0 ? (
        <details className={styles.validationDetails}>
          <summary className={styles.verificationToggle}>{verificationWords(attempts)}</summary>
          <ol className={styles.attempts} aria-label="Verification attempts">
            {attempts.map((attempt) => (
              <li key={attempt.round}>
                <span className={styles.attemptHead}>
                  Round {attempt.round} ·{" "}
                  {attempt.verdict === "pass"
                    ? "pass ✓"
                    : attempt.verdict === "not-executable"
                      ? documentValidated(validation)
                        ? "validated against its grammar, not executed"
                        : "not executable: no code to run, nothing ran"
                      : attempt.verdict}
                  {attempt.kind && attempt.verdict !== "pass" && attempt.verdict !== "not-executable" ? ` · ${attempt.kind}` : ""}
                  {attempt.source === "current content" ? " · the node's current code" : ""}
                </span>
                {attempt.reusedNodes?.length ? (
                  <span className={styles.attemptDetail}>
                    {" "}· reused {attempt.reusedNodes.length} upstream result{attempt.reusedNodes.length === 1 ? "" : "s"}
                    {attempt.reuseRetried ? " (re-run whole once)" : ""}
                  </span>
                ) : null}
                {attempt.verdict === "pass" ? (
                  <span className={styles.attemptDetail}>
                    {attempt.outputDataType ? ` output: ${attempt.outputDataType}` : ""}
                    {typeof attempt.durationMs === "number" ? ` · ${(attempt.durationMs / 1000).toFixed(1)} s` : ""}
                  </span>
                ) : !validatedRound(validation, attempt) && (attempt.detail || attempt.stderrTail) ? (
                  <details className={styles.attemptError}>
                    <summary>{(attempt.detail ?? attempt.stderrTail ?? "").slice(0, 120)}</summary>
                    <pre>{attempt.stderrTail ?? attempt.detail}</pre>
                  </details>
                ) : null}
                {attempt.verdict !== "pass" && attempt.endpointEvidence ? (
                  <span className={styles.attemptEndpoint}>Endpoint: {attempt.endpointEvidence}</span>
                ) : null}
                {validatedRound(validation, attempt) && attempt.code ? (
                  // dev/127: every round's content stays in the chat; this one passed its check.
                  <details className={styles.attemptDocument}>
                    <summary>
                      The document this round validated
                      {attempt.codeTruncated ? " (truncated)" : ""}
                    </summary>
                    <pre>{attempt.code}</pre>
                  </details>
                ) : attempt.verdict !== "pass" && attempt.code ? (
                  // dev/127: what this round actually ran.
                  <details className={styles.attemptError}>
                    <summary>
                      {attempt.codeIsProse ? "What the builder said instead of writing code" : "The code this attempt ran"}
                      {attempt.codeTruncated ? " (truncated)" : ""}
                    </summary>
                    <pre>{attempt.code}</pre>
                  </details>
                ) : null}
                {attempt.verdict !== "pass" && attempt.remedy ? (
                  <AddKeyAction remedy={attempt.remedy} className={styles.attemptRemedy} />
                ) : null}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </div>
  );
};
