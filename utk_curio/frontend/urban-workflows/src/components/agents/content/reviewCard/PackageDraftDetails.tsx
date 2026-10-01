import React from "react";

import type { AgentProposalPart } from "../../../../services/agents";
import styles from "../AgentReviewCard.module.css";

type Draft = NonNullable<AgentProposalPart["draft"]>;

/** dev/96: the diff, dependencies, and preview the Apply text claims the user
 * reviewed — collapsed to counts by default; blocking findings and failed
 * previews render OPEN (impossible to miss). Every capped list states its
 * overflow; all text renders inert. */
export const PackageDraftDetails: React.FC<{ draft: Draft }> = ({ draft }) => (
  <>
    <details className={styles.draftSection}>
      <summary>
        Files: {draft.files.addedTotal} added ·{" "}
        {draft.files.modifiedTotal} modified ·{" "}
        {draft.files.preservedTotal} preserved
      </summary>
      <ul className={styles.draftList}>
        {draft.files.added.map((name) => (
          <li key={`a:${name}`}>added {name}</li>
        ))}
        {draft.files.addedTotal > draft.files.added.length ? (
          <li className={styles.draftOverflow}>…and {draft.files.addedTotal - draft.files.added.length} more added</li>
        ) : null}
        {draft.files.modified.map((name) => (
          <li key={`m:${name}`}>modified {name}</li>
        ))}
        {draft.files.modifiedTotal > draft.files.modified.length ? (
          <li className={styles.draftOverflow}>
            …and {draft.files.modifiedTotal - draft.files.modified.length} more modified
          </li>
        ) : null}
        <li>
          templates: {draft.templates.addedTotal} added ·{" "}
          {draft.templates.modifiedTotal} modified ·{" "}
          {draft.templates.preservedTotal} preserved
          {draft.templates.added.length
            ? ` (${draft.templates.added.join(", ")}${
                draft.templates.addedTotal > draft.templates.added.length ? ", …" : ""})`
            : ""}
        </li>
      </ul>
    </details>
    {draft.dependencies ? (
      <details className={styles.draftSection} open={draft.dependencies.blocked}>
        <summary>
          Dependencies: {draft.dependencies.pythonTotal} python ·{" "}
          {draft.dependencies.jsTotal} js ·{" "}
          {draft.dependencies.findingsTotal} finding
          {draft.dependencies.findingsTotal === 1 ? "" : "s"}
        </summary>
        <ul className={styles.draftList}>
          {draft.dependencies.home === "overlay" ? (
            // dev/97: the isolation statement — same routing rule the install
            // applies, so the card can never disagree with it.
            <li>python deps install into the package's isolated overlay; the shared interpreter is not touched</li>
          ) : draft.dependencies.home === "both" ? (
            <li>
              python deps install into the package's isolated overlay, plus the shared interpreter for its
              python node templates
            </li>
          ) : null}
          {draft.dependencies.python.map((row) => (
            <li key={`py:${row.name}`}>python · {row.name} {row.constraint}</li>
          ))}
          {draft.dependencies.js.map((row) => (
            <li key={`js:${row.name}`}>js · {row.name} {row.version}</li>
          ))}
          {draft.dependencies.pythonTotal + draft.dependencies.jsTotal >
          draft.dependencies.python.length + draft.dependencies.js.length ? (
            <li className={styles.draftOverflow}>
              …and {draft.dependencies.pythonTotal + draft.dependencies.jsTotal - draft.dependencies.python.length - draft.dependencies.js.length} more dependencies
            </li>
          ) : null}
          {draft.dependencies.findings.map((finding, index) => (
            <li
              key={`f:${finding.code}:${index}`}
              className={
                finding.severity === "block" ? styles.findingBlock : finding.severity === "warn" ? styles.findingWarn : undefined
              }
            >
              {finding.severity}: {finding.message}
            </li>
          ))}
          {draft.dependencies.findingsTotal > draft.dependencies.findings.length ? (
            <li className={styles.draftOverflow}>
              …and {draft.dependencies.findingsTotal - draft.dependencies.findings.length} more findings
            </li>
          ) : null}
        </ul>
      </details>
    ) : null}
    {draft.preview ? (
      <details className={styles.draftSection} open={draft.preview.status === "failed"}>
        <summary>Preview: {draft.preview.status}</summary>
        <ul className={styles.draftList}>
          {draft.preview.reasons.map((reason, index) => (
            <li key={`r:${index}`} className={draft.preview!.status === "ok" ? undefined : styles.findingWarn}>
              {reason}
            </li>
          ))}
          {draft.preview.templates.map((row) => (
            <li key={`t:${row.templateId}`}>
              {row.templateId}: {row.ok ? "all states rendered" : `failed states: ${row.failedStates.join(", ")}`}
            </li>
          ))}
          {draft.preview.runnerVersion ? <li>runner {draft.preview.runnerVersion}</li> : null}
        </ul>
      </details>
    ) : null}
    {draft.requestedNodes ? (
      <div className={styles.draftNodesRow}>
        Creates {draft.requestedNodes.total} node
        {draft.requestedNodes.total === 1 ? "" : "s"} after install:{" "}
        {draft.requestedNodes.rows.map((row) => `${row.title}${row.color ? ` (${row.color})` : ""}`).join(", ")}
        {draft.requestedNodes.total > draft.requestedNodes.rows.length
          ? `, …and ${draft.requestedNodes.total - draft.requestedNodes.rows.length} more`
          : ""}
      </div>
    ) : null}
  </>
);
