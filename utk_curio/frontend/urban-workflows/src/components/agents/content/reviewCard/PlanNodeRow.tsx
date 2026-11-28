import React, { useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCheck } from "@fortawesome/free-solid-svg-icons";

import styles from "../AgentReviewCard.module.css";
import { ROW_CHECK, ROW_UNCHECKED, ROW_WAIT_WORDS, type PlanRowView } from "./reviewCardText";

/** Where a row whose node waits for the person's pick goes: its sources, in
 *  this chat or in its Dataset Finder's, and the tooltip that says which. */
export interface RowSources {
  show: () => void;
  hint: string;
}

/** One node of a landed plan (dev/71's lifecycle), one row: its name, which
 * opens the chat of its node's own agent; its state in one word, or a tick
 * once its code landed and a check ran on it ("Not checked" when none did);
 * its Solve while it can run and its Run once built; then what it does, and
 * why it failed when it did. A row whose node waits for the person's pick
 * goes to its own sources. */
export const PlanNodeRow: React.FC<{
  node: { ref: string; nodeType: string; title: string; intent: string; expects?: string; scenario?: string };
  view: PlanRowView;
  /** Its Solve may start now. */
  solvable: boolean;
  /** How its code was checked, once built: ran, valid, written. */
  check: string | null;
  /** What a build or a Solve does on it now. */
  atWork: string | null;
  /** The node upstream of it it waits for, by name. */
  afterLabel: string | null;
  /** Why it failed, and a notice that is no failure. */
  reason: string | null;
  notice: string | null;
  /** The row's Solve and Run, each told the line the row shows while a
   *  download on first use of what the node reads comes (empty once over). */
  onSolve?: (onLine: (line: string) => void) => Promise<void>;
  onRun?: (onLine: (line: string) => void) => Promise<void>;
  /** Opens the chat of its node's own agent, named *chatAgentName*. */
  onOpenChat?: () => void;
  chatAgentName?: string | null;
  /** Its node's sources, while it waits for the person's pick. */
  sources?: RowSources | null;
}> = ({
  node,
  view,
  solvable,
  check,
  atWork,
  afterLabel,
  reason,
  notice,
  onSolve,
  onRun,
  onOpenChat,
  chatAgentName,
  sources = null,
}) => {
  // #662: a copy has its original's title; its scenario tells them apart.
  const label = node.scenario ? `${node.title} (${node.scenario})` : node.title;
  const [rowBusy, setRowBusy] = useState<"solve" | "run" | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);
  // How far a download the row's run waits on has come, as a node's Solve
  // says it on its own line: shown while the run lasts.
  const [rowLine, setRowLine] = useState<string | null>(null);

  const act = async (kind: "solve" | "run", fn?: (onLine: (line: string) => void) => Promise<void>) => {
    if (!fn || rowBusy) return;
    setRowBusy(kind);
    setRowError(null);
    let running = true;
    try {
      await fn((line) => {
        if (running) setRowLine(line || null);
      });
    } catch (e) {
      setRowError(e instanceof Error ? e.message : `The ${kind} failed`);
    } finally {
      running = false;
      setRowLine(null);
      setRowBusy(null);
    }
  };

  // Its tick says how its code was checked; a check this row cannot name is
  // no claim.
  const ticked = check ? ROW_CHECK[check] ?? null : null;
  const building = view === "building" || rowBusy === "solve";
  return (
    <li className={styles.planNodeRow} data-curio-plan-row={node.ref} data-curio-row-view={building ? "building" : view}>
      <div className={styles.planNodeHead}>
        {onOpenChat ? (
          <button
            type="button"
            className={styles.planNodeName}
            data-tooltip={`Open its ${chatAgentName || "agent"}`}
            onClick={onOpenChat}
          >
            {node.title}
          </button>
        ) : (
          // A name too long for the row is cut: its tooltip says it whole.
          <span className={styles.planNodeTitle} data-tooltip={node.title}>
            {node.title}
          </span>
        )}
        {ticked && !building ? (
          <span className={styles.planNodeTick} role="img" aria-label={ticked.name} data-tooltip={ticked.says}>
            <FontAwesomeIcon icon={faCheck} />
          </span>
        ) : null}
        <span className={styles.planNodeSpacer} />
        {view === "not-placed" ? <span className={styles.planRowFailed}>Not placed</span> : null}
        {building ? (
          <span className={styles.planRowBuilding} data-tooltip={atWork ?? undefined}>
            Building…
          </span>
        ) : view === "done" && !ticked ? (
          <span className={styles.planRowAfter} data-tooltip={ROW_UNCHECKED.says}>
            {ROW_UNCHECKED.word}
          </span>
        ) : view === "pick" && sources ? (
          // Its word goes to its own sources, and says where on its tooltip.
          <button
            type="button"
            className={styles.planRowWaitsLink}
            data-tooltip={sources.hint}
            aria-label={`${ROW_WAIT_WORDS["awaiting-source"]}: show the sources of ${label}`}
            onClick={sources.show}
          >
            {ROW_WAIT_WORDS["awaiting-source"]}
          </button>
        ) : view === "pick" ? (
          <span className={styles.planRowWaits}>{ROW_WAIT_WORDS["awaiting-source"]}</span>
        ) : view === "download" ? (
          <span className={styles.planRowWaits}>{ROW_WAIT_WORDS["awaiting-download"]}</span>
        ) : view === "install" ? (
          <span className={styles.planRowWaits}>{ROW_WAIT_WORDS["awaiting-install"]}</span>
        ) : view === "failed" ? (
          <span className={styles.planRowFailed}>Failed</span>
        ) : view === "after" && afterLabel ? (
          <span className={styles.planRowAfter}>after {afterLabel}</span>
        ) : null}
        {onSolve && solvable && !building ? (
          <button
            type="button"
            className={styles.apply}
            disabled={rowBusy !== null}
            onClick={() => void act("solve", onSolve)}
            aria-label={`Solve node ${label}`}
          >
            Solve
          </button>
        ) : null}
        {onRun && view === "done" ? (
          <button
            type="button"
            className={styles.planRowRun}
            disabled={rowBusy !== null}
            onClick={() => void act("run", onRun)}
            aria-label={`Run through node ${label}`}
          >
            {rowBusy === "run" ? "Running…" : "Run"}
          </button>
        ) : null}
      </div>
      {rowLine ? <div className={styles.planNodeExpects}>{rowLine}</div> : null}
      <div className={styles.planNodeIntent}>{node.intent}</div>
      {reason ? <div className={styles.planRowReason}>{reason}</div> : null}
      {notice && view !== "failed" ? <div className={styles.planNodeExpects}>{notice}</div> : null}
      {rowError ? <div className={styles.error}>{rowError}</div> : null}
    </li>
  );
};
