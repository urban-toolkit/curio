import React, { useState } from "react";
import type {
  AgentDatasetCandidateRow,
  AgentDatasetCandidatesPart,
} from "../../../api/agentsApi";
import styles from "./AgentDatasetCandidatesCard.module.css";
import { VerificationChip } from "./verificationChip";

const LANE_LABEL: Record<"external" | "catalog", string> = {
  external: "External sources",
  catalog: "From your Data Catalog",
};

/** dev/114: whose chat the card lives in — the Dataset Finder's (the DEC-047
 * install / hand-off prompt) or the Node Builder's (the runtime minted the
 * candidates from a dataset.discover delegation; the confirmation asks the
 * builder to build from the selection). */
export type CandidatesVariant = "finder" | "builder";

/** Compose the docs/06 confirmation prompt from the current selection —
 * catalog picks route to the reviewed install, external picks to the
 * DEC-047 Node Builder handoff. In a Node Builder chat (dev/114) the same
 * selection reads as the build request instead. Exported for tests. */
export function composeConfirmationPrompt(
  catalogRows: AgentDatasetCandidateRow[],
  externalRows: AgentDatasetCandidateRow[],
  variant: CandidatesVariant = "finder",
): string {
  const bits: string[] = [];
  if (variant === "builder") {
    if (catalogRows.length) {
      bits.push(
        `load from the Data Catalog: ${catalogRows
          .map((r) => `${r.name} (${r.datasetId ?? "?"})`)
          .join(", ")}`,
      );
    }
    if (externalRows.length) {
      bits.push(
        `fetch from: ${externalRows
          .map((r) => (r.url ? `${r.name} (${r.url})` : r.name))
          .join(", ")}`,
      );
    }
    return bits.length ? `Build the data-loading node — ${bits.join("; ")}.` : "";
  }
  if (catalogRows.length) {
    bits.push(
      `install from the Data Catalog: ${catalogRows
        .map((r) => `${r.name} (${r.datasetId ?? "?"})`)
        .join(", ")}`,
    );
  }
  if (externalRows.length) {
    bits.push(
      `hand off to Node Builder: ${externalRows.map((r) => r.name).join(", ")}`,
    );
  }
  return bits.length ? `Confirm my selection — ${bits.join("; ")}.` : "";
}

/**
 * The dev/50 two-lane suggestions surface (docs/06): one grouped card, two
 * labeled lanes, keyboard-operable multi-select rows carrying safe metadata
 * only. Rows have NO bespoke action buttons — toggling a selection composes
 * the editable confirmation prompt into the chat input (the suggested-prompt
 * vehicle); Apply/Dismiss stay exclusively on review cards. Every text field
 * arrives bounded + scheme-allowlisted from the server and renders as plain
 * text here (REQ-SEC-002).
 */
export const AgentDatasetCandidatesCard: React.FC<{
  part: AgentDatasetCandidatesPart;
  tintClassName?: string;
  /** Prefill the chat input (a prefill never overwrites a user-typed draft). */
  onComposePrompt?: (prompt: string) => void;
  /** dev/114: the host agent's chat — decides the confirmation prompt's shape. */
  variant?: CandidatesVariant;
}> = ({ part, tintClassName, onComposePrompt, variant = "finder" }) => {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const rowKey = (lane: string, index: number) => `${lane}:${index}`;

  const toggle = (lane: "external" | "catalog", index: number) => {
    const key = rowKey(lane, index);
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelected(next);
    const pick = (l: "external" | "catalog") =>
      (part.lanes[l] ?? []).filter((_, i) => next.has(rowKey(l, i)));
    onComposePrompt?.(composeConfirmationPrompt(pick("catalog"), pick("external"), variant));
  };

  const renderRow = (lane: "external" | "catalog", row: AgentDatasetCandidateRow, i: number) => {
    const key = rowKey(lane, i);
    const meta = [row.provider, row.format, row.coverage].filter(Boolean).join(" · ");
    return (
      <li key={key} className={styles.row}>
        <label className={styles.rowLabel}>
          <input
            type="checkbox"
            checked={selected.has(key)}
            onChange={() => toggle(lane, i)}
            aria-label={`Select ${row.name}`}
          />
          <span className={styles.rowBody}>
            <span className={styles.rowHead}>
              <span className={styles.name}>{row.name}</span>
              <span className={styles.badge}>{row.sourceType}</span>
              {lane === "catalog" ? (
                <span className={row.installed ? styles.installedChip : styles.notInstalledChip}>
                  {row.installed ? "Installed" : "Not installed"}
                </span>
              ) : null}
              {lane === "external" && row.verification ? (
                // dev/67-4 (DEC-053): the runtime's verdict, never the
                // model's claim — verified ✓ or a loud warning (the ONE
                // label table, shared with the review card — dev/114).
                <VerificationChip verification={row.verification} />
              ) : null}
            </span>
            {meta ? <span className={styles.meta}>{meta}</span> : null}
            {row.url ? <span className={styles.url}>{row.url}</span> : null}
            {row.fit ? (
              <span className={styles.fit}>
                Fit {row.fit.score}/100 — {row.fit.rationale}
              </span>
            ) : null}
            {row.requirement ? (
              <span className={styles.requirement}>{row.requirement}</span>
            ) : null}
          </span>
        </label>
      </li>
    );
  };

  const lanes = (["external", "catalog"] as const).filter(
    (lane) => (part.lanes[lane] ?? []).length > 0,
  );

  return (
    <div className={styles.card} role="group" aria-label="Dataset candidates">
      <div className={`${styles.header} ${tintClassName ?? ""}`}>
        <span className={styles.accentDot} aria-hidden="true" />
        <span>Dataset candidates</span>
        <span className={styles.kind}>select &amp; confirm in chat</span>
      </div>
      {lanes.map((lane) => (
        <div key={lane} role="group" aria-label={LANE_LABEL[lane]} className={styles.lane}>
          <div className={styles.laneLabel}>{LANE_LABEL[lane]}</div>
          <ul className={styles.rows}>
            {part.lanes[lane].map((row, i) => renderRow(lane, row, i))}
          </ul>
        </div>
      ))}
    </div>
  );
};
