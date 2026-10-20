import React from "react";
import { HeaderDrawer } from "../layout/HeaderDrawer";
import { useFlowContext } from "../../providers/FlowProvider";
import type { NodeProvenanceTarget } from "../../providers/provenanceDrawerContext";
import { DataflowProvenance } from "./DataflowProvenance";
import { NodeRunsProvenance } from "./NodeRunsProvenance";
import type { HistoryView } from "./ProvenanceHistory";
import styles from "./ProvenanceHistory.module.css";

/** Whose history the drawer shows: the dataflow's versions, or a node's runs. */
export type ProvenanceTarget = { kind: "dataflow" } | ({ kind: "node" } & NodeProvenanceTarget);

export interface ProvenanceDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
  target: ProvenanceTarget;
  view: HistoryView;
  onViewChange: (view: HistoryView) => void;
}

/**
 * The provenance drawer: a dataflow's versions or a node's runs, on the right
 * with the catalog drawers' pin and width, as the List or the Graph of Curio's
 * Nest.
 */
export function ProvenanceDrawer({
  presented,
  onRequestClose,
  onExitComplete,
  target,
  view,
  onViewChange,
}: ProvenanceDrawerProps) {
  const { workflowNameRef } = useFlowContext();
  const node = target.kind === "node" ? target : null;
  return (
    <HeaderDrawer
      presented={presented}
      onRequestClose={onRequestClose}
      onExitComplete={onExitComplete}
      title={node ? "Node provenance" : "Dataflow provenance"}
      titleId="provenance-drawer-title"
      name="provenance"
      subtitle={node ? `Runs of ${node.title}` : `Versions of ${workflowNameRef.current || "Untitled dataflow"}`}
      actions={<ViewSwitch view={view} onChange={onViewChange} />}
      pinnable
      wide={false}
    >
      {node ? (
        <NodeRunsProvenance
          key={node.nodeId}
          nodeId={node.nodeId}
          restore={node.restore}
          view={view}
          onNodeGone={onRequestClose}
        />
      ) : (
        <DataflowProvenance key="dataflow" view={view} />
      )}
    </HeaderDrawer>
  );
}

/** List or Graph, as the Nest flips between its views. */
function ViewSwitch({ view, onChange }: { view: HistoryView; onChange: (view: HistoryView) => void }) {
  return (
    <div className={styles.switch} role="group" aria-label="Show the history as">
      <button type="button" aria-pressed={view === "list"} onClick={() => onChange("list")}>
        List
      </button>
      <button type="button" aria-pressed={view === "graph"} onClick={() => onChange("graph")}>
        Graph
      </button>
    </div>
  );
}

export default ProvenanceDrawer;
