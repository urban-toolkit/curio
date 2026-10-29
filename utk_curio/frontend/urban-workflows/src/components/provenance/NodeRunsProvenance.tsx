import React, { useEffect, useMemo } from "react";
import { type NodeExecRecord, useProvenanceContext } from "../../providers/ProvenanceProvider";
import { useFlowContext } from "../../providers/FlowProvider";
import { useServerHistory } from "../../providers/history/serverHistory";
import { useNodeEntries } from "../../providers/history/useHistoryReads";
import { useOptionalToastContext } from "../../providers/ToastProvider";
import { historyApi } from "../../api/historyApi";
import { nodeCode } from "../../utils/editFeatures/mapLayerEdits";
import { isEdit, runDuration, runItems, runKinds, runTime } from "../../utils/nodeRuns";
import shell from "../packages/publishing/CatalogDrawerShell.module.css";
import { ProvenanceHistory } from "./ProvenanceHistory";
import styles from "./ProvenanceHistory.module.css";

const RUN_NOUN = ["run", "runs"] as const;
/** A history that holds edits as well as runs counts entries. */
const ENTRY_NOUN = ["entry", "entries"] as const;

export interface NodeRunsProvenanceProps {
  nodeId: string;
  /** Puts a run's code back in the node's editor. */
  restore: (code: string) => void;
  /** Shows the node's code, which the server put back. */
  showCode?: () => void;
  /** The node left the canvas: the drawer closes. */
  onNodeGone: () => void;
}

/**
 * A node's runs in the provenance drawer, and its edits: those made in its
 * body (a Map Editor node's actions, and the entries of its list switched off
 * or deleted), each listed by what it changed, and an agent's changes the
 * user applied, each named after the agent.
 * An opened run shows what it read and returned, when it ran and for how long,
 * and its code; an opened edit shows when it was made and the code it left.
 * Either one's button puts that code back in the node without running it, and
 * the node's next run or edit branches from it.
 *
 * On a canvas bound to the dataflow's doc the entries are the server's, and
 * the code goes back only if the node still holds what this tab showed:
 * someone's change after it is kept, and the drawer says who made it.
 */
export function NodeRunsProvenance({ nodeId, restore, showCode, onNodeGone }: NodeRunsProvenanceProps) {
  const { setSelectedExec, chooseEntry } = useProvenanceContext();
  const toast = useOptionalToastContext();

  // Closed with its node: deleted on the canvas, or by a collaborator.
  const { nodes } = useFlowContext();
  const node = (Array.isArray(nodes) ? nodes : []).find((n: { id: string }) => n.id === nodeId) as
    | { id: string; data?: unknown }
    | undefined;
  const present = !!node;
  useEffect(() => {
    if (!present) onNodeGone();
  }, [present, onNodeGone]);

  // The node's code as its editor shows it: the doc's, on a bound canvas.
  const shown = node ? nodeCode(node.data) : undefined;
  const bound = useServerHistory();
  const { server, records, currentId: current, loaded, error } = useNodeEntries(
    nodeId,
    bound?.codeOf(nodeId) ?? shown,
  );
  const currentId = current == null ? null : String(current);
  const items = useMemo(() => runItems(records), [records]);
  const byId = useMemo(() => new Map(records.map((record) => [String(record.id), record])), [records]);
  const noun = records.some(isEdit) ? ENTRY_NOUN : RUN_NOUN;

  if (error) return <div className={shell.empty}>{error}</div>;
  if (!loaded) return <div className={shell.empty}>Reading the history…</div>;

  const putBack = async (record: NodeExecRecord) => {
    if (!server) {
      setSelectedExec(nodeId, record.id);
      restore(record.code);
      return;
    }
    const from = server.codeOf(nodeId) ?? shown ?? "";
    chooseEntry(nodeId, record.id, record.code);
    try {
      await server.whenKept();
      await historyApi.writeCode(server.projectId, nodeId, { from, code: record.code, label: "Code put back" });
      showCode?.();
    } catch (failure) {
      toast?.showToast((failure as Error)?.message || "This code could not be put back.", "warning");
    }
  };

  const details = (id: string) => {
    const record = byId.get(id);
    if (!record) return null;
    const at = runTime(record.startTime);
    const took = runDuration(record);
    const edit = isEdit(record);
    return (
      <>
        {edit ? (
          at ? <p className={styles.detailLine}>Made {at.toLocaleString()}</p> : null
        ) : (
          <>
            <p className={styles.detailLine}>{runKinds(record)}</p>
            {at ? (
              <p className={styles.detailLine}>
                Started {at.toLocaleString()}
                {took ? `, ran for ${took}` : ""}
              </p>
            ) : null}
          </>
        )}
        {record.code ? <pre className={styles.code}>{record.code}</pre> : null}
        {id === currentId ? (
          <p className={styles.inUse}>
            {noun === ENTRY_NOUN ? "The next run or edit branches from this one" : "The next run branches from this one"}
          </p>
        ) : null}
        <button type="button" className={styles.restore} onClick={() => void putBack(record)}>
          Put this code back in the node
        </button>
      </>
    );
  };

  return (
    <ProvenanceHistory
      items={items}
      currentId={currentId}
      noun={noun}
      details={details}
      emptyText="No runs yet"
    />
  );
}

export default NodeRunsProvenance;
