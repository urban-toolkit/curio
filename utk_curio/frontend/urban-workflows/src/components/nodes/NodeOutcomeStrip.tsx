import React, { useEffect, useState } from "react";
import { getToken } from "../../utils/authApi";
import { backendUrl } from "../../utils/backendUrl";
import styles from "./NodeOutcomeStrip.module.css";

/**
 * A node's last outcome, in the node (memo dev/138).
 *
 * The owner's report: *"the error message seems to be through the toast and not
 * carried into node's spec object."* A toast fades, and after it faded the node
 * was a blank chart with a red **Error** and no text — the reason lived in the
 * journal (server-side) and in `data.output.content` (memory, that tab only).
 * A code node at least prints its traceback into its own output area; a grammar
 * or presentation node has no such surface at all.
 *
 * Two sources, one formatter, so a user and an agent never read different
 * explanations of the same node:
 *
 * - the LIVE outcome (`data.output`) while this tab holds one — it appears the
 *   instant a render fails;
 * - the JOURNAL otherwise, fetched once on mount, so the reason is still there
 *   after a reload. That is also the record the agents read (`DEC-052`), and it
 *   is deliberately not a new field on the saved node: dev/135 keeps the
 *   document and the run log apart.
 */

export interface NodeOutcomeStripProps {
  nodeId: string;
  /** The project this node belongs to; without it there is nothing to fetch. */
  projectId?: string | null;
  /** The node's live output, when it has one. */
  output?: { code?: string; content?: unknown } | null;
}

type Level = "error" | "notice";

interface Outcome {
  level: Level;
  text: string;
  /** Where it came from, for the label: this render, or the last one. */
  live: boolean;
}

const FIRST_LINE_CHARS = 140;

function textOf(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/** The live outcome, or null when this tab has nothing settled to show. */
export function liveOutcome(
  output: { code?: string; content?: unknown } | null | undefined,
): Outcome | null {
  const code = typeof output?.code === "string" ? output.code : "";
  const text = textOf(output?.content);
  if (code === "error") {
    return { level: "error", text: text || "This node reported an error.", live: true };
  }
  return null;
}

/** A journal record (run or render) as an outcome, or null. */
export function recordOutcome(record: unknown, live = false): Outcome | null {
  if (!record || typeof record !== "object") return null;
  const row = record as Record<string, unknown>;
  const status = typeof row.status === "string" ? row.status : "";
  if (status !== "error") return null;
  const text = textOf(row.stderrTail) || "This node's last run failed.";
  return { level: "error", text, live };
}

/** The first line, for the collapsed strip. */
export function firstLine(text: string): string {
  const line = text.split("\n").find((l) => l.trim()) ?? text;
  const trimmed = line.trim();
  return trimmed.length > FIRST_LINE_CHARS
    ? trimmed.slice(0, FIRST_LINE_CHARS - 1) + "…"
    : trimmed;
}

export const NodeOutcomeStrip: React.FC<NodeOutcomeStripProps> = ({
  nodeId,
  projectId,
  output,
}) => {
  const [recorded, setRecorded] = useState<Outcome | null>(null);
  const [expanded, setExpanded] = useState(false);
  const live = liveOutcome(output);

  useEffect(() => {
    if (!projectId || !nodeId) return;
    let cancelled = false;
    const token = getToken();
    fetch(
      `${backendUrl()}/nodeRuntime?dataflowId=${encodeURIComponent(projectId)}` +
        `&nodeId=${encodeURIComponent(nodeId)}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : undefined },
    )
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => {
        if (cancelled || !body) return;
        // The failure leads: a user looking at a red node wants the reason,
        // and dev/137 keeps the run and the render separately readable.
        setRecorded(recordOutcome(body.run) ?? recordOutcome(body.render));
      })
      .catch(() => {
        // No record readable: no claim. The live path still works.
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, nodeId, output]);

  const outcome = live ?? recorded;
  if (!outcome || !outcome.text) return null;

  const head = firstLine(outcome.text);
  const hasMore = outcome.text.trim() !== head;

  return (
    <div
      className={`${styles.strip} ${outcome.level === "error" ? styles.error : styles.notice}`}
      role="status"
      data-testid={`node-outcome-${nodeId}`}
    >
      <span className={styles.label}>
        {outcome.live ? "Error" : "Last run"}
      </span>
      <span className={styles.text}>{expanded ? outcome.text : head}</span>
      {hasMore ? (
        <button
          type="button"
          className={styles.more}
          onClick={() => setExpanded((was) => !was)}
          aria-expanded={expanded}
        >
          {expanded ? "less" : "more"}
        </button>
      ) : null}
    </div>
  );
};
