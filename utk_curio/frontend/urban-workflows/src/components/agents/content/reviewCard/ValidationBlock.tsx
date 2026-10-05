import React from "react";

import type { AgentProposalPart } from "../../../../services/agents";
import { AddKeyAction } from "../../../connectionKeys/AddKeyAction";
import styles from "../AgentReviewCard.module.css";

type Validation = NonNullable<AgentProposalPart["validation"]>;

/** dev/67-7: the validation verdict — real runtime evidence, rendered inert.
 * PASS or FAIL, Apply stays available (labeled honestly). dev/115: the
 * engineering loop's trail — every round the runtime ran (or refused before
 * running), how it failed, and that a fix followed. Collapsed by default. */
export const ValidationBlock: React.FC<{ validation: Validation }> = ({ validation }) => (
  <div
    className={`${styles.validation} ${validation.verdict === "pass" ? styles.validationPass : styles.validationFail}`}
    role="status"
    aria-label={`Validation ${validation.verdict}`}
  >
    <span className={styles.validationBadge}>{validation.verdict === "pass" ? "PASS" : "FAIL"}</span>
    <span>
      {validation.verdict === "pass"
        ? `Executed through the dataflow${
            validation.evidence?.outputDataType ? ` (output: ${validation.evidence.outputDataType})` : ""
          }`
        : validation.evidence?.kind === "upstream-blocker"
          ? `Upstream node ${validation.evidence?.blockerLabel ?? "?"} failed before this node ran`
          : (validation.evidence?.detail ??
             `Validation failed after ${validation.rounds} round${validation.rounds === 1 ? "" : "s"}`)}
      {validation.rounds > 1 ? ` (${validation.rounds} generation rounds)` : ""}
    </span>
    {validation.evidence?.stderrTail ? (
      <details className={styles.validationDetails}>
        <summary>error output</summary>
        <pre>{validation.evidence.stderrTail}</pre>
      </details>
    ) : null}
    {validation.attempts && validation.attempts.length > 0 ? (
      <details className={styles.validationDetails}>
        <summary>
          Verification · {validation.attempts.length} attempt
          {validation.attempts.length === 1 ? "" : "s"}
        </summary>
        <ol className={styles.attempts} aria-label="Verification attempts">
          {validation.attempts.map((attempt) => (
            <li key={attempt.round}>
              <span className={styles.attemptHead}>
                Round {attempt.round} ·{" "}
                {attempt.verdict === "pass"
                  ? "pass ✓"
                  : attempt.verdict === "not-executable"
                    ? "not executable: no code to run, nothing ran"
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
              ) : attempt.detail || attempt.stderrTail ? (
                <details className={styles.attemptError}>
                  <summary>{(attempt.detail ?? attempt.stderrTail ?? "").slice(0, 120)}</summary>
                  <pre>{attempt.stderrTail ?? attempt.detail}</pre>
                </details>
              ) : null}
              {attempt.verdict !== "pass" && attempt.endpointEvidence ? (
                <span className={styles.attemptEndpoint}>Endpoint: {attempt.endpointEvidence}</span>
              ) : null}
              {attempt.verdict !== "pass" && attempt.code ? (
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
