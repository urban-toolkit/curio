import React, { useState } from "react";
import type {
  AgentDatasetCandidateRow,
  AgentDatasetCandidatesPart,
  AgentDatasetPick,
  AgentDatasetSelection,
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
  // The external lane splits in two. A row Curio can download says so; one it
  // cannot still goes to Node Builder, which is the right answer for a source
  // no provider covers - it just stops being the ONLY answer.
  const downloadable = externalRows.filter((r) => r.acquirable && r.sourceId && r.resourceId);
  const handoff = externalRows.filter((r) => !downloadable.includes(r));
  if (downloadable.length) {
    bits.push(
      `download into my Data Catalog: ${downloadable
        .map((r) => `${r.name} (${r.sourceId}/${r.resourceId})`)
        .join(", ")}`,
    );
  }
  if (handoff.length) {
    bits.push(
      `hand off to Node Builder: ${handoff.map((r) => r.name).join(", ")}`,
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
  /** dev/126: record the confirmed selection for the node this Dataset Finder
   * is attached to. Present only there; without it the card keeps its
   * dev/114 behavior exactly (select → prompt). */
  onRecordSelection?: (picks: AgentDatasetPick[]) => Promise<AgentDatasetSelection>;
  /** dev/132: the ONE catalog import (`useDatasetImport`), so a row that must
   * be downloaded from a portal can be brought in from the card that taught
   * the download. Resolves to the imported dataset's id, or null when the
   * import failed (the hook has already shown its own toast). */
  onImportDataset?: (file: File) => Promise<string | null>;
}> = ({
  part,
  tintClassName,
  onComposePrompt,
  variant = "finder",
  onRecordSelection,
  onImportDataset,
}) => {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [recording, setRecording] = useState(false);
  const [recorded, setRecorded] = useState<AgentDatasetSelection | null>(null);
  const [recordError, setRecordError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  const rowKey = (lane: string, index: number) => `${lane}:${index}`;

  /** The server addresses rows by identifier: a catalog row's datasetId, an
   * external row's url. A row with neither cannot be confirmed. */
  const picksFor = (keys: Set<string>): AgentDatasetPick[] => {
    const out: AgentDatasetPick[] = [];
    (["catalog", "external"] as const).forEach((lane) => {
      (part.lanes[lane] ?? []).forEach((row, i) => {
        if (!keys.has(rowKey(lane, i))) return;
        const key = lane === "catalog" ? row.datasetId : row.url;
        if (key) out.push({ lane, key });
      });
    });
    return out;
  };

  const confirm = async () => {
    if (!onRecordSelection || recording) return;
    const picks = picksFor(selected);
    if (!picks.length) return;
    setRecording(true);
    setRecordError(null);
    try {
      setRecorded(await onRecordSelection(picks));
    } catch (e) {
      setRecordError(e instanceof Error ? e.message : "the selection could not be recorded");
    } finally {
      setRecording(false);
    }
  };

  /** dev/132: the download's other half — the file the user just fetched from
   * the portal is imported through the SAME catalog pathway as everywhere
   * else, and its id is then confirmed as this node's source, so solving
   * continues from it without the user explaining anything further. */
  const importAndConfirm = async (file: File) => {
    if (!onImportDataset || importing) return;
    setImporting(true);
    setRecordError(null);
    try {
      const datasetId = await onImportDataset(file);
      if (!datasetId) return; // the import hook reported its own failure
      if (onRecordSelection) {
        setRecorded(await onRecordSelection([{ lane: "catalog", key: datasetId }]));
      }
    } catch (e) {
      setRecordError(
        e instanceof Error ? e.message : "the imported dataset could not be recorded",
      );
    } finally {
      setImporting(false);
    }
  };

  const recordedNote = (selection: AgentDatasetSelection): string => {
    // dev/132: when the runtime handed the fetch to the node's own builder,
    // say THAT — the user has nothing left to compose or press.
    const delegated = selection.delegated;
    if (delegated?.status === "delegating") {
      return "Source recorded — this node's builder is writing the loader for it now.";
    }
    if (delegated?.status === "session-running") {
      return "Source recorded — the running Solve session picks this node up on its next pass.";
    }
    if (delegated?.reason) {
      return `Source recorded — ${delegated.reason}.`;
    }
    if (selection.status === "resolved") {
      return "Source recorded for this node — Solve it to build the loader from this source.";
    }
    if (selection.status === "awaiting-install") {
      return "Source recorded — install the dataset from the Data Catalog, then Solve the node.";
    }
    return "Nothing selectable was confirmed — the runtime could not reach it. Pick another row.";
  };

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
              {lane === "external" && row.acquirable ? (
                // Set by the runtime against the real source roster, never by
                // the model. It is the difference between a row Curio can
                // download and one it can only hand to Node Builder.
                <span className={styles.installedChip} title="Curio can download this for you">
                  Downloadable
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
            {row.access === "manual-download" ? (
              // dev/132: this source is a portal download, and the card is
              // where the user learns how — the steps are the portal's own
              // (or what the probe observed), never invented here.
              <span className={styles.download}>
                <span className={styles.downloadHead}>
                  Download it from the portal
                  {row.accessWhy ? ` — ${row.accessWhy}` : ""}
                </span>
                {row.downloadSteps?.length ? (
                  <ol className={styles.steps}>
                    {row.downloadSteps.map((step, si) => (
                      <li key={si}>{step}</li>
                    ))}
                  </ol>
                ) : null}
                {onImportDataset ? (
                  <label className={styles.importControl}>
                    <input
                      type="file"
                      className={styles.importInput}
                      disabled={importing}
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        e.target.value = "";
                        if (file) void importAndConfirm(file);
                      }}
                    />
                    <span
                      className={styles.importButton}
                      aria-disabled={importing || undefined}
                    >
                      {importing ? "Importing…" : "Import dataset"}
                    </span>
                  </label>
                ) : null}
              </span>
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
      {onRecordSelection ? (
        <div className={styles.confirmRow}>
          <button
            type="button"
            className={styles.confirm}
            disabled={recording || picksFor(selected).length === 0}
            title="Records this source for the node. Solve then builds the loader from exactly this source — nothing else is accepted."
            onClick={() => void confirm()}
          >
            {recording ? "Recording…" : "Confirm source for this node"}
          </button>
          {recorded ? (
            <span className={styles.recorded} role="status">{recordedNote(recorded)}</span>
          ) : null}
          {recordError ? (
            <span className={styles.recordError} role="alert">{recordError}</span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};
