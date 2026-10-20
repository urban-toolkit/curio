import React from "react";
import { HeaderDrawer } from "../layout/HeaderDrawer";
import { useFlowContext } from "../../providers/FlowProvider";
import { DataflowProvenance } from "./DataflowProvenance";
import type { HistoryView } from "./ProvenanceHistory";
import styles from "./ProvenanceHistory.module.css";

/** Whose history the drawer shows. */
export type ProvenanceTarget = { kind: "dataflow" };

export interface ProvenanceDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
  target: ProvenanceTarget;
  view: HistoryView;
  onViewChange: (view: HistoryView) => void;
}

/**
 * The provenance drawer: a dataflow's versions, on the right with the catalog
 * drawers' pin and width, as the List or the Graph of Curio's Nest.
 */
export function ProvenanceDrawer({
  presented,
  onRequestClose,
  onExitComplete,
  view,
  onViewChange,
}: ProvenanceDrawerProps) {
  const { workflowNameRef } = useFlowContext();
  return (
    <HeaderDrawer
      presented={presented}
      onRequestClose={onRequestClose}
      onExitComplete={onExitComplete}
      title="Dataflow provenance"
      titleId="provenance-drawer-title"
      name="provenance"
      subtitle={`Versions of ${workflowNameRef.current || "Untitled dataflow"}`}
      actions={<ViewSwitch view={view} onChange={onViewChange} />}
      pinnable
      wide={false}
      bodyClassName={view === "graph" ? styles.graphBody : undefined}
    >
      <DataflowProvenance view={view} />
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
