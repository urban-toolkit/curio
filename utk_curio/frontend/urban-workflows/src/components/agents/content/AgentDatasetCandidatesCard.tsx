import React, { useState } from "react";
import type {
  AgentDatasetCandidateRow,
  AgentDatasetCandidatesPart,
} from "../../../api/agentsApi";
import styles from "./AgentDatasetCandidatesCard.module.css";

const LANE_LABEL: Record<"external" | "catalog", string> = {
  external: "External sources",
  catalog: "From your Data Catalog",
};

/** Compose the docs/06 confirmation prompt from the current selection —
 * catalog picks route to the reviewed install, external picks to the
 * DEC-047 Node Builder handoff. Exported for tests. */
export function composeConfirmationPrompt(
  catalogRows: AgentDatasetCandidateRow[],
  externalRows: AgentDatasetCandidateRow[],
): string {
  const bits: string[] = [];
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
}> = ({ part, tintClassName, onComposePrompt }) => {
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
    onComposePrompt?.(composeConfirmationPrompt(pick("catalog"), pick("external")));
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
