import React from "react";
import { HeaderDrawer } from "../layout/HeaderDrawer";
import { useFlowContext } from "../../providers/FlowProvider";
import { DataflowProvenance } from "./DataflowProvenance";

/** Whose history the drawer shows. */
export type ProvenanceTarget = { kind: "dataflow" };

export interface ProvenanceDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
  target: ProvenanceTarget;
}

/**
 * The provenance drawer: a dataflow's versions, on the right with the catalog
 * drawers' pin and width, listed as Curio's Nest lists work.
 */
export function ProvenanceDrawer({ presented, onRequestClose, onExitComplete }: ProvenanceDrawerProps) {
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
      pinnable
      wide={false}
    >
      <DataflowProvenance />
    </HeaderDrawer>
  );
}

export default ProvenanceDrawer;
