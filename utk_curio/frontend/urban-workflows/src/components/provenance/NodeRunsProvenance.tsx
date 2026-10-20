import React, { useEffect, useMemo, useState } from "react";
import { type NodeExecRecord, useProvenanceContext } from "../../providers/ProvenanceProvider";
import { useFlowContext } from "../../providers/FlowProvider";
import { runDuration, runItems, runKinds, runTime } from "../../utils/nodeRuns";
import { type HistoryView, ProvenanceHistory } from "./ProvenanceHistory";
import styles from "./ProvenanceHistory.module.css";

const RUN_NOUN = ["run", "runs"] as const;
const NO_RUNS: NodeExecRecord[] = [];

function runInUse(selected: Record<string, number | null>, nodeId: string): string | null {
  const id = selected[nodeId];
  return id == null ? null : String(id);
}

export interface NodeRunsProvenanceProps {
  nodeId: string;
  /** Puts a run's code back in the node's editor. */
  restore: (code: string) => void;
  view: HistoryView;
  /** The node left the canvas: the drawer closes. */
  onNodeGone: () => void;
}

/**
 * A node's runs in the provenance drawer. An opened run shows what it read and
 * returned, when it ran and for how long, and its code. Its button puts that
 * code back in the node without running it, and the node's next run branches
 * from it.
 */
export function NodeRunsProvenance({ nodeId, restore, view, onNodeGone }: NodeRunsProvenanceProps) {
  const { provenanceGraphNodes, selectedParentExecRef, setSelectedExec } = useProvenanceContext();
  const records = provenanceGraphNodes[nodeId] ?? NO_RUNS;
  const items = useMemo(() => runItems(records), [records]);
  const byId = useMemo(() => new Map(records.map((record) => [String(record.id), record])), [records]);

  // The run the next one branches from. The provider moves it to each run it
  // files, in a ref, so the drawer reads it again whenever a run is filed.
  const [currentId, setCurrentId] = useState<string | null>(() => runInUse(selectedParentExecRef.current, nodeId));
  useEffect(() => {
    setCurrentId(runInUse(selectedParentExecRef.current, nodeId));
  }, [records, nodeId, selectedParentExecRef]);

  // Closed with its node: deleted on the canvas, or by a collaborator.
  const { nodes } = useFlowContext();
  const present = (Array.isArray(nodes) ? nodes : []).some((node: { id: string }) => node.id === nodeId);
  useEffect(() => {
    if (!present) onNodeGone();
  }, [present, onNodeGone]);

  const putBack = (record: NodeExecRecord) => {
    setSelectedExec(nodeId, record.id);
    setCurrentId(String(record.id));
    restore(record.code);
  };

  const details = (id: string) => {
    const record = byId.get(id);
    if (!record) return null;
    const at = runTime(record.startTime);
    const took = runDuration(record);
    return (
      <>
        <p className={styles.detailLine}>{runKinds(record)}</p>
        {at ? (
          <p className={styles.detailLine}>
            Started {at.toLocaleString()}
            {took ? `, ran for ${took}` : ""}
          </p>
        ) : null}
        {record.code ? <pre className={styles.code}>{record.code}</pre> : null}
        {id === currentId ? <p className={styles.inUse}>The next run branches from this one</p> : null}
        <button type="button" className={styles.restore} onClick={() => putBack(record)}>
          Put this code back in the node
        </button>
      </>
    );
  };

  return (
    <ProvenanceHistory
      items={items}
      currentId={currentId}
      view={view}
      noun={RUN_NOUN}
      details={details}
      emptyText="No runs yet"
    />
  );
}

export default NodeRunsProvenance;
