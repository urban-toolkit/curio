import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
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
 * - the LIVE outcome (`data.output`) while this tab holds a settled one. A
 *   failure appears the instant a render fails, and a success clears the strip;
 * - the JOURNAL otherwise, so the reason is still there after a reload. That is
 *   also the record the agents read (`DEC-052`), and it is deliberately not a
 *   new field on the saved node: dev/135 keeps the document and the run log
 *   apart. It is never read over a settled outcome: the success of a rerun is
 *   posted to the journal after the node settles, so a read at that moment
 *   still returns the failure it replaced.
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

/** Whether this tab holds the node's outcome, so the journal has nothing to add. */
export function isSettled(
  output: { code?: string; content?: unknown } | null | undefined,
): boolean {
  return output?.code === "success" || output?.code === "error";
}

/** The live outcome, or null when this tab has no failure to show. */
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
  return clip(line.trim());
}

function clip(line: string): string {
  return line.length > FIRST_LINE_CHARS
    ? line.slice(0, FIRST_LINE_CHARS - 1) + "…"
    : line;
}

const PYTHON_TRACEBACK_HEADER = "Traceback (most recent call last):";

/**
 * The line the collapsed strip shows. A Python traceback's last line, which is
 * the exception itself (the rule the monitor's ``summarise_traceback`` uses);
 * any other text's first line. A code node's error is its stdout and then the
 * traceback, so its first line was "stdout:" or the traceback header (#603).
 */
export function summaryLine(text: string): string {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  if (lines.includes(PYTHON_TRACEBACK_HEADER)) return clip(lines[lines.length - 1]);
  return firstLine(text);
}

export const NodeOutcomeStrip: React.FC<NodeOutcomeStripProps> = ({
  nodeId,
  projectId,
  output,
}) => {
  const [recorded, setRecorded] = useState<Outcome | null>(null);
  const [expanded, setExpanded] = useState(false);
  // The collapsed line is cut to the node's width, so a single long line can
  // hide text too; the disclosure follows what is actually cut.
  const [clipped, setClipped] = useState(false);
  const textRef = useRef<HTMLSpanElement>(null);
  const settled = isSettled(output);
  const live = liveOutcome(output);

  useEffect(() => {
    if (settled) {
      setRecorded(null);
      return;
    }
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
  }, [projectId, nodeId, settled]);

  const outcome = settled ? live : recorded;
  const text = outcome?.text ?? "";

  useLayoutEffect(() => {
    const el = textRef.current;
    if (!el || expanded) return;
    const measure = () => setClipped(el.scrollWidth > el.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text, expanded]);

  if (!outcome || !text) return null;

  const head = summaryLine(text);
  const hasMore = clipped || text.trim() !== head;

  return (
    <div
      // A press here selects the text: `nodrag` keeps it from moving the
      // node, and `nopan` from panning or (on a double-click) zooming the
      // canvas, which react-flow does inside a node that cannot be dragged,
      // as in a read-only dataflow. `nowheel` scrolls the opened strip.
      className={`${styles.strip} ${outcome.level === "error" ? styles.error : styles.notice}` +
        (expanded ? ` ${styles.expanded}` : "") + " nodrag nopan nowheel"}
      role="status"
      data-testid={`node-outcome-${nodeId}`}
    >
      <span className={styles.label}>
        {outcome.live ? "Error" : "Last run"}
      </span>
      <span ref={textRef} className={styles.text}>{expanded ? text : head}</span>
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
